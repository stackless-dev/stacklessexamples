#
# Copyright (c) 2005, Asgeir Bjarni Ingvarsson
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
#    * Redistributions of source code must retain the above copyright notice, this
#      list of conditions and the following disclaimer.
#    * Redistributions in binary form must reproduce the above  copyright notice,
#      this list of conditions and the following disclaimer in the documentation
#      and/or other materials provided with the distribution.
#    * Neither the name of the original author nor the names of other contributors
#      may be used to endorse or promote products derived from this software
#      without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

#
# Obtain the latest version from:
#
#   http://ares.hlekkir.com/repo/shady-utils/trunk/uthread.py
#

import stackless
import weakref
import cPickle
import atexit
import sys
import time

#----------------------------------------------------------------------------
# A class to support named microthreads
#----------------------------------------------------------------------------
class NamedTasklet(stackless.tasklet):
    __slots__ = ['name']

    def __init__(self, func, name=None):
        stackless.tasklet.__init__(self, func)

        if not name:
            name = '%08x' % (id(self))
        self.name = name

    def __new__(self, func, name=None):
        return stackless.tasklet.__new__(self, func)

    def __repr__(self):
        try:
            return '%s' % self.name
        except AttributeError:
            # I think that this will only happen with the main tasklet
            return '%08x' % (id(self))

#----------------------------------------------------------------------------
# A class to manage sleeping tasklets
#----------------------------------------------------------------------------
_timeKeeperTaskletName = '__internal__TimeKeeper__mainLoop__'

class TimeKeeper(object):
    """Manages sleeping tasklets

    Uses channels to block tasklets that want to sleep.
    """
    __slots__ = ['chnPool', 'sleepers']

    def __init__(self):
        self.chnPool = [stackless.channel() for i in range(100)]
        self.sleepers = []

    def getSleeperCount(self):
        """Returns the number of sleeping tasklets
        """
        return len(self.sleepers)

    def sleep(self, delay=0):
        """Suspend the active tasklet for a specified amount of seconds

        If delay is zero (default) then the tasklet just blocks.
        Returns seconds passed since sleep was called.
        """
        startTime = time.clock()
        when = startTime + delay

        if delay:
            try:
                try:
                    chn = self.chnPool.pop()
                except IndexError:
                    chn = stackless.channel()
                    # could also allocate more channels for chnPool

                self.sleepers.append((when, chn))
                chn.receive()
            finally:
                self.chnPool.append(chn)
        else:
            stackless.schedule()

        return time.clock() - startTime

    def mainLoop(self):
        """Internal function

        Created in a new tasklet by the scheduler
        """
        try:
            while True:
                try:
                    # assume that the sleeper list is ordered
                    (when, chn) = self.sleepers.pop(0)
                    # an empty list will raise IndexError
                    while when <= time.clock():
                        chn.send(None)
                        (when, chn) = self.sleepers.pop(0)
                        # an empty list will raise IndexError

                    # The only way to reach this point is if the while evaluates as False.
                    # That means that the current sleeper wants to sleep longer.
                    self.sleepers.insert(0, (when, chn))
                except IndexError:
                    # The sleeper list is empty, nothing to do
                    pass

                stackless.schedule()
        except Exception, e:
            # Restart TimeKeeper unless it's being killed
            if isinstance(e, TaskletExit):
                # TimeKeeper is being killed.
                # Send a TaskletExit to all sleepers
                for (when, chn) in self.sleepers:
                    chn.send_exception(e)

                self.sleepers = []
            else:
                # recreate the timeKeeper tasklet from another tasklet so
                # the timeKeeper name may be reused
                new(newNamed, self.mainLoop, _timeKeeperTaskletName)

