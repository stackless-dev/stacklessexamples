"""
The Stackless module allows you to do multitasking without using threads.
The essential objects are tasklets and channels.
Please refer to their documentation.

December 1st, 2010 Andrew Francis Notes

stackless.select() now returns a _chanop, not a <ch, operation, value> tuple
the only _chanop attribute that should be used is value

TODOs

1) Add schedule and channel callbacks
2) Add properties to the _chanop class
3) Make a decision about what ought to be done about a select channel list created in a tasklet other than the one using the select
4) Write new set of tests

<song>37 Hours - Kristen Hersh</song>
"""

import sys

SEND = 1
RECEIVE = -1

DEBUG = False

__nrand_next = 1
def nrand(n):
   global __nrand_next
   __nrand_next = __nrand_next * 1103515245 + 12345
   return (__nrand_next / 65536) % n 


def debug(message):
    if DEBUG:
       print "[DEBUG ", message," ",getcurrent(),"]"


def dprint(*args):
    for arg in args:
        print arg,
    print

import traceback
import sys
try:
    from _stackless import coroutine, greenlet
except ImportError: # we are running from CPython
    from greenlet import greenlet
    try:
        from functools import partial
    except ImportError: # we are not running python 2.5
        class partial(object):
            # just enough of 'partial' to be usefull
            def __init__(self, func, *argl, **argd):
                self.func = func
                self.argl = argl
                self.argd = argd

            def __call__(self):
                return self.func(*self.argl, **self.argd)

    class GWrap(greenlet):
        """This is just a wrapper around greenlets to allow
           to stick additional attributes to a greenlet.
           To be more concrete, we need a backreference to
           the coroutine object"""

    class MWrap(object):
        def __init__(self,something):
            self.something = something

        def __getattr__(self, attr):
            return getattr(self.something, attr)

    class coroutine(object):
        "we can't have greenlet as a base, because greenlets can't be rebound"

        def __init__(self):
            self._frame = None
            self.is_zombie = False

        def __getattr__(self, attr):
            return getattr(self._frame, attr)

        def __del__(self):
            self.is_zombie = True
            del self._frame
            self._frame = None

        def bind(self, func, *argl, **argd):
            """coro.bind(f, *argl, **argd) -> None.
               binds function f to coro. f will be called with
               arguments *argl, **argd
            """
            if self._frame is None or self._frame.dead:
                self._frame = frame = GWrap()
                frame.coro = self
            if hasattr(self._frame, 'run') and self._frame.run:
                raise ValueError("cannot bind a bound coroutine")
            self._frame.run = partial(func, *argl, **argd)

        def switch(self):
            """coro.switch() -> returnvalue
               switches to coroutine coro. If the bound function
               f finishes, the returnvalue is that of f, otherwise
               None is returned
            """
            try:
                return greenlet.switch(self._frame)
            except TypeError, exp: # self._frame is the main coroutine
                return greenlet.switch(self._frame.something)

        def kill(self):
            """coro.kill() : kill coroutine coro"""
            self._frame.throw()

        def _is_alive(self):
            if self._frame is None:
                return False
            return not self._frame.dead
        is_alive = property(_is_alive)
        del _is_alive

        def getcurrent():
            """coroutine.getcurrent() -> the currently running coroutine"""
            try:
                return greenlet.getcurrent().coro
            except AttributeError:
                return _maincoro
        getcurrent = staticmethod(getcurrent)

        def __reduce__(self):
            raise TypeError, 'pickling is not possible based upon greenlets'

    _maincoro = coroutine()
    maingreenlet = greenlet.getcurrent()
    _maincoro._frame = frame = MWrap(maingreenlet)
    frame.coro = _maincoro
    del frame
    del maingreenlet

from collections import deque

import operator
__all__ = 'run getcurrent getmain schedule tasklet channel coroutine \
                TaskletExit greenlet'.split()

_global_task_id = 0
_squeue = None
_main_tasklet = None
_main_coroutine = None
_last_task = None
_channel_callback = None
_schedule_callback = None

