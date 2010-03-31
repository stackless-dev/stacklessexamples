"""Python Microthread Library, version 1.0

Stackless adds tasklets to Python, a more modern form of the
microthreads this library originally provided.  This modified
version of the original uthread library provides a range of
useful functions and classes.

Use of this class generally requires a certain approach to
using Stackless.  Use only the provided 'uthread.sleep()' and
'uthread.benice()' functions to yield and never
'stackless.schedule()'.  The reason for this is that each
tasklet scheduled is expected to be removed from the scheduler
when it either yields or exits.  This way the watchdog can be
relied upon to exit pretty much immediately, and will only
hit the instruction count timeout when a runaway tasklet
does not yield because of bad programming.

Do not use 'stackless.run()'.  Instead use 'uthread.run()' as
it takes care of scheduling tasklets that are sleeping and
being nice.

Permission was granted by Halldor Fannar Gudjonsson, Chief
Technical Officer of CCP Games to Richard Tew to release the
modified version of the original uthread library which they
use internally.  Changes have been made to replace functionality
provided by the EVE game framework by Richard Tew.
"""

__version__ = "1.0"

__license__ = \
"""Python Microthread Library version 1.0
Copyright (C)2000  Will Ware, Christian Tismer
Copyright (C)2000-2006 CCP Games
Copytight (C)2006 Richard Tew

Permission to use, copy, modify, and distribute this software and its
documentation for any purpose and without fee is hereby granted,
provided that the above copyright notice appear in all copies and that
both that copyright notice and this permission notice appear in
supporting documentation, and that the names of the authors not be
used in advertising or publicity pertaining to distribution of the
software without specific, written prior permission.

WILL WARE AND CHRISTIAN TISMER DISCLAIM ALL WARRANTIES WITH REGARD TO
THIS SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS. IN NO EVENT SHALL WILL WARE OR CHRISTIAN TISMER BE LIABLE FOR
ANY SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT
OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
"""

import stackless
import sys
import time
import types
import weakref
import traceback
import copy
import logging

# This is a simple replacement for what CCP uses which is linked into our
# framework.
def WriteTraceback(text, tb):
    logging.error(text)
    for s in traceback.format_tb(tb):
        logging.error(s.strip())
    logging.error(str(excInstance))

def LogTraceback(text):
    if text is None:
        text = "Traceback:"
    tb = traceback.extract_stack()
    WriteTraceback(text, tb)

def StackTrace(text=None):
    excClass, excInstance, tb = sys.exc_info()
    if excClass:
        if text is None:
            text = "Stacktrace:"
        WriteTraceback(text, tb)
    else:
        LogTraceback(text)

# Internal Stackless functionality.
schedule = stackless.schedule

# We need to subclass it so that we can store attributes on it.
class Tasklet(stackless.tasklet):
    def __call__(self, *args, **kwargs):
        oldFunction = self.tempval
        def newFunction(oldFunction, args, kwargs):
            try:
                oldFunction(*args, **kwargs) 
            except Exception, e:
                traceback.print_exc()
                raise e
        self.tempval = newFunction
        stackless.tasklet.setup(self, oldFunction, args, kwargs)
        return self

def new(func, *args, **kw):
    return Tasklet(func)(*args, **kw)

def newWithoutTheStars(func, args, kw):
    return Tasklet(func)(*args, **kw)

idIndex = 0

def uniqueId():
    """Microthread-safe way to get unique numbers, handy for
    giving things unique ID numbers"""
    global idIndex
    ## CCP is cutting out atomic as we never preemtivly schedule and stackless was crashing there
    #tmp = stackless.atomic()
    z = idIndex
    idIndex += 1
    return z

def irandom(n):
    """Microthread-safe version of random.randrange(0,n)"""
    import random
    ## CCP is cutting out atomic as we never preemtivly schedule and stackless was crashing there
    #tmp = stackless.atomic()
    n = random.randrange(0, n)
    return n

synonyms = {}

def MakeSynonymOf(threadid, synonym_threadid):
    global synonyms
    key = (threadid, synonym_threadid)
    if key not in synonyms:
        synonyms[key] = 1
    else:
        synonyms[key] += 1

