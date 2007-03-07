#
# The normal approach to scheduling.
#
# Author: Richard Tew <richard.m.tew@gmail.com>
#
# This code was written to serve as an example of Stackless Python usage.
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#
# Benefits of this approach:
#
# - It is easy to use from the interpreter.
#
# Limitations of this approach:
#
# - If there are no tasklets that run for the life of the application
#   or script then the scheduler may exit when things are not complete.
#   One example of this is when all tasklets which were in the
#   scheduler and did not complete are waiting on channels.
#

import time
import stackless

exitScheduler = False

sleepingTasklets = []

# Utility functions for tasklets to call.

def Sleep(secondsToWait):
    """ Put the current tasklet to sleep for a number of seconds. """
    channel = stackless.channel()
    endTime = time.time() + secondsToWait
    sleepingTasklets.append((endTime, channel))
    sleepingTasklets.sort()
    # Block until we get sent an awakening notification.
    channel.receive()

# Scheduler running related functions.

def ManageSleepingTasklets():
    """ Awaken all tasklets which are due to be awakened. """
    while not exitScheduler:
        while len(sleepingTasklets):
            endTime = sleepingTasklets[0][0]
            if endTime > time.time():
                break
            channel = sleepingTasklets[0][1]
            del sleepingTasklets[0]
            # It does not matter what we send as it is not used.
            channel.send(None)
        stackless.schedule()


def Run():
    def Test(n):
        global exitScheduler
        while n:
            print n, "Sleep"
            Sleep(1.0)
            n -= 1
        exitScheduler = True

    stackless.tasklet(Test)(10)
    stackless.tasklet(ManageSleepingTasklets)()

    # This will run until there are no scheduled tasklets.  But because we
    # create one to manage the sleeping tasklets this will mean it will run
    # indefinitely.
    stackless.run()

if __name__ == '__main__':
    Run()
