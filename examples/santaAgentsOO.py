import time
import random
import stackless

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

sleep = Sleep().Sleep

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

    stackless.run()