def MakeCurrentSynonymOf(synonym_threadid):
    return MakeSynonymOf(id(stackless.getcurrent()), synonym_threadid)

def RemoveSynonymOf(threadid, synonym_threadid):
    global synonyms
    key = (threadid, synonym_threadid)
    if key not in synonyms:
        StackTrace("RemoveSynonymOf unexpected call threadid:%s synonym_threadid:%s" % key)
        return
    synonyms[key] -= 1
    if 0 == synonyms[key]:
        del synonyms[key]

def RemoveCurrentSynonymOf(synonym_threadid):
    return RemoveSynonymOf(id(stackless.getcurrent()), synonym_threadid)

def IsSynonymOf(threadid, synonym_threadid):
    global synonyms
    key = (threadid, synonym_threadid)
    return key in synonyms

def IsCurrentSynonymOf(synonym_threadid):
    return IsSynonymOf(id(stackless.getcurrent()), synonym_threadid)

# Sleeping related logic.

sleepingTasklets = []

def Sleep(secondsToWait):
    '''
    Yield the calling tasklet until the given number of seconds have passed.
    '''
    global sleepingTasklets
    channel = stackless.channel()
    endTime = time.time() + secondsToWait
    sleepingTasklets.append((endTime, channel))
    sleepingTasklets.sort()
    # Block until we get sent an awakening notification.
    channel.receive()

def CheckSleepingTasklets():
    '''
    Function for internal uthread.py usage.
    '''
    global sleepingTasklets
    if len(sleepingTasklets):
        endTime = sleepingTasklets[0][0]
        if endTime <= time.time():
            channel = sleepingTasklets[0][1]
            del sleepingTasklets[0]
            # We have to send something, but it doesn't matter what as it is not used.
            # Handle the case where the tasklet has been prematurely killed, otherwise
            # the caller will be blocked indefinitely.
            if channel.balance:
                channel.send(None)

def KillSleepingTasklets():
    global sleepingTasklets
    if len(sleepingTasklets):
        for timestamp, channel in sleepingTasklets:
            t = channel.queue
            while t is not None:
                toBeKilled = t
                t = t.next
                toBeKilled.raise_exception(TaskletExit)
        sleepingTasklets = []

# Being nice related logic.

yieldChannel = stackless.channel()
yieldChannel.preference = 1

def BeNice():
    '''
    Yield the calling tasklet.  Use instead of schedule in order to keep
    the scheduler empty.
    '''
    global yieldChannel
    yieldChannel.receive()

# We need to have a tasklet of our own calling this, then the watchdog.
def RunNiceTasklets():
    '''
    Function for internal uthread.py usage.
    '''
    global yieldChannel
    # Only schedule as many tasklets as there are waiting when
    # we start.  This is because some of the tasklets we awaken
    # may BeNice their way back onto the channel.
    n = -yieldChannel.balance
    while n > 0:
        yieldChannel.send(None)
        n -= 1

# Scheduling related logic.

class TimeoutException(Exception):
    pass

def Run():
    '''
    Use instead of stackless.run() in order.to allow Sleep and BeNice
    to work.  If this is not called and BeNice is used and RunNiceTasklets
    is not called or Sleep is used and CheckSleepingTasklets is not called,
    then any tasklets which call BeNice or Sleep respectively will block
    indefinitely as there will be nothing to wake them up.

    This function will exit when there are no remaining tasklets to run,
    whether being nice or sleeping.
    '''
    while yieldChannel.balance or len(sleepingTasklets) or stackless.runcount > 1:
        RunNiceTasklets()
        t = stackless.run(500000)
        if t is not None:
            print "*** Uncooperative tasklet", t, "detected ***"
            traceback.print_stack(t.frame)
            print "*** Uncooperative tasklet", t, "being sent exception ***"
            t.raise_exception(TimeoutException)
        CheckSleepingTasklets()

semaphores               = weakref.WeakKeyDictionary({})

def GetSemaphores():
    return semaphores

