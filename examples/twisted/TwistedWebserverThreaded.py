#!/usr/bin/env python
"""
ThreadedWebserver.py
Andrew Francis
March 1st, 2007

Example of Twisted and Stackless integration that allows non-blocking
tasklets to execute

The server listens on http://localhost:8000

Unlike the previous example, ThreadedWebserver runs Stackless in a
separate thread. While Twisted is blocked waiting for connections,
the tick tasklet (or any other tasklet) can execute.

As per Carlos's de Paula's observation, a time.sleep is included to
increase performance. I suspect the Global interpreter lock is playing
a role. On my machine time.sleep(.01) is fine. at .001, the server will
fail after multiple uses.
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
        MyRequestHandler.channel = requestChannel
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
                               self.name + " count :" + str(self.count) + \
            "</body></html>")

            self.count = self.count + 1
            stackless.schedule()


def tick():
    count = 0
    while (1):
        count += 1
        print count
        time.sleep(.005)
        stackless.schedule()



class MyRequestHandler(http.Request):

    def process(self):
        replyChannel = stackless.channel()
        channel.send(replyChannel)
        result = replyChannel.receive()
        self.write(result)
        self.finish()


class MyHttp(http.HTTPChannel):
    requestFactory = MyRequestHandler


class MyHttpFactory(http.HTTPFactory):
    protocol = MyHttp


def stacklessThread(requestChannel):

    cgiTasklet = Cgi("cgiTasklet-1", requestChannel)
    stackless.tasklet(cgiTasklet.execute)()

    """
    in this example, if the tick tasklet did not exist,
    Stackless would complain about deadlock since the
    last runnable tasklet (cgiTasklet) would be blocked
    """
    stackless.tasklet(tick)()

    while (stackless.getruncount() > 1):
        stackless.schedule()


if __name__ == "__main__":
    from twisted.internet import reactor

    print "ThreadedWebserver"

    channel = stackless.channel()
    reactor.callInThread(stacklessThread,channel)
    Server().execute(8000, channel)
    reactor.run()
