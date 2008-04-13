#
# An example which implements a WSGI compliant HTTP server using asyncore
# networking. Each HTTP connection is dispatched to a new tasklet for
# processing.
#
# Author: Arnar Birgisson <arnarbi@gmail.com>
#
# Code implementing the HTTP RFCs by Robert Brewer and the CherryPy team,
# see disclaimer below.
#
# This code was written to serve as an example of Stackless Python usage.
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#
# But a better place to discuss Stackless Python related matters is the
# mailing list:
#
#   http://www.tismer.com/mailman/listinfo/stackless
#

import re
import rfc822
import sys
import traceback
from urllib import unquote
from urlparse import urlparse
import asyncore
import socket
import stackless


class Server(object):
    """A WSGI complient web server.
    
    A usage example:
    >>> s = Server((127.0.0.1, 8080), wsgi_app_callable)
    >>> s.start()
    
    This will start a server listening on 127.0.0.1 port 8080.
    It will also start the stackless scheduler and begin serving
    requests.
    """
    
    protocol = "HTTP/1.1"
    version = "stacklesswsgi/0.1alpha"
    ready = False
    environ = {}
    
    def __init__(self, bind_addr, wsgi_app, server_name=None):
        """Instantiate a WSGI server.
        - bind_addr is a (hostname,port) tuple
        - wsgi_app is a callable application as per the WSGI spec
        - server_name is the server name, defaulting to the local hostname
        """
        self.bind_addr = bind_addr
        self.wsgi_app = wsgi_app
        if not server_name:
            server_name = socket.gethostname()
        self.server_name = server_name
        
        self.connection_class = HTTPConnection
        self.tasklet_class = stackless.tasklet
        
        self.running = False
    
    def start(self, start_stackless=True):
        """Start serving HTTP requests on bound port. If start_stackless
        is True (default) this will call stackless.run() and block. Set it
        to False if you intend to start the stackless processing loop yourself or
        call stackless.schedule by some other means. Otherwise the server will
        not function since all work is deferred to a tasklet.
        """
        self.sock_server = sock_server(self.bind_addr)
        self.running = True
        
        self.tasklet_class(self._accept_loop)()
        
        if start_stackless:
            stackless.run()
    
    def stop(self):
        """Call this to make the server stop serving requests. If it is serving
        a request at the time stop() is called, it will finish that and then stop."""
        self.running = False
    
    def _accept_loop(self):
        """The main loop of the server, run in a seperate tasklet by start()."""
        while self.running:
            # This line will suspend the server tasklet until there is a connection
            s, addr = self.sock_server.accept()
            
            # See if we have already been asked to stop
            if not self.running:
                return
            
            # Initialize the WSGI environment
            environ = self.environ.copy()
            environ["SERVER_SOFTWARE"] = "%s WSGI Server" % self.version
            environ["ACTUAL_SERVER_PROTOCOL"] = self.protocol
            environ["SERVER_NAME"] = self.server_name
            environ["SERVER_PORT"] = str(self.bind_addr[1])
            environ["REMOTE_ADDR"] = addr[0]
            environ["REMOTE_PORT"] = str(addr[1])
            
            # self.connection_class is a reference to a class that will
            # take care of reading and parsing requests out of the connection
            conn = self.connection_class(s, self.wsgi_app, environ)
            
            # We create a new tasklet for each connection. This is similar
            # to how threaded web servers work, except they usually keep a thread
            # pool with an upper limit on number of threads. We just create new tasklets
            # blindly without regard for how many requests the server is serving
            # already. This is possible because of the light-weight nature of
            # tasklets compared to threads.
            def comm(connection):
                try:
                    connection.communicate()
                finally:
                    connection.close()
            self.tasklet_class(comm)(conn)


# This method is intended to be started in a seperate tasklet.
# It will repeatedly call asyncore.poll() to dispatch asyncore events
# to the relevant listeners.
# This is started by sock_server, which is in turn started by the server above.
# It is the responsibility of the caller not to invoke this if it's already
# running. Callers can check the asyncore_loop.running attribute to see
# if another invocation is active.
def asyncore_loop():
    # Make sure only one invocation is active at any time
    assert asyncore_loop.running == False
    asyncore_loop.running = True
    try:
        while len(asyncore.socket_map):
            asyncore.poll(0.05)
            stackless.schedule()
    finally:
        asyncore_loop.running = False