def _scheduler_remove(value):
    try:
        del _squeue[operator.indexOf(_squeue, value)]
    except ValueError:pass

def _scheduler_append(value, normal=True):
    if normal:
        _squeue.append(value)
    else:
        _squeue.rotate(-1)
        _squeue.appendleft(value)
        _squeue.rotate(1)

def _scheduler_contains(value):
    try:
        operator.indexOf(_squeue, value)
        return True
    except ValueError:
        return False

def _scheduler_switch(current, next):
    global _last_task
    prev = _last_task
    if (_schedule_callback is not None and
        prev is not next):
        _schedule_callback(prev, next)
    _last_task = next
    assert not next.blocked
    if next is not current:
        next.switch()
    return current


class TaskletExit(Exception):pass

def set_schedule_callback(callback):
    global _schedule_callback
    _schedule_callback = callback

def set_channel_callback(callback):
    global _channel_callback
    _channel_callback = callback

def getruncount():
    return len(_squeue)

class bomb(object):
    def __init__(self, exp_type=None, exp_value=None, exp_traceback=None):
        self.type = exp_type
        self.value = exp_value
        self.traceback = exp_traceback

    def raise_(self):
        raise self.type, self.value, self.traceback

#
# helpers for pickling
#

_stackless_primitive_registry = {}

def register_stackless_primitive(thang, retval_expr='None'):
    import types
    func = thang
    if isinstance(thang, types.MethodType):
        func = thang.im_func
    code = func.func_code
    _stackless_primitive_registry[code] = retval_expr
    # It is not too nice to attach info via the code object, but
    # I can't think of a better solution without a real transform.

def rewrite_stackless_primitive(coro_state, alive, tempval):
    flags, state, thunk, parent = coro_state
    for i, frame in enumerate(state):
        retval_expr = _stackless_primitive_registry.get(frame.f_code)
        if retval_expr:
            # this tasklet needs to stop pickling here and return its value.
            tempval = eval(retval_expr, globals(), frame.f_locals)
            state = state[:i]
            coro_state = flags, state, thunk, parent
    return coro_state, alive, tempval

#
#

