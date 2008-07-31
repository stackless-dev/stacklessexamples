#
# Remote procedure calls over sockets with Stackless Python.
#
# Author: Richard Tew <richard.m.tew@gmail.com>
#
# This code was written to serve as an example of Stackless Python usage.
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#
# With just a page of code and the replacement socket module that is
# currently known as "stacklesssocket", it is possible to easily write
# a straightforward remote procedure call layer over a socket.
#

import stackless
#import stacklesssocket as socket
import stacklesssocket
stacklesssocket.install()
import socket
import weakref

import types, struct, cPickle

class EndPoint:
    def __init__(self, epSocket):
        self.socket = epSocket
        self.callID = 0
        self.channelsByCallID = {}
        self.otherEnd = RemoteEndPoint(self)

        stackless.tasklet(self.ManageSocket)()

    def ManageSocket(self):
        try:
            self.ReceiveIncomingData()
        except socket.error:
            # Disconnection while blocking on a recv call.
            return

    def ReceiveIncomingData(self):
        sizeLength = struct.calcsize("I")
        readBuffer = ""
        while True:
            rawPacket = self.socket.recv(sizeLength-len(readBuffer))
            if not rawPacket:
                print self.__class__.__name__, "socket disconnected"
                return
            readBuffer += rawPacket
            if len(readBuffer) == sizeLength:
                dataLength = struct.unpack("I", readBuffer)[0]
                readBuffer = ""
                while len(readBuffer) != dataLength:
                    rawPacket = self.socket.recv(dataLength - len(readBuffer))
                    if not rawPacket:
                        print self.__class__.__name__, "socket unexpectedly disconnected"
                        return
                    readBuffer += rawPacket

                packet = cPickle.loads(rawPacket)
                callID = packet[1]
                if packet[0]:
                    channel = self.channelsByCallID[callID]
                    del self.channelsByCallID[callID]
                    channel.send(packet[2])
                else:
                    ret = self.HandleIncomingCall(packet[2], packet[3], packet[4])
                    self.SendPacket(True, callID, ret)
                readBuffer = ""

            stackless.schedule()

    def HandleIncomingCall(self, name, args, kwargs):
        if name.startswith("__") or hasattr(EndPoint, name):
            return # Raise error?
        method = getattr(self, name)
        if type(method) is not types.MethodType:
            return # Raise error?
        return method(*args, **kwargs)

    def RemoteCall(self, methodInfo):
        self.callID += 1
        callID = self.callID

        channel = self.channelsByCallID[callID] = stackless.channel()
        self.SendPacket(False, callID, methodInfo.name, methodInfo.args, methodInfo.kwargs)
        return channel.receive()

    def SendPacket(self, *bits):
        data = cPickle.dumps(bits)
        data = struct.pack("I", len(data)) + data
        self.socket.send(data)

class RemoteEndPoint:
    def __init__(self, endpoint):
        self.endpoint = endpoint

    def __getattr__(self, name):
        return RemoteFunction(self.endpoint, name)

class RemoteFunction:
    def __init__(self, endpoint, name):
        self.endpoint = endpoint
        self.name = name

    def __call__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

        return self.endpoint.RemoteCall(self)

if __name__ == "__main__":
    # This test/example code is a little artificial, but it should both
    # adequately test the RPC code above and demonstrate how easy it is
    # to write this sort of code with Stackless Python.

    class Server:
        def __init__(self, address):
            self.socket = listenSocket = socket.socket()
            listenSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listenSocket.bind(address)
            listenSocket.listen(5)

            self.endPoints = []

            self.accepting = False

            t = stackless.tasklet(self.ManageSocket)(listenSocket)
            self.listenTasklet = weakref.proxy(t)

        def ManageSocket(self, listenSocket):
            self.accepting = True
            try:
                while 1:
                    epSocket, clientAddress = listenSocket.accept()
                    endPoint = ServerEndPoint(epSocket)
                    self.endPoints.append(endPoint)
            except socket.error:
                pass # Listen socket disconnected.  Our job is done.
            finally:
                self.accepting = False

                listenSocket.close()
                for ep in self.endPoints:
                    ep.socket.close()
                self.endPoints = []

    class ClientEndPoint(EndPoint):
        def Hello(self):
            return "Client Hello!"

    class ServerEndPoint(EndPoint):
        def Hello(self):
            return "Server Hello!"

    address = "127.0.0.1", 3000

    # Start the server.
    server = Server(address)

    clientSocket = socket.socket()
    clientSocket.connect(address)

    # Then connect the client.
    client = ClientEndPoint(clientSocket)
    
    def ClientTasklet(client, server, clientSocket):
        # Tell the server hello.
        ret = client.otherEnd.Hello()
        print "  CLIENT GOT", ret

        # Start the server tasklet which will call on the
        # client-side.  We need to keep the client-side open
        # until it has completed its work.
        serverTasklet = stackless.tasklet(ServerTasklet)(server)
        while serverTasklet.alive:
            stackless.schedule()

        # Close the client connection.
        clientSocket.close()
        # Close the server end of the client connection.
        client.socket.close()
    
    def ServerTasklet(server):
        # Tell all the clients hello.
        for endpoint in server.endPoints:
            ret = endpoint.otherEnd.Hello()
            print "  SERVER GOT", ret, "FROM CLIENT"

        # Make sure all the tasklets are dead so the scheduler can exit.
        server.listenTasklet.kill()
        server.socket.close()

    stackless.tasklet(ClientTasklet)(client, server, clientSocket)
    # Run until there are no tasklets left running.  Keep in mind that
    # as long as sockets are still open, asyncore will keep its
    # management.. managing them.
    stackless.run()

    print "Scheduler exited"
