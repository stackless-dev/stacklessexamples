#
# Stackless compatible thread module:
#
# Author: Richard Tew <richard.m.tew@gmail.com>
#
# This code was written to serve as an example of Stackless Python usage.
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#

import sys
import thread 
import stackless

stdallocate_lock = thread.allocate_lock

def install():
    global stdallocate_lock
    if thread.allocate is allocate_lock:
        raise StandardError("Still installed")
    thread.allocate_lock = thread.allocate = allocate_lock

def uninstall():
    thread.allocate_lock = thread.allocate = stdallocate_lock



def _wait_for_lock(lock, blocking, channel):
    """
    Do the blocking lock acquisition within a thread that the scheduler is not running on.
    """
    ret = lock.acquire(blocking)
    channel.send(ret)

class _Lock(object):
    """
    A proxy object to a read lock object, which redirects blocking lock acquisition to
    another thread so that the scheduler is not blocked.  Both uses of the lock may be
    in the scheduler, so if one blocks the entire thread waiting for a lock, the other
    will never get a chance to release it.
    """

    def __init__(self):
        self.stdlock = stdallocate_lock()

    def acquire(self, blocking=1):
        if blocking:
            channel = stackless.channel()
            thread_id = thread.start_new_thread(_wait_for_lock, (self.stdlock, blocking, channel))
            return channel.receive()

        return self.stdlock.acquire(blocking)

    def __getattr__(self, name):
        return getattr(self.stdlock, name)

def allocate_lock():
    return _Lock()