class channel(object):
    """
    A channel object is used for communication between tasklets.
    By sending on a channel, a tasklet that is waiting to receive
    is resumed. If there is no waiting receiver, the sender is suspended.
    By receiving from a channel, a tasklet that is waiting to send
    is resumed. If there is no waiting sender, the receiver is suspended.

    Attributes:

    preference
    ----------
    -1: prefer receiver
     0: don't prefer anything
     1: prefer sender

    Pseudocode that shows in what situation a schedule happens:

    def send(arg):
        if !receiver:
            schedule()
        elif schedule_all:
            schedule()
        else:
            if (prefer receiver):
                schedule()
            else (don't prefer anything, prefer sender):
                pass

        NOW THE INTERESTING STUFF HAPPENS

    def receive():
        if !sender:
            schedule()
        elif schedule_all:
            schedule()
        else:
            if (prefer sender):
                schedule()
            else (don't prefer anything, prefer receiver):
                pass

        NOW THE INTERESTING STUFF HAPPENS

    schedule_all
    ------------
    True: overwrite preference. This means that the current tasklet always
          schedules before returning from send/receive (it always blocks).
          (see Stackless/module/channelobject.c)
    """

    def __init__(self, label=''):
        self.balance = 0
        self.closing = False
        self.queue = None
        self.label = label
        self.preference = -1
        self.schedule_all = False

    def __str__(self):
        return 'channel[%s](%s,%s)' % (self.label, self.balance, self.queue)


    def printQueue(self):
        print "PRINTING QUEUE"
        p = self.queue
        while p != None:
            print p.tasklet
            p = p.next


    def close(self):
        """
        channel.close() -- stops the channel from enlarging its queue.
        
        If the channel is not empty, the flag 'closing' becomes true.
        If the channel is empty, the flag 'closed' becomes true.
        """
        self.closing = True

    @property
    def closed(self):
        return self.closing and not self.queue

    def open(self):
        """
        channel.open() -- reopen a channel. See channel.close.
        """
        self.closing = False


    def addOperation(self, operation):
        if self.queue:
           operation.prev = self.__tail
           self.__tail.next = operation
        else:
           operation.prev = None
           self.queue = operation

        operation.next = None
        self.__tail = operation
        self.balance += operation.dir


    def removeOperation(self, operation):
        if operation == self.queue:
           self.queue = operation.next
        if operation.next:
           operation.next.prev = operation.prev
        if operation.prev:
           operation.prev.next = operation.next
        if operation == self.__tail:
           self.__tail = operation.prev
        self.balance -= operation.dir


    def _channel_action(self, operation):
        debug("[entering channel_action]")
        """
        operation == -1 : receive
        operation ==  1 : send

        the original CStackless has an argument 'stackl' which is not used
        here.

        'target' is the peer tasklet to the current one
        """
        
        if _channel_callback is not None:
           _channel_callback(self, getcurrent(), operation)

        target = self.queue

        operation.copyOperation(target) 
        target.tasklet._operation = target

        #clear operation from remaining channels
        target.removeall()

        target.tasklet.blocked = 0

        if self.schedule_all:
            # examine this logic
           _scheduler_append(target.tasklet)
           schedule()
        elif self.preference * operation.dir < 0:
           _scheduler_append(target.tasklet, False)
           schedule()
        else:
             # source tasklet has preference
           _scheduler_append(target.tasklet)

        debug("[EXITING channel_action]")
        return 


    def receive(self):
        """
        channel.receive() -- receive a value over the channel.
        If no other tasklet is already sending on the channel,
        the receiver will be blocked. Otherwise, the receiver will
        continue immediately, and the sender is put at the end of
        the runnables list.
        The above policy can be changed by setting channel flags.
        """
        return select([_chanop(self, RECEIVE, None)]).value

    register_stackless_primitive(receive, retval_expr='receiver.tempval')

    def send_exception(self, exp_type, msg):
        self.send(bomb(exp_type, exp_type(msg)))

    def send_sequence(self, iterable):
        for item in iterable:
            self.send(item)

    def send(self, msg):
        """
        channel.send(value) -- send a value over the channel.
        If no other tasklet is already receiving on the channel,
        the sender will be blocked. Otherwise, the receiver will
        be activated immediately, and the sender is put at the end of
        the runnables list.
        """
        return select([_chanop(self, SEND, msg)]).value

    
    def receiveCase(self):
        debug("entering receiveCase")
        result = _chanop(self, RECEIVE, None)
        debug("exit receiveCase")
        return result


    def sendCase(self, value):
        debug("entering sendCase")
        result = _chanop(self, SEND, value)
        debug("exitng receiveCase")
        return result


            
    register_stackless_primitive(send)


class _chanop(object):
   """
   _chanop is a channel operation. _chanops have a one-to-one 
   correspondence to case statements in a select
   """
   def __init__(self, channel, operation, value = None):
       self.tasklet = getcurrent()
       self.channel = channel
       self.dir = operation
       self.value = value
       self.next = None
       self.prev = None


   def __eq__(self, other):
       return self.channel == other.channel and self.dir == other.dir

   def __ne__(self, other):
       return not (self.channel == other.channel and self.dir == other.dir)

   def __str__(self):
        return '_chanop[%s](%s,%s)' % (self.tasklet, self.dir, self.value)

   def add(self):
       tasklet = getcurrent()
       self.channel.addOperation(self)
       tasklet.operations.append(self)


   def copyOperation(self, other):
       debug("[COPY]")
       if self.dir == SEND:
          other.value = self.value
       else:
          self.value = other.value
       return


   def __remove(self):
       self.channel.removeOperation(self)


   def removeall(self):
       try:
         for s in self.tasklet.operations:
              s.__remove()    
         self.tasklet.operations = []
       except:
           print sys.exc.info()


   def action(self):
       debug("_channop action")
       self.retval = self.channel._channel_action(self)
       debug("exiting _chanop action")

   def ready(self):
       return self.channel.balance * self.dir < 0

   
   def result(self):
       return self.channel, self.dir, self.value

            
