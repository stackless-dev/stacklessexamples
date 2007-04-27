# Twisted and Stackless - example 2
#
# In this example, a large portion of the time is spent in stackless. This
# approach allows you to control the granularity of tasklet execution based on
# cooperative yield points in the tasklet. At 30fps, a timer executes that
# prints the fps. A simple tasklet just prints "." and yields to the reactor.
# The reactor processes all pending events, then reschedules the tasklet.
#
# This example eats a lot of cpu, because no time is spent blocking - the
# control is constantly being passed back and forth between the reactor and
# stackless.
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


import sys
import time
import stackless
from twisted.internet import task, reactor

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
    print '\n', fps


# start the timer
t = task.LoopingCall(frame)
t.start(1.0/ideal_fps)


def tasklet():

    while True:
        # complicated operation with side-effects
        sys.stdout.write('.')

        # allow the reactor to run all pending events, then come back
        reactor.callLater(0, stackless.schedule)
        stackless.schedule()

        # don't loop forever
        if not reactor.running:
            break


# start the simple tasklet
stackless.tasklet(tasklet)()

# start the reactor
stackless.tasklet(reactor.run)()
# start the stackless scheduler
stackless.run()
