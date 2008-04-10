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


import stackless, sys
import socket as stdsocket

try:
    import event
except:
    sys.exit("This module requires libevent and pyevent.")

# For SSL support, this module uses the 'ssl' module:
#                                             'http://pypi.python.org/pypi/ssl/
try:
    import ssl as ssl_
    ssl_enabled = True
except:
    ssl_enabled = False

# Smoke 'em if you got 'em
try:
    import psyco
    psyco.full()
except:
    pass


#____Socket Module Constants (from stacklesscket.py (Richard Tew))______________

if "__all__" in stdsocket.__dict__:
    __all__ = stdsocket.__dict__
    for k, v in stdsocket.__dict__.iteritems():
        if k in __all__:
            globals()[k] = v
        elif k == "EBADF":
            globals()[k] = v
else:
    for k, v in stdsocket.__dict__.iteritems():
        if k.upper() == k:
            globals()[k] = v
    error = stdsocket.error
    timeout = stdsocket.timeout
    # WARNING: this function blocks and is not thread safe.
    # The only solution is to spawn a thread to handle all
    # getaddrinfo requests.  Implementing a stackless DNS
    # lookup service is only second best as getaddrinfo may
    # use other methods.
    getaddrinfo = stdsocket.getaddrinfo

# urllib2 apparently uses this directly.  We need to cater for that.
_fileobject = stdsocket._fileobject


#________Event Loop Management__________________________________________________

loop_running = False

def killEventLoop():
    global loop_running
    loop_running = False
    
def eventLoop():
    while loop_running:
        event.loop(True)
        stackless.schedule()

def runEventLoop():
    global loop_running
    if loop_running:
        return
    loop_running = True
    event.init()
    event.signal(2, killEventLoop)
    stackless.tasklet(eventLoop)()        


#________Replacement Socket Module Functions____________________________________

def socket(family=AF_INET, type=SOCK_STREAM, proto=0):
    real = stdsocket.socket(family, type, proto)
    proxy = evsocket(real)
    runEventLoop()
    return proxy
    
def ssl(sock, keyfile=None, certfile=None):
    if ssl_enabled:
        return evsocketssl(sock, keyfile, certfile)
    else:
        raise RuntimeError(\
            "SSL requires the 'ssl' module: 'http://pypi.python.org/pypi/ssl/'")
    

#________Socket Proxy Class_____________________________________________________

class evsocket():
    # XXX Not all socketobject methods are implemented!
    
    connected = False
    remote_addr = None
    
    def __init__(self, sock):
        self.sock = sock
        self.read_channel = stackless.channel()
        self.write_channel = stackless.channel()
        self.accept_channel = None
    
    def __getattr__(self, attr):
        return getattr(self.sock, attr)


    def accept(self):
        if not self.accept_channel:
            self.accept_channel = stackless.channel()
            event.event(self.handle_accept, handle=self.sock._sock,
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
        event.write(self.sock._sock, self.handle_send, data)
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
        event.read(self.sock._sock, self.handle_recv, bytes)
        return self.read_channel.receive()
    
    def handle_recv(self, bytes):
        stackless.tasklet(self.read_channel.send(self.sock.recv(bytes)))

    
    def recvfrom(self, bytes, *args):
        event.read(self.sock._sock, self.handle_recv, bytes)
        return self.read_channel.receive()

    def handle_recvfrom(self, bytes):
        stackless.tasklet(self.read_channel.send(self.sock.recvfrom(bytes)))


    def makefile(self, mode='r', bufsize=-1):
        return stdsocket._fileobject(self, mode, bufsize)


#________SSL Proxy Class________________________________________________________

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




