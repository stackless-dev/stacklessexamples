#
# A demonstration of how channels are allow interthread communication.
#
# Author: Richard Tew <richard.m.tew@gmail.com>
#
# This code was written to serve as an example of Stackless Python usage.
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#
# FURTHER DETAIL:
#
#   Sending or receiving on a channel when there is a waiting tasklet
#   from another thread, will always block and schedule the tasklet
#   on the other thread.  The channel 'preference' attribute has no
#   effect on this behaviour.  This may not be the most optimal way
#   to do sleeping and it might be better to have per-thread
#   management of sleepers.
#

import threading
import stackless
import time

# Flag which should allow the threads to exit if cleared.
running = True

# Altered boilerplate Sleep function.
sleepingTasklets = []
sleepCountByThread = {}
threadIDByChannelID = {}
lock = threading.Lock()

def GetThreadID():
    return id(threading.currentThread())

def Sleep(secondsToWait):
    global sleepingTasklets, lock, threadIDByChannelID, sleepCountByThread

    channel = stackless.channel()
    endTime = time.time() + secondsToWait
    threadID = GetThreadID()

    lock.acquire(True)
    sleepCountByThread[threadID] = sleepCountByThread.get(threadID, 0) + 1
    threadIDByChannelID[id(channel)] = threadID
    sleepingTasklets.append((endTime, channel))
    sleepingTasklets.sort()
    lock.release()

    # Block until we get sent an awakening notification.
    channel.receive()

def ManageSleepingTasklets(threadID):
    global sleepingTasklets, lock, running, threadIDByChannelID, sleepCountByThread

    sleepingTasklets = []
    while running:
        if len(sleepingTasklets):
            lock.acquire(True)
            endTime = sleepingTasklets[0][0]
            if endTime <= time.time():
                channel = sleepingTasklets[0][1]
                del sleepingTasklets[0]
                threadID = threadIDByChannelID[id(channel)]
                sleepCountByThread[threadID] -= 1
                lock.release()

                # We have to send something, but it doesn't matter what as it is not used.
                channel.send(None)
            else:
                lock.release()
        elif stackless.getruncount() == 1:
            # Give up if there are no more sleeping tasklets.  Otherwise the two
            # threads keep on running endlessly.
            print "Sleeping tasklet exited due to no remaining work."
            break
        stackless.schedule()
    else:
        print threadID, "Sleeping tasklet exited due to change in 'running' flag"

# ...

def looping_tasklet(threadID, taskletID):
    n = 3
    while n > 0:
        n -= 1
        print threadID, "looping_tasklet", taskletID, "loop", n
        Sleep(1.0)
    print threadID, "looping_tasklet", taskletID, "exit"


def a_main_tasklet():
    global running

    threadID = GetThreadID()

    for i in range(3):
        stackless.tasklet(looping_tasklet)(threadID, i+1)

    # We need to catch the keyboard interrupt and signal the other thread to exit.
    try:
        print threadID, "start: runcount", stackless.getruncount()

        # Do a preliminary run to get some tasklets in the scheduler or some
        # sleeping tasklets in place, otherwise we would not run at all.
        stackless.run()

        # Now we should be set to run until we are done.
        while running and (stackless.getruncount() > 1 or sleepCountByThread.get(threadID, 0)):
            print threadID, "start: runcount", stackless.getruncount(), "sleepcount", sleepCountByThread.get(threadID, 0)
            stackless.run()
        print threadID, "stop: runcount", stackless.getruncount(), "sleepcount", sleepCountByThread.get(threadID, 0)
    except:
        running = False
        raise

if __name__ == "__main__":
    threadID = GetThreadID()

    stackless.tasklet(ManageSleepingTasklets)(threadID)

    thread = threading.Thread(target=a_main_tasklet)
    thread.start()

    a_main_tasklet()
