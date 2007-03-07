#
# The alternative approach to scheduling.
#
# Author: Richard Tew <richard.m.tew@gmail.com>
#
# This code was written to serve as an example of Stackless Python usage.
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#
# Benefits of this approach:
#
# - It lends itself well to embedding, if implemented in C or C++.
#
# - It allows more precise control.
#
# Limitations of this approach:
#
# - The expectation is that the scheduler will be empty because of this
#   will exit pretty much immediately.  So anything which calls to
#   'stackless.schedule' rather than using 'BeNice' or 'Sleep' will
#   break this scheduling model and prevent it from working as
#   expected.  After all, if there are tasklets in the scheduler it
#   continues to run and does not exit.
#
#   Ideally 'stackless.schedule' should be patched to call BeNice.  Or
#   calls to it just avoided completely.
#

import time
import stackless

yieldChannel = stackless.channel()
sleepingTasklets = []

# Utility functions for tasklets to call.

def BeNice():
    """ Signal that the tasklet can be interrupted. """
    yieldChannel.receive()

def Sleep(secondsToWait):
    """ Put the current tasklet to sleep for a number of seconds. """
    channel = stackless.channel()
    endTime = time.time() + secondsToWait
    sleepingTasklets.append((endTime, channel))
    sleepingTasklets.sort()
    # Block until we get sent an awakening notification.
    channel.receive()

# Scheduler running related functions.

def CheckSleepingTasklets():
    """ Awaken all tasklets which are due to be awakened. """
    while len(sleepingTasklets):
        endTime = sleepingTasklets[0][0]
        if endTime > time.time():
            break
        channel = sleepingTasklets[0][1]
        del sleepingTasklets[0]
        # We have to send something, but it doesn't matter what as it is not used.
        channel.send(None)

def ScheduleTasklets():
    # Only schedule as many tasklets as there are waiting when
    # we start.  This is because some of the tasklets we awaken
    # may BeNice their way back onto the channel.  Well they
    # would
    n = -yieldChannel.balance
    while n > 0:
        yieldChannel.send(None)
        n -= 1
        
    CheckSleepingTasklets()

    # Run any tasklets which need to be scheduled.  As long as the BeNice and
    # Sleep callers do not use schedule they should never be in the scheduler
    # at this point, but rather back in the yield channel or on a sleep channel.
    # Loosely guessing, I would say that only newly created tasklets should
    # ever be in the scheduler.  And nothing should stay in there for that
    # long before moving out by using Sleep or BeNice.  If something does stay
    # in there too long then it is not yielding or is keeping the scheduler
    # running by using 'stackless.schedule' which is not compatible with the
    # way this method intends the scheduler to be used.
    
    interruptedTasklet = stackless.run(1000000)
    if interruptedTasklet:
        # Should really print a stacktrace from the tasklet so it can be
        # rewritten to 'be nice'.  Alternatively the tasklet could be killed
        # at this point if that suits the application.
        interruptedTasklet.insert()

exitScheduler = False

def Run():
    def Test(n):
        global exitScheduler
        while n:
            if n % 2 == 1:
                print n, "BeNice"
                BeNice()
            else:
                print n, "Sleep"
                Sleep(1.0)
            n -= 1
        exitScheduler = True

    # Do 10 iterations.
    stackless.tasklet(Test)(10)

    while not exitScheduler:
        ScheduleTasklets()

if __name__ == '__main__':
    Run()