class Semaphore:
    """Semaphores protect globally accessible resources from
    the effects of context switching."""

    def __init__(self, semaphoreName=None, maxcount=1, strict=True):
        global semaphores

        semaphores[self] = 1

        self.semaphoreName  = semaphoreName
        self.maxcount       = maxcount
        self.count          = maxcount
        self.waiting        = stackless.channel()
        self.thread         = None
        self.lockedWhen     = None
        self.strict         = strict

    def IsCool(self):
        '''
            returns true if and only if nobody has, or is waiting for, this lock
        '''
        return self.count==self.maxcount

    def __str__(self):
        return "Semaphore("+ str(self.semaphoreName) +")"

    def __del__(self):
        if not self.IsCool():
            logger.error("Semaphore "+ str(self) +" is being destroyed in a locked or waiting state")

    def acquire(self):
        if self.strict:
            assert self.thread is not stackless.getcurrent()
            if self.thread is stackless.getcurrent():
                raise RuntimeError, "tasklet deadlock, acquiring tasklet holds strict semaphore"
        self.count -= 1
        if self.count < 0:
            self.waiting.receive()

        self.lockedWhen = time.time()
        self.thread = stackless.getcurrent()

    claim = acquire

    def release(self):
        if self.strict:
            assert self.thread is stackless.getcurrent()
            if self.thread is not stackless.getcurrent():
                raise RuntimeError, "wrong tasklet releasing strict semaphore"

        self.count += 1
        self.thread     =   None
        self.lockedWhen =   None
        if self.count <= 0:
            PoolWorker("uthread::Semaphore::delayed_release",self.__delayed_release)

    #This allows the release thread to continue without being interrupted
    def __delayed_release(self):
        self.waiting.send(None)

class CriticalSection(Semaphore):
    def __init__(self, semaphoreName = None, strict=True):
        Semaphore.__init__(self, semaphoreName)
        self.__reentrantRefs = 0

    def acquire(self):
        # MEB: if (self.count<=0) and (self.thread is stackless.getcurrent() or stackless.getcurrent() is synonymof self.thread):
        if (self.count<=0) and (self.thread is stackless.getcurrent() or IsCurrentSynonymOf(self.thread)):
            self.__reentrantRefs += 1
        else:
            Semaphore.acquire(self)

    def release(self):
        if self.__reentrantRefs:
            # MEB: assert self.thread is stackless.getcurrent()
            assert self.thread is stackless.getcurrent() or IsCurrentSynonymOf(self.thread)
            # MEB: if self.thread is not stackless.getcurrent():
            if not (self.thread is stackless.getcurrent() or IsCurrentSynonymOf(self.thread)):
                raise RuntimeError, "wrong tasklet releasing reentrant CriticalSection"
            self.__reentrantRefs -= 1
        else:
            Semaphore.release(self)

def FNext(f):
    first  = stackless.getcurrent()
    try:
        cursor = first.next
        while cursor != first:
            if cursor.frame.f_back == f:
                return FNext(cursor.frame)
            cursor = cursor.next
        return f
    finally:
        first  = None
        cursor = None

