"""
Utilities to use the socketserver with stackless
"""
import stackless
import socket

class TaskletMixIn:
    """SocketServer mix-in class to handle each request in a new tasklet."""

    def process_request_tasklet(self, request, client_address):
        """Same as in BaseServer but as a tasklet.
        In addition, exception handling is done here.
        """
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.close_request(request)

    def process_request(self, request, client_address):
        """Start a new tasklet to process the request."""
        t = stackless.tasklet(self.process_request_tasklet)(request, client_address)
        t.run() #make it run immediately, taking over from us


class PatchServer:
    """
    A mixin to disable the "select" call that has been put into
    Socketserver.  This is unnecessary and annoying, the code should rely
    on the timeout properties of the listening socket.
    An extra "select" call just adds latency, even when the select
    call is properly emulated
    """
    def serve_forever(self, poll_interval=0.5):
        while True:
            try:
                self._handle_request_timeout(poll_interval)
            except socket.timeout:
                pass
            self.service_actions()

    def handle_request(self):
        """Handle one request, possibly blocking.

        Respects self.timeout.
        """
        # Support people who used socket.settimeout() to escape
        # handle_request before self.timeout was available.
        timeout = self.socket.gettimeout()
        if timeout is None:
            timeout = self.timeout
        elif self.timeout is not None:
            timeout = min(timeout, self.timeout)
        try:
            self._handle_request_timeout(timeout)
        except socket.timeout:
            self.handle_timeout()

    def _handle_request_timeout(self, timeout):
        try:
            if timeout is not None:
                #Do this complex dance to set the timeout temporarily
                old = self.socket.gettimeout()
                self.socket.settimeout(timeout)
                try:
                    request, client_address = self.get_request()
                    request.settimeout(old)
                finally:
                    self.socket.settimeout(old)
            else:
                request, client_address = self.get_request()
        except socket.error:
            return
        if self.verify_request(request, client_address):
            try:
                self.process_request(request, client_address)
            except:
                self.handle_error(request, client_address)
                self.shutdown_request(request)
