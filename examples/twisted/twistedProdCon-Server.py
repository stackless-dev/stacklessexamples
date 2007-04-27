#
# This example uses Stackless together with Twisted Perspective Broker(PB)
# Perspective Broker (affectionately known as PB) is an asynchronous,
# symmetric network protocol for secure, remote method calls and transferring of objects.
# PB has support for direct or authenticated sessions where the user receives a "Perspective"
# containning the methods it could call.
#
# This example mimics the producer consumer example having the production
# queue (stack) in a server and the producers and consumers accessing it
# over the network using predefined exported methods.
#
# For more information on PB check http://twistedmatrix.com/projects/core/documentation/howto/index.html
#
# The examples provided by Greg Hazel were used to allow the integration between
# tasklets and deferred calls. Also the sleep manager code from Richard Tew to handle
# sleep requests.
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

import stackless
import time
from zope.interface import implements
from twisted.spread import pb
from twisted.cred import checkers, portal, credentials
from twisted.internet import reactor, task

class Sleep(object):
    def __init__(self):
        self.sleepingTasklets = []
        stackless.tasklet(self.ManageSleepingTasklets)()

    def Sleep(self, secondsToWait):
        channel = stackless.channel()
        endTime = time.time() + secondsToWait
        self.sleepingTasklets.append((endTime, channel))
        self.sleepingTasklets.sort()
        # Block until we get sent an awakening notification.
        channel.receive()

    def ManageSleepingTasklets(self):
        while True:
            if len(self.sleepingTasklets):
                endTime = self.sleepingTasklets[0][0]
                if endTime <= time.time():
                    channel = self.sleepingTasklets[0][1]
                    del self.sleepingTasklets[0]
                    # We have to send something, but it doesn't matter what as it is not used.
                    channel.send(None)
                elif stackless.getruncount() == 1:
                    # We are the only tasklet running, the rest are blocked on channels sleeping.
                    # We can call time.sleep until the first awakens to avoid a busy wait.
                    delay = endTime - time.time()
                    #print "wait delay", delay
                    time.sleep(max(delay,0))
            stackless.schedule()

Sleep = Sleep().Sleep

class Queue(object):
    def __init__(self, name):
        self.name = name
        self.queue_start=0
        self.qt = self.queue_start
        self.max_size = 60
        self.running = False
        self.kill = False
        self.produced = 0
        self.consumed = 0
        self.q_empty = 0
        self.q_full = 0
        self.producers = []
        self.consumers = []

    def put(self, qty=1, who=None):
        if self.qt+qty < self.max_size:
            self.qt += qty
            self.produced += 1
        else:
            self.q_full += 1

    def get(self, qty=1, who=None):
        if self.qt >= qty:
            self.qt -= qty
            self.consumed += 1
        else:
            self.q_empty += 1


class Monitor(object):
    '''
    This class monitors the attached queue and prints a representation in terminal
    When its instance is created, a tasklet is created and the monitor starts
    to scan the queue status at 30fps (configurable in the Sleep call)
    This could also be part of the Queue object itself.
    '''
    def __init__(self, queue):
        self.running = 1
        self.queue = queue
        stackless.tasklet(self.run)()

    def run(self):
        print "Started monitor for queue " + self.queue.name
        while self.running:
            print "Size: [" + "#" * self.queue.qt + " " * (self.queue.max_size-self.queue.qt) + "] Qty:" , self.queue.qt , "\r",
            Sleep(0.033)
            #stackless.schedule()


class MyPerspective(pb.Avatar):
    '''
    This perspective is passed to the client when the login phase completes
    It contains all methods accessible by the clients prefixed by perspective_
    A non authentication version could be created using pb.Root, check documentation
    in http://twistedmatrix.com/projects/core/documentation/howto/index.html
    Perspective Broker session.
    '''
    def __init__(self, name):
        global q
        self.queue = q
        self.name = name
    def perspective_getqueue(self):
        return self.queue.qt

    def perspective_getqueuesize(self):
        return self.queue.max_size

    def perspective_put(self, arg):
        self.queue.put(arg)
        return arg

    def perspective_get(self, arg):
        self.queue.get(arg)
        return arg

class MyRealm:
    '''
    The realm handles the user authentications, we could have different
    perspectives for the producer and the consumer where each would have
    access to its methods.
    '''
    implements(portal.IRealm)
    def requestAvatar(self, avatarId, mind, *interfaces):
        assert pb.IPerspective in interfaces
        return pb.IPerspective, MyPerspective(avatarId), lambda:None


p = portal.Portal(MyRealm())
c1 = checkers.InMemoryUsernamePasswordDatabaseDontUse(producer="prod", consumer="cons")
p.registerChecker(c1)
q = Queue('q1')
m = Monitor(q)

reactor.listenTCP(8800, pb.PBServerFactory(p))
t = task.LoopingCall(stackless.schedule).start(0.0001)
re = stackless.tasklet(reactor.run)()
stackless.run()
