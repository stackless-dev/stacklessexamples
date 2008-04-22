#
# A simple web server designed to handle ajax and comet requests.  This
# creates a custom version of the chat example for the 'pi.comet'
# javascript library.
#
# Author: Richard Tew <richard.m.tew@gmail.com>
#
# This code was written to serve as an example of Stackless Python usage.
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#
# But a better place to discuss Stackless Python related matters is the
# mailing list found at:
#
#   http://www.tismer.com/mailman/listinfo/stackless
#

## You will need to ensure that the following dependencies are present:

# Obtain this from: http://code.google.com/p/stacklessexamples/
import stacklesssocket
stacklesssocket.install()
# Obtain this from: http://pypi.python.org/pypi/simplejson/
import simplejson
# Obtain this from: http://pi-js.googlecode.com/files/pi.py
import pi                   # 
# Obtain also: http://pi-js.googlecode.com/files/pi-comet-v0.1-stable.js
# Rename this javascript file as 'pi.js' so this web server can find it.

# Code continues..

import stackless
import urlparse, cStringIO
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer

# Import the pi.comet related modules.
import time, cgi
piChatMessages = []
# The channel needs to have its waiting tasklets scheduled for later
# resumption rather than being immediately run.  This means that the
# chat broadcast can happen without blocking or creating extra
# unnecessary tasklets to invoke the channel send.
waitChannel = stackless.channel()
waitChannel.preference = 1

pages = {
    "/":            "index.html",
    "/index.html":  "index.html",
    "/pi.js":       "pi.js",
}

class RequestHandler(BaseHTTPRequestHandler):
    # Respect keep alive requests.
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        scheme, netloc, path, parameters, query, fragment = urlparse.urlparse(self.path, "http")
        self.handle_command(path, query, "")

    def do_POST(self):
        scheme, netloc, path, parameters, query, fragment = urlparse.urlparse(self.path, "http")
        contentType, contentTypeParameters = cgi.parse_header(self.headers.getheader('content-type'))
        contentLength = int(self.headers.get("content-length", -1))

        content = ""
        if contentType == "application/x-www-form-urlencoded":
            query = self.rfile.read(contentLength)

        self.handle_command(path, query, content)

    def handle_command(self, path, query, content):
        kwargs = cgi.parse_qs(query, keep_blank_values=1)

        if path == "/pi-push":
            cometType = int(kwargs["cometType"][0])
            self.pi_push(cometType)
        elif path == "/pi-send":
            self.pi_send(kwargs["nickname"][0], kwargs["text"][0])
        elif path in pages:
            body = open(pages[path], "r").read()

            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.send_header("Content-Length", len(body))
            self.end_headers()

            self.wfile.write(body)
        else:
            # Page not found.
            self.send_response(404,"Page not found")
            body = "404 - Page '%s' not found." % path
            self.send_header("Content-type", "text/plain")
            self.send_header("Content-Length", len(body))
            self.end_headers()

            self.wfile.write(body)

    def pi_push(self, cometType):
        cometName = "PI-RPC"

        self.send_response(200)
        self.send_header("Content-type", pi.getContentType(cometType))
        self.end_headers()
    
        global piChatMessages, waitChannel
        
        while True:
            output = "["
            first = True
            for x in piChatMessages:
                if first==False:output+=","
                else: first = False
                output += "{ id:%i, 'text':'%s', 'nickname':'%s' }"%(x[2],x[0],x[1])
            output += "];" 
            s = pi.getOutput(output,cometType,cometName)
            self.wfile.write(s)

            # Block this tasklet on the common channel waiting for further
            # messages.  This is not really that safe, the connection it is
            # blocking may need special handling.  What happens if it closes?
            # Does it need regular awakening to send token messages to keep
            # the connection alive?
            waitChannel.receive()
            
    def pi_send(self, nickname, text):
        # These messages come in through an XHR connection.  The web page
        # creates a new one of these and therefore new connection each
        # time it needs to send a message.  So in order to respect the
        # limitation the browser has (if it is IE or Firefox) of only
        # being able to have two open connections to a site, we need to
        # make sure the send connection is closed so that a new one can
        # arrive.
        self.close_connection = 1

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

        global piChatMessages, waitChannel
        piChatMessages.append((text, nickname, len(piChatMessages)))
        
        # With normal channel behaviour, calling this would block this tasklet as
        # each blocked subscriber channel was sent to and immediately received.
        # Instead because each subscriber channel has had its preference changed
        # each send will schedule the tasklet waiting on the other side of the
        # channel.
        while waitChannel.balance < 0:
            waitChannel.send(None)
            

class StacklessHTTPServer(HTTPServer):
    # In order to ensure that the request handling does not block the entire
    # web server, we launch the handling of each request in its own tasklet.
    def process_request(self, request, client_address):
        stackless.tasklet(self.process_request_tasklet)(request, client_address)

    # This adapts what 'SocketServer.ThreadingMixIn' does for threads.
    def process_request_tasklet(self, request, client_address):
        try:
            self.finish_request(request, client_address)
            self.close_request(request)
        except:
            self.handle_error(request, client_address)
            self.close_request(request)

def Run():
    address = ('127.0.0.1', 80)
    print "Starting web server on %s port %d" % address
    server = StacklessHTTPServer(address, RequestHandler)
    server.serve_forever()

if __name__ == "__main__":
    stackless.tasklet(Run)()
    stackless.run()
