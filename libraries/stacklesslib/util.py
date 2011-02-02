#util.py
#See the LICENSE file for copyright information.
import sys
import stackless
import contextlib
import weakref
from stacklesslib.main import mainloop

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
