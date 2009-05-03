import sys, os, weakref
import stackless

if __name__ == "__main__":
    currentPath = sys.path[0]
    parentPath = os.path.dirname(currentPath)
    if parentPath not in sys.path:
        sys.path.append(parentPath)

    # Insist on a local version of 'stacklesssocket.py'.
    stacklesssocketPath = os.path.join(currentPath, "stacklesssocket.py")
    if not os.path.exists(stacklesssocketPath):
        print "The unit tests require 'stacklesssocket.py' to be present in the 'examples' directory"
        sys.exit()

    import stacklesssocket
    stacklesssocket.install()

import socket
from socket import AF_INET, SOCK_STREAM, SOL_SOCKET, SO_REUSEADDR
import rpc

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 40404

def Run():    
    def ConnectClientAndMakeCalls():
        server = Server(SERVER_HOST, SERVER_PORT)

        clientSocket = socket.socket(AF_INET, SOCK_STREAM)
        clientSocket.connect((SERVER_HOST, SERVER_PORT))
        
        endpoint = rpc.EndPoint(clientSocket)
        svc = rpc.RemoteEndPoint(endpoint, "testSvc")
        print "CLIENT: Making a call over the socket to 'testSvc.TestFunc'"
        result = svc.TestFunc(1, 2, kwarg="xxx")
        print "CLIENT: Received a return value of '%s'" % result
        endpoint.Release()
        
        server.Shutdown()

    stackless.tasklet(ConnectClientAndMakeCalls)()

    # Run the scheduler until it is empty.    
    while stackless.runcount > 1:
        stackless.run()


## Server-side code.

class ServerEndPoint(rpc.EndPoint):
    def __init__(self, server, *args, **kwargs):
        rpc.EndPoint.__init__(self, *args, **kwargs)
        self.server = weakref.proxy(server)

    def DispatchIncomingCall(self, functionID, args, kwargs):
        print "SERVER: Dispatching incoming call", functionID, args, kwargs
        namespaceID, functionName = functionID
        if namespaceID not in self.server.namespaces:
            raise AttributeError, "Service %s has no attribute %s" % (namespaceID, functionName)

        svc = self.server.namespaces[namespaceID]
        function = getattr(svc, functionName, None)
        if function is None:
            raise AttributeError, "Service %s has no attribute %s" % (namespaceID, functionName)

        return function(*args, **kwargs)


class TestService:
    def TestFunc(self, *args, **kwargs):
        print "SERVER: TestFunc called with", args, kwargs
        return "return value string"


class Server:
    def __init__(self, host, port):
        listenSocket = socket.socket(AF_INET, SOCK_STREAM)
        listenSocket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        listenSocket.bind((host, port))
        listenSocket.listen(5)
        print "SERVER: Listening"

        self.endpointsByAddress = {}
        self.namespaces = { "testSvc": TestService() }

        self.tasklet = stackless.tasklet(self.AcceptConnections)(listenSocket)

    def AcceptConnections(self, listenSocket):
        while True:
            self.AcceptEndpointConnection(listenSocket)

    def AcceptEndpointConnection(self, listenSocket):
        clientSocket, clientAddress = listenSocket.accept()
        print "SERVER: Accepted connection from", clientAddress
        print "SERVER: Client socket", id(clientSocket._sock)
        self.endpointsByAddress[clientAddress] = ServerEndPoint(self, clientSocket)

    def Shutdown(self):
        print "SERVER: Shutting down the server"
        self.tasklet.kill()


if __name__ == "__main__":
    Run()
