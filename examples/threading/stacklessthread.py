#
# Stackless compatible thread module:
#
# Author: Richard Tew <richard.m.tew@gmail.com>
#
# This code was written to serve as an example of Stackless Python usage.
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#
# This is not optimal code.  It creates a thread everytime it needs one
# and could easily benefit from a thread pool, should it be used in
# non-testing situations.
#

import sys
import thread, threading, time, select
import stackless

stdallocate_lock = thread.allocate_lock
stdsleep = time.sleep
stdstart_new_thread = thread.start_new_thread
stdselect = select.select

main_thread = threading.currentThread()
try:
    main_thread_id = main_thread.ident
except AttributeError:
    print __file__, "Looks like Python 2.5, working around it"
    main_thread_id = stackless.main.thread_id

def install():
    global stdallocate_lock
    if thread.allocate is allocate_lock:
        raise StandardError("Still installed")
    thread.allocate_lock = thread.allocate = allocate_lock
    # thread.start_new_thread = start_new_thread
    threading._allocate_lock = allocate_lock
    time.sleep = _sleep
    threading._sleep = _sleep
    select.select = _select

def uninstall():
    threading._allocate_lock = stdallocate_lock
    threading._sleep = stdsleep
    thread.allocate_lock = thread.allocate = stdallocate_lock
    # thread.start_new_thread = stdstart_new_thread
    time.sleep = stdsleep
    select.select = stdselect


## time module functions

def _wait_for_sleep(seconds, channel):
    ret = stdsleep(seconds)
    channel.send(ret)

def _sleep(seconds):
    if stackless.current.thread_id == main_thread_id:
        channel = stackless.channel()
        thread_id = stdstart_new_thread(_wait_for_sleep, (seconds, channel))
        return channel.receive()
    return stdsleep(seconds)

## select module functions

def _isolate_bad_fd(idx, blist):
    args = [ [], [], [], 0 ]
    args[idx] = blist
    try:
        stdselect(*args)
        return False
    except select.error:
        return True

def _wait_for_select(channel, rlist, wlist, xlist, timeout):
    attemptsLeft = 3
    errorContext = "Broken"
    while attemptsLeft > 0:
        attemptsLeft -= 1

        try:
            ret = stdselect(rlist, wlist, xlist, timeout)
            channel.send(ret)
            return
        except select.error, e:
            errorContext = e.args
            sys.exc_clear()

            checklist = [ rlist, wlist, xlist ]
            for idx, clist in enumerate(checklist):
                clist2 = []
                if _isolate_bad_fd(idx, clist):
                    for fd in clist:
                        if not _isolate_bad_fd(idx, [ fd ]):
                            clist2.append(fd)
                if clist != clist2:
                    checklist[idx] = clist2

            oldChecklist = [ rlist, wlist, xlist ]
            if oldChecklist != checklist:
                print attemptsLeft, "FIXED", idx, "FROM", oldChecklist, "TO", checklist

            # CASE 1: Nothing valid left.
            if checklist == [ [], [], [] ]:
                channel.send(checklist)
                return

            # CASE 2: Something left, pass it through again.
            rlist, wlist, xlist = checklist

    print str(("SELECT FAILED (if you see this, copy paste it to richard)", rlist, wlist, xlist))
    channel.send_exception(select.error, errorContext)

def _select(rlist, wlist, xlist, timeout=None):
    if stackless.current.thread_id == main_thread_id and timeout != 0:
        channel = stackless.channel()
        thread_id = stdstart_new_thread(_wait_for_select, (channel, rlist, wlist, xlist, timeout))
        return channel.receive()
    return stdselect(rlist, wlist, xlist, timeout)
    

## thread module functions

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
            thread_id = stdstart_new_thread(_wait_for_lock, (self.stdlock, blocking, channel))
            return channel.receive()

        return self.stdlock.acquire(blocking)

    def __getattr__(self, name):
        return getattr(self.stdlock, name)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *args):
        self.stdlock.release()

def allocate_lock():
    return _Lock()

def _scheduler_thread_func(h, args):
    stackless.tasklet(h)(*args)
    stackless.run(threadblock=1)

def start_new_thread(f, args):
    return stdstart_new_thread(_scheduler_thread_func, (f, args))
