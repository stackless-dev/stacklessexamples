################################################################################
#
#   A libevent/ pyevent based Stackless-compatible socket module
#   
#   (Owing much to Richard Tew's stacklesssocket (and Sam Rushing's Asyncore))
#
#
#   MIT License                                          phoenix@burninglabs.com
#
################################################################################


import traceback
import stackless
import event
import socket as stdsocket

from errno import EALREADY, EINPROGRESS, EWOULDBLOCK, ECONNRESET, \
     ENOTCONN, ESHUTDOWN, EINTR, EISCONN, EBADF, errorcode


sockets = []
managerRunning = False


# Arnar Birgisson's neat little sleep function ;-)
def sleep(seconds):
    def wakeup(ch):
        ch.send(None)
    ch = stackless.channel()
    event.timeout(seconds, wakeup, ch)
    ch.receive()


# If we are to masquerade as the socket module, we need to provide the constants.
if "__all__" in stdsocket.__dict__:
    __all__ = stdsocket.__dict__
    for k, v in stdsocket.__dict__.iteritems():
        if k in __all__:
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


# Event Loop:
def ManageSockets():
    while managerRunning: #len(sockets):
        #print "event loop"
        event.loop(True)
        stackless.schedule()

    #managerRunning = False

def die():
    #global sockets
    #sockets = []
    global managerRunning
    managerRunning = False

def StartManager():
    global managerRunning
    if not managerRunning:
        event.signal(2, die)
        managerRunning = True
        stackless.tasklet(ManageSockets)()

#
# Replacement for standard socket() constructor.
#
def socket(family=AF_INET, type=SOCK_STREAM, proto=0):
    realSocket = stdsocket.socket(family, type, proto)
    realSocket.setblocking(0)
    evsock = evSocket(realSocket)
    global sockets
    sockets.append(evsock)
    StartManager()
    return evsock
    

class evSocket(object):
    """a pyEvent based socket proxy object"""
    
    address = None
    connected = False
    sending = False
    receiving = True
    acceptChannel = None
    recvChannel = None
    
    def __init__(self, sock):
        # Assert that we have a real socket, not a proxy object
        if not isinstance(sock, stdsocket.socket):
            raise StandardError("Invalid socket passed to dispatcher")
        
        self.sock = sock
        self._fileno = sock.fileno()
        self.recvChannel = stackless.channel()
        self.sendChannel = stackless.channel()

    def __getattr__(self, attr):
        if not attr.startswith('__'):
            return getattr(self.sock, attr)        

    def makefile(self, mode='r', bufsize=-1):
        return stdsocket._fileobject(self, mode, bufsize)

    def accept(self):
    
        # For some reason this option degrades performance
        self.sock.setsockopt(stdsocket.SOL_SOCKET, stdsocket.SO_REUSEADDR, 1)
        
        if not self.acceptChannel:
            self.acceptChannel = stackless.channel()
            
        def cb(ev, sock, event_type, *arg):
            s, a = self.sock.accept()
            self.acceptChannel.send((s, a))
            
        event.event(cb, handle=self.sock, evtype=event.EV_READ |
                                                 event.EV_PERSIST).add()
        
        return (self.acceptChannel.receive())

    def bind(self, address):
        self.address = address
        return self.sock.bind(address)

    def close(self):
        stackless.tasklet(self.handle_close)()

    def handle_close(self):
    
        # XXX There just might be a better way to do this:
        while self.receiving:
            # Busy wait; sleeping was too slow; duh
            stackless.schedule()
            continue
        
        self.sending = False  # breaks the loop in sendall

        global sockets
        sockets.remove(self)
        self._fileno = None
        self.sock.close()
        
        # XXX Am I forgetting anything here?

        #Clear out all the channels with relevant errors.
        while self.acceptChannel and self.acceptChannel.balance < 0:
            self.acceptChannel.send_exception(error, 9, 'Bad file descriptor')
        
        while self.recvChannel and self.recvChannel.balance < 0:
            self.recvChannel.send("")
    
    def connect(self, address):
        stackless.tasklet(self.handle_connect)(address)
    
    def handle_connect(self, address):
        while not self.is_connected:
            err = self.sock.connect_ex(address)
            
            if err in (EINPROGRESS, EALREADY, EWOULDBLOCK):
                stackless.schedule()
                continue
                
            if err in (0, EISCONN):
                self.address = address
            else:
                raise socket.error, (err, errorcode[err])

    def connect_ex(self, address):
        err = self.sock.connect_ex(address)
        
        if err in (0, EISCONN):
            self.address = address
        
        return err
    
    def recv(self, byteCount):
        self.receiving = True
        
        def cb():
            self.recvChannel.send(self.sock.recv(byteCount))
                        
        data = ""
        if len(data) < byteCount:
            try:
                event.read(self.sock, cb)
                data += self.recvChannel.receive()
            except socket.error, error:
                if error[0] in [ECONNRESET, ENOTCONN, ESHUTDOWN]:
                    self.close()
                else:
                    raise
                
        self.receiving = False
        return data
        
        
    def recvfrom(self, byteCount):
        if self.socket.type == SOCK_STREAM:
            return (self.recv(byteCount), None)
        else:
            return (self.recv(byteCount), address)
    
    def send(self, data):
        def cb():
            try:
                self.sendChannel.send(self.sock.send(data))
            except stdsocket.error, err:
                if err[0] == EWOULDBLOCK:
                    return 0
                else:
                    raise
                return 0
        
        event.write(self.sock, cb)
        return self.sendChannel.receive()
    
    def sendall(self, data):
        stackless.tasklet(handle_sendall)(data)
    
    def handle_sendall(self, data):
        self.sending = True
        while data and self.sending:
            sent = self.send(data)
            data = data[sent + 1:]
            stackless.schedule()
        self.sending = False
        
    def sendto(self, data, address):
        def cb():
            try:
                self.sendChannel(self.sock.sendto(data, address))
            except stdsocket.error, err:
                if err[0] == EWOULDBLOCK:
                    return 0
                else:
                    raise
                return 0
        
        event.write(self.sock, cb)
        return self.sendChannel.receive()
        

