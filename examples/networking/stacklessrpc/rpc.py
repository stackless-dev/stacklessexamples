#
# Remote procedure calls over sockets with Stackless Python.
#
# Author: Richard Tew <richard.m.tew@gmail.com>
#
# This code was written to serve as an example of Stackless Python usage.
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#
# Purpose:
#
#  - To allow programmers to make synchronous calls over sockets.
#
# Expectations:
# 
#  - The Stackless socket module has already been monkeypatched in place.
#  - The responsibility for running the Stackless scheduler lies elsewhere.
#  - Connected sockets are established and provided by the user.
#

"""
Allowing synchronous calls over sockets.

The advantage of Stackless Python and its C level coroutine functionality
is that control flow can be kept linear by using the ability to block
any calling function to abstract away boilerplate.  This allows
straightforward readable code to be written by any programmer using
the resulting framework.

The ability to make function calls directly through a network connection
is one example of this.
"""

__all__ = [ "EndPoint", "RemoteEndPoint" ]

import socket
import types, struct, cPickle, sys
import stackless

PKT_CALL = 1
PKT_RESULT = 2
PKT_ERROR = 3

class EndPoint:
    """Used to manage incoming and outgoing packets over a socket, allowing
    synchronous calls to be made over it.
    
    The resulting EndPoint instance should be wrapped with any number of
    RemoteEndpoint objects, on which calls made will be proxied through
    the EndPoint instance.
    
    Each socket should be wrapped by  one and only one EndPoint object.
    Multiple EndPoint objects that wrap the same socket will fight for
    incoming data from it, and will end up getting garbage instead of
    complete sets of data."""

    packetSizeFmt = "!I"
    packetSizeLength = struct.calcsize(packetSizeFmt)

    def __init__(self, epSocket):
        """Stores and manages the socket to allow synchronous calls over it."""
        self.socket = epSocket
        self.callID = 0
        self.channelsByCallID = {}

        self.tasklet = stackless.tasklet(self._ManageSocket)()

    def Release(self):
        self.tasklet.kill()

    def _ManageSocket(self):
        try:
            self._ReceivePackets()
        except socket.error:
            # Disconnection while blocking on a recv call.
            return

    def _ReceivePackets(self):
        rawPacket = self._ReadIncomingPacket()
        while rawPacket:
            self._DispatchIncomingPacket(rawPacket)
            rawPacket = self._ReadIncomingPacket()

    def _ReadIncomingPacket(self):
        sizeData = self._ReadIncomingData(self.packetSizeLength)
        if sizeData:
            dataLength = struct.unpack(self.packetSizeFmt, sizeData)[0]
            return self._ReadIncomingData(dataLength)

    def _ReadIncomingData(self, dataLength):
        readBuffer = ""
        while len(readBuffer) != dataLength:
            data = self.socket.recv(dataLength - len(readBuffer))
            if not data:
                # print self.__class__.__name__, "socket unexpectedly disconnected"
                return
            readBuffer += data
        return readBuffer

    def _DispatchIncomingPacket(self, rawPacket):
        packetType, callID, payload = cPickle.loads(rawPacket)
        if packetType == PKT_CALL:
            try:
                self._SendPacket(PKT_RESULT, callID, self.DispatchIncomingCall(*payload))
            except Exception, e:
                # For now let the local side know of the error the remote side triggered.
                import traceback
                traceback.print_exc()

                # Send the error message.
                self._SendPacket(PKT_ERROR, callID, "SOME EXC STATE HERE")

                # Prevent the exception being leaked.
                sys.exc_clear()
        elif packetType == PKT_RESULT:
            self._DispatchIncomingResult(callID, payload)
        elif packetType == PKT_ERROR:
            raise NotImplementedError("todo, call error handling")
        else:
            raise NotImplementedError("unknown packet type %s" % packetType)

    def _DispatchIncomingResult(self, callID, payload):
        channel = self.channelsByCallID[callID]
        del self.channelsByCallID[callID]
        channel.send(payload)

    def DispatchIncomingCall(self, functionID, args, kwargs):
        """This method should be overridden so that the user can deal with
        dispatching incoming calls in the manner that suits their application."""
        raise NotImplementedError("Application is responsible for dispatching incoming calls")
        # return the result...

    def _SendPacket(self, packetType, callID, payload):
        # Marshal the data to be sent, into a packet.
        data = cPickle.dumps((packetType, callID, payload))
        # Packet size.
        self.socket.send(struct.pack("!I", len(data)))
        # Packet data.
        self.socket.send(data)

    def _RemoteCall(self, remoteFunction):
        self.callID += 1
        callID = self.callID

        channel = self.channelsByCallID[callID] = stackless.channel()
        # Ensure recipients of sends are scheduled, and our send operation returns immediately.
        channel.preference = 1
        functionData = remoteFunction.functionID, remoteFunction.args, remoteFunction.kwargs
        self._SendPacket(PKT_CALL, callID, functionData)
        # Block the calling tasklet until its result (or error) has arrived.
        return channel.receive()


class RemoteEndPoint:
    """RemoteEndpoint(endpoint, namespaceID=None)
    
    Proxies calls to the remote side of an endpoint.  The id of a namespace
    can be given to differentiate what entity the call is being made on.
    Mapping the namespace id to an entity is the responsibility of the
    application on the remote side of the connection.""" 

    def __init__(self, endpoint, namespaceID=None):
        """A given endpoint can be wrapped in any number of these objects.
        By specifying unique namespaceID values for each, an application
        can have multiple RemoteEndpoint proxy objects for a given socket
        that send calls to different systems or target objects.
        
        The EndPoint subclass on the remote side is responsible for
        interpreting the namespaceID values used, dispatching calls
        through its overriden DispatchIncomingCall method."""
        self.namespaceID = namespaceID
        self.endpoint = endpoint

    def __getattr__(self, functionName):
        """Catches attribute access to proxy function calls over the socket."""
        return _RemoteFunction(self.endpoint, self.namespaceID, functionName)


class _RemoteFunction:
    def __init__(self, endpoint, *functionID):
        self.endpoint = endpoint
        self.functionID = functionID

    def __call__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

        return self.endpoint._RemoteCall(self)
