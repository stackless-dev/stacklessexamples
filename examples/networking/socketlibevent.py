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
event_errors = 0

def die():
    global sockets
    sockets = {}

def eventLoop():
    global loop_running
    global event_errors
    downtime = 0  # Current Sleep Value
    max_downtime = 0.5  # Max Sleep Value
    
    while sockets.values():
        # If there are other tasklets scheduled, then use the nonblocking loop,
        # else, use the blocking loop
        if stackless.getruncount() > 2: # main tasklet + this one
            status = event.loop(True)
        else:
            status = event.loop(False)
        if status == -1: event_errors += 1
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
        #self.bufferevent = event.bufferevent(self.sock,
        #                                     self.handleRead,
        #                                     self.handleWrite,
        #                                     self.handleError)
        #self.bufferevent.enable(event.EV_READ | event.EV_WRITE)
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
    
    def handleRead(self):
        print "handleRead()"
    
    def handleWrite(self):
        print "handleWrite()"
        #self.bufferevent.disable(event.EV_WRITE)
    
    def handleError(self):
        print "handleError()"
    
    def __getattr__(self, attr):
        return getattr(self.sock, attr)

    def listen(self, backlog=128):
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
        for i in range(10): # try to connect 10 times!
            if self.sock.connect_ex(address) == 0:
                self.connected = True
                self.remote_addr = address
                return
            stackless.schedule()
        if not self.connected:
            # One last try, just to raise an error
            return self.sock.connect(address)

    def send(self, data, *args):
        event.write(self.sock, self.handle_send, data)
        return self.write_channel.receive()
        #print "send()"
        #status = self.bufferevent.write(data)
        #if status == 0:
        #    return len(data)
        #else:
        #    print "bufferevent write error"
        #    return status
        
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
    
    def recvfrom(self, bytes, *args):
        event.read(self.sock, self.handle_recv, bytes)
        return self.read_channel.receive()

    def handle_recvfrom(self, bytes):
        stackless.tasklet(self.read_channel.send(self.sock.recvfrom(bytes)))

    def makefile(self, mode='r', bufsize=-1):
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


# Very minimal test
if __name__ == "__main__":
    sys.modules["socket"] = __import__(__name__)
    
    import urllib2
    
    def test(i):
        print "url read", i
        print urllib2.urlopen("http://www.google.com").read(12)
    
    for i in range(5):
        stackless.tasklet(test)(i)
    
    stackless.run()