class SquidgySemaphore:
    '''
        This is a semaphore which allows exclusive locking
    '''

    def __init__(self, lockName):
        self.__outer__  = Semaphore(lockName)
        self.lockers    = {}
        self.__wierdo__ = 0

    def IsCool(self):
        '''
            returns true if and only if nobody has, or is waiting for, this lock
        '''
        while 1:
            lockers = []
            try:
                for each in self.lockers:
                    return 0
                break
            except:
                StackTrace()
                sys.exc_clear()
        return self.__outer__.IsCool() and not self.__wierdo__

    def acquire_pre_friendly(self):
        '''
            Same as acquire, but with respect for pre_acquire_exclusive
        '''
        while 1:
            if self.__wierdo__:
                Sleep(0.5)
            else:
                self.acquire()
                if self.__wierdo__:
                    self.release()
                else:
                    break

    def pre_acquire_exclusive(self):
        '''
            Prepares the lock for an acquire_exclusive call, so that
            acquire_pre_friendly will block on the dude.
        '''
        self.__wierdo__ += 1

    def acquire_exclusive(self):
        i = 0
        while 1:
            self.__outer__.acquire()
            theLocker = None
            try:
                # self.lockers is a dict, and we just want one entry from it.
                # for each in/break is a convenient way to get one entry.
                for each in self.lockers:
                    theLocker = each
                    break
            except:
                StackTrace()
                sys.exc_clear()

            if theLocker is not None:
                self.__outer__.release() # yielding to the sucker is fine, since we're waiting for somebody anyhow.
                if i and ((i%(3*4*60))==0):
                    logger.error("Acquire-exclusive is waiting for the inner lock (%d seconds total, lockcount=%d)" % (i/4, len(self.lockers)))
                    LogTraceback("This acquire_exclusive is taking a considerable amount of time")
                    logger.error("This dude has my lock:")
                    logger.error("tasklet: "+str(theLocker))
                    for s in traceback.format_list(traceback.extract_stack(FNext(theLocker.frame),40)):
                        for n in range(0,10120,253): # forty lines max.
                            if n==0:
                                if len(s)<=255:
                                    x = s
                                else:
                                    x = s[:(n+253)]
                            else:
                                x = " - " + s[n:(n+253)]
                            logger.error(x, 4)
                            if (n+253)>=len(s):
                                break
                Sleep(0.500)
            else:
                break
            i += 1

    def release_exclusive(self):
        self.__outer__.release()
        self.__wierdo__ -= 1

    def acquire(self):
        # you don't need the outer lock to re-acquire
        self.__outer__.acquire()
        self.__acquire_inner()
        self.__outer__.release()

    def release(self, t=None):
        if t is None:
            t = stackless.getcurrent()
        self.__release_inner(t)

    def __acquire_inner(self):
        while 1:
            try:
                if self.lockers.has_key(stackless.getcurrent()):
                    self.lockers[stackless.getcurrent()] += 1
                else:
                    self.lockers[stackless.getcurrent()] = 1
                break
            except:
                StackTrace()
                sys.exc_clear()

    def __release_inner(self, t):
        while 1:
            try:
                if self.lockers.has_key(t):
                    self.lockers[t] -= 1
                    if self.lockers[t]==0:
                        del self.lockers[t]
                else:
                    StackTrace("You can't release a lock you didn't acquire")
                break
            except:
                StackTrace()
                sys.exc_clear()

channels            = weakref.WeakKeyDictionary()

def GetChannels():
    return channels

class Channel:
    """
        A Channel is a stackless.channel() with administrative spunk
    """

    def __init__(self,channelName=None):
        global channels
        self.channelName = channelName
        self.channel = stackless.channel()
        self.send = self.channel.send
        self.send_exception = self.channel.send_exception
        channels[self] = 1

    def receive(self):
        return self.channel.receive()

    def __getattr__(self,k):
        return getattr(self.channel,k)




# -----------------------------------------------------------------------------------
#  FIFO Class
# -----------------------------------------------------------------------------------
class FIFO(object):

    __slots__ = ('data',)

    # -----------------------------------------------------------------------------------
    #  FIFO - Constructor
    # -----------------------------------------------------------------------------------
    def __init__(self):
        self.data = [[], []]

    # -----------------------------------------------------------------------------------
    #  FIFO - push
    # -----------------------------------------------------------------------------------
    def push(self, v):
        self.data[1].append(v)

    # -----------------------------------------------------------------------------------
    #  FIFO - pop
    # -----------------------------------------------------------------------------------
    def pop(self):
        d = self.data
        if not d[0]:
            d.reverse()
            d[0].reverse()
        return d[0].pop()

    # -----------------------------------------------------------------------------------
    #  FIFO - __nonzero__
    # -----------------------------------------------------------------------------------
    # NB: Please don't define this function, as it will break some legacy code in client
    #     Use the len() function instead
    #def __nonzero__(self):
    #    d = self.data
    #    return not (not (d[0] or d[1]))

    # -----------------------------------------------------------------------------------
    #  FIFO - __contains__
    # -----------------------------------------------------------------------------------
    def __contains__(self, o):
        d = self.data
        return (o in d[0]) or (o in d[1])


    # -----------------------------------------------------------------------------------
    #  FIFO - Length
    # -----------------------------------------------------------------------------------
    def Length(self):
        d = self.data
        return len(d[0]) + len(d[1])

    # -----------------------------------------------------------------------------------
    #  FIFO - clear
    # -----------------------------------------------------------------------------------
    def clear(self):
        self.data = [[], []]

    # -----------------------------------------------------------------------------------
    #  FIFO - clear
    # -----------------------------------------------------------------------------------
    def remove(self, o):
        d = self.data
        try:
            d[0].remove(o)
        except ValueError:
            sys.exc_clear()

        try:
            d[1].remove(o)
        except ValueError:
            sys.exc_clear()