asyncore_loop.running = False


class sock_server(asyncore.dispatcher):
    """This is an asyncore.dispatcher that listens on a TCP port. For each
    incoming connection, a sock_channel dispatcher is created and given
    responsibility over the socket"""
    
    def __init__(self, addr):
        """Bind to addr and start listening"""
        asyncore.dispatcher.__init__(self)
        self.accept_channel = None
        self.addr = addr
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.bind(addr)
        self.listen(5)
        
        # Start the asyncore polling loop if it's not already running
        if not asyncore_loop.running:
            stackless.tasklet(asyncore_loop)()
    
    def accept(self):
        # This will suspend the current tasklet (by reading from
        # self.accept_channel). See handle_accept for details on
        # when the tasklet is resumed.
        if self.accept_channel is None:
            self.accept_channel = stackless.channel()
        return self.accept_channel.receive()

    def handle_accept(self):
        # This is called by asyncore to signal that a socket is ready for
        # accept on the listening port. We see if any calls to self.accept()
        # are waiting on self.accept_channel. If so, we accept the socket
        # and write the results on the channel and the tasklet that called
        # accept() is resumed.
        if self.accept_channel and self.accept_channel.balance < 0:
            s, a = asyncore.dispatcher.accept(self)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s = sock_channel(s)
            self.accept_channel.send((s,a))
    

class sock_channel(asyncore.dispatcher):
    """This is an asyncore dispatcher in charge of handling connections
    to http clients."""
    
    def __init__(self, sock):
        """Initialize and start handling the connection on sock. Usually called
        by sock_server"""
        if sock.type == socket.SOCK_DGRAM:
            raise NotImplementedError("sock_channel can only handle TCP sockets")
        asyncore.dispatcher.__init__(self, sock)
        self.send_buffer = ""
        self.recv_buffer = ""
        self.sendall_channel = None
        self.recv_channel = stackless.channel()
    
    def writable(self):
        if not self.connected:
            return True
        # If we have buffered data to send, we're intersted in write events
        return len(self.send_buffer)
    
    def send(self, data):
        if self.send_buffer is None:
            raise socket.error(socket.EBADF, "Connection closed")
        self.send_buffer += data
        # Request a schedule so that asyncore get's a chance to invoke the
        # handle_write event. There is no guarantee that the data will have
        # been sent completely when we return to here again.
        stackless.schedule()
        return len(data)

    def sendall(self, data):
        if self.send_buffer is None:
            raise socket.error(socket.EBADF, "Connection closed")
        self.send_buffer += data
        # Instead of asking for a schedule like send() does, we suspend
        # the current tasklet by reading from self.sendall_channel. Only
        # when the send_buffer has been completely sent on the wire, this
        # call is resumed.
        if self.sendall_channel is None:
            self.sendall_channel = stackless.channel()
        self.sendall_channel.receive()
        # Here we are guaranteed that all of data has been sent
        return len(data)
    
    def handle_write(self):
        # This is called by asyncore when it is ready to send out data.
        # First see if we have some data to send...
        if len(self.send_buffer):
            sent = asyncore.dispatcher.send(self, self.send_buffer[:512])
            self.send_buffer = self.send_buffer[sent:]

            # If we completed sending everything in self.send_buffer and a call to
            # sendall is waiting in another tasklet, let it know so it can resume.
            if len(self.send_buffer) == 0 and self.sendall_channel and self.sendall_channel.balance < 0:
                self.sendall_channel.send(None)

    def recv(self, byte_count):
        # A call to this method will suspend the current tasklet until there is
        # data available to be received. See handle_read on how that happens.
        if byte_count > 0 and len(self.recv_buffer) == 0 or self.recv_channel.balance > 0:
            self.recv_buffer += self.recv_channel.receive()
        
        # Give the caller only as much as he asked for
        ret = self.recv_buffer[:byte_count]
        
        # and stash the rest in self.recv_buffer
        self.recv_buffer = self.recv_buffer[byte_count:]
        
        return ret
    
    def handle_read(self):
        # This is called by asyncore to let us know that there is data available
        # to be received.
        try:
            ret = asyncore.dispatcher.recv(self, 20000)
            if not ret:
                # This means the other end closed the connection, close our end.
                self.close()
            # Send the data to whoever is or will be calling recv()
            self.recv_channel.send(ret)
        except socket.error, err:
            if self.send_buffer:
                self.send_buffer = ""
            # Any errors on the socket is propogated to the callers of recv()
            self.recv_channel.send_exception(stdsocket.error, err)

    def close(self):
        asyncore.dispatcher.close(self)
        self.connected = False
        self.accepting = False
        self.send_buffer = None
        
        # Wake any tasklets that are waiting for sendall() to return
        if self.sendall_channel and self.sendall_channel.balance < 0:
            self.sendall_channel.send(None)
        
        # Wake any tasklets that are waiting for recv to return
        while self.recv_channel and self.recv_channel.balance < 0:
            self.recv_channel.send("")
    
    def handle_close(self):
        pass

    def handle_expt(self):
        self.close()


