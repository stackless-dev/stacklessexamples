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
import asyncore
import socket as stdsocket # We need the "socket" name for the function we export.

# If we are to masquerade as the socket module, we need to provide the constants.
for k, v in stdsocket.__dict__.iteritems():
    if k.upper() == k:
        globals()[k] = v
error = stdsocket.error
timeout = stdsocket.timeout

# urllib2 apparently uses this directly.  We need to cater for that.
_fileobject = stdsocket._fileobject

# WARNING: this function blocks and is not thread safe.
# The only solution is to spawn a thread to handle all
# getaddrinfo requests.  Implementing a stackless DNS
# lookup service is only second best as getaddrinfo may
# use other methods.
getaddrinfo = stdsocket.getaddrinfo


managerRunning = False

def ManageSockets():
    global managerRunning

    while len(asyncore.socket_map):
        # Check the sockets for activity.
        asyncore.poll(0.05)
        # Yield to give other tasklets a chance to be scheduled.
        stackless.schedule()

    managerRunning = False

def socket(family=AF_INET, type=SOCK_STREAM, proto=0):
    global managerRunning

    currentSocket = stdsocket.socket(family, type, proto)
    ret = stacklesssocket(currentSocket)
    # Ensure that the sockets actually work.
    if not managerRunning:
        managerRunning = True
        stackless.tasklet(ManageSockets)()
    return ret

# This is a facade to the dispatcher object.
# It exists because asyncore's socket map keeps a bound reference to
# the dispatcher and hence the dispatcher will never get gc'ed.
#
# The rest of the world sees a 'stacklesssocket' which has no cycles
# and will be gc'ed correctly

class stacklesssocket(object):
    def __init__(self, sock):
        self.sock = sock
        self.dispatcher = dispatcher(sock)

    def __getattr__(self, name):
        # Forward nearly everything to the dispatcher
        if not name.startswith("__"):
            # I don't like forwarding __repr__
            return getattr(self.dispatcher, name)

    def __setattr__(self, name, value):
        if name == "wrap_accept_socket":
            # We need to pass setting of this to the dispatcher.
            self.dispatcher.wrap_accept_socket = value
        else:
            # Anything else gets set locally.
            object.__setattr__(self, name, value)

    def __del__(self):
        # Close dispatcher if it isn't already closed
        if self.dispatcher._fileno is not None:
            try:
                self.dispatcher.close()
            finally:
                self.dispatcher = None

    # Catch this one here to make gc work correctly.
    # (Consider if stacklesssocket gets gc'ed before the _fileobject)
    def makefile(self, mode='r', bufsize=-1):
        return stdsocket._fileobject(self, mode, bufsize)


class dispatcher(asyncore.dispatcher):
    connectChannel = None
    acceptChannel = None
    recvChannel = None

    def __init__(self, sock):
        # This is worth doing.  I was passing in an invalid socket which was
        # an instance of dispatcher and it was causing tasklet death.
        if not isinstance(sock, stdsocket.socket):
            raise StandardError("Invalid socket passed to dispatcher")
        asyncore.dispatcher.__init__(self, sock)

        # if self.socket.type == SOCK_DGRAM:
        #    self.dgramRecvChannels = {}
        #    self.dgramReadBuffers = {}
        #else:
        self.recvChannel = stackless.channel()
        self.readBufferString = ''
        self.readBufferList = []

        self.sendBuffer = ''
        self.sendToBuffers = []

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
            self.connectChannel.receive()

    def send(self, data):
        self.sendBuffer += data
        stackless.schedule()
        return len(data)

    def sendall(self, data):
        # WARNING: this will busy wait until all data is sent
        # It should be possible to do away with the busy wait with
        # the use of a channel.
        self.sendBuffer += data
        while self.sendBuffer:
            stackless.schedule()
        return len(data)

    def sendto(self, sendData, sendAddress):
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
    def recv(self, byteCount):
        if len(self.readBufferString) < byteCount:
            self.readBufferString += self.recvChannel.receive()
        # Disabling this because I believe it is the onus of the application
        # to be aware of the need to run the scheduler to give other tasklets
        # leeway to run.
        # stackless.schedule()
        ret = self.readBufferString[:byteCount]
        self.readBufferString = self.readBufferString[byteCount:]
        return ret

    def recvfrom(self, byteCount):
        ret = ""
        address = None
        while 1:
            while len(self.readBufferList):
                data, dataAddress = self.readBufferList[0]
                if address is None:
                    address = dataAddress
                elif address != dataAddress:
                    # They got all the sequential data from the given address.
                    return ret, address

                ret += data
                if len(ret) >= byteCount:
                    # We only partially used up this data.
                    self.readBufferList[0] = ret[byteCount:], address
                    return ret[:byteCount], address

                # We completely used up this data.
                del self.readBufferList[0]

            self.readBufferList.append(self.recvChannel.receive())

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
            currentSocket, clientAddress = asyncore.dispatcher.accept(self)
            currentSocket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
            # Give them the asyncore based socket, not the standard one.
            currentSocket = self.wrap_accept_socket(currentSocket)
            stackless.tasklet(self.acceptChannel.send)((currentSocket, clientAddress))

    # Inform the blocked connect call that the connection has been made.
    def handle_connect(self):
        if self.socket.type != SOCK_DGRAM:
            if not self.connectChannel:
                self.connectChannel = stackless.channel()
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
                ret, address = self.socket.recvfrom(20000)
                stackless.tasklet(self.recvChannel.send)((ret, address))
            else:
                ret = asyncore.dispatcher.recv(self, 20000)
                # Not sure this is correct, but it seems to give the
                # right behaviour.  Namely removing the socket from
                # asyncore.
                if not ret:
                    self.close()
                stackless.tasklet(self.recvChannel.send)(ret)
        except stdsocket.error, err:
            # XXX Is this correct?
            # If there's a read error assume the connection is
            # broken and drop any pending output
            if self.sendBuffer:
                self.sendBuffer = ""
            # Why can't I pass the 'err' by itself?
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

    # In order for incoming connections to be stackless compatible,
    # they need to be wrapped by an asyncore based dispatcher subclass.
    def wrap_accept_socket(self, currentSocket):
        return stacklesssocket(currentSocket)


