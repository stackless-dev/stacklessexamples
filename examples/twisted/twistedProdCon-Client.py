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
import random
import time
from twisted.spread import pb
from twisted.internet import reactor, task
from twisted.cred import credentials
from twisted.internet.error import *

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
              elif stackless.getruncount == 1:
                  # We are the only tasklet running, the rest are blocked on channels sleeping.
                  # We can call time.sleep until the first awakens to avoid a busy wait.
                  delay = endTime - time.time()
                  #print "wait delay", delay
                  time.sleep(max(delay,0))
          stackless.schedule()

Sleep = Sleep().Sleep

class NWChannel(stackless.channel):
    '''
    Greg Hazel's twisted_yield.py example
    '''
    def send_nowait(self, v):
        if self.balance == 0:
            self.value = v
        else:
            self.send(v)

    def send_exception_nowait(self, type, value):
        if self.balance == 0:
            self.exc = (type, value)
        else:
            self.send_exception(type, value)

    def receive(self):
        if hasattr(self, 'value'):
            v = self.value
            del self.value
            return v
        if hasattr(self, 'exc'):
            type, value = self.exc
            del self.exc
            raise type, value
        return stackless.channel.receive(self)

def blockOn(d, timeout=999):
    """
    Use me in stacklessy-code to wait for a Deferred to fire.
    If the result is an failure, send the exception via the channel
    to be captured by the tasklet.
    The timeout parameter is passed in seconds, defaults to 999 seconds
    and returns an exception.
    """
    ch = NWChannel()
    me = stackless.getcurrent()
    def goodCB(r, me, return_channel):
        cancelTimeout()
        return_channel.send_nowait(r)
        # if the deferred is called back immediately, this function will be called
        # from the original tasklet. no need to reschedule.
        if stackless.getcurrent() != me:
            stackless.schedule()

    def badCB(f, me, return_channel):
        cancelTimeout()
        return_channel.send_exception_nowait(f.type, f.value)
        # if the deferred fails immediately, this function will be called
        # from the original tasklet. no need to reschedule.
        if stackless.getcurrent() != me:
            stackless.schedule()

    def onTimeout(me, return_channel):
        return_channel.send_exception_nowait("TimeoutException", "Defer Timeout")
        if stackless.getcurrent() != me:
            stackless.schedule()

    def cancelTimeout():
        if delayedCall.active():
           delayedCall.cancel()

    delayedCall = reactor.callLater(timeout, onTimeout, me, ch)
    d.addCallback(goodCB, me, ch)
    d.addErrback(badCB, me, ch)
    return ch.receive()

class Agent(object):
    '''
    This class is the base for the producer and consumer classes
    It contains all init stuff and execution skeleton.
    '''
    def __init__(self, name, login, password):
        self.me = stackless.tasklet(self.runAction)()
        self.name = name
        self.items = 0
        self.time = random.random()
        self.login = login
        self.pwd = password

    def runAction(self):
        factory = pb.PBClientFactory()
        try:
            reactor.connectTCP("localhost", 8800, factory)
            def1 = factory.login(credentials.UsernamePassword(self.login, self.pwd))
            self.perspective = blockOn(def1, 3) # Wait 3 seconds to login, then timeout.
        except ConnectionRefusedError, val:
            print "Connection could not be opened."
            exit()
        except "TimeoutException":
               print "Timeout exception"
               exit()
        except:
            print "MISC ERROR"
            exit()

        #print "got perspective ref:", self.perspective
        self.connected = 1
        self.kill = False
        
        def1 = self.perspective.callRemote("getqueuesize")
        self.qmaxsize = blockOn(def1)
        while not self.kill:
            self.action()
    
    def action(self):
        pass


class Producer(Agent):
    def __init__(self, name, login, password):
        Agent.__init__(self, name, login, password)

    def action(self):
        # gets the queue size for the first time
        def1 = self.perspective.callRemote("getqueue")
        self.qsize = blockOn(def1)

        while self.qsize+1 < self.qmaxsize:
            if self.qsize < 5:
                print self.name, "sleeping time"
                Sleep(self.time)
            else:
                print self.name, "sleeping 2*time"
                Sleep(self.time*2)
            # asks the queue for its size
            def1 = self.perspective.callRemote("getqueue")
            self.qsize = blockOn(def1)
            # puts 1 production unit into queue
            def1 = self.perspective.callRemote("put", 1)
            resp = blockOn(def1)
            print self.name, " put ", resp
            self.items += resp
        else:
            # queue is full, no work to be done, just sleep
            print self.name, " sleeping"
            Sleep(self.time)


class Consumer(Agent):
    def __init__(self, name, login, password):
        Agent.__init__(self, name, login, password)
    
    def action(self):
        # gets the queue size for the first time
        def1 = self.perspective.callRemote("getqueue")
        self.qsize = blockOn(def1)

        while self.qsize > 0:
            if self.qsize > 5:
                print self.name, "sleeping time"
                Sleep(self.time)
            else:
                print self.name, "sleeping 2*time"
                Sleep(self.time*2)
            # asks the queue for its size
            def1 = self.perspective.callRemote("getqueue")
            self.qsize = blockOn(def1)

            # gets 1 production unit from queue
            def1 = self.perspective.callRemote("get", 1)
            resp = blockOn(def1)
            print self.name, " got ", resp
            self.items += resp
        else:
            # queue is empty, no work to be done, just sleep
            print self.name, " sleeping"
            Sleep(self.time)

def main():
    PID = 0
    CID = 0
    num_prod = 10                # Number of starting producers
    num_cons = 10                # Number of starting consumers

    for i in range(num_prod):
        ID = PID
        name = "P"+str(ID)
        a = Producer(name,"producer", "prod")
        PID += 1

    for i in range(num_cons):
        ID = CID
        name = "C"+str(ID)
        a = Consumer(name, "consumer", "cons")
        CID += 1

    t = task.LoopingCall(stackless.schedule).start(0.0001)
    re = stackless.tasklet(reactor.run)()
    stackless.run()

if __name__ == "__main__":
    main()
