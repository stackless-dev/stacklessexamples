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

class Server():
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
            # If the user sends a q!, close the connection and remove from list
            if 'q!\r\n' in data:
                print "Closed connection for %s:%s" % (address[0],address[1])
                del self.clients[clientsocket]
                break
            # If we detect a \n send the message to all clients
            if '\n' in data:
                for client in self.clients:
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

