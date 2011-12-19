#sliomain.py 

import heapq
import sys
import time
import traceback

import stackless
try:
    import stacklessio
except ImportError:
    stacklessio = None

_sleep = time.sleep # Steal this before monkeypatching occurs.

# Get the best wallclock time to use.
if sys.platform == "win32":
    elapsed_time = time.clock
else:
    # Time.clock reports CPU time on unix, not good.
    elapsed_time = time.time

# Tools for adjusting the scheduling mode.

SCHEDULING_ROUNDROBIN = 0
SCHEDULING_IMMEDIATE = 1
scheduling_mode = SCHEDULING_ROUNDROBIN


def set_scheduling_mode(mode):
    global scheduling_mode
    old = scheduling_mode
    if mode is not None:
        scheduling_mode = mode
    return old

    
def set_channel_pref(c):
    if scheduling_mode == SCHEDULING_ROUNDROBIN:
        c.preference = 0
    else:
        c.preference = -1
    
    
# A event queue class.
class EventQueue(object):
    def __init__(self):
        self.queue_a = []
        self.queue_b = []
        
    def push_at(self, what, when):
        """
        Push an event that will be executed at the given UTC time.
        """
        # The heappush operation should be atomic, so we don't need locking
        # even when it comes from another thread.
        heapq.heappush(self.queue_a, (when, what))
        
    def push_after(self, what, delay):
        """
        Push an event that will be executed after a certain delay in seconds.
        """
        self.push_at(what, delay+elapsed_time())
        
    def push_yield(self, what):
        """
        Push an event that will be run the next time it is convenient
        """
        self.queue_b.append(what)
        
    def cancel(self, what):
        """
        Cancel an event that has been submitted.  Raise ValueError if it isn't there.
        """
        # Note, there is no way currently to ensure that either the event was
        # removed or successfully executed, i.e. no synchronization.
        # Caveat Emptor.
        try:
            self.queue_b.remove(what)
        except ValueError:
            pass
        for e in self.queue_a:
            if e[1] == what:
                self.queue_a.remove(e)
                return
        raise ValueError, "event not in queue"                        
        
    def pump(self):
        """
        The worker functino for the main loop to process events in the queue
        """
        # Get the events due now
        now = elapsed_time()
        batch_a = []
        while self.queue_a and self.queue_a[0][0] <= now:
            batch_a.append(heapq.heappop(self.queue_a))
        batch_b, self.queue_b = self.queue_b, []
        
        # Run the events, the timed ones first, then the others.
        batch_a.extend(batch_b)
        for when, what in batch_a:
            try:
                what()
            except Exception:
                self.handle_exception(sys.exc_info())
        return len(batch_a)
    
    @property
    def is_due(self):
        """Returns true if the queue needs pumping now."""
        when = self.next_time()
        if when is not None:
            return when <= elapsed_time()
    
    def next_time(self):
        """the UTC time at which the next event is due."""
        try:
            return self.queue_a[0][0]
        except IndexError:
            return None
        
    def handle_exception(self, exc_info):
        traceback.print_exception(*exc_info)
            
 
# A mainloop class.
class MainLoop(object):
    def __init__(self):
        self.max_wait_time = 1.0
        self.running = True
        self.break_wait = False
        
    def get_wait_time(self, time):
        delay = self.max_wait_time
        next_event = event_queue.next_time()
        if next_event:
            delay = min(delay, next_event - time)
            delay = max(delay, 0.0)
        return delay
        
    def wait(self, delay):
        """Wait until the next event is due.  Override this to break when IO is ready """
        try:
            if delay:
                # Sleep with 10ms granularity to allow another thread to wake us up.
                t1 = elapsed_time() + delay
                while True:
                    if self.break_wait:
                        # Ignore wakeup if there is nothing to do.
                        if not event_queue.is_due and stackless.runcount == 1:
                            self.break_wait = False
                        else:
                            break
                    now = elapsed_time()
                    remaining = t1-now
                    if remaining <= 0.0:
                        break
                    _sleep(min(remaining, 0.01))                                          
        finally:
            self.break_wait = False

    def interrupt_wait(self):
        # If another thread wants to interrupt the mainloop, e.g. if it
        # has added IO to it.
        self.break_wait = True
            
    def wakeup_tasklets(self, time):
        """ Perform whatever tasks required to wake up sleeping tasks """
        event_queue.pump()
        
    def run_tasklets(self, run_for=0):
        """ Run tasklets for as long as necessary """
        try:
            return stackless.run(run_for)
        except Exception:
            self.handle_run_error(sys.exc_info())

    def handle_run_error(self, ei):
        traceback.print_exception(*ei)

    def pump(self, run_for=0):
        t = elapsed_time()
        wait_time = self.get_wait_time(t)
        if wait_time:
            self.wait(wait_time)
            t = elapsed_time()
        self.wakeup_tasklets(t + 0.001) #fuzz
        return self.run_tasklets(run_for=run_for)
        
    def run(self):
        while self.running:
            self.pump()
            
    def stop(self):
        self.running = False
        
    def sleep(self, delay):
        """Sleep the current tasklet for a while"""
        c = stackless.channel()
        set_channel_pref(c)
        def wakeup():
            if c.balance:
                c.send(None)
        event_queue.push_after(wakeup, delay)
        c.receive()


class SLIOMainLoop(MainLoop):
    def wait(self, delay):
        stacklessio.wait(delay)
        stacklessio.dispatch()

    def interrupt_wait(self):
        stacklessio.break_wait()


# Perhaps this function should be elsewhere...
def sleep(delay):
    """Sleep the current tasklet for a while"""
    c = stackless.channel()
    set_channel_pref(c)
    def wakeup():
        if c.balance:
            c.send(None)
    event_queue.push_after(wakeup, delay)
    c.receive()

    
event_queue = EventQueue()
# Disable preferred socket solution of stacklessio for now.
if stacklessio:
    mainloop = SLIOMainLoop()
else:
    mainloop = MainLoop()