# -----------------------------------------------------------------------------------
#  Queue - QueueCheck
# -----------------------------------------------------------------------------------
def QueueCheck(o):

    while True:
        try:
            o.pump()
        except ReferenceError:
            sys.exc_clear()
            break
        except StandardError:
            StackTrace()
            sys.exc_clear()

        Sleep(0.1)


# -----------------------------------------------------------------------------------
#  Queue Class
# -----------------------------------------------------------------------------------
class Queue(FIFO):
    """A queue is a microthread-safe FIFO."""

    # -----------------------------------------------------------------------------------
    #  Queue - Constructor
    # -----------------------------------------------------------------------------------
    def __init__(self):
        FIFO.__init__(self)
        self.channel  = stackless.channel()
        self.blockingThreadRunning = False

    # -----------------------------------------------------------------------------------
    #  Queue - put
    # -----------------------------------------------------------------------------------
    def put(self, x):
        self.push(x)
        self.pump()

    # -----------------------------------------------------------------------------------
    #  Queue - pump
    # -----------------------------------------------------------------------------------
    def pump(self):

        while self.channel.queue and self.Length() and self.channel.balance < 0:
            o = self.pop()
            self.channel.send(o)

    # -----------------------------------------------------------------------------------
    #  Queue - non_blocking_put
    # -----------------------------------------------------------------------------------
    def non_blocking_put(self, x):

        # Create a non blocking worker thread if this is the first time this gets called
        if not self.blockingThreadRunning:
            self.blockingThreadRunning = True
            new(QueueCheck, weakref.proxy(self)).context = "uthread::QueueCheck"

        self.push(x)

    # -----------------------------------------------------------------------------------
    #  Queue - get
    # -----------------------------------------------------------------------------------
    def get(self):
        if self.Length():
            return self.pop()

        return self.channel.receive()


# --------------------------------------------------------------------
class Event:

    # --------------------------------------------------------------------
    def __init__(self, manual=1, signaled=0):
        self.channel = stackless.channel()
        self.manual = manual
        self.signaled = signaled

    # --------------------------------------------------------------------
    def Wait(self, timeout=-1):
        if timeout != -1:
            raise RuntimeError("No timeouts supported in Event")

        if not self.signaled:
            self.channel.receive()

    # --------------------------------------------------------------------
    def SetEvent(self):
        if self.manual:
            self.signaled = 1

        while self.channel.queue:
            self.channel.send(None)

    # --------------------------------------------------------------------
    def ResetEvent(self):
        self.signaled = 0



def LockCheck():
    global semaphores
    while 1:
        each = None
        Sleep(5 * 60)
        now = time.time()
        try:
            for each in semaphores.keys():
                BeNice()
                if (each.count<=0) and (each.waiting.balance < 0) and (each.lockedWhen and (now - each.lockedWhen)>=(5*MIN)):
                    logger.error("Semaphore %s appears to have threads in a locking conflict."%id(each))
                    logger.error("holding thread:")
                    try:
                        for s in traceback.format_list(traceback.extract_stack(each.thread.frame,40)):
                            logger.error(s)
                    except:
                        sys.exc_clear()
                    first = each.waiting.queue
                    t = first
                    while t:
                        logger.error("waiting thread %s:"%id(t),4)
                        try:
                            for s in traceback.format_list(traceback.extract_stack(t.frame,40)):
                                logger.error(s,4)
                        except:
                            sys.exc_clear()
                        t = t.next
                        if t is first:
                            break
                    logger.error("End of locking conflict log")
        except StandardError:
            StackTrace()
            sys.exc_clear()

new(LockCheck).context = "uthread::LockCheck"