#----------------------------------------------------------------------------
# Schedulers to manage tasklets
#----------------------------------------------------------------------------
class BaseScheduler(object):
    """This is the base thread scheduler

    _activeScheduler should not be set to an instance of this class.
    Subclasses must override the run and runSingle methods
    """
    __slots__ = ['running', 'paused', 'timeKeeper']

    def __init__(self):
        # References to tasklets will be dropped as soon as they
        # stop executing
        self.running = weakref.WeakValueDictionary()
        self.paused = weakref.WeakValueDictionary()

        self.timeKeeper = TimeKeeper()
        self.new(self.timeKeeper.mainLoop, _timeKeeperTaskletName)

    def new(self, func, name=None, *args, **kw):
        """Create a new tasklet

        If name is already in use, a *random* name will be chosen
        """
        if name not in self.listTasks():
            task = NamedTasklet(func, name)
        else:
            task = NamedTasklet(func)
        task(*args, **kw)  # tasklet will be lost in dict if this is not done
        task.insert()

        currID = repr(task)
        self.running[currID] = task
        return currID

    def killAll(self):
        """Kills all tasklets
        """
        for taskID in (self.running.keys() + self.paused.keys()):
            try:
                self.kill(taskID)
            except:
                pass

    def kill(self, taskID):
        """Stops a running tasklet
        """
        task = self.running.pop(taskID, None)
        workingDict = self.running
        if task is None:
            task = self.paused.pop(taskID, None)
            workingDict = self.paused

        if task:
            try:
                task.kill()
                return
            except:
                workingDict[taskID] = task
                raise

    def pause(self, taskID):
        """Pauses a running tasklet
        """
        task = self.running.pop(taskID, None)
        if task:
            task.remove()
            self.paused[taskID] = task

    def resume(self, taskID):
        """Resumes a paused tasklet
        """
        task = self.paused.pop(taskID, None)
        if task:
            task.insert()
            self.running[taskID] = task

    def run(self):
        """Execute all tasklets
        """
        pass

    def runSingle(self):
        """Execute the schedule list once, then return
        """
        pass

    def dumpTask(self, taskID, kill=0):
        """Returns a pickled tasklet
        """
        task = self.running.get(taskID, None) or self.paused.get(taskID, None)
        if task:
            data = cPickle.dumps(task, 2)
            if kill:
                self.kill(repr(task))
            return data

    def loadTask(self, data, paused=1):
        """Loads a pickled tasklet
        """
        task = cPickle.loads(data)
        currID = repr(task)
        if paused:
            self.paused[currID] = task
        else:
            self.running[currID] = task
            task.insert()
        return currID

    def listTasks(self):
        """Returns a list of all tasklets
        """
        return self.running.keys() + self.paused.keys()

    def getRunCount(self):
        """Same as stackless.getruncount but takes sleeping tasklets into account

        Will return 1 when only the main tasklet is left, the timeKeeper tasklet
        will not be counted since it is not a client tasklet.

        For consideration: If stackless.getruncount() returns 2
            only the main tasklet and the TimeKeeper tasklets are currently
            running. This might then be a good place to sleep for one millisecond
            to reduce CPU load
        """
        runCount = stackless.getruncount() + self.timeKeeper.getSleeperCount()
        return (runCount - 1)  # subtract the timeKeeper tasklet

    def sleepTask(self, delay=0):
        """Suspend the active tasklet for a specified amount of seconds

        If delay is zero (default) then the tasklet just blocks.
        Returns seconds passed since sleep was called.
        """
        return self.timeKeeper.sleep(delay)

    def printException(self):
        """Uses sys.excepthook to report exceptions
        """
        exc_info = sys.exc_info()
        sys.excepthook(exc_info[0], exc_info[1], exc_info[2])

class PreemptiveScheduler(BaseScheduler):
    """This is a preemptive tasklet scheduler

    This scheduler will execute each thread for as little time as possible.
    When it interrupts tasklets, it will keep them in the scheduler list.

    THIS IS EXPERIMENTAL AND HAS NOT BEEN TESTED. UTHREAD HAS NOT BEEN
    DESIGNED WITH THIS KIND OF USE IN MIND. You may need to modify code
    in this module if you plan on using this scheduler.
    """
    def __init__(self):
        BaseScheduler.__init__(self)
        self.maxSlice = 50

    def run(self):
        """Execute all tasklets
        """
        while self.getRunCount() > 1:
            try:
                # Run a single slice, if the currently executing thread is
                # still running append it to the scheduler list
                victim = stackless.run(self.maxSlice)
                if victim:
                    victim.insert()
            except:
                self.printException()

    def runSingle(self):
        """Execute the schedule list once, then return
        """
        try:
            # Run a single slice, if the currently executing thread is
            # still running append it to the scheduler list
            victim = stackless.run(self.maxSlice)
            if victim:
                victim.insert()
        except:
            self.printException()

class DefaultScheduler(BaseScheduler):
    """This is the default tasklet scheduler

    This scheduler will execute threads sequentially.
    If it needs to interrupt the execution of a tasklet it will remove
    that tasklet from the scheduler list
    """
    def __init__(self):
        BaseScheduler.__init__(self)

    def run(self):
        """Execute all tasklets
        """
        while self.getRunCount() > 1:
            try:
                stackless.schedule()
            except:
                self.printException()

    def runSingle(self):
        """Execute the schedule list once, then return
        """
        try:
            stackless.schedule()
        except:
            self.printException()