class tasklet(coroutine):
    """
    A tasklet object represents a tiny task in a Python thread.
    At program start, there is always one running main tasklet.
    New tasklets can be created with methods from the stackless
    module.
    """
    tempval = None
    def __new__(cls, func=None, label=''):
        res = coroutine.__new__(cls)
        res.label = label
        res._task_id = None
        return res

    def __init__(self, func=None, label=''):
        coroutine.__init__(self)
        self._init(func, label)

    def _init(self, func=None, label=''):
        global _global_task_id
        self.func = func
        self.alive = False
        self.blocked = False
        self._task_id = _global_task_id
        self.label = label
        _global_task_id += 1

        """
        for select
        """
        self.operations = []

    def __str__(self):
        return '<tasklet[%s, %s]>' % (self.label,self._task_id)

    __repr__ = __str__

    def __call__(self, *argl, **argd):
        return self.setup(*argl, **argd)

    def bind(self, func):
        """
        Binding a tasklet to a callable object.
        The callable is usually passed in to the constructor.
        In some cases, it makes sense to be able to re-bind a tasklet,
        after it has been run, in order to keep its identity.
        Note that a tasklet can only be bound when it doesn't have a frame.
        """
        if not callable(func):
            raise TypeError('tasklet function must be a callable')
        self.func = func

    def kill(self):
        """
        tasklet.kill -- raise a TaskletExit exception for the tasklet.
        Note that this is a regular exception that can be caught.
        The tasklet is immediately activated.
        If the exception passes the toplevel frame of the tasklet,
        the tasklet will silently die.
        """
        if not self.is_zombie:
            coroutine.kill(self)
            _scheduler_remove(self)
            self.alive = False

    def setup(self, *argl, **argd):
        """
        supply the parameters for the callable
        """
        if self.func is None:
            raise TypeError('cframe function must be callable')
        func = self.func
        def _func():
            try:
                try:
                    func(*argl, **argd)
                except TaskletExit:
                    pass
            finally:
                _scheduler_remove(self)
                self.alive = False

        self.func = None
        coroutine.bind(self, _func)
        self.alive = True
        _scheduler_append(self)
        return self


    def run(self):
        self.insert()
        _scheduler_switch(getcurrent(), self)

    def insert(self):
        if self.blocked:
            raise RuntimeError, "You cannot run a blocked tasklet"
            if not self.alive:
                raise RuntimeError, "You cannot run an unbound(dead) tasklet"
        _scheduler_append(self)

    def remove(self):
        if self.blocked:
            raise RuntimeError, "You cannot remove a blocked tasklet."
        if self is getcurrent():
            raise RuntimeError, "The current tasklet cannot be removed."
            # not sure if I will revive this  " Use t=tasklet().capture()"
        _scheduler_remove(self)
        
    def __reduce__(self):
        one, two, coro_state = coroutine.__reduce__(self)
        assert one is coroutine
        assert two == ()
        # we want to get rid of the parent thing.
        # for now, we just drop it
        a, b, c, d = coro_state
        if d:
            assert isinstance(d, coroutine)
        coro_state = a, b, c, None
        coro_state, alive, tempval = rewrite_stackless_primitive(coro_state, self.alive, self.tempval)
        inst_dict = self.__dict__.copy()
        inst_dict.pop('tempval', None)
        return self.__class__, (), (coro_state, alive, tempval, inst_dict)

    def __setstate__(self, (coro_state, alive, tempval, inst_dict)):
        coroutine.__setstate__(self, coro_state)
        self.__dict__.update(inst_dict)
        self.alive = alive
        self.tempval = tempval

def getmain():
    """
    getmain() -- return the main tasklet.
    """
    return _main_tasklet

def getcurrent():
    """
    getcurrent() -- return the currently executing tasklet.
    """

    curr = coroutine.getcurrent()
    if curr is _main_coroutine:
        return _main_tasklet
    else:
        return curr

