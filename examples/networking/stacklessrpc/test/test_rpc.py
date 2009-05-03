import os, sys, logging, unittest, StringIO
import stackless

# Ensure the module to be tested is importable.
if __name__ == "__main__":
    currentPath = sys.path[0]
    parentPath = os.path.dirname(currentPath)
    if parentPath not in sys.path:
        sys.path.append(parentPath)

    # Insist on a local version of 'stacklesssocket.py'.
    stacklesssocketPath = os.path.join(currentPath, "stacklesssocket.py")
    if not os.path.exists(stacklesssocketPath):
        print "The unit tests require 'stacklesssocket.py' to be present in the 'test' directory"
        sys.exit()

    import stacklesssocket
    stacklesssocket.install()

import rpc


# Add test information to the logging output.
class TestCase(unittest.TestCase):
    def run(self, *args, **kwargs):
        logging.debug("%s %s", self._testMethodName, (79 - len(self._testMethodName) - 1) *"-")
        super(TestCase, self).run(*args, **kwargs)



class RPCTestCase(TestCase):
    def setUp(self):
        rpc.stackless = DummyClass()

    def tearDown(self):
        if rpc.stackless is not stackless:
            rpc.stackless = stackless

    def testSocketIsManaged(self):
        """The goal of this test is to verify that the tasklet created to
        manage the socket, actually starts."""

        # Give the rpc module access to the 'tasklet' class as its stackless
        # module has been replaced with a mock object.
        rpc.stackless.tasklet = stackless.tasklet

        # Make a mock version of '_ManageSocket' we can tell has been called.
        def new_ManageSocket(self):
            new_ManageSocket.called = True
        new_ManageSocket.called = False

        # Inject it in a way where we restore the old version so that
        # subsequent tests are not clobbered by leakage.
        old_ManageSocket = rpc.EndPoint._ManageSocket
        rpc.EndPoint._ManageSocket = new_ManageSocket
        try:
            _socket = DummyClass()
            endpoint = rpc.EndPoint(_socket)
            self.failUnless(stackless.runcount == 2, "_ManageSocket was not launched in a tasklet")
            # Ensure the _ManageSocket tasklet starts.
            stackless.run()
        finally:
            rpc.EndPoint._ManageSocket = old_ManageSocket

        # Verify that the scheduler/tasklet state is correct.
        self.failUnless(stackless.runcount == 1, "The scheduler still contains tasklets")
        # Verify that the tasklet gets started.
        self.failUnless(new_ManageSocket.called, "The mock _ManageSocket function was not called")

    def testResultIsScheduled(self):
        """The goal of this test is to ensure that the passing of results to
        pending calls is scheduled, rather than dispatched immediately.  The
        reason for this design decision is so that the dispatcher does not
        get arbitrarily blocked, continually waiting for pending calls to
        deal with their results.  Instead it dispatches results promptly."""
    
        # Give the rpc module access to the 'channel' class as its stackless
        # module has been replaced with a mock object.
        rpc.stackless.channel = stackless.channel

        # Create an endpoint with a mock object for a socket.
        _socket = DummyClass()
        endpoint = rpc.EndPoint(_socket)
        exitOrder = []

        def CallingARemoteFunction():
            _remoteFunction = DummyClass()
            endpoint._RemoteCall(_remoteFunction)
            exitOrder.append(stackless.current)

        # Launch the function as a tasklet and get it blocked waiting for the result.
        callingTasklet = stackless.tasklet(CallingARemoteFunction)()
        callingTasklet.run()
        self.failUnless(callingTasklet.blocked, "Client tasklet should be blocked on a channel awaiting a result")

        def ReceivingACallResult():            
            _result = DummyClass()
            callID = endpoint.channelsByCallID.keys()[0]
            endpoint._DispatchIncomingResult(callID, _result)
            exitOrder.append(stackless.current)

        resultTasklet = stackless.tasklet(ReceivingACallResult)()
        stackless.run()

        # Validate the state.        
        self.failUnless(stackless.runcount == 1, "Scheduler expected to be empty")
        self.failUnless(len(exitOrder) == 2, "Both tasklets are expected to have hit their exit order points")

        # Now check that the main aspect of this test is correct.
        self.failUnless(exitOrder[0] is resultTasklet, "Calling tasklet was not scheduled, but run immediately")

    def testSerialisationReliability(self):
        """The goal of this test is to trigger the packet serialisation and
        the restoration of the serialised data back into a packet.  The
        input and output of this process should be the same, to ensure that
        the local and remote sides are dealing with the same data."""
        
        # Create an endpoint with a mock object for a socket.
        _socket = DummyClass()
        endpoint = rpc.EndPoint(_socket)

        # Inject a method into the socket to collect sent strings.
        socketSends = []
        def socket_send(data):
            socketSends.append(data)
        _socket.send = socket_send

        # Inject a method into the endpoint to collect deserialised packets.
        deserialisedPackets = []
        def EndPoint__DispatchIncomingResult(callID, payload):
            deserialisedPackets.append((callID, payload))
        endpoint._DispatchIncomingResult = EndPoint__DispatchIncomingResult

        callIDAndPayload = ("B", "C")
        endpoint._SendPacket(rpc.PKT_RESULT, *callIDAndPayload)        
        
        # Ensure we received to sends, the length and the raw packet that it was followed by.
        self.failUnless(len(socketSends) == 2, "Expected two entries, a length and packet, got %s entries" % len(socketSends))
        
        endpoint._DispatchIncomingPacket(socketSends[1])

        # Ensure we got only as many deserialised packet data entries as we expect.
        self.failUnless(len(deserialisedPackets) == 1, "Expected one deserialised packet, got %d" % len(deserialisedPackets))
        # Ensure we got the packet data we sent.        
        self.failUnless(deserialisedPackets[0] == callIDAndPayload, "Did not get the callID and payload we sent")

    def testConsecutivePacketProcessing(self):
        """The goal of this test is to ensure that processing one packet does
        not leak state so that processing a subsequent packet fails because of
        it."""

        # Give the rpc module access to the 'tasklet' class as its stackless
        # module has been replaced with a mock object.
        rpc.stackless.tasklet = stackless.tasklet

        # Create an endpoint with a mock object for a socket.
        _socket = DummyClass()
        endpoint = rpc.EndPoint(_socket)

        # Make a file-like object that we can serialise a sequence of packets into.
        sio = StringIO.StringIO()        

        # Inject a method into the mocked socket to collect the "sent" data.
        def socket_send(data):
            sio.write(data)
        socket_send.raise_error = False
        _socket.send = socket_send

        numPackets = 3
        functionDatas = []
        for i in range(numPackets):
            functionData = "functionID%d" % i, "args%d" % i, "kwargs%d" % i
            functionDatas.append(functionData)
            endpoint._SendPacket(rpc.PKT_CALL, i, functionData)

        self.failUnless(sio.len > 0, "There was no collected sent data in the StringIO object")
        # Rewind the string IO object to the beginning ready for reeling its contents off.
        sio.seek(0)
        # Ignore error and result packets that may be caused.
        _socket.send = lambda *args, **kwargs: None
        
        callsToDispatch = []
        def EndPoint_DispatchIncomingCall(*args):
            callsToDispatch.append(args)
        endpoint.DispatchIncomingCall = EndPoint_DispatchIncomingCall

        def socket_recv(numBytes):
            return sio.read(numBytes)
        _socket.recv = socket_recv

        stackless.run()
        
        # Validate the state.        
        self.failUnless(stackless.runcount == 1, "Scheduler expected to be empty")
        self.failUnless(len(callsToDispatch) == numPackets, "Expected to have received %d calls, got %d" % (numPackets, len(callsToDispatch)))
        self.failUnless(callsToDispatch == functionDatas, "Send function data does not match that which was received")

# ...

class DummyClass:
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        instance = self.__class__()
        instance.args = args
        instance.kwargs = kwargs
        return instance

    def __getattr__(self, attrName, defaultValue=None):
        if attrName.startswith("__"):
            return getattr(self.__class__, attrName)

        instance = self.__class__()
        instance.attrName = attrName
        instance.defaultValue = defaultValue
        return instance


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)

    unittest.main()
