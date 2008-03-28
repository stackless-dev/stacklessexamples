#
# Stackless compatible socket module:
#
# Author: Richard Tew <richard.m.tew@gmail.com>
#
# This code was written to serve as an example of Stackless Python usage.
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#
# This wraps the asyncore module and the dispatcher class it provides in order
# write a socket module replacement that uses channels to allow calls to it to
# block until a delayed event occurs.
#
# Not all aspects of the socket module are provided by this file.  Examples of
# it in use can be seen at the bottom of this file.
#
# NOTE: Versions of the asyncore module from Python 2.4 or later include bug
#       fixes and earlier versions will not guarantee correct behaviour.
#       Specifically, it monitors for errors on sockets where the version in
#       Python 2.3.3 does not.
#

# Possible improvements:
# - More correct error handling.  When there is an error on a socket found by
#   poll, there is no idea what it actually is.
# - Launching each bit of incoming data in its own tasklet on the recvChannel
#   send is a little over the top.  It should be possible to add it to the
#   rest of the queued data

import stackless
import asyncore, weakref
import socket as stdsocket # We need the "socket" name for the function we export.

# If we are to masquerade as the socket module, we need to provide the constants.
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

# Someone needs to invoke asyncore.poll() regularly to keep the socket
# data moving.  The "ManageSockets" function here is a simple example
# of such a function.  It is started by StartManager(), which uses the
# global "managerRunning" to ensure that no more than one copy is
# running.
#
# If you think you can do this better, register an alternative to
# StartManager using stacklesssocket_manager().  Your function will be
# called every time a new socket is created; it's your responsibility
# to ensure it doesn't start multiple copies of itself unnecessarily.
#

managerRunning = False

def ManageSockets():
    global managerRunning

    while len(asyncore.socket_map):
        # Check the sockets for activity.
        asyncore.poll(0.05)
        # Yield to give other tasklets a chance to be scheduled.
        stackless.schedule()

    managerRunning = False

def StartManager():
    global managerRunning
    if not managerRunning:
        managerRunning = True
        stackless.tasklet(ManageSockets)()

_manage_sockets_func = StartManager

def stacklesssocket_manager(mgr):
    global _manage_sockets_func
    _manage_sockets_func = mgr

def socket(*args, **kwargs):
    import sys
    if "socket" in sys.modules and sys.modules["socket"] is not stdsocket:
        raise RuntimeError("Use 'stacklesssocket.install' instead of replacing the 'socket' module")

_realsocket_old = stdsocket._realsocket
_socketobject_old = stdsocket._socketobject

class _socketobject_new(_socketobject_old):
    def __init__(self, family=AF_INET, type=SOCK_STREAM, proto=0, _sock=None):
        # We need to do this here.
        if _sock is None:
            _sock = _realsocket_old(family, type, proto)
            _sock = _fakesocket(_sock)
            _manage_sockets_func()
        _socketobject_old.__init__(self, family, type, proto, _sock)
        if not isinstance(self._sock, _fakesocket):
            raise RuntimeError("bad socket")

    def accept(self):
        sock, addr = self._sock.accept()
        sock = _fakesocket(sock)
        sock.wasConnected = True
        return _socketobject_new(_sock=sock), addr
        
    accept.__doc__ = _socketobject_old.accept.__doc__


def check_still_connected(f):
    " Decorate socket functions to check they are still connected. "
    def new_f(self, *args, **kwds):
        if not self.connected:
            # The socket was never connected.
            if not self.wasConnected:
                raise error(10057, "Socket is not connected")
            # The socket has been closed already.
            raise error(EBADF, 'Bad file descriptor')
        return f(self, *args, **kwds)
    return new_f


def install():
    if stdsocket._realsocket is socket:
        raise StandardError("Still installed")
    stdsocket._realsocket = socket
    stdsocket.socket = stdsocket.SocketType = stdsocket._socketobject = _socketobject_new

def uninstall():
    stdsocket._realsocket = _realsocket_old
    stdsocket.socket = stdsocket.SocketType = stdsocket._socketobject = _socketobject_old


