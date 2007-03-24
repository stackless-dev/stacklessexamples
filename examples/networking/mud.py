#
# A very simple MUD server based on the Stackless compatible sockets.
#
# Author: Richard Tew <richard.m.tew@gmail.com>
#
# This code was written to serve as an example of Stackless Python usage.
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#
# - Could possibly be even simpler if the TelnetConnection class were removed
#   and read/readline were done locally to the MUD code.  Then disconnection
#   detection could be built into the stacklesssocket.dispatcher class.
#

import stackless
import stacklesssocket as socket
import random, time
import traceback

class TelnetConnectionWrapper(socket.stacklesssocket):
    connectionID = None
    disconnectChannel = None

    def __init__(self, sock):
        self.sock = sock
        self.dispatcher = TelnetConnection(sock)

    def close(self):
        # Notify the server.
        if self.disconnectChannel is not None:
            # This will not block.  The channel is set to schedule
            # receivers and return to the sender immediately.
            self.disconnectChannel.send(self)
            self.disconnectChannel = None
        # Do the standard socket closure handling.  But we can't
        # call the underlying function as it doesn't exist on the
        # superclass, and trying to call it there anyway won't get it
        # routed through getattr.
        self.dispatcher.close()

class TelnetConnection(socket.dispatcher):
    echo = False

    def read(self): # TELNET
        ret = self.recvChannel.receive()
        if self.echo:
            if ret == '\x08':
                self.send(ret+" ")
            self.send(ret)
        return ret

    def readline(self): # TELNET
        buf = self.readBufferString

        while True:
            if buf.find('\r\n') > -1:
                i = buf.index('\r\n')
                ret = buf[:i+2]
                self.readBufferString = buf[i+2:]
                while '\x08' in ret:
                    i = ret.index('\x08')
                    if i == 0:
                        ret = ret[1:]
                    else:
                        ret = ret[:i-1]+ret[i+1:]
                return ret

            buf += self.read()

def RunServer(host, port):
    listenSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listenSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listenSocket.bind((host, port))
    listenSocket.listen(5)

    # Connecting sockets should be wrapped in TelnetConnection, rather than
    # stacklesssocket.dispatcher (the default wrapper).
    def wrap_accept_socket(currentSocket):
        return TelnetConnectionWrapper(currentSocket)
    listenSocket.wrap_accept_socket = wrap_accept_socket

    nextConnectionID = 1
    infoByConnectionID = {}
    disconnectChannel = stackless.channel()
    disconnectChannel.preference = 1
    stackless.tasklet(MonitorDisconnections)(disconnectChannel, infoByConnectionID)

    print "Accepting connections on", host, port
    try:
        while listenSocket.accepting:
            clientSocket, clientAddress = listenSocket.accept()
            clientSocket.disconnectChannel = disconnectChannel
            clientSocket.connectionID = nextConnectionID
            print "Received connection #", clientSocket.connectionID, "from", clientAddress
            infoByConnectionID[clientSocket.connectionID] = clientAddress, clientSocket
            nextConnectionID += 1
            stackless.tasklet(MonitorIncomingConnection)(clientSocket, clientAddress, infoByConnectionID)
            stackless.schedule()
    except socket.error:
        print "RunServer.error"
        traceback.print_exc()
    print "RunServer.exit"

def MonitorDisconnections(disconnectChannel, infoByConnectionID):
    print "MonitorDisconnections"
    try:
        while True:
            clientSocket = disconnectChannel.receive()
            print "Received disconnection of #", clientSocket.connectionID, "from", infoByConnectionID[clientSocket.connectionID][0]
            del infoByConnectionID[clientSocket.connectionID]
    except socket.error:
        print "MonitorDisconnections.error"
        traceback.print_exc()
    print "MonitorDisconnections.exit"

def MonitorIncomingConnection(clientSocket, clientAddress, infoByConnectionID):
    clientSocket.send("Welcome to a basic Stackless Python MUD server.\r\n")
    try:
        while clientSocket.connected:
            clientSocket.send("> ")
            line = clientSocket.readline()[:-2].strip()
            words = [ word.strip() for word in line.split(" ") ]
            verb = words[0]

            if verb == "look":
                clientSocket.send("There are %d users connected:\r\n" % len(infoByConnectionID))
                clientSocket.send("Name\tHost\t\tPort\r\n")
                clientSocket.send("-" * 40 +"\r\n")
                for clientAddress2, clientSocket2 in infoByConnectionID.itervalues():
                    clientSocket.send("Unknown\t"+ str(clientAddress2[0]) +"\t"+ str(clientAddress2[1]) +"\r\n")
            elif verb == "say":
                line = line[4:]
                secondPartyPrefix = "Someone says: "
                for clientAddress2, clientSocket2 in infoByConnectionID.itervalues():
                    if clientSocket2 is clientSocket:
                        prefix = "You say: "
                    else:
                        prefix = secondPartyPrefix
                    clientSocket2.send(prefix + "\"%s\"\r\n" % line)
            elif verb == "quit":
                clientSocket.close()
            elif verb == "help":
                clientSocket.send("Commands:\r\n")
                for verb in [ "look", "say", "quit", "help" ]:
                    clientSocket.send("  "+ verb +"\r\n")
            else:
                clientSocket.send("Unknown command.  Type 'help' to see a list of available commands.\r\n")

            stackless.schedule()
    except socket.error:
        print "MonitorIncomingConnection.socket.error"
        traceback.print_exc()

if __name__ == "__main__":
    host = "127.0.0.1"
    port = 3000

    # We do not want this to start as we will run it ourselves.
    socket.managerRunning = True

    t = stackless.tasklet(RunServer)(host, port)
    # ManageSockets will exit if there are no sockets existing, so
    # by running this tasklet once, we will get the listen socket in
    # place before we invoke ManageSockets to run.
    t.run()

    try:
        socket.ManageSockets()
    except KeyboardInterrupt:
        print "** Detected ctrl-c in the console"
    except:
        print "main error"
        traceback.print_exc()
    print "EXIT"