__uthread__queue__          = None
def PoolHelper(queue):
    t = stackless.getcurrent()
    t.localStorage   = {}
    respawn = True
    try:
        try:
            while 1:
                BeNice()
                ctx, callingContext, func, args, keywords = queue.get()
                if (queue.channel.balance >= 0):
                    new(PoolHelper, queue).context = "uthread::PoolHelper"
                #SetLocalStorage(loc)
                # _tmpctx = t.PushTimer(ctx)
                try:
                    apply( func, args, keywords )
                finally:
                    ctx                 = None
                    callingContext      = None
                    func                = None
                    #t.localStorage      = {}
                    #loc                 = None
                    args                = None
                    keywords            = None
                    # t.PopTimer(_tmpctx)
        except SystemExit:
            respawn = False
            raise
        except:
            if callingContext is not None:
                extra = "spawned at %s %s(%s)"%callingContext
            else:
                extra = ""
            StackTrace("Unhandled exception in %s%s" % (ctx, extra))
            sys.exc_clear()
    finally:
        if respawn:
            del t
            new(PoolHelper, queue).context = "uthread::PoolHelper"

def PoolWorker(ctx,func,*args,**keywords):
    '''
        Same as uthread.pool, but without copying local storage, thus resetting session, etc.

        Should be used for spawning worker threads.
    '''
    return PoolWithoutTheStars(ctx,func,args,keywords,0,1)

def PoolWorkerWithoutTheStars(ctx,func,args,keywords):
    '''
        Same as uthread.worker, but without copying local storage, thus resetting session, etc.

        Should be used for spawning worker threads.
    '''
    return PoolWithoutTheStars(ctx,func,args,keywords,0,1)

def PoolWithoutTheStars(ctx,func,args,keywords,unsafe=0,worker=0):
    if type(ctx) not in types.StringTypes:
        StackTrace("uthread.pool must be called with a context string as the first parameter")
    global __uthread__queue__
    callingContext = None
    if ctx is None:
        if unsafe:
            ctx = "uthread::PoolHelper::UnsafeCrap"
        else:
            tb = traceback.extract_stack(limit=2)[0]
            ctx = getattr(stackless.getcurrent(), "context", "")
            callingContext = tb[2], tb[0], tb[1] #function , file, lineno
            del tb

    if __uthread__queue__ is None:
        __uthread__queue__ = Queue()
        for i in range(60):
            new(PoolHelper, __uthread__queue__).context = "uthread::PoolHelper"
    #if unsafe or worker:
    #    st = None
    #else:
    #    st = copy.copy(GetLocalStorage())
    __uthread__queue__.non_blocking_put( (str(ctx), callingContext, func, args, keywords,) )
    return None

def Pool(ctx,func,*args,**keywords):
    '''
        Executes apply(args, keywords) on a new uthread.  The uthread in question is taken
        from a thread pool, rather than created one-per-shot call.  ctx is used as the
        thread context.  This should generally be used for short-lived threads to reduce
        overhead.
    '''
    return PoolWithoutTheStars(ctx,func,args,keywords)

def UnSafePool(ctx,func,*args,**keywords):
    '''
        uthread.pool, but without any dangerous calls to stackless.getcurrent(), which could
        have dramatic and drastic effects in the wrong context.
    '''
    return PoolWithoutTheStars(ctx,func,args,keywords,1)

def ParallelHelper(ch,idx,what):
    ch, threadid = ch
    MakeCurrentSynonymOf(threadid)
    try:
        ei = None
        try:
            if len(what)==3:
                ret = (idx, apply(what[0], what[1], what[2] ))
                if ch.balance < 0 :
                    ch.send( (1, ret) )
            else:
                ret = (idx, apply(what[0], what[1] ))
                if ch.balance < 0:
                    ch.send( (1, ret) )
        except StandardError:
            ei = sys.exc_info()
            sys.exc_clear()

        if ei:
            if ch.balance < 0:
                ch.send((0,ei))
        del ei
    finally:
        RemoveCurrentSynonymOf(threadid)

