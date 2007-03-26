#
# This is a small producer-consumer application integrated with PyQt.
#
# Author: Carlos Eduardo de Paula
#
# The application uses no threads, all is done by tasklets, simple but
# is valid and can be extended.
#
# If you have any questions about this example, please feel free to
# contact the Stackless mailing list.  You can subscribe at this
# address:
#
#     http://www.tismer.com/mailman/listinfo/stackless
#

import stackless
import time
import random
import sys
from PyQt4 import QtGui, QtCore

from ProdConPyQt_ui import Ui_MainWindow

# Nice way to put the tasklet to sleep - from stackless.com wiki/Idioms
##########################################################
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

Sleep = Sleep().Sleep

##########################################################

class Agent(object):
    def __init__(self, name=None):
        self.ch = stackless.channel()
        self.name = name
        self.items = 0
        self.kill = False
        self.t = stackless.tasklet(self.runAction)()

    def runAction(self):
        while not self.kill:
            self.action()

    def action(self):
        pass

class Queue(object):
    def __init__(self, name):
        self.queue_start=0
        self.qt = self.queue_start
        self.max_size = 100
        self.running = False
        self.kill = False
        self.produced = 0
        self.consumed = 0
        self.q_empty = 0
        self.q_full = 0
        self.producers = []
        self.consumers = []

    def put(self, qty=1, who=None):
        if self.qt+qty < self.max_size:
            self.qt += qty
            self.produced += 1
        else:
            self.q_full += 1

    def get(self, qty=1, who=None):
        if self.qt >= qty:
            self.qt -= qty
            self.consumed += 1
        else:
            self.q_empty += 1


class Producer(Agent):
    def __init__(self,name, queue):
        Agent.__init__(self, name)
        self.time = random.random()
        self.items = 0
        self.queue = queue
        self.queue.producers.append(self)

    def action(self):
        while self.queue.running:
            if self.queue.qt < 5:
                Sleep(self.time)
            else:
                Sleep(self.time*2)
            self.queue.put(1, self.name)
            self.items += 1
        else:
            Sleep(self.time)

class Consumer(Agent):
    def __init__(self, name, queue):
        Agent.__init__(self, name)
        self.time = random.random()
        self.queue = queue
        self.queue.consumers.append(self)
    def action(self):
        while self.queue.running:
            self.queue.get(1, self.name)
            self.items += 1
            if self.queue.qt < 5:
                Sleep(self.time*2)
            else:
                Sleep(self.time)
        else:
            Sleep(self.time)

##########################################################################

class mainWindow(QtGui.QMainWindow):
    def __init__(self):
        QtGui.QMainWindow.__init__(self)

        # Set up the user interface from Designer.
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.connect(self.ui.start, QtCore.SIGNAL("clicked()"),self.start) # <- Button
        self.connect(self.ui.stop, QtCore.SIGNAL("clicked()"),self.stop) # <- Button
        self.connect(self.ui.add, QtCore.SIGNAL("clicked()"),self.addtoqueue) # <- Button
        self.connect(self.ui.addprod, QtCore.SIGNAL("clicked()"),self.addprod) # <- Button
        self.connect(self.ui.addcons, QtCore.SIGNAL("clicked()"),self.addcons) # <- Button

        self.started = False
        self.killtasks = False
        self.q = Queue("Queue")
        self.PID = 0
        self.CID = 0

    def closeEvent(self, event):
        self.killtasks = True
        try:
            for p in self.q.producers:
                p.kill = True
            for c in self.q.consumers:
                c.kill = True
            self.sleepMan.kill()
            self.showReport()
        except: pass

    def start(self):
        if self.started: 
            self.q.running = True
            self.ui.statusbar.showMessage("Running")
            return
        self.ui.statusbar.showMessage("Starting up...")
        self.started = True
        self.q.running = True
        self.monit = stackless.tasklet(self.monitor)()
        self.ui.queue.setMaximum(self.q.max_size)
        
        for i in range(num_prod):
            self.addprod()

        for i in range(num_cons):
            self.addcons()       
       
        self.ui.statusbar.showMessage("Running")
        stackless.run()
        

    def stop(self):
        self.q.running = False
        self.ui.statusbar.showMessage("Stopped")
        
    def addprod(self):
        ID = self.PID
        name = "P"+str(ID)
        a = Producer(name, self.q)
        self.PID += 1

    def addcons(self):
        ID = self.CID
        name = "C"+str(ID)
        a = Consumer(name, self.q)
        self.CID += 1
        
    def addtoqueue(self):
        self.q.qt += 10
        
    def monitor(self):
        while not self.killtasks:
            QtGui.QApplication.processEvents()
            self.ui.queue.setValue(self.q.qt)
            self.ui.prod.setText(str(len(self.q.producers)))
            self.ui.cons.setText(str(len(self.q.consumers)))
            Sleep(0.033)
            #stackless.schedule()
        
    def showReport(self):
        print
        print "--------------------------"
        for p in self.q.producers:
            print "Producer", p.name , "produced: ", p.items, "items. Each production took: ", p.time
        print
        for c in self.q.consumers:
            print "Consumer", c.name , "consumed: ", c.items, "items. Each consuption took: ", c.time
        print "--------------------------"
        print "Produced units: ", self.q.produced
        print "Consumed units: ", self.q.consumed
        print "Left in queue: ", self.q.qt
        print
        print "Queue became zero ", self.q.q_empty, " times."
        print "Queue became full ", self.q.q_full, " times."
        print
        print "--------------------------"

        

###########################################################

num_prod = 10                # Number of starting producers
num_cons = 10                # Number of starting consumers


def main(args):
    app = QtGui.QApplication(sys.argv)
    mainwindow = mainWindow()
    mainwindow.show()
    sys.exit(app.exec_())

if __name__=="__main__":
    main(sys.argv)













