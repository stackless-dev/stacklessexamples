#util.py
import sys
import stackless
import contextlib
import weakref
from .main import mainloop, event_queue

import threading
if hasattr(threading, "real_threading"):
    _RealThread = threading.realthreading.Thread
else:
    _RealThread = threading.Thread
del threading
    

@contextlib.contextmanager
def atomic():
    """a context manager to make the tasklet atomic for the duration"""
    c = stackless.getcurrent()
    old = c.set_atomic(True)
    try:
        yield
    finally:
        c.set_atomic(old)
        
@contextlib.contextmanager
def block_trap(trap=True):
    """
    A context manager to temporarily set the block trap state of the
    current tasklet.  Defaults to setting it to True
    """
    c = stackless.getcurrent()
    old = c.block_trap
    c.block_trap = trap
    try:
        yield
    finally:
        c.block_trap = old

@contextlib.contextmanager
def ignore_nesting(flag=True):
    """
    A context manager which allows the current tasklet to engage the
    ignoring of nesting levels.  By default pre-emptive switching can
    only happen at the top nesting level, setting this allows it to
    happen at all nesting levels.  Defaults to setting it to True.
    """
    c = stackless.getcurrent()
    old = c.set_ignore_nesting(flag)
    try:
        yield
    finally:
        c.set_ignore_nesting(old)

class local(object):
    """Tasklet local storage.  Similar to threading.local"""
    def __init__(self):
        object.__getattribute__(self, "__dict__")["_tasklets"] = weakref.WeakKeyDictionary()
        
    def get_dict(self):
        d = object.__getattribute__(self, "__dict__")["_tasklets"]
        try:
            a = d[stackless.getcurrent()]
        except KeyError:
            a = {}
            d[stackless.getcurrent()] = a
        return a
        
    def __getattribute__(self, name):        
        a = object.__getattribute__(self, "get_dict")()
        if name == "__dict__":
            return a
        elif name in a:
            return a[name]
        else:
            return object.__getattribute__(self, name)            

    
    def __setattr__(self, name, value):
        a = object.__getattribute__(self, "get_dict")()
        a[name] = value
        
    def __delattr__(self, name):
        a = object.__getattribute__(self, "get_dict")()
        try:
            del a[name]
        except KeyError:
            raise AttributeError, name
            

def call_on_thread(target, args=(), kwargs={}):
    """Run the given callable on a different thread and return the result
       This function blocks on a channel until the result is available.
       Ideal for performing OS type tasks, such as saving files or compressing
    """
    chan = stackless.channel()
    def Helper():
        try:
            r = target(*args, **kwargs)
            chan.send(r)
        except:
            e, v = sys.exc_info()[:2]
            chan.send_exception(e, v)
        finally:
            #in break any wait in progress
            mainloop.interrupt_wait()
    thread = _RealThread(target=Helper)
    thread.start()  #can take up to a few ms.  A pool would help here.
    return chan.receive()


class WaitTimeoutError(RuntimeError):
    pass
    
def channel_wait(chan, timeout):
    if timeout is None:
        chan.receive()
        return
        
    waiting_tasklet = stackless.getcurrent()
    def break_wait():
        #careful to only timeout if it is still blocked.  This ensures
        #that a successful channel.send doesn't simultaneously result in
        #a timeout, which would be a terrible source of race conditions.
        with atomic():
            if waiting_tasklet and waiting_tasklet.blocked:
                waiting_tasklet.raise_exception(WaitTimeoutError)
    with atomic():
        try:
            #schedule the break event after a certain time
            event_queue.push_after(break_wait, timeout)
            return chan.receive()
        finally:
            waiting_tasklet = None

    
class ValueEvent(stackless.channel):
    """
    This synchronization object wraps channels in a simpler interface
    and takes care of ensuring that any use of the channel after its
    lifetime has finished results in a custom exception being raised
    to the user, rather than the standard StopIteration they would
    otherwise get.

    set() or abort() can only be called once for each instance of this object.
    """

    def __new__(cls, timeout=None, timeoutException=None, timeoutExceptionValue=None):
        obj = super(stackless.channel, cls).__new__(cls)
        obj.timeout = timeout

        if timeout > 0.0:
            if timeoutException is None:
                timeoutException = WaitTimeoutError
                timeoutExceptionValue = "Event timed out"

            def break_wait():
                if not obj.closed:
                    obj.abort(timeoutException, timeoutExceptionValue)
            event_queue.push_after(break_wait, timeout)

        return obj

    def __repr__(self):
        return "<ValueEvent object at 0x%x, balance=%s, queue=%s, timeout=%s>" % (id(self), self.balance, self.queue, self.timeout)

    def set(self, value=None):
        """
        Resume all blocking tasklets by signaling or sending them 'value'.
        This function will raise an exception if the object is already signaled or aborted.
        """
        if self.closed:
            raise RuntimeError("ValueEvent object already signaled or aborted.")

        while self.queue:
            self.send(value)

        self.close()
        self.exception, self.value = RuntimeError, "Already resumed"

    def abort(self, exception=None, value=None):
        """
        Abort all blocking tasklets by raising an exception in them.
        This function will raise an exception if the object is already signaled or aborted.
        """
        if self.closed:
            raise RuntimeError("ValueEvent object already signaled or aborted.")

        if exception is None:
            exception, value = self.exception, self.value
        else:
            self.exception, self.value = exception, value

        while self.queue:
            self.send_exception(exception, value)

        self.close()

    def wait(self):
        """Wait for the data. If time-out occurs, an exception is raised"""
        if self.closed:
            raise self.exception(self.value)
            
        return self.receive()

