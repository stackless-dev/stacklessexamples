#  socketlibevent.py - MIT License
#  phoenix@burninglabs.com
#
#  Non-blocking socket I/O for Stackless Python using libevent, via pyevent.
#
#  Usage:
#      import sys, socketlibevent; sys.modules['socket'] = socketlibevent
#
#  Based on Richard Tew's stacklesssocket module.
#  Uses Dug Song's pyevent.
#
#  Thanks a Heap !


import stackless, sys, time, traceback
from weakref import WeakValueDictionary
import socket as stdsocket
from socket import _fileobject

try:
    import event
except:
    try:
        import rel; rel.override()
        import event
    except:
        print "please install libevent and pyevent"
                # http://code.google.com/p/pyevent/
        print "(or 'stackless ez_setup.py rel' for quick testing)"
                # http://code.google.com/p/registeredeventlistener/
        sys.exit()

# For SSL support, this module uses the 'ssl' module (built in from 2.6 up):
#               ('back-port' for Python < 2.6: http://pypi.python.org/pypi/ssl/)
try:
    import ssl as ssl_
    ssl_enabled = True
except:
    ssl_enabled = False

#  Nice socket globals import ripped from Minor Gordon's Yield.
if "__all__" in stdsocket.__dict__:
    __all__ = stdsocket.__dict__["__all__"]
    globals().update((key, value) for key, value in\
             stdsocket.__dict__.iteritems() if key in __all__ or key == "EBADF")
else:
    other_keys = ("error", "timeout", "getaddrinfo")
    globals().update((key, value) for key, value in\
        stdsocket.__dict__.iteritems() if key.upper() == key or key in\
                                                                     other_keys)
_GLOBAL_DEFAULT_TIMEOUT = 0.1

# simple decorator to run a function in a tasklet
def tasklet(task):
    def run(*args, **kwargs):
        stackless.tasklet(task)(*args, **kwargs)
    return run

# Event Loop Management
loop_running = False
sockets = WeakValueDictionary()

def die():
    global sockets
    sockets = {}
    sys.exit()

@tasklet
def eventLoop():
    global loop_running
    global event_errors
    
    while sockets.values():
        # If there are other tasklets scheduled:
        #     use the nonblocking loop
        # else: use the blocking loop
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
        event.signal(3, die)
        eventLoop()
        loop_running = True


# Replacement Socket Module Functions
def socket(family=AF_INET, type=SOCK_STREAM, proto=0):
    return evsocket(stdsocket.socket(family, type, proto))

def create_connection(address, timeout=0.1):
    s = socket()
    s.connect(address, timeout)
    return s

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

    def listen(self, backlog=255):
        self.accepting = True
        return self.sock.listen(backlog)

    def accept(self):
        if not self.accept_channel:
            self.accept_channel = stackless.channel()
            event.event(self.handle_accept, handle=self.sock,
                        evtype=event.EV_READ | event.EV_PERSIST).add()
        return self.accept_channel.receive()

    @tasklet
    def handle_accept(self, ev, sock, event_type, *arg):
        s, a = self.sock.accept()
        s.setsockopt(stdsocket.SOL_SOCKET, stdsocket.SO_REUSEADDR, 1)
        s = evsocket(s)
        self.accept_channel.send((s,a))

    def connect(self, address, timeout=0.1):
        endtime = time.time() + timeout
        while time.time() < endtime:
            if self.sock.connect_ex(address) == 0:
                self.connected = True
                self.remote_addr = address
                return
        if not self.connected:
            # One last try, just to raise an error
            return self.sock.connect(address)

    def send(self, data, *args):
        event.write(self.sock, self.handle_send, data)
        return self.write_channel.receive()

    @tasklet
    def handle_send(self, data):
        self.write_channel.send(self.sock.send(data))

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
    
    @tasklet
    def handle_recv(self, bytes):
        self.read_channel.send(self.sock.recv(bytes))
    
    def recvfrom(self, bytes, *args):
        event.read(self.sock, self.handle_recv, bytes)
        return self.read_channel.receive()

    @tasklet
    def handle_recvfrom(self, bytes):
        self.read_channel.send(self.sock.recvfrom(bytes))

    def makefile(self, mode='r', bufsize=-1):
        self.fileobject = stdsocket._fileobject(self, mode, bufsize)
        return self.fileobject

    def close(self):
        # XXX Stupid workaround
        # Don't close while the fileobject is still using the fakesocket
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

    @tasklet
    def handle_accept(self, ev, sock, event_type, *arg):
        s, a = self.sock.accept()
        s.setsockopt(stdsocket.SOL_SOCKET, stdsocket.SO_REUSEADDR, 1)
        s.setsockopt(stdsocket.IPPROTO_TCP, stdsocket.TCP_NODELAY, 1)
        s = evsocketssl(s)
        self.accept_channel.send((s,a))


if __name__ == "__main__":
    sys.modules["socket"] = __import__(__name__)
    
    # Minimal Client Test
    # TODO: Add a Minimal Server Test
    
    import urllib2
    
    @tasklet
    def test(i):
        print "url read", i
        print urllib2.urlopen("http://www.google.com").read(12)
    
    for i in range(5):
        test(i)
    
    stackless.run()