class sock_channel_rfile(object):
    """This class provides a read-only file-like object on top of sock_channel.
    It is used by the HTTPRequest class to get data from the connection and
    allow WSGI apps to read the request body."""
    
    def __init__(self, sock_chan):
        self.sock_chan = sock_chan
        self.buffer = ""
    
    def read(self, size=-1):
        if size == -1:
            data = self.sock_chan.recv(512)
            while len(data):
                self.buffer += data
                data = self.sock_chan.recv(512)
            data = self.buffer
            self.buffer = ""
            return data
        else:
            data = self.sock_chan.recv(size)
            retval = self.buffer + data
            self.buffer = ""
            return retval
    
    def readline(self):
        idx = self.buffer.find("\n")
        if idx > -1:
            line = self.buffer[:idx+1]
            self.buffer = self.buffer[idx+1:]
            return line
        
        while "\n" not in self.buffer:
            chunk = self.read(512)
            if chunk == "":
                break
            self.buffer += chunk
        
        if self.buffer == "":
            return ""
        
        idx = self.buffer.find("\n")
        if idx > -1:
            line = self.buffer[:idx+1]
            self.buffer = self.buffer[idx+1:]
            return line
        else:
            line = self.buffer
            self.buffer = ""
            return line
    
    def readlines(self, hint=None):
        lines = []
        line = self.readline()
        while line:
            lines.append(line)
            line = self.readline()
        return lines
    
    def __iter__(self):
        return self
    
    def next(self):
        line = self.readline()
        if line:
            return line
        else:
            raise StopIteration
    
    def close(self):
        self.sock_chan = None
        self.buffer = ""


# The rest of this file is taken from CherryPy's excellent WSGI Server by Robert
# Brewer. CherryPy is distributed under the BSD license.
# See http://www.cherrypy.org for more information. I have only removed parts
# relevant to SSL support and added one call to stackless.schedule.
# Otherwise, this code is:
#
# Copyright (c) 2004, CherryPy Team (team@cherrypy.org)
# All rights reserved.

quoted_slash = re.compile("(?i)%2F")

import errno
socket_errors_to_ignore = set(_ for _ in ("EPIPE", "ETIMEDOUT", "ECONNREFUSED", "ECONNRESET",
          "EHOSTDOWN", "EHOSTUNREACH",
          "WSAECONNABORTED", "WSAECONNREFUSED", "WSAECONNRESET",
          "WSAENETRESET", "WSAETIMEDOUT") if _ in dir(errno))
socket_errors_to_ignore.add("timed out")

