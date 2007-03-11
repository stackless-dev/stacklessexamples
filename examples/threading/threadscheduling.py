#
# A demonstration of how each thread has its own scheduler.
#
# Author: Richard Tew <richard.m.tew@gmail.com>
#
# This code was written to serve as an example of Stackless Python usage.
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#
# FURTHER DETAIL:
#
# This example starts some tasklets on the main thread, and starts a second
# thread as well, starting some tasklets on that.  You should be able to
# see that the scheduler on each thread is unrelated to the one on the
# other, which is why I need to start a ManageSleepingTasklets for each of
# them.
#
# POSSIBLE PROBLEMS:
#
#   If Stackless complains that "run() must be run from the main thread's
#   main tasklet", then you need to get a later version of Stackless.
#   This constraint was removed.
#

import threading
import stackless
import time

_locals = threading.local()
running = True

# Altered boilerplate Sleep function.

def Sleep(secondsToWait):
    channel = stackless.channel()
    endTime = time.time() + secondsToWait
    _locals.sleepingTasklets.append((endTime, channel))
    _locals.sleepingTasklets.sort()
    # Block until we get sent an awakening notification.
    channel.receive()

def ManageSleepingTasklets(threadID):
    global running

    _locals.sleepingTasklets = []
    while running:
        if len(_locals.sleepingTasklets):
            endTime = _locals.sleepingTasklets[0][0]
            if endTime <= time.time():
                channel = _locals.sleepingTasklets[0][1]
                del _locals.sleepingTasklets[0]
                # We have to send something, but it doesn't matter what as it is not used.
                channel.send(None)
        elif stackless.getruncount() == 1:
            # Give up if there are no more sleeping tasklets.  Otherwise the two
            # threads keep on running endlessly.
            break
        stackless.schedule()

# ...

def looping_tasklet(threadID, taskletID):
    n = 3
    while n > 0:
        n -= 1
        print threadID, "looping_tasklet", taskletID, "loop", n
        Sleep(1.0)
    print threadID, "looping_tasklet", taskletID, "exit"


def a_main_tasklet():
    threadID = 2

    stackless.tasklet(ManageSleepingTasklets)(threadID)

    stackless.tasklet(looping_tasklet)(threadID, 1)

    print threadID, "runcount.1", stackless.getruncount()
    stackless.run()

if __name__ == "__main__":
    global running

    threadID = 1

    stackless.tasklet(ManageSleepingTasklets)(threadID)

    stackless.tasklet(looping_tasklet)(threadID, 1)
    stackless.tasklet(looping_tasklet)(threadID, 2)

    print threadID, "runcount", stackless.getruncount()

    thread = threading.Thread(target=a_main_tasklet)
    thread.start()

    try:
        stackless.run()
    except:
        running = False
        raise
