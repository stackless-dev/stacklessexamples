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

# Small parts of this code were contributed back with permission from an
# internal version of this module in use at CCP Games.

import stackless
import asyncore, weakref, time, select

OPTION_WEAKREF_SOCKETMAP = True

if OPTION_WEAKREF_SOCKETMAP:
    asyncore.socket_map = weakref.WeakValueDictionary()

import socket as stdsocket # We need the "socket" name for the function we export.
from errno import EALREADY, EINPROGRESS, EWOULDBLOCK, ECONNRESET, \
     ENOTCONN, ESHUTDOWN, EINTR, EISCONN, EBADF, ECONNABORTED

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

    try:
        while len(asyncore.socket_map):
            # Check the sockets for activity.
            asyncore.poll(0.05)
            # Yield to give other tasklets a chance to be scheduled.
            _schedule_func()
    finally:
        managerRunning = False

def StartManager():
    global managerRunning
    if not managerRunning:
        managerRunning = True
        return stackless.tasklet(ManageSockets)()

_schedule_func = stackless.schedule
_manage_sockets_func = StartManager
_sleep_func = None
_timeout_func = None

def can_timeout():
    return _sleep_func is not None or _timeout_func is not None

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
    wasConnected = False

    _timeout = None
    _blocking = True

    def __init__(self, realSocket):
        # This is worth doing.  I was passing in an invalid socket which
        # was an instance of _fakesocket and it was causing tasklet death.
        if not isinstance(realSocket, _realsocket_old):
            raise StandardError("An invalid socket passed to fakesocket %s" % realSocket.__class__)

        # This will register the real socket in the internal socket map.
        asyncore.dispatcher.__init__(self, realSocket)

        self.readQueue = []
        self.writeQueue = []
        self.sendToBuffers = []

        if can_timeout():
            self._timeout = stdsocket.getdefaulttimeout()

    def receive_with_timeout(self, channel):
        if self._timeout is not None:
            # Start a timing out process.
            # a) Engage a pre-existing external tasklet to send an exception on our channel if it has a receiver, if we are still there when it times out.
            # b) Launch a tasklet that does a sleep, and sends an exception if we are still waiting, when it is awoken.
            # Block waiting for a send.

            if _timeout_func is not None:
                # You will want to use this if you are using sockets in a different thread from your sleep functionality.
                _timeout_func(self._timeout, channel, (timeout, "timed out"))
            elif _sleep_func is not None:
                stackless.tasklet(self._manage_receive_with_timeout)(channel)
            else:
                raise NotImplementedError("should not be here")

            try:
                ret = channel.receive()
            except BaseException, e:
                raise e
            return ret
        else:
            return channel.receive()

    def _manage_receive_with_timeout(self, channel):
        if channel.balance < 0:            
            _sleep_func(self._timeout)
            if channel.balance < 0:
                channel.send_exception(timeout, "timed out")

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

    if not OPTION_WEAKREF_SOCKETMAP:
        def add_channel(self, map=None):
            if map is None:
                map = self._map
            map[self._fileno] = weakref.proxy(self)

    def readable(self):
        if self.socket.type == SOCK_DGRAM:
            return True
        if len(self.readQueue):
            return True
        if self.acceptChannel is not None and self.acceptChannel.balance < 0:
            return True
        if self.connectChannel is not None and self.connectChannel.balance < 0:
            return True
        return False

    def writable(self):
        if self.socket.type != SOCK_DGRAM and not self.connected:
            return True
        if len(self.writeQueue):
            return True
        if len(self.sendToBuffers):
            return True
        return False

    def accept(self):
        self._ensure_non_blocking_read()
        if not self.acceptChannel:
            self.acceptChannel = stackless.channel()
        return self.receive_with_timeout(self.acceptChannel)

    def connect(self, address):
        asyncore.dispatcher.connect(self, address)
        
        # UDP sockets do not connect.
        if self.socket.type != SOCK_DGRAM and not self.connected:
            if not self.connectChannel:
                self.connectChannel = stackless.channel()
                # Prefer the sender.  Do not block when sending, given that
                # there is a tasklet known to be waiting, this will happen.
                self.connectChannel.preference = 1
            self.receive_with_timeout(self.connectChannel)

    def _send(self, data, flags):
        self._ensure_connected()

        channel = stackless.channel()
        channel.preference = 1 # Prefer the sender.
        self.writeQueue.append((flags, data, channel))
        return self.receive_with_timeout(channel)

    def send(self, data, flags=0):
        return self._send(data, flags)

    def sendall(self, data, flags=0):
        while len(data):
            nbytes = self._send(data, flags)
            if nbytes == 0:
                raise Exception("completely unexpected situation, no data sent")
            data = data[nbytes:]

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
        return self.receive_with_timeout(waitChannel)

    def _recv(self, methodName, args):
        self._ensure_non_blocking_read()

        if self._fileno is None:
            return ""
        channel = stackless.channel()
        channel.preference = 1 # Prefer the sender.
        self.readQueue.append((channel, methodName, args))
        return self.receive_with_timeout(channel)

    def recv(self, *args):
        if not self.connected:
            # Sockets which have never been connected do this.
            if not self.wasConnected:
                raise error(10057, 'Socket is not connected')

        return self._recv("recv", args)

    def recv_into(self, *args):
        if not self.connected:
            # Sockets which have never been connected do this.
            if not self.wasConnected:
                raise error(10057, 'Socket is not connected')

        return self._recv("recv_into", args)

    def recvfrom(self, *args):
        return self._recv("recvfrom", args)

    def recvfrom_into(self, *args):
        return self._recv("recvfrom_into", args)

    def close(self):
        if self._fileno is None:
            return

        asyncore.dispatcher.close(self)

        self.connected = False
        self.accepting = False
        self.writeQueue = []

        # Clear out all the channels with relevant errors.
        while self.acceptChannel and self.acceptChannel.balance < 0:
            self.acceptChannel.send_exception(error, 9, 'Bad file descriptor')
        while self.connectChannel and self.connectChannel.balance < 0:
            self.connectChannel.send_exception(error, 10061, 'Connection refused')
        self._clear_read_queue()

    def _clear_read_queue(self, *args):
        for t in self.readQueue:
            if t[0].balance < 0:
                if len(args):
                    t[0].send_exception(*args)
                else:
                    t[0].send("")
        self.readQueue = []        

    # asyncore doesn't support this.  Why not?
    def fileno(self):
        return self.socket.fileno()

    def _is_non_blocking(self):
        return not self._blocking or self._timeout == 0.0

    def _ensure_non_blocking_read(self):
        if self._is_non_blocking():
            # Ensure there is something on the socket, before fetching it.  Otherwise, error complaining.
            r, w, e = select.select([ self ], [], [], 0.0)
            if not r:
                raise stdsocket.error(EWOULDBLOCK, "The socket operation could not complete without blocking")

    def _ensure_connected(self):
        if not self.connected:
            # The socket was never connected.
            if not self.wasConnected:
                raise error(10057, "Socket is not connected")
            # The socket has been closed already.
            raise error(EBADF, 'Bad file descriptor')

    def setblocking(self, flag):    
        self._blocking = flag

    def gettimeout(self):
        return self._timeout

    def settimeout(self, value):
        if value and not can_timeout():
            raise RuntimeError("This is a stackless socket - to have timeout support you need to provide a sleep function")
        self._timeout = value

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
        # This also gets called in the case that a non-blocking connect gets
        # back to us with a no.  If we don't reject the connect, then all
        # connect calls that do not connect will block indefinitely.
        if self.connectChannel is not None:
            self.close()

    # Some error, just close the channel and let that raise errors to
    # blocked calls.
    def handle_expt(self):
        if False:
            import traceback
            print "handle_expt: START"
            traceback.print_exc()
            print "handle_expt: END"
        self.close()

    def handle_read(self):
        if not len(self.readQueue):
            return

        channel, methodName, args = self.readQueue[0]

        try:
            result = getattr(self.socket, methodName)(*args)
        except Exception, e:
            # winsock sometimes throws ENOTCONN
            if isinstance(e, stdsocket.error) and e.args[0] in [ECONNRESET, ENOTCONN, ESHUTDOWN, ECONNABORTED]:
                self.handle_close()
                result = ''
            elif channel.balance < 0:
                channel.send_exception(e.__class__, *e.args)

        if channel.balance < 0:
            channel.send(result)

        if len(self.readQueue) and self.readQueue[0][0] is channel:
            del self.readQueue[0]

    def handle_write(self):
        if len(self.writeQueue):
            flags, data, channel = self.writeQueue[0]
            del self.writeQueue[0]

            # asyncore does not expose sending the flags.
            def asyncore_send(self, data, flags=0):
                try:
                    result = self.socket.send(data, flags)
                    return result
                except socket.error, why:
                    if why.args[0] == EWOULDBLOCK:
                        return 0
                    elif why.args[0] in (ECONNRESET, ENOTCONN, ESHUTDOWN, ECONNABORTED):
                        self.handle_close()
                        return 0
                    else:
                        raise

            nbytes = asyncore_send(self, data, flags)
            if channel.balance < 0:
                channel.send(nbytes)
        elif len(self.sendToBuffers):
            data, address, channel, oldSentBytes = self.sendToBuffers[0]
            sentBytes = self.socket.sendto(data, address)
            totalSentBytes = oldSentBytes + sentBytes
            if len(data) > sentBytes:
                self.sendToBuffers[0] = data[sentBytes:], address, channel, totalSentBytes
            else:
                del self.sendToBuffers[0]
                stackless.tasklet(channel.send)(totalSentBytes)


if False:
    def dump_socket_stack_traces():
        import traceback
        for skt in asyncore.socket_map.values():
            for k, v in skt.__dict__.items():
                if isinstance(v, stackless.channel) and v.queue:
                    i = 0
                    current = v.queue
                    while i == 0 or v.queue is not current:
                        print "%s.%s.%s" % (skt, k, i)
                        traceback.print_stack(t)
                        i += 1


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
            uninstall()

    def TestMonkeyPatchUDP(address):
        # replace the system socket with this module
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
                rdata = ""
                while len(rdata) < 512:
                    data, address = listenSocket.recvfrom(4096)
                    print "received", data, len(data)
                    rdata += data

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
