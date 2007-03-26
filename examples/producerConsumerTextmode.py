# 
# Almost the same Producer/Consumer example from PyQt but without
# the graphical interface, the queue status is printed in console.
#
# by Carlos Eduardo de Paula <carlosedp@gmail.com>
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

import stackless
import time
import random

# Nice way to put the tasklet to sleep - from stackless.com wiki/Idioms
##########################################################
sleepingTasklets = []

def Sleep(secondsToWait):
    channel = stackless.channel()
    endTime = time.time() + secondsToWait
    sleepingTasklets.append((endTime, channel))
    sleepingTasklets.sort()
    # Block until we get sent an awakening notification.
    channel.receive()

def ManageSleepingTasklets():
    while True:
     if len(sleepingTasklets):
       endTime = sleepingTasklets[0][0]
       if endTime <= time.time():
         channel = sleepingTasklets[0][1]
         del sleepingTasklets[0]
         # We have to send something, but it doesn't matter what as it is not used.
         channel.send(None)
       elif stackless.getruncount() == 1:
         # We are the only tasklet running, the rest are blocked on channels sleeping.
         # We can call time.sleep until the first awakens to avoid a busy wait.
         delay = endTime - time.time()
         #print "wait delay", delay
         time.sleep(max(delay,0))
     stackless.schedule()

stackless.tasklet(ManageSleepingTasklets)()

##########################################################

def printStatus(reporter):
     print reporter + " " * (3 - len(reporter)) + "[" + "#" * len(queue) + " " * (q_size-len(queue))  + "] Qty:" , len(queue) , "\r",
     time.sleep(0.05)  # so we have time to see the displayed data
     # keep in mind that this call to time.sleep will stall
     # all tasklets stop until time.sleep returns

def producer(who,sleeptime):
    global full_queue
    while True:
        if (len(queue) < q_size):
            queue.append("#")
            p_counter[int(who)] += 1
            printStatus('P'+who)
            if len(queue) < q_size/4:
                Sleep(sleeptime)
            else:
                Sleep(sleeptime*1.5)
        else:
            full_queue += 1
            stackless.schedule()

def consumer(who,sleeptime):
    global zero_queue
    while True:
       if (len(queue) >= 1):
           queue.pop()
           c_counter[int(who)] += 1
           printStatus('C'+who)
           if len(queue) < q_size/4:
               Sleep(sleeptime*1.5)
           else:
               Sleep(sleeptime)
       else:
           zero_queue += 1
           stackless.schedule()
'''
def watch():
    while True:
        if len(sleepingTasklets) <= 0:
        stackless.schedule()

stackless.tasklet(watch)()	
'''

def launch_p (ind,sleeptime):         # Launches and initializes the producers lists
    producers.append(int(ind))
    p_counter.append(0)
    producers[int(ind)] = stackless.tasklet(producer)(ind,sleeptime)

def launch_c (ind,sleeptime):         # Launches and initializes the consumers lists
    consumers.append(int(ind))
    c_counter.append(0)
    consumers[int(ind)] = stackless.tasklet(consumer)(ind,sleeptime)

#-------------------- Configuration --------------------------------

q_size = 60                 # Defines the queue size
queue = ["#"] * 0           # Defines the queue start size

producers = []              # List to reference the producers
consumers = []              # List to reference the consumers
p_counter = []              # Counter to hold how much units each producer inserted in queue
c_counter = []              # Counter to hold how much units each consumer removed from queue

num_prod = 5                # Number of starting producers
num_cons = 5                # Number of starting consumers

zero_queue = 0
full_queue = 0

for p in range(num_prod):
    sl = random.random()
    launch_p(repr(p),sl)

for c in range(num_cons):
    sl = random.random()
    launch_c(repr(c),sl)


try:
    stackless.run()

# Handle the keyboard interruption and prints the production report

except KeyboardInterrupt:
    print ""
    print "** Detected ctrl-c in the console"
    exit

total_p = 0
total_c = 0

print
for p in range(0,len(producers)):
    print "Producer", p , "produced: ", p_counter[p]
    total_p += p_counter[p]
for c in range(0,len(consumers)):
    print "Consumer", c , "consumed: ", c_counter[c]
    total_c += c_counter[c]
print
print "Produced units: ", total_p
print "Consumed units: ", total_c
print "Left in queue: ", len(queue)
print

print "Queue became zero ", zero_queue, " times."
print "Queue became full ", full_queue, " times."

print "Press enter to finish" , raw_input()
