#
# One way of timing out tasklets waiting on a channel.
#
# Author: Richard Tew <richard.m.tew@gmail.com>
#
# This code was written to serve as an example of Stackless Python usage.
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#
# Limitations of this approach:
#
# - There is no need to know the order the tasklets are waiting on the
#   channel because of the uniform expiration period so we can assume
#   that the first to expire will be the first in line on the channel
#   and we can remove it by sending an exception.
#

import time, weakref
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


class ChannelWaitExpiration(Exception):
    pass

class TimeLimitedReceiveChannel(stackless.channel):
    def __init__(self, *args, **kwargs):
        self.expirySeconds = 5.0
        self.receiveAddTimes = []

        stackless.channel.__init__(self, *args, **kwargs)

    def receive(self):
        if self.balance > 0:
            # We can return from this immediately.
            return stackless.channel.receive(self)

        if self.balance == 0:
            def ManageWaitingTasklets(c):
                while c.balance < 0:
                    earliestExpirationTime = None
                    for timeAdded, tasklet in self.receiveAddTimes:
                        if not tasklet.blocked:
                            # This tasklet has already been removed but since
                            # it hasn't been scheduled yet it hasn't exited its
                            # call to our receive function and cleared out its
                            # entry.  This can happen if the channel is configured
                            # to schedule waiting tasklets when they receive
                            # rather than running them immediately (i.e. via the
                            # 'preference' attribute).
                            continue
                        if timeAdded + self.expirySeconds < time.time():
                            # This tasklet is guaranteed to be the first tasklet
                            # on the channel.
                            self.send_exception(ChannelWaitExpiration)
                        else:
                            # Otherwise note the time at which the next expiring
                            # tasklet expires so we can sleep until then.  Since
                            # all expiration delays are the same amount of time
                            # from the period of addition, we can guess the
                            # earliest we will need to check next.
                            earliestExpirationTime = timeAdded + self.expirySeconds
                            break
                    # Wait until the earliest we will need to next check.
                    if earliestExpirationTime is None:
                        Sleep(self.expirySeconds)
                    else:
                        Sleep(time.time() - earliestExpirationTime)
            stackless.tasklet(ManageWaitingTasklets)(self)

        t = time.time(), weakref.proxy(stackless.getcurrent())
        self.receiveAddTimes.append(t)
        self.receiveAddTimes.sort()

        try:
            ret = stackless.channel.receive(self)
            self.receiveAddTimes.remove(t)
            return ret
        except:
            # Any exception should be met with the same handling.
            self.receiveAddTimes.remove(t)
            raise

def Run():
    c = TimeLimitedReceiveChannel()
    
    def Test(c):
        global exitScheduler
        t = time.time()
        print "Waiting for %0.1f seconds" % c.expirySeconds
        try:
            c.receive()
        except Exception, e:
            if isinstance(e, ChannelWaitExpiration):
                print "Exited receive, took %0.1f seconds" % (time.time() - t)
            else:
                print "Unexpected exit '%s', took %0.1f seconds" % (str(e), time.time() - t)
        finally:
            exitScheduler = True

    stackless.tasklet(Test)(c)
    stackless.tasklet(ManageSleepingTasklets)()

    # This will run until there are no scheduled tasklets.  But because we
    # create one to manage the sleeping tasklets this will mean it will run
    # indefinitely.
    stackless.run()

if __name__ == '__main__':
    Run()
