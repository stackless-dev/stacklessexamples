# Twisted and Stackless - example 3
#
# In this example, most of the time is spent in the twisted event loop. This
# approach allows you to control the granularity of tasklet execution based on
# deferred operations a tasklet waits on. At 30fps, a timer executes that
# prints the fps. A simple tasklet begins a deferred operation, and waits for
# the result. During that time, control is returned to the reactor.
#
# Because of the possibility that a deferred operation completes immediately,
# a channel subclass is used to hold the value and return it without any
# rescheduling. stackless.channel.send() would otherwise block the tasklet
# before it could call stackless.channel.receive().
#
# by Greg Hazel
#
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
from twisted.internet import task, reactor, defer
from twisted.python import failure

# a few globals for fun
ideal_fps = 30.0
fps = 0
clock = getattr(time, 'clock', time.time)
last_time = clock()


def frame():
    global fps, last_time

    # a silly fps counter
    this_time = clock()
    d = 1.0 / (this_time - last_time)
    fps = (fps + d) / 2.0
    last_time = this_time
    print fps
    

# start the timer
t = task.LoopingCall(frame)
t.start(1.0/ideal_fps)


# a fake operation that returns a defered
def deferredOp():
    
    df = defer.Deferred()

    # complete in 0.5 seconds
    reactor.callLater(0.5, df.callback, "result!")
    # a deferred that completed already
    #df.callback("result!")
    
    # we could also fake an error
    #reactor.callLater(0.5, df.errback, failure.Failure(Exception("failed")))
    # a deferred that failed already
    #df.errback(failure.Failure(Exception("failed")))
    
    return df


# a stackless channel which can hold a single value without scheduling.
# handy for tasklets that might send data to themselves before calling receive.
class NWChannel(stackless.channel):

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
    

def good(r, me, return_channel):
    return_channel.send_nowait(r)
    # if the deferred is called back immediately, this function will be called
    # from the original tasklet. no need to reschedule.
    if stackless.getcurrent() != me:
        stackless.schedule()

def bad(f, me, return_channel):
    return_channel.send_exception_nowait(f.type, f.value)
    # if the deferred fails immediately, this function will be called
    # from the original tasklet. no need to reschedule.
    if stackless.getcurrent() != me:
        stackless.schedule()

def tasklet():
    return_channel = NWChannel()
    me = stackless.getcurrent()

    while True:
        # a deferred operation
        df = deferredOp()

        df.addCallback(good, me, return_channel)
        df.addErrback(bad, me, return_channel)
        x = return_channel.receive()
        print x

        # don't loop forever
        if not reactor.running:
            break

# start the simple tasklet
stackless.tasklet(tasklet)()

# start the reactor
stackless.tasklet(reactor.run)()
# start the stackless scheduler
stackless.run()
