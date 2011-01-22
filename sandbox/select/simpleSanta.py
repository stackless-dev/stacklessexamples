#!/usr/bin/env python
"""
simpleSanta.py
Andrew Francis
December 1st, 2010

The purpose of simpleSanta is as follows:

1) Show a solution to the Santa Claus problem using the select
2) Implement an improvement to the select statement
3) Give hints as to why a solution with Join conditions may be easier

for now, we leave out priority to reindeer - hence simple

simpleSanta.py should be used with stackless_v2.py 

"""

import random

import time
import sys

from twisted.internet                                 import reactor
from twisted.internet                                 import task
from twisted.python.failure                           import Failure

import stackless

# we can use ETIME and RTIME to control how long reindeers and elves wait
# before asking questions

RTIME = (10,12)
ETIME = (1,12)


def tick(seconds):
    tickCh = stackless.channel()
    reactor.callLater(seconds, tickCh.send, None)
    tickCh.receive()


def startTwisted():
    reactor.run()


def stopTwisted():
    reactor.callLater(1, reactor.stop)
    print "that's all folks"


"""
a way of telling the tasklets that Santa tasklet is done
"""
def acceptChannels(channels, status):
    for name, channel in channels:
        channel.send(status)


def worker(ch, name, theRange):
    myChannel = stackless.channel()
    while True:
       waitTime = random.randint(theRange[0], theRange[1])
       tick(waitTime)
       ch.send((name, myChannel))
       answer = myChannel.receive()


def deliveryToys(reindeer):
    print "All the reindeer have arrived - delivering toys"


def consultWithSanta(elves):
    print "Santa consulting with elves"
    acceptChannels(elves, True)


def harness(reindeer):
    print "harnessing"


def unharness(reindeer):
    print "unharnessing"
    acceptChannels(reindeer, True)
    

def santa(reindeer, elves):
    reindeerCases = [ch.receiveCase() for name, ch, waitTime in reindeer]
    elvesCases = [ch.receiveCase() for name, ch, waitTime in elves]
    reindeerQueue = []
    elvesQueue = []

    cases = reindeerCases + elvesCases

    while True:
        ch = stackless.select(cases)
        print ch.value
        if ch in reindeerCases: 
           reindeerQueue.append(ch.value)
           if len(reindeerQueue) == 9:
              harness(reindeerQueue)
              deliveryToys(reindeerQueue)
              unharness(reindeerQueue)
              reindeerQueue = []
        elif ch in elvesCases:
           elvesQueue.append(ch.value)
           if len(elvesQueue) == 3:
              consultWithSanta(elvesQueue)
              elvesQueue = []
        else:
           print "WHAT?"

    stopTwisted()
    print "Twisted is dead"


def makeWorkers(workers):
    for name, ch, waitTime in workers:
        stackless.tasklet(worker)(ch, name, waitTime)
    return 


if __name__ == "__main__":
   random.seed()
   reindeers = [(reindeer, stackless.channel(), RTIME) for reindeer in \
               ["DANCER", "PRANCER", "VIXEN", "COMET", "CUPID", "DONER", \
                "DASHER", "BLITZEN", "RUDOLPH"]]

   elves = [(elf, stackless.channel(), ETIME) for elf in \
            ['A','B','C','D','E','F','G','H','I','J']]

    
   makeWorkers(reindeers)
   makeWorkers(elves)

   l = task.LoopingCall(stackless.schedule)
   l.start(.001)
   stackless.tasklet(startTwisted)()
   stackless.tasklet(santa)(reindeers, elves)
   stackless.run()