def Parallel(funcs,exceptionHandler=None,maxcount=30):
    '''
        Executes in parallel all the function calls specified in the list/tuple 'funcs', but returns the
        return values in the order of the funcs list/tuple.  If an exception occurs, only the first exception
        will reach you.  The rest will dissapear in a puff of logic.

        Each 'func' entry should be a tuple/list of:
        1.  a function to call
        2.  a tuple of arguments to call it with
        3.  optionally, a dict of keyword args to call it with.
    '''
    if not funcs:
        return

    context = "ParallelHelper::"+getattr(stackless.getcurrent(),"context","???")
    ch = stackless.channel(), id(stackless.getcurrent())
    ret = [ None ] * len(funcs)
    n = len(funcs)
    if n > maxcount:
        n = maxcount
    for i in range(n):
        if type(funcs[i]) != types.TupleType:
            raise RuntimeError("Parallel requires a list/tuple of (function, args tuple, optional keyword dict,)")
        Pool(context, ParallelHelper, ch, i, funcs[i])
    for i in range(len(funcs)):
        ok, bunch = ch[0].receive()
        if ok:
            idx,val = bunch
            if len(funcs[i])==4:
                ret[idx] = (funcs[i][3], val,)
            else:
                ret[idx] = val
        else:
            try:
                raise bunch[0],bunch[1],bunch[2]
            except StandardError:
                if exceptionHandler:
                    exctype, exc, tb = sys.exc_info()
                    try:
                        try:
                            apply( exceptionHandler, (exc,) )
                        except StandardError:
                            raise exc, None, tb
                    finally:
                        exctype, exc, tb = None, None, None
                else:
                    StackTrace()
                    raise

        if n<len(funcs):
            if type(funcs[n]) != types.TupleType:
                raise RuntimeError("Parallel requires a list/tuple of (function, args tuple, optional keyword dict,)")
            Pool(context, ParallelHelper, ch, n, funcs[n])
            n+=1
    return ret

locks = {}
def Lock(object, *args):
    '''
    Blocks the calling tasklet until a specific globally accessible lock is
    acquired.  The lock acquired is defined by the arguments passed to this
    function.  The lock is not reentrant and any attempt by a tasklet to
    reacquire the lock it already holds will result in a deadlock related error.
    '''
    global locks
    t = (id(object), args)
    if t not in locks:
        locks[t] = Semaphore(t, strict=False)
    locks[t].acquire()

def TryLock(object, *args):
    '''
    Attempts to acquire a specific globally accessible lock.  The lock to be
    acquired is defined by the arguments passed to this function.  If the lock
    is not currently available, then False will be returned.  If the lock is
    available, it will be acquired and True will be returned.
    '''
    global locks
    t = (id(object), args)
    if t not in locks:
        locks[t] = Semaphore(t, strict=False)
    if not locks[t].IsCool():
        return False
    locks[t].acquire()
    return True

def ReentrantLock(object, *args):
    '''
    Blocks the calling tasklet until a specific globally accessible lock is
    acquired, unless the calling tasklet has already acquired it in which
    case it is reacquired in a reentrant manner.  The lock to be acquired is
    defined by the arguments passed to this function.
    '''
    global locks
    t = (id(object), args)
    if t not in locks:
        locks[t] = CriticalSection(t)
    locks[t].acquire()

def UnLock(object, *args):
    '''
    Releases a lock which the calling tasklet has previously acquired.  The
    lock to be released is defined by the arguments passed to this function.
    If the calling tasklet has acquired the lock several times reentrantly
    then the lock will not be released unblocking other waiting tasklets
    until all the reentrant locking actions have been matched with unlocking
    actions.
    '''
    global locks
    t = (id(object), args)
    locks[t].release()
    if (t in locks) and (locks[t].IsCool()): # may be gone or changed by now
        del locks[t]

def with_instance_locking(f):
    '''
        Decorator which provides instance level locking.
        When used on an instance method locks the instance for the duration
        of the function call.  Requires that the first argument is the
        instance the lock belongs to, which will be implicit with decorated
        instance methods.
    '''
    def new_f(self, *args, **kwds):
        Lock(self)
        try:
            return f(self, *args, **kwds)
        finally:
            UnLock(self)
    return new_f


# Exported names.
parallel = Parallel
worker = PoolWorker
workerWithoutTheStars = PoolWorkerWithoutTheStars
unsafepool = UnSafePool
pool = Pool
poolWithoutTheStars = PoolWithoutTheStars

sleep = Sleep
benice = BeNice
run = Run
