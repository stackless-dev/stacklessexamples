"""
 ___________________________________________________________________________
|                   |             |                         |               |
| socketlibevent.py | MIT License | phoenix@burninglabs.com |  April 2008   |
|___________________|_____________|_________________________|_______________|
|                                                                           |  
|   Non-blocking socket I/O for Stackless Python using libevent / pyevent   |
|                                                                           |
| Usage: import sys, socketlibevent; sys.modules['socket'] = socketlibevent |
|___________________________________________________________________________|

"""

import stackless, sys, time, traceback
from weakref import WeakValueDictionary
import socket as stdsocket
from socket import _fileobject

try: import event
except: sys.exit("This module requires libevent and pyevent.")

# For SSL support, this module uses the 'ssl' module:
#                                              'http://pypi.python.org/pypi/ssl/
try:
    import ssl as ssl_
    ssl_enabled = True
except:
    ssl_enabled = False

try:
    import psyco
    psyco.full()
except:
    pass

from errno import EALREADY, EINPROGRESS, EWOULDBLOCK, EISCONN, errorcode

if "__all__" in stdsocket.__dict__:
    __all__ = stdsocket.__dict__["__all__"]
    globals().update((key, value) for key, value in\
             stdsocket.__dict__.iteritems() if key in __all__ or key == "EBADF")
else:
    other_keys = ("error", "timeout", "getaddrinfo")
    globals().update((key, value) for key, value in\
        stdsocket.__dict__.iteritems() if key.upper() == key or key in\
                                                                     other_keys)


# Event Loop Management
loop_running = False
sockets = WeakValueDictionary()

def die():
    global sockets
    sockets = {}

def eventLoop():
    global loop_running
    global event_errors
    
    while sockets:
        # If there are other tasklets scheduled, then use the nonblocking loop,
        # else, use the blocking loop
        if stackless.getruncount() > 2: # main tasklet + this one
            event.loop(True)
        else:
            event.loop(False)
        stackless.schedule()
    loop_running = False

def runEventLoop():
    global loop_running
    if not loop_running:
        event.init()
        event.signal(2, die)
        stackless.tasklet(eventLoop)()
        loop_running = True


# Replacement Socket Module Functions
def socket(family=AF_INET, type=SOCK_STREAM, proto=0):
    return evsocket(stdsocket.socket(family, type, proto))
    
def ssl(sock, keyfile=None, certfile=None):
    if ssl_enabled:
        return evsocketssl(sock, keyfile, certfile)
    else:
        raise RuntimeError(\
            "SSL requires the 'ssl' module: 'http://pypi.python.org/pypi/ssl/'")
    