class _fakesocket(asyncore.dispatcher):
    connectChannel = None
    acceptChannel = None
    recvChannel = None
    wasConnected = False

    def __init__(self, realSocket):
        # This is worth doing.  I was passing in an invalid socket which
        # was an instance of _fakesocket and it was causing tasklet death.
        if not isinstance(realSocket, _realsocket_old):
            raise StandardError("An invalid socket passed to fakesocket %s" % realSocket.__class__)

        # This will register the real socket in the internal socket map.
        asyncore.dispatcher.__init__(self, realSocket)
        self.socket = realSocket

        self.recvChannel = stackless.channel()
        self.readString = ''
        self.readIdx = 0

        self.sendBuffer = ''
        self.sendToBuffers = []

    def __del__(self):
        # There are no more users (sockets or files) of this fake socket, we
        # are safe to close it fully.  If we don't, asyncore will choke on
        # the weakref failures.
        self.close()

    # The asyncore version of this function depends on socket being set
    # which is not the case when this fake socket has been closed.
    def __getattr__(self, attr):
        if not hasattr(self, "socket"):
            raise AttributeError("socket attribute unset on '"+ attr +"' lookup")
        return getattr(self.socket, attr)

    def add_channel(self, map=None):
        if map is None:
            map = self._map
        map[self._fileno] = weakref.proxy(self)

    def writable(self):
        if self.socket.type != SOCK_DGRAM and not self.connected:
            return True
        return len(self.sendBuffer) or len(self.sendToBuffers)

    def accept(self):
        if not self.acceptChannel:
            self.acceptChannel = stackless.channel()
        return self.acceptChannel.receive()

    def connect(self, address):
        asyncore.dispatcher.connect(self, address)
        # UDP sockets do not connect.
        if self.socket.type != SOCK_DGRAM and not self.connected:
            if not self.connectChannel:
                self.connectChannel = stackless.channel()
                # Prefer the sender.  Do not block when sending, given that
                # there is a tasklet known to be waiting, this will happen.
                self.connectChannel.preference = 1
            self.connectChannel.receive()

    @check_still_connected
    def send(self, data, flags=0):
        self.sendBuffer += data
        stackless.schedule()
        return len(data)

    @check_still_connected
    def sendall(self, data, flags=0):
        # WARNING: this will busy wait until all data is sent
        # It should be possible to do away with the busy wait with
        # the use of a channel.
        self.sendBuffer += data
        while self.sendBuffer:
            stackless.schedule()
        return len(data)

    def sendto(self, sendData, sendArg1=None, sendArg2=None):
        # sendto(data, address)
        # sendto(data [, flags], address)
        if sendArg2 is not None:
            flags = sendArg1
            sendAddress = sendArg2
        else:
            flags = 0
            sendAddress = sendArg1
            
        waitChannel = None
        for idx, (data, address, channel, sentBytes) in enumerate(self.sendToBuffers):
            if address == sendAddress:
                self.sendToBuffers[idx] = (data + sendData, address, channel, sentBytes)
                waitChannel = channel
                break
        if waitChannel is None:
            waitChannel = stackless.channel()
            self.sendToBuffers.append((sendData, sendAddress, waitChannel, 0))
        return waitChannel.receive()

    # Read at most byteCount bytes.
    def recv(self, byteCount, flags=0):        
        # recv() must not concatenate two or more data fragments sent with
        # send() on the remote side. Single fragment sent with single send()
        # call should be split into strings of length less than or equal
        # to 'byteCount', and returned by one or more recv() calls.

        remainingBytes = self.readIdx != len(self.readString)
        # TODO: Verify this connectivity behaviour.

        if not self.connected:
            # Sockets which have never been connected do this.
            if not self.wasConnected:
                raise error(10057, 'Socket is not connected')

            # Sockets which were connected, but no longer are, use
            # up the remaining input.  Observed this with urllib.urlopen
            # where it closes the socket and then allows the caller to
            # use a file to access the body of the web page.
        elif not remainingBytes:            
            self.readString = self.recvChannel.receive()
            self.readIdx = 0
            remainingBytes = len(self.readString)

        if byteCount == 1 and remainingBytes:
            ret = self.readString[self.readIdx]
            self.readIdx += 1
        elif self.readIdx == 0 and byteCount >= len(self.readString):
            ret = self.readString
            self.readString = ""
        else:
            idx = self.readIdx + byteCount
            ret = self.readString[self.readIdx:idx]
            self.readString = self.readString[idx:]
            self.readIdx = 0

        # ret will be '' when EOF.
        return ret

    def recvfrom(self, byteCount, flags=0):
        if self.socket.type == SOCK_STREAM:
            return self.recv(byteCount), None

        # recvfrom() must not concatenate two or more packets.
        # Each call should return the first 'byteCount' part of the packet.
        data, address = self.recvChannel.receive()
        return data[:byteCount], address

    def close(self):
        asyncore.dispatcher.close(self)

        self.connected = False
        self.accepting = False
        self.sendBuffer = None  # breaks the loop in sendall

        # Clear out all the channels with relevant errors.
        while self.acceptChannel and self.acceptChannel.balance < 0:
            self.acceptChannel.send_exception(error, 9, 'Bad file descriptor')
        while self.connectChannel and self.connectChannel.balance < 0:
            self.connectChannel.send_exception(error, 10061, 'Connection refused')
        while self.recvChannel and self.recvChannel.balance < 0:
            # The closing of a socket is indicted by receiving nothing.  The
            # exception would have been sent if the server was killed, rather
            # than closed down gracefully.
            self.recvChannel.send("")
            #self.recvChannel.send_exception(error, 10054, 'Connection reset by peer')

    # asyncore doesn't support this.  Why not?
    def fileno(self):
        return self.socket.fileno()

    def handle_accept(self):
        if self.acceptChannel and self.acceptChannel.balance < 0:
            t = asyncore.dispatcher.accept(self)
            if t is None:
                return
            t[0].setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
            stackless.tasklet(self.acceptChannel.send)(t)

    # Inform the blocked connect call that the connection has been made.
    def handle_connect(self):
        if self.socket.type != SOCK_DGRAM:
            self.wasConnected = True
            self.connectChannel.send(None)

    # Asyncore says its done but self.readBuffer may be non-empty
    # so can't close yet.  Do nothing and let 'recv' trigger the close.
    def handle_close(self):
        pass

    # Some error, just close the channel and let that raise errors to
    # blocked calls.
    def handle_expt(self):
        self.close()

    def handle_read(self):
        try:
            if self.socket.type == SOCK_DGRAM:
                ret = self.socket.recvfrom(20000)
            else:
                ret = asyncore.dispatcher.recv(self, 20000)
                # Not sure this is correct, but it seems to give the
                # right behaviour.  Namely removing the socket from
                # asyncore.
                if not ret:
                    self.close()
            stackless.tasklet(self.recvChannel.send)(ret)
        except stdsocket.error, err:
            # If there's a read error assume the connection is
            # broken and drop any pending output
            if self.sendBuffer:
                self.sendBuffer = ""
            self.recvChannel.send_exception(stdsocket.error, err)

    def handle_write(self):
        if len(self.sendBuffer):
            sentBytes = asyncore.dispatcher.send(self, self.sendBuffer[:512])
            self.sendBuffer = self.sendBuffer[sentBytes:]
        elif len(self.sendToBuffers):
            data, address, channel, oldSentBytes = self.sendToBuffers[0]
            sentBytes = self.socket.sendto(data, address)
            totalSentBytes = oldSentBytes + sentBytes
            if len(data) > sentBytes:
                self.sendToBuffers[0] = data[sentBytes:], address, channel, totalSentBytes
            else:
                del self.sendToBuffers[0]
                stackless.tasklet(channel.send)(totalSentBytes)