#----------------------------------------------------------------------------
# Functions to interact with the active scheduler
#----------------------------------------------------------------------------
_activeScheduler = DefaultScheduler()

def setScheduler(newMgr, killOld=1, copy=0):
    """Replace the active tasklet scheduler

    It is not recommended to call this after threads have been started.
    If killOld is set to 1 then all threads in the old manager are killed.
    If copy is set to 1 then the running and paused dicts are copied into
    the new scheduler
    """
    assert isinstance(newMgr, BaseScheduler), 'newMgr must inherit from BaseScheduler'

    global _activeScheduler
    if killOld:
        _activeScheduler.KillAll()
    if copy:
        newMgr.running = _activeScheduler.running
        newMgr.paused = _activeScheduler.paused
    _activeScheduler = newMgr

def getScheduler():
    """Returns the active tasklet scheduler
    """
    global _activeScheduler
    return _activeScheduler

def _exitHandler():
    """This function calls killAll on the active scheduler

    This function is called by the atexit module before interpreter shutdown.
    This will give all tasklets a chance to shutdown cleanly if they are not
    blocked.
    """
    _activeScheduler.killAll()

atexit.register(_exitHandler)

#----------------------------------------------------------------------------
# Functions to expose the scheduler to users
#----------------------------------------------------------------------------
def new(func, *args, **kw):
    """Create a new tasklet
    """
    return _activeScheduler.new(func, None, *args, **kw)

def newNamed(func, name, *args, **kw):
    """Create a new named tasklet

    If name is already in use, a *random* name will be chosen
    """
    return _activeScheduler.new(func, name, *args, **kw)

def run():
    """Execute all tasklets
    """
    _activeScheduler.run()

def runSingle():
    """Execute the schedule list once, then return
    """
    _activeScheduler.runSingle()

def pause(taskID):
    """Pauses a running tasklet
    """
    _activeScheduler.pause(taskID)

def resume(taskID):
    """Resumes a paused tasklet
    """
    _activeScheduler.resume(taskID)

def kill(taskID):
    """Stops a running tasklet
    """
    _activeScheduler.kill(taskID)

def dumpTask(taskID, kill=0):
    """Returns a pickled tasklet
    """
    return _activeScheduler.dumpTask(taskID, kill)

def loadTask(data, paused=1):
    """Loads a pickled tasklet
    """
    return _activeScheduler.loadTask(data, paused)

def sleep(delay=0):
    """Suspend the active thread for a specified amount of seconds

    If delay is zero (default) then the tasklet just blocks.
    Returns seconds passed since sleep was called.
    """
    return _activeScheduler.sleepTask(delay)

def getCurrent():
    """Returns the currently running tasklet
    """
    return stackless.getcurrent()

#----------------------------------------------------------------------------
# Utility classes
#----------------------------------------------------------------------------
class Semaphore(object):
    """Protects globally accessible resources from context switching
    """
    __slots__ = ['count', 'channel']

    def __init__(self, maxcount=1):
        self.count = maxcount
        self.channel = stackless.channel()

    def acquire(self):
        if self.count == 0:
            self.channel.receive()
        else:
            self.count = self.count - 1

    def release(self):
        if self.channel.queue:
            self.channel.send(None)
        else:
            self.count = self.count + 1

class Queue(object):
    """A queue is a microthread-safe FIFO.
    """
    __slots__ = ['contents', 'channel']

    def __init__(self):
        self.contents = []
        self.channel = stackless.channel()

    def put(self, x):
        self.contents.append(x)
        self.pump()

    def pump(self):
        # Channel balance is <0 when there are tasklets waiting to recieve
        while self.channel.queue and self.contents and self.channel.balance < 0:
            self.channel.send(self.contents.pop(0))

    def nonBlockingPut(self, x):
        self.contents.append(x)

    def get(self):
        if self.contents:
            return self.contents.pop(0)
        return self.channel.receive()

    def unget(self, x):
        self.contents.insert(0, x)

class Synchronizer(object):
    """A traffic light for microthreads

    No synchronized thread can continue execution until all the other
    synchronized threads have called sync.
    """
    __slots__ = ['maxCount', 'queue', 'count']

    def __init__(self, count):
        self.maxCount = count
        self.queue = Queue()
        self.count = 0

    def sync(self):
        self.count += 1
        if self.count == self.maxCount:
            for i in range(self.maxCount):
                self.queue.put(None)
            self.count = 0
        return self.queue.get()