_run_calls = []
def run():
    """
    run_watchdog(timeout) -- run tasklets until they are all
    done, or timeout instructions have passed. Tasklets must
    provide cooperative schedule() calls.
    If the timeout is met, the function returns.
    The calling tasklet is put aside while the tasklets are running.
    It is inserted back after the function stops, right before the
    tasklet that caused a timeout, if any.
    If an exception occours, it will be passed to the main tasklet.

    Please note that the 'timeout' feature is not yet implemented
    """
    curr = getcurrent()
    _run_calls.append(curr)
    _scheduler_remove(curr)
    try:
        schedule()
        assert not _squeue
    finally:
        _scheduler_append(curr)
    
def schedule_remove(retval=None):
    """
    schedule(retval=stackless.current) -- switch to the next runnable tasklet.
    The return value for this call is retval, with the current
    tasklet as default.
    schedule_remove(retval=stackless.current) -- ditto, and remove self.
    """
    _scheduler_remove(getcurrent())
    r = schedule(retval)
    return r


def schedule(retval=None):
    """
    schedule(retval=stackless.current) -- switch to the next runnable tasklet.
    The return value for this call is retval, with the current
    tasklet as default.
    schedule_remove(retval=stackless.current) -- ditto, and remove self.
    """
    debug("SCHEDULE")
    mtask = getmain()
    curr = getcurrent()
    if retval is None:
        retval = curr
    while True:
        debug("SQUEUE:" + str(_squeue))
        if _squeue:
            if _squeue[0] is curr:
                # If the current is at the head, skip it.
                debug("NEXT")
                _squeue.rotate(-1)
                
            task = _squeue[0]
            #_squeue.rotate(-1)
        elif _run_calls:
            task = _run_calls.pop()
        else:
            raise RuntimeError('No runnable tasklets left.')
        debug("SWITCHING " + str(curr) + " to " + str(task))
        _scheduler_switch(curr, task)
        if curr is _last_task:
            # We are in the tasklet we want to resume at this point.
            return retval


def select(operations):
    """
    The select function searches a list of channel operations
    if one or more channels are ready, one is randomly selected
    if no channel is ready, the tasklet suspends until a peer
    tasklet is ready

    returns a channel operation (_chanop)
    """

    choice = None
    source = getcurrent()
    numberReady = 0

    """
    check for operations for one or more ready channels
    use Pike's one pass algorithm
    """
    for operation in operations:
        if operation.ready():
            numberReady += 1
            if nrand(numberReady) == 0:
                choice = operation
 
    if choice:
       debug("[START OPERATION]")
       choice.action()
       debug("END OPERATION]")
    else:
       debug("START SUSPEND PROCESS")

       for operation in operations:
           debug("entering operation add")
           operation.add()
           debug("exiting operation add")

       schedule_remove()
       schedule()
 
       choice = source._operation
       source._operation = None
       debug("RESUME PROCESS")
 
    debug("exiting select")
    return choice 


def _init():
    global _main_tasklet
    global _global_task_id
    global _squeue
    global _last_task
    _global_task_id = 0
    _main_tasklet = coroutine.getcurrent()
    try:
        _main_tasklet.__class__ = tasklet
    except TypeError: # we are running pypy-c
        class TaskletProxy(object):
            """TaskletProxy is needed to give the _main_coroutine tasklet behaviour"""
            def __init__(self, coro):
                self._coro = coro

            def __getattr__(self,attr):
                return getattr(self._coro,attr)

            def __str__(self):
                return '<tasklet %s a:%s>' % (self._task_id, self.is_alive)

            def __reduce__(self):
                return getmain, ()

            __repr__ = __str__


        global _main_coroutine
        _main_coroutine = _main_tasklet
        _main_tasklet = TaskletProxy(_main_tasklet)
        assert _main_tasklet.is_alive and not _main_tasklet.is_zombie
    _last_task = _main_tasklet
    tasklet._init.im_func(_main_tasklet, label='main')
    _squeue = deque()
    _scheduler_append(_main_tasklet)

_init()
