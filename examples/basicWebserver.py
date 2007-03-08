#
# An example which adapts the standard library module BaseHTTPServer to
# handle concurrent requests each on their own tasklet (as opposed to
# using the ThreadingMixIn from the SocketServer module).
#
# Author: Richard Tew <richard.m.tew@gmail.com>
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

# Monkeypatch in the stacklesssocket module.
import sys
import stacklesssocket
sys.modules["socket"] = stacklesssocket

import stackless
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer

body = """
<html>
<head>
<title>StacklessHTTPServer page</title>
</head>
<body>
Nothing to see here, move along..
</body>
</html>
"""

class RequestHandler(BaseHTTPRequestHandler):
    # Respect keep alive requests.
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
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

def Run():
    server = StacklessHTTPServer(('', 80), RequestHandler)
    server.serve_forever()

if __name__ == "__main__":
    stackless.tasklet(Run)()
    stackless.run()