if __name__ == '__main__':
    import sys
    import struct
    # Test code goes here.
    testAddress = "127.0.0.1", 3000
    info = -12345678
    data = struct.pack("i", info)
    dataLength = len(data)

    def TestTCPServer(address):
        global info, data, dataLength

        print "server listen socket creation"
        listenSocket = stdsocket.socket(AF_INET, SOCK_STREAM)
        listenSocket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        listenSocket.bind(address)
        listenSocket.listen(5)

        NUM_TESTS = 2

        i = 1
        while i < NUM_TESTS + 1:
            # No need to schedule this tasklet as the accept should yield most
            # of the time on the underlying channel.
            print "server connection wait", i
            currentSocket, clientAddress = listenSocket.accept()
            print "server", i, "listen socket", currentSocket.fileno(), "from", clientAddress

            if i == 1:
                print "server closing (a)", i, "fd", currentSocket.fileno(), "id", id(currentSocket)
                currentSocket.close()
                print "server closed (a)", i
            elif i == 2:
                print "server test", i, "send"
                currentSocket.send(data)
                print "server test", i, "recv"
                if currentSocket.recv(4) != "":
                    print "server recv(1)", i, "FAIL"
                    break
                # multiple empty recvs are fine
                if currentSocket.recv(4) != "":
                    print "server recv(2)", i, "FAIL"
                    break
            else:
                print "server closing (b)", i, "fd", currentSocket.fileno(), "id", id(currentSocket)
                currentSocket.close()

            print "server test", i, "OK"
            i += 1

        if i != NUM_TESTS+1:
            print "server: FAIL", i
        else:
            print "server: OK", i

        print "Done server"

    def TestTCPClient(address):
        global info, data, dataLength

        # Attempt 1:
        clientSocket = stdsocket.socket()
        clientSocket.connect(address)
        print "client connection (1) fd", clientSocket.fileno(), "id", id(clientSocket._sock), "waiting to recv"
        if clientSocket.recv(5) != "":
            print "client test", 1, "FAIL"
        else:
            print "client test", 1, "OK"

        # Attempt 2:
        clientSocket = stdsocket.socket()
        clientSocket.connect(address)
        print "client connection (2) fd", clientSocket.fileno(), "id", id(clientSocket._sock), "waiting to recv"
        s = clientSocket.recv(dataLength)
        if s == "":
            print "client test", 2, "FAIL (disconnect)"
        else:
            t = struct.unpack("i", s)
            if t[0] == info:
                print "client test", 2, "OK"
            else:
                print "client test", 2, "FAIL (wrong data)"

        print "client exit"

    def TestMonkeyPatchUrllib(uri):
        # replace the system socket with this module
        #oldSocket = sys.modules["socket"]
        #sys.modules["socket"] = __import__(__name__)
        install()
        try:
            import urllib  # must occur after monkey-patching!
            f = urllib.urlopen(uri)
            if not isinstance(f.fp._sock, _fakesocket):
                raise AssertionError("failed to apply monkeypatch, got %s" % f.fp._sock.__class__)
            s = f.read()
            if len(s) != 0:
                print "Fetched", len(s), "bytes via replaced urllib"
            else:
                raise AssertionError("no text received?")
        finally:
            #sys.modules["socket"] = oldSocket
            uninstall()

    def TestMonkeyPatchUDP(address):
        # replace the system socket with this module
        #oldSocket = sys.modules["socket"]
        #sys.modules["socket"] = __import__(__name__)
        install()
        try:
            def UDPServer(address):
                listenSocket = stdsocket.socket(AF_INET, SOCK_DGRAM)
                listenSocket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
                listenSocket.bind(address)

                # Apparently each call to recvfrom maps to an incoming
                # packet and if we only ask for part of that packet, the
                # rest is lost.  We really need a proper unittest suite
                # which tests this module against the normal socket
                # module.
                print "waiting to receive"
                data, address = listenSocket.recvfrom(256)
                print "received", data, len(data)
                if len(data) != 256:
                    raise StandardError("Unexpected UDP packet size")

            def UDPClient(address):
                clientSocket = stdsocket.socket(AF_INET, SOCK_DGRAM)
                # clientSocket.connect(address)
                print "sending 512 byte packet"
                sentBytes = clientSocket.sendto("-"+ ("*" * 510) +"-", address)
                print "sent 512 byte packet", sentBytes

            stackless.tasklet(UDPServer)(address)
            stackless.tasklet(UDPClient)(address)
            stackless.run()
        finally:
            #sys.modules["socket"] = oldSocket
            uninstall()

    if len(sys.argv) == 2:
        if sys.argv[1] == "client":
            print "client started"
            TestTCPClient(testAddress)
            print "client exited"
        elif sys.argv[1] == "slpclient":
            print "client started"
            stackless.tasklet(TestTCPClient)(testAddress)
            stackless.run()
            print "client exited"
        elif sys.argv[1] == "server":
            print "server started"
            TestTCPServer(testAddress)
            print "server exited"
        elif sys.argv[1] == "slpserver":
            print "server started"
            stackless.tasklet(TestTCPServer)(testAddress)
            stackless.run()
            print "server exited"
        else:
            print "Usage:", sys.argv[0], "[client|server|slpclient|slpserver]"

        sys.exit(1)
    else:
        print "* Running client/server test"
        install()
        try:
            stackless.tasklet(TestTCPServer)(testAddress)
            stackless.tasklet(TestTCPClient)(testAddress)
            stackless.run()
        finally:
            uninstall()

        print "* Running urllib test"
        stackless.tasklet(TestMonkeyPatchUrllib)("http://python.org/")
        stackless.run()

        print "* Running udp test"
        TestMonkeyPatchUDP(testAddress)

        print "result: SUCCESS"
