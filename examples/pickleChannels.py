import stackless
import cPickle as pickle
import sys

"""
Serialisation test
April 27th, 2006
Andrew Francis
"""

running = []

class Foo(object):
    x = 10
    y = 20


class Task(Foo):
    def __init__(self, name, channel):
        self.name = name
        self.channel = channel
        
    def execute(self):
        print "in task ", self.name
        print self.name, " about to sleep"
        message = self.channel.receive()
        print self.name, " woke up", message
        

class P(Foo):
    def __init__(self, name, list, channel):
        self.name = name
        self.tasks = list
        self.running = []
        self.channel = channel
        
    def execute(self):
        print "in task ", self.name
        for task in self.tasks:
            t = stackless.tasklet(task.execute)()
            running.append(t)
            t.run()
            
        print self.name, " about to sleep"
        message = self.channel.receive()
        print self.name, " woke up"
        
        
c = []
for i in range(0,3):
    c.append(stackless.channel())
        
p = P("A", [Task("C",c[1]),Task("B",c[2])], c[0])

t = stackless.tasklet(p.execute)()
running.append(t)
t.run()

try:
    print "pickling tasks"
    #schedule()
    f = open("test1.dat","w")
    pickledTasks = pickle.dump(running,f)
    f.close()
    
    print "unpickling tasks"
    f = open("test1.dat")
    pickle.load(f)
    f.close()
    
    for channel in c:
        channel.send("Hello")
    
    while stackless.getruncount() > 1:
        stackless.schedule()
except:
    print sys.exc_info()