if __name__ == '__main__':
    import sys
    import struct
    # Test code goes here.
    testAddress = "127.0.0.1", 3000
    info = -12345678
    data = struct.pack("i", info)
    dataLength = len(data)

    print "creating listen socket"
    def TestTCPServer(address, socketClass=None):
        global info, data, dataLength

        if not socketClass:
            socketClass = socket

        listenSocket = socketClass(AF_INET, SOCK_STREAM)
        listenSocket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        listenSocket.bind(address)
        listenSocket.listen(5)

        NUM_TESTS = 2

        i = 1
        while i < NUM_TESTS + 1:
            # No need to schedule this tasklet as the accept should yield most
            # of the time on the underlying channel.
            print "waiting for connection test", i
            currentSocket, clientAddress = listenSocket.accept()
            print "received connection", i, "from", clientAddress

            if i == 1:
                currentSocket.close()
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
                currentSocket.close()

            print "server test", i, "OK"
            i += 1

        if i != NUM_TESTS+1:
            print "server: FAIL", i
        else:
            print "server: OK", i

        print "Done server"

    def TestTCPClient(address, socketClass=None):
        global info, data, dataLength

        if not socketClass:
            socketClass = socket

        # Attempt 1:
        clientSocket = socketClass()
        clientSocket.connect(address)
        print "client connection", 1, "waiting to recv"
        if clientSocket.recv(5) != "":
            print "client test", 1, "FAIL"
        else:
            print "client test", 1, "OK"

        # Attempt 2:
        clientSocket = socket()
        clientSocket.connect(address)
        print "client connection", 2, "waiting to recv"
        s = clientSocket.recv(dataLength)
        if s == "":
            print "client test", 2, "FAIL (disconnect)"
        else:
            t = struct.unpack("i", s)
            if t[0] == info:
                print "client test", 2, "OK"
            else:
                print "client test", 2, "FAIL (wrong data)"

    def TestMonkeyPatchUrllib(uri):
        # replace the system socket with this module
        oldSocket = sys.modules["socket"]
        sys.modules["socket"] = __import__(__name__)
        try:
            import urllib  # must occur after monkey-patching!
            f = urllib.urlopen(uri)
            if not isinstance(f.fp._sock, stacklesssocket):
                raise AssertionError("failed to apply monkeypatch")
            s = f.read()
            if len(s) != 0:
                print "Fetched", len(s), "bytes via replaced urllib"
            else:
                raise AssertionError("no text received?")
        finally:
            sys.modules["socket"] = oldSocket

    def TestMonkeyPatchUDP(address):
        # replace the system socket with this module
        oldSocket = sys.modules["socket"]
        sys.modules["socket"] = __import__(__name__)
        try:
            def UDPServer(address):
                listenSocket = socket(AF_INET, SOCK_DGRAM)
                listenSocket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
                listenSocket.bind(address)

                i = 1
                cnt = 0
                while 1:
                    #print "waiting for connection test", i
                    #currentSocket, clientAddress = listenSocket.accept()
                    #print "received connection", i, "from", clientAddress
                    
                    print "waiting to receive"
                    t = listenSocket.recvfrom(256)
                    cnt += len(t[0])
                    print "received", t[0], cnt
                    if cnt == 512:
                        break

            def UDPClient(address):
                clientSocket = socket(AF_INET, SOCK_DGRAM)
                # clientSocket.connect(address)
                print "sending 512 byte packet"
                sentBytes = clientSocket.sendto("-"+ ("*" * 510) +"-", address)
                print "sent 512 byte packet", sentBytes 

            stackless.tasklet(UDPServer)(address)
            stackless.tasklet(UDPClient)(address)
            stackless.run()
        finally:
            sys.modules["socket"] = oldSocket

    if len(sys.argv) == 2:
        if sys.argv[1] == "client":
            print "client started"
            TestTCPClient(testAddress, stdsocket.socket)
            print "client exited"
        elif sys.argv[1] == "slpclient":
            print "client started"
            stackless.tasklet(TestTCPClient)(testAddress)
            stackless.run()
            print "client exited"
        elif sys.argv[1] == "server":
            print "server started"
            TestTCPServer(testAddress, stdsocket.socket)
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
        stackless.tasklet(TestTCPServer)(testAddress)
        stackless.tasklet(TestTCPClient)(testAddress)
        stackless.run()

        stackless.tasklet(TestMonkeyPatchUrllib)("http://python.org/")
        stackless.run()

        TestMonkeyPatchUDP(testAddress)

        print "SUCCESS"
