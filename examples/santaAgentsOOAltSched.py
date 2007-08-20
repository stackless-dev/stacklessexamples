import time
import random
import stackless

yieldChannel = stackless.channel()
sleepingTasklets = []

# Utility functions for tasklets to call.

def BeNice():
    """ Signal that the tasklet can be interrupted. """
    yieldChannel.receive()

def sleep(secondsToWait):
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
        print interruptedTasklet
        interruptedTasklet.insert()

#########################################################


class Agent(object):
    def __init__(self):
        self.ch = stackless.channel()
        self.running = True
        stackless.tasklet(self.runAction)()

    def runAction(self):
        while self.running:
            self.action()

    def action(self):
        pass

class santa(Agent):
    def action(self):
        (kind, visitors) = self.ch.receive()
        print {
              "elves":"Ho, ho, ho!  Let's meet in the study!",
              "reindeer":"Ho, ho, ho!  Let's deliver toys!",
        }[kind]
        [v.send(None) for v in visitors]

class secretary(Agent):
    def __init__(self, santa, kind, count):
        super(secretary, self).__init__()
        self.santa = santa
        self.kind = kind
        self.count = count
        self.visitors = []

    def action(self):
        visitor = self.ch.receive()
        self.visitors.append(visitor)
        if len(self.visitors) == self.count:
            self.santa.ch.send((self.kind, self.visitors))
            self.visitors = []
        stackless.schedule()

class worker(Agent):
    def __init__(self, sec, message):
        super(worker,self).__init__()
        self.sec = sec
        self.message = message

    def action(self):
        sleep(random.randint(0, 3))
        self.sec.ch.send(self.ch)
        self.ch.receive()
        print self.message
        stackless.schedule()

if __name__ == '__main__':
    sa = santa()
    edna = secretary(sa, "elves", 3)
    robin = secretary(sa, "reindeer", 9)

    for i in xrange(21):
        worker(edna, " Elf %d meeting in the study." % (i))
    for i in xrange(10):
        worker(robin, " Reindeer %d delivery toys." % (i))

    stackless.schedule = BeNice

    exitScheduler = False
    while not exitScheduler:
        ScheduleTasklets()

