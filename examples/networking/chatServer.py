#
# An example that uses stacklesssocket to provide a chat like application.
# The users connect via telnet to the IP:port of the server and type in any
# text and all users connected receives it.
# The server identifies an special character to close the connection and handle
# the connected client list.
#
# The example is based on mud.py but uses the standard dispatcher creating a
# tasklet for each connected client.
#
# Author: Carlos Eduardo de Paula <carlosedp@gmail.com>
#
# This code was written to serve as an example of Stackless Python usage.
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#
# But a better place to discuss Stackless Python related matters is the
# mailing list:
#
#   http://www.tismer.com/mailman/listinfo/stackless
#

import sys, time
import stackless

import stacklesssocket
sys.modules["socket"] = stacklesssocket
import socket

class Server(object):
    def __init__(self, conn):
        self.clients = {}
        # Create an INET, STREAMing socket
        self.serversocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.serversocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Bind the socket to an addres, and a port
        self.serversocket.bind(conn)
        # Become a server socket
        self.serversocket.listen(5)
        stackless.tasklet(self.acceptConn)()

    def acceptConn(self):
        while self.serversocket.accepting:
            # Accept connections from outside
            (clientsocket, address) = self.serversocket.accept()
            # Now do something with the clientsocket
            # In this case, each client is managed in a tasklet
            stackless.tasklet(self.manageSocket)(clientsocket, address)
            stackless.schedule()

    def manageSocket(self, clientsocket, address):
        # Record the client data in a dict
        self.clients[clientsocket] = address
        print "Client %s:%s connected..." % (address[0],address[1])
        # For each send we expect the socket returns 1, if its 0 an error ocurred
        if not clientsocket.send('Connection OK\n\rType q! to quit.\n\r>'):
            clientsocket.close()
            return
        data = ''
        while clientsocket.connected:
            data += clientsocket.recv(4096)
            if data == '':
                break
            # If we detect a \n filter the event
            if '\n' in data:
                if data == '\r\n':
                    if not clientsocket.send("Unknown command.  Type 'help' to see a list of available commands.\r\n>"):
                        break
                elif data == 'q!\r\n':
                    # If the user sends a q!, close the connection and remove from list
                    print "Closed connection for %s:%s" % (address[0],address[1])
                    del self.clients[clientsocket]
                    break
                elif data == 'help\r\n':
                    # Display available commands
                    clientsocket.send("Commands:\r\n")
                    for verb in ["look - Who is online", "help - Display this.", "q! - Quit"]:
                        clientsocket.send("  "+ verb +"\r\n")
                    clientsocket.send(">")
                elif data == 'look\r\n':
                    # Show the connected clients
                    clientsocket.send("There are %d users connected:\r\n" % len(self.clients))
                    clientsocket.send("Name\tHost\t\tPort\r\n")
                    clientsocket.send("-" * 40 +"\r\n")
                    for clientIP, clientPort in self.clients.itervalues():
                        clientsocket.send("Unknown\t"+ str(clientIP) +"\t"+ str(clientPort) +"\r\n")
                    clientsocket.send(">")
                else:
                    # Send the message to all connected clients
                    for client in self.clients:
                        if client is clientsocket:
                            if not client.send('\rYou said: %s>' % data):
                                break
                        else:
                            if not client.send('\rClient %s said: %s>' % (address,data)):
                                break
                data = ''
            stackless.schedule()
        clientsocket.close()

if __name__ == "__main__":
    host = "127.0.0.1"
    port = 3000
    print "Starting up server on IP:port %s:%s" % (host, port)
    s = Server((host,port))
    stackless.run()