# Socket Proxy Class
class evsocket():
    # XXX Not all socketobject methods are implemented!
    # XXX Currently, the sockets are using the default, blocking mode.
    
    def __init__(self, sock):
        self.sock = sock
        self.accepting = False
        self.connected = False
        self.remote_addr = None
        self.fileobject = None
        self.read_channel = stackless.channel()
        self.write_channel = stackless.channel()
        self.accept_channel = None
        global sockets
        sockets[id(self)] = self
        runEventLoop()
    
    def __getattr__(self, attr):
        return getattr(self.sock, attr)

    def listen(self, backlog=1):
        self.accepting = True
        self.sock.listen(backlog)

    def accept(self):
        if not self.accept_channel:
            self.accept_channel = stackless.channel()
            event.event(self.handle_accept, handle=self.sock,
                        evtype=event.EV_READ | event.EV_PERSIST).add()
        return self.accept_channel.receive()

    def handle_accept(self, ev, sock, event_type, *arg):
        s, a = self.sock.accept()
        s.setsockopt(stdsocket.SOL_SOCKET, stdsocket.SO_REUSEADDR, 1)
        s.setsockopt(stdsocket.IPPROTO_TCP, stdsocket.TCP_NODELAY, 1)
        s = evsocket(s)
        stackless.tasklet(self.accept_channel.send((s,a)))

    def connect(self, address):
        err = self.sock.connect_ex(address)
        if err in (EINPROGRESS, EALREADY, EWOULDBLOCK):
            return
        if err in (0, EISCONN):
            self.remote_addr = address
            self.connected = True
        else:
            raise socket.error, (err, errorcode[err])

    def send(self, data, *args):
        event.write(self.sock, self.handle_send, data)
        return self.write_channel.receive()

    def handle_send(self, data):
        stackless.tasklet(self.write_channel.send(self.sock.send(data)))

    def sendall(self, data, *args):
        while data:
            try:
                sent = self.send(data)
                data = data[sent + 1:]
            except:
                raise
        return None

    def recv(self, bytes, *args):
        event.read(self.sock, self.handle_recv, bytes)
        return self.read_channel.receive()
    
    def handle_recv(self, bytes):
        stackless.tasklet(self.read_channel.send(self.sock.recv(bytes)))
    
    #def recvfrom(self, bytes, *args):
    #    event.read(self.sock, self.handle_recv, bytes)
    #    return self.read_channel.receive()

    #def handle_recvfrom(self, bytes):
    #    stackless.tasklet(self.read_channel.send(self.sock.recvfrom(bytes)))

    def makefile(self, mode='r', bufsize=-1):
        # XXX Implement a fileobject
        self.fileobject = stdsocket._fileobject(self, mode, bufsize)
        return self.fileobject

    def close(self):
        # Don't close while the fileobject is still using the fakesocket
        # XXX Temporary fix
        def _close():
            while self.fileobject._sock == self:
                stackless.schedule()
            self._sock.close()
            del sockets[id(self)]
        if self.fileobject:
            stackless.tasklet(_close)()


# SSL Proxy Class
class evsocketssl(evsocket):
    def __init__(self, sock, keyfile=None, certfile=None):
        if certfile:
            server_side = True
        else:
            server_side = False
        
        # XXX This currently performs a BLOCKING handshake operation
        # TODO Implement a non-blocking handshake
        self.sock = ssl_.wrap_socket(sock, keyfile, certfile, server_side)

    def handle_accept(self, ev, sock, event_type, *arg):
        s, a = self.sock.accept()
        s.setsockopt(stdsocket.SOL_SOCKET, stdsocket.SO_REUSEADDR, 1)
        s.setsockopt(stdsocket.IPPROTO_TCP, stdsocket.TCP_NODELAY, 1)
        s = evsocketssl(s)
        stackless.tasklet(self.accept_channel.send((s,a)))


if __name__ == "__main__":
    sys.modules["socket"] = __import__(__name__)
    
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    import urllib, urllib2

    num = 0

    class RequestHandler(BaseHTTPRequestHandler):
        # Respect keep alive requests.
        protocol_version = "HTTP/1.1"
        
        def do_GET(self):
            global num
            body = "fetch %i" % num
            num += 1
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

    class StacklessHTTPServer(HTTPServer):
        def handle_request(self):
            try:
                request, client_address = self.get_request()
            except socket.error:
                return
            stackless.tasklet(self.handle_request_tasklet)(request, client_address)

        def handle_request_tasklet(self, request, client_address):
            if self.verify_request(request, client_address):
                try:
                    self.process_request(request, client_address)
                except:
                    self.handle_error(request, client_address)
                    self.close_request(request)
    
    
    server = StacklessHTTPServer(('', 8080), RequestHandler)
    stackless.tasklet(server.serve_forever)()
    
    
    def test_urllib(i):
        print "urllib test", i
        print urllib.urlopen("http://localhost:8080").read()
    
    def test_urllib2(i):
        print "urllib2 test", i
        print urllib2.urlopen("http://localhost:8080").read()
    
    for i in range(5):
        stackless.tasklet(test_urllib)(i)
        
    for i in range(5):
        stackless.tasklet(test_urllib2)(i)
    
    stackless.run()