comma_separated_headers = set(['ACCEPT', 'ACCEPT-CHARSET', 'ACCEPT-ENCODING',
    'ACCEPT-LANGUAGE', 'ACCEPT-RANGES', 'ALLOW', 'CACHE-CONTROL',
    'CONNECTION', 'CONTENT-ENCODING', 'CONTENT-LANGUAGE', 'EXPECT',
    'IF-MATCH', 'IF-NONE-MATCH', 'PRAGMA', 'PROXY-AUTHENTICATE', 'TE',
    'TRAILER', 'TRANSFER-ENCODING', 'UPGRADE', 'VARY', 'VIA', 'WARNING',
    'WWW-AUTHENTICATE'])


class HTTPRequest(object):
    """An HTTP Request (and response).
    
    A single HTTP connection may consist of multiple request/response pairs.
    
    sendall: the 'sendall' method from the connection's fileobject.
    wsgi_app: the WSGI application to call.
    environ: a partial WSGI environ (server and connection entries).
        The caller MUST set the following entries:
        * All wsgi.* entries, including .input
        * SERVER_NAME and SERVER_PORT
        * Any SSL_* entries
        * Any custom entries like REMOTE_ADDR and REMOTE_PORT
        * SERVER_SOFTWARE: the value to write in the "Server" response header.
        * ACTUAL_SERVER_PROTOCOL: the value to write in the Status-Line of
            the response. From RFC 2145: "An HTTP server SHOULD send a
            response version equal to the highest version for which the
            server is at least conditionally compliant, and whose major
            version is less than or equal to the one received in the
            request.  An HTTP server MUST NOT send a version for which
            it is not at least conditionally compliant."
    
    outheaders: a list of header tuples to write in the response.
    ready: when True, the request has been parsed and is ready to begin
        generating the response. When False, signals the calling Connection
        that the response should not be generated and the connection should
        close.
    close_connection: signals the calling Connection that the request
        should close. This does not imply an error! The client and/or
        server may each request that the connection be closed.
    chunked_write: if True, output will be encoded with the "chunked"
        transfer-coding. This value is set automatically inside
        send_headers.
    """
    
    def __init__(self, sendall, environ, wsgi_app):
        self.rfile = environ['wsgi.input']
        self.sendall = sendall
        self.environ = environ.copy()
        self.wsgi_app = wsgi_app
        
        self.ready = False
        self.started_response = False
        self.status = ""
        self.outheaders = []
        self.sent_headers = False
        self.close_connection = False
        self.chunked_write = False
    
    def parse_request(self):
        """Parse the next HTTP request start-line and message-headers."""
        # HTTP/1.1 connections are persistent by default. If a client
        # requests a page, then idles (leaves the connection open),
        # then rfile.readline() will raise socket.error("timed out").
        # Note that it does this based on the value given to settimeout(),
        # and doesn't need the client to request or acknowledge the close
        # (although your TCP stack might suffer for it: cf Apache's history
        # with FIN_WAIT_2).
        request_line = self.rfile.readline()
        if not request_line:
            # Force self.ready = False so the connection will close.
            self.ready = False
            return
        
        if request_line == "\r\n":
            # RFC 2616 sec 4.1: "...if the server is reading the protocol
            # stream at the beginning of a message and receives a CRLF
            # first, it should ignore the CRLF."
            # But only ignore one leading line! else we enable a DoS.
            request_line = self.rfile.readline()
            if not request_line:
                self.ready = False
                return
        
        environ = self.environ
        
        method, path, req_protocol = request_line.strip().split(" ", 2)
        environ["REQUEST_METHOD"] = method
        
        # path may be an abs_path (including "http://host.domain.tld");
        scheme, location, path, params, qs, frag = urlparse(path)
        
        if frag:
            self.simple_response("400 Bad Request",
                                 "Illegal #fragment in Request-URI.")
            return
        
        if scheme:
            environ["wsgi.url_scheme"] = scheme
        if params:
            path = path + ";" + params
        
        environ["SCRIPT_NAME"] = ""
        
        # Unquote the path+params (e.g. "/this%20path" -> "this path").
        # http://www.w3.org/Protocols/rfc2616/rfc2616-sec5.html#sec5.1.2
        #
        # But note that "...a URI must be separated into its components
        # before the escaped characters within those components can be
        # safely decoded." http://www.ietf.org/rfc/rfc2396.txt, sec 2.4.2
        atoms = [unquote(x) for x in quoted_slash.split(path)]
        path = "%2F".join(atoms)
        environ["PATH_INFO"] = path
        
        # Note that, like wsgiref and most other WSGI servers,
        # we unquote the path but not the query string.
        environ["QUERY_STRING"] = qs
        
        # Compare request and server HTTP protocol versions, in case our
        # server does not support the requested protocol. Limit our output
        # to min(req, server). We want the following output:
        #     request    server     actual written   supported response
        #     protocol   protocol  response protocol    feature set
        # a     1.0        1.0           1.0                1.0
        # b     1.0        1.1           1.1                1.0
        # c     1.1        1.0           1.0                1.0
        # d     1.1        1.1           1.1                1.1
        # Notice that, in (b), the response will be "HTTP/1.1" even though
        # the client only understands 1.0. RFC 2616 10.5.6 says we should
        # only return 505 if the _major_ version is different.
        rp = int(req_protocol[5]), int(req_protocol[7])
        server_protocol = environ["ACTUAL_SERVER_PROTOCOL"]
        sp = int(server_protocol[5]), int(server_protocol[7])
        if sp[0] != rp[0]:
            self.simple_response("505 HTTP Version Not Supported")
            return
        # Bah. "SERVER_PROTOCOL" is actually the REQUEST protocol.
        environ["SERVER_PROTOCOL"] = req_protocol
        self.response_protocol = "HTTP/%s.%s" % min(rp, sp)
        
        # If the Request-URI was an absoluteURI, use its location atom.
        if location:
            environ["SERVER_NAME"] = location
        
        # then all the http headers
        try:
            self.read_headers()
        except ValueError, ex:
            self.simple_response("400 Bad Request", repr(ex.args))
            return
        
        creds = environ.get("HTTP_AUTHORIZATION", "").split(" ", 1)
        environ["AUTH_TYPE"] = creds[0]
        if creds[0].lower() == 'basic':
            user, pw = base64.decodestring(creds[1]).split(":", 1)
            environ["REMOTE_USER"] = user
        
        # Persistent connection support
        if self.response_protocol == "HTTP/1.1":
            if environ.get("HTTP_CONNECTION", "") == "close":
                self.close_connection = True
        else:
            # HTTP/1.0
            if environ.get("HTTP_CONNECTION", "") != "Keep-Alive":
                self.close_connection = True
        
        # Transfer-Encoding support
        te = None
        if self.response_protocol == "HTTP/1.1":
            te = environ.get("HTTP_TRANSFER_ENCODING")
            if te:
                te = [x.strip().lower() for x in te.split(",") if x.strip()]
        
        read_chunked = False
        
        if te:
            for enc in te:
                if enc == "chunked":
                    read_chunked = True
                else:
                    # Note that, even if we see "chunked", we must reject
                    # if there is an extension we don't recognize.
                    self.simple_response("501 Unimplemented")
                    self.close_connection = True
                    return
        
        if read_chunked:
            if not self.decode_chunked():
                return
        
        # From PEP 333:
        # "Servers and gateways that implement HTTP 1.1 must provide
        # transparent support for HTTP 1.1's "expect/continue" mechanism.
        # This may be done in any of several ways:
        #   1. Respond to requests containing an Expect: 100-continue request
        #      with an immediate "100 Continue" response, and proceed normally.
        #   2. Proceed with the request normally, but provide the application
        #      with a wsgi.input stream that will send the "100 Continue"
        #      response if/when the application first attempts to read from
        #      the input stream. The read request must then remain blocked
        #      until the client responds.
        #   3. Wait until the client decides that the server does not support
        #      expect/continue, and sends the request body on its own.
        #      (This is suboptimal, and is not recommended.)
        #
        # We used to do 3, but are now doing 1. Maybe we'll do 2 someday,
        # but it seems like it would be a big slowdown for such a rare case.
        if environ.get("HTTP_EXPECT", "") == "100-continue":
            self.simple_response(100)
        
        self.ready = True
    
    def read_headers(self):
        """Read header lines from the incoming stream."""
        environ = self.environ
        
        while True:
            line = self.rfile.readline()
            if not line:
                # No more data--illegal end of headers
                raise ValueError("Illegal end of headers.")
            
            if line == '\r\n':
                # Normal end of headers
                break
            
            if line[0] in ' \t':
                # It's a continuation line.
                v = line.strip()
            else:
                k, v = line.split(":", 1)
                k, v = k.strip().upper(), v.strip()
                envname = "HTTP_" + k.replace("-", "_")
            
            if k in comma_separated_headers:
                existing = environ.get(envname)
                if existing:
                    v = ", ".join((existing, v))
            environ[envname] = v
        
        ct = environ.pop("HTTP_CONTENT_TYPE", None)
        if ct:
            environ["CONTENT_TYPE"] = ct
        cl = environ.pop("HTTP_CONTENT_LENGTH", None)
        if cl:
            environ["CONTENT_LENGTH"] = cl
    
    def decode_chunked(self):
        """Decode the 'chunked' transfer coding."""
        cl = 0
        data = StringIO.StringIO()
        while True:
            line = self.rfile.readline().strip().split(";", 1)
            chunk_size = int(line.pop(0), 16)
            if chunk_size <= 0:
                break
            cl += chunk_size
            data.write(self.rfile.read(chunk_size))
            crlf = self.rfile.read(2)
            if crlf != "\r\n":
                self.simple_response("400 Bad Request",
                                     "Bad chunked transfer coding "
                                     "(expected '\\r\\n', got %r)" % crlf)
                return
        
        # Grab any trailer headers
        self.read_headers()
        
        data.seek(0)
        self.environ["wsgi.input"] = data
        self.environ["CONTENT_LENGTH"] = str(cl) or ""
        return True
    
    def respond(self):
        """Call the appropriate WSGI app and write its iterable output."""
        response = self.wsgi_app(self.environ, self.start_response)
        try:
            for chunk in response:
                # "The start_response callable must not actually transmit
                # the response headers. Instead, it must store them for the
                # server or gateway to transmit only after the first
                # iteration of the application return value that yields
                # a NON-EMPTY string, or upon the application's first
                # invocation of the write() callable." (PEP 333)
                if chunk:
                    self.write(chunk)
                stackless.schedule()
        finally:
            if hasattr(response, "close"):
                response.close()
        if (self.ready and not self.sent_headers):
            self.sent_headers = True
            self.send_headers()
        if self.chunked_write:
            self.sendall("0\r\n\r\n")
    
    def simple_response(self, status, msg=""):
        """Write a simple response back to the client."""
        status = str(status)
        buf = ["%s %s\r\n" % (self.environ['ACTUAL_SERVER_PROTOCOL'], status),
               "Content-Length: %s\r\n" % len(msg)]
        
        if status[:3] == "413" and self.response_protocol == 'HTTP/1.1':
            # Request Entity Too Large
            self.close_connection = True
            buf.append("Connection: close\r\n")
        
        buf.append("\r\n")
        if msg:
            buf.append(msg)
        self.sendall("".join(buf))
    
    def start_response(self, status, headers, exc_info = None):
        """WSGI callable to begin the HTTP response."""
        if self.started_response:
            if not exc_info:
                raise AssertionError("WSGI start_response called a second "
                                     "time with no exc_info.")
            else:
                try:
                    raise exc_info[0], exc_info[1], exc_info[2]
                finally:
                    exc_info = None
        self.started_response = True
        self.status = status
        self.outheaders.extend(headers)
        return self.write
    
    def write(self, chunk):
        """WSGI callable to write unbuffered data to the client.
        
        This method is also used internally by start_response (to write
        data from the iterable returned by the WSGI application).
        """
        if not self.started_response:
            raise AssertionError("WSGI write called before start_response.")
        
        if not self.sent_headers:
            self.sent_headers = True
            self.send_headers()
        
        if self.chunked_write and chunk:
            buf = [hex(len(chunk))[2:], "\r\n", chunk, "\r\n"]
            self.sendall("".join(buf))
        else:
            self.sendall(chunk)
    
    def send_headers(self):
        """Assert, process, and send the HTTP response message-headers."""
        hkeys = [key.lower() for key, value in self.outheaders]
        status = int(self.status[:3])
        
        if status == 413:
            # Request Entity Too Large. Close conn to avoid garbage.
            self.close_connection = True
        elif "content-length" not in hkeys:
            # "All 1xx (informational), 204 (no content),
            # and 304 (not modified) responses MUST NOT
            # include a message-body." So no point chunking.
            if status < 200 or status in (204, 205, 304):
                pass
            else:
                if self.response_protocol == 'HTTP/1.1':
                    # Use the chunked transfer-coding
                    self.chunked_write = True
                    self.outheaders.append(("Transfer-Encoding", "chunked"))
                else:
                    # Closing the conn is the only way to determine len.
                    self.close_connection = True
        
        if "connection" not in hkeys:
            if self.response_protocol == 'HTTP/1.1':
                if self.close_connection:
                    self.outheaders.append(("Connection", "close"))
            else:
                if not self.close_connection:
                    self.outheaders.append(("Connection", "Keep-Alive"))
        
        if "date" not in hkeys:
            self.outheaders.append(("Date", rfc822.formatdate()))
        
        if "server" not in hkeys:
            self.outheaders.append(("Server", self.environ['SERVER_SOFTWARE']))
        
        buf = [self.environ['ACTUAL_SERVER_PROTOCOL'], " ", self.status, "\r\n"]
        try:
            buf += [k + ": " + v + "\r\n" for k, v in self.outheaders]
        except TypeError:
            if not isinstance(k, str):
                raise TypeError("WSGI response header key %r is not a string.")
            if not isinstance(v, str):
                raise TypeError("WSGI response header value %r is not a string.")
            else:
                raise
        buf.append("\r\n")
        self.sendall("".join(buf))


