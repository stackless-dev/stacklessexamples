#!/usr/bin/env python
"""
Webserver.py
Andrew Francis
March 1st, 2007

Example of Twisted and Stackless integration that
blocks.

The server listens on http://localhost:8000

The programme is fine for many purposes. However there is a
flaw. Whenever the server tasklet blocks, it blocks the entire
programme. Ideally other tasklets, such as the Tick tasklet should
run while the server tasklet waits for connections.
"""

# If you have any questions related to this example:
#
# - If they are related to how Twisted works, please contact the
#   Twisted mailing list:
#
#     http://twistedmatrix.com/cgi-bin/mailman/listinfo/twisted-python
#
# - If they are related to how Stackless works, please contact
#   the Stackless mailing list:
#
#     http://www.tismer.com/mailman/listinfo/stackless
#
# Otherwise if they are related to how Twisted works in conjunction with
# Stackless, please contact the Stackless mailing list:
#
#   http://www.tismer.com/mailman/listinfo/stackless

import time
import stackless
from twisted.web           import http

class Server(object):

    def execute(self, port, requestChannel):
        MyRequestHandler.requestChannel = requestChannel
        reactor.listenTCP(port, MyHttpFactory())
        reactor.run()


class Cgi(object):
    def __init__(self, name, channel):
        self.name = name
        self.channel = channel
        self.count = 0
        return

    def execute(self):
        while (1):

            replyChannel = self.channel.receive()
            replyChannel.send("<html><body>" + \
                               self.name + "count :" + str(self.count) + \
            "</body></html>")

            self.count = self.count + 1
            stackless.schedule()


def tick():
    count = 0
    while (1):
        print "tick: ", count
        count += 1
        stackless.schedule()



class MyRequestHandler(http.Request):

    def process(self):
        """
        send back a unique channel that identifies the request handler
        """
        replyChannel = stackless.channel()
        MyRequestHandler.requestChannel.send(replyChannel)
        result = replyChannel.receive()
        self.write(result)
        self.finish()


class MyHttp(http.HTTPChannel):
    requestFactory = MyRequestHandler


class MyHttpFactory(http.HTTPFactory):
    protocol = MyHttp


if __name__ == "__main__":
    from twisted.internet import reactor

    channel = stackless.channel()

    cgiTasklet = Cgi("cgiTasklet-1", channel)
    server = Server()

    stackless.tasklet(cgiTasklet.execute)()
    stackless.tasklet(server.execute)(8000, channel)
    print "Web Server started"
    stackless.tasklet(tick)()

    print "entering main loop"
    while (stackless.getruncount() > 1):
        stackless.schedule()
