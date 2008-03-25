#
# A very simple MUD server based on the Stackless compatible sockets.
#
# Author: Richard Tew <richard.m.tew@gmail.com>
#
# This code was written to serve as an example of Stackless Python usage.
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#

import sys, traceback, weakref, logging
import stackless

# Monkeypatch in the 'stacklesssocket' module, so we get blocking sockets
# which are Stackless compatible.  This example code will avoid any use of
# the Stackless sockets except through normal socket usage.
import stacklesssocket
#sys.modules["socket"] = stacklesssocket
stacklesssocket.install()
import socket


class RemoteDisconnectionError(StandardError):
    pass


class User:
    def __init__(self, connection):
        self.connection = connection

        # The tasklet will hold a reference to the user keeping the instance
        # alive as long as it is handling commands.
        stackless.tasklet(self.Run)()

    def Run(self):
        global server

        # Notify the server that a user is connected.
        server.RegisterUser(self)
        logging.info("Connected %d from %s", id(self), self.connection.clientAddress)

        try:
            while self.HandleCommand():
                pass

            self.OnUserDisconnection()
        except RemoteDisconnectionError:
            self.OnRemoteDisconnection()
            self.connection = None
        except:
            traceback.print_exc()
        finally:
            if self.connection:
                self.connection.Disconnect()
                self.connection = None

    def HandleCommand(self):
        self.connection.Write("> ")
        line = self.connection.ReadLine()
        words = [ word.strip() for word in line.strip().split(" ") ]
        verb = words[0]

        if verb == "look":
            userList = server.ListUsers()
            self.connection.WriteLine("There are %d users connected:" % len(userList))
            self.connection.WriteLine("Name\tHost\t\tPort")
            self.connection.WriteLine("-" * 40)
            for user in userList:
                host, port = user.connection.clientAddress
                self.connection.WriteLine("Unknown\t"+ str(host) +"\t"+ str(port))
        elif verb == "say":
            line = line[4:]
            secondPartyPrefix = "Someone says: "
            for user in server.ListUsers():
                if user is self:
                    prefix = "You say: "
                else:
                    prefix = secondPartyPrefix
                user.connection.WriteLine(prefix + "\"%s\"" % line)
        elif verb == "quit":
            return False
        elif verb == "help":
            self.connection.WriteLine("Commands:")
            for verb in [ "look", "say", "quit", "help" ]:
                self.connection.WriteLine("  "+ verb)
        else:
            self.connection.WriteLine("Unknown command.  Type 'help' to see a list of available commands.")

        return True

    def OnRemoteDisconnection(self):
        logging.info("Disconnected %d (remote)", id(self))

    def OnUserDisconnection(self):
        logging.info("Disconnected %d (local)", id(self))

class Connection:
    disconnected = False

    def __init__(self, clientSocket, clientAddress):
        self.clientSocket = clientSocket
        self.clientAddress = clientAddress

        self.readBuffer = ""

        self.userID = id(User(self))

    def Disconnect(self):
        if self.disconnected:
            raise RuntimeError("Unexpected call")
        self.disconnected = True
        self.clientSocket.close()

    def Write(self, s):
        self.clientSocket.send(s)

    def WriteLine(self, s):
        self.Write(s +"\r\n")

    def ReadLine(self):
        global server
    
        s = self.readBuffer
        while True:
            # If there is a CRLF in the text we have, we have a full
            # line to return to the caller.
            if s.find('\r\n') > -1:
                i = s.index('\r\n')
                # Strip the CR LF.
                line = s[:i]
                self.readBuffer = s[i+2:]
                while '\x08' in line:
                    i = line.index('\x08')
                    if i == 0:
                        line = line[1:]
                    else:
                        line = line[:i-1] + line[i+1:]
                return line

            # An empty string indicates disconnection.
            v = self.clientSocket.recv(1000)
            if v == "":
                self.disconnected = True
                raise RemoteDisconnectionError
            s += v


class Server:
    def __init__(self, host, port):
        self.host = host
        self.port = port
                
        self.userIndex = weakref.WeakValueDictionary()

        stackless.tasklet(self.Run)()

    def Run(self):
        listenSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listenSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listenSocket.bind((self.host, self.port))
        listenSocket.listen(5)

        logging.info("Accepting connections on %s %s", self.host, self.port)
        try:
            while listenSocket.accepting:
                clientSocket, clientAddress = listenSocket.accept()
                Connection(clientSocket, clientAddress)
                stackless.schedule()
        except socket.error:
            traceback.print_exc()

    def RegisterUser(self, user):
        self.userIndex[id(user)] = user
        
    def ListUsers(self):
        return [ v for v in self.userIndex.itervalues() ]


def Run(host, port):
    global server
    server = Server(host, port)
    while 1:
        stackless.run()

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s %(levelname)s %(message)s')

    try:
        Run("127.0.0.1", 3000)
    except KeyboardInterrupt:
        logging.info("Server manually stopped")