class HTTPConnection(object):
    """An HTTP connection (active socket).
    
    sock_chan: the sock_channel object for this connection.
    wsgi_app: the WSGI application for this server/connection.
    environ: a WSGI environ template. This will be copied for each request.
    
    rfile: a fileobject for reading from the sock_chan.
    sendall: a function for writing (+ flush) to the sock_chan.
    """
    
    RequestHandlerClass = HTTPRequest
    environ = {"wsgi.version": (1, 0),
               "wsgi.url_scheme": "http",
               "wsgi.multithread": True,
               "wsgi.multiprocess": False,
               "wsgi.run_once": False,
               "wsgi.errors": sys.stderr,
               }
    
    def __init__(self, sock_chan, wsgi_app, environ):
        self.sock_chan = sock_chan
        self.wsgi_app = wsgi_app
        
        # Copy the class environ into self.
        self.environ = self.environ.copy()
        self.environ.update(environ)
        
        self.rfile = sock_channel_rfile(sock_chan)
        self.sendall = sock_chan.sendall
        
        self.environ["wsgi.input"] = self.rfile
    
    def communicate(self):
        """Read each request and respond appropriately."""
        try:
            while True:
                # (re)set req to None so that if something goes wrong in
                # the RequestHandlerClass constructor, the error doesn't
                # get written to the previous request.
                req = None
                req = self.RequestHandlerClass(self.sendall, self.environ,
                                               self.wsgi_app)
                # This order of operations should guarantee correct pipelining.
                req.parse_request()
                if not req.ready:
                    return
                req.respond()
                if req.close_connection:
                    return
        except socket.error, e:
            errno = e.args[0]
            if errno not in socket_errors_to_ignore:
                if req:
                    req.simple_response("500 Internal Server Error",
                                        traceback.format_exc())
            return
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            if req:
                try:
                    req.simple_response("500 Internal Server Error", traceback.format_exc())
                except socket.error, e:
                    if e.args[0] != socket.EBADF:
                        raise
                    # Otherwise, connection was closed and we have nowhere to print error
    
    def close(self):
        """Close the socket underlying this connection."""
        self.rfile.close()
        self.sock_chan.close()
