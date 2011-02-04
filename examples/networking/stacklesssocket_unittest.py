import thread
import stackless
import sys

import stacklesslib.main
import stacklesslib.magic
stacklesslib.magic.monkeypatch()

import stacklesssocket
stacklesssocket.install()
stacklesssocket.managerRunning = True


import asyncore, traceback, sys, time, threading
from test import test_support

main_thread_id = stackless.main.thread_id

def new_tasklet(f, *args, **kwargs):
    try:
        f(*args, **kwargs)
    except Exception:
        print "TASKLET CAUGHT EXCEPTION"
        traceback.print_exc()


sleepingTasklets = []
workerChannels = []

# Limit the time worker tasklets are sitting around sleeping, so that they can return to the pool early if their channel is empty.
MAX_SECONDS_TO_WAIT_PERIOD = 5.0

def timeout_worker(workerChannel):
    workerChannel.preference = 1 # Prefer the sender.
    while True:
        #print "timeout_worker:SLEEP", id(workerChannel)
        workerChannels.append(workerChannel)
        secondsToWait, sleeperChannel, args = workerChannel.receive()
        #print "timeout_worker:WAKE", id(workerChannel), secondsToWait

        #print "timeout_worker:SLEEP", secondsToWait, args
        while secondsToWait > 1e-5 and sleeperChannel.balance < 0:
            secondsToActuallyWait = min(secondsToWait, MAX_SECONDS_TO_WAIT_PERIOD)
            secondsToWait -= secondsToActuallyWait
            sleep(secondsToActuallyWait)
        #print "timeout_worker:SLEPT", secondsToWait, args

        if sleeperChannel.balance < 0:
            #print "timeout_worker:WAKEUP", secondsToWait, args
            if args is not None:
                sleeperChannel.send_exception(*args)
            else:
                sleeperChannel.send(None)
        #print "timeout_worker:DONE", secondsToWait, args

# Start up a nominal amount of worker tasklets.    
for i in range(50):
    stackless.tasklet(new_tasklet)(timeout_worker, stackless.channel())

def timeout_wrap_sleep(seconds, timeoutChannel, args):
    #print "timeout_wrap_sleep:ENTER balance=%d" % timeoutChannel.balance
    if timeoutChannel.balance < 0:
        #print "timeout_wrap_sleep:SLEEP balance=%d" % timeoutChannel.balance
        sleep(seconds)
        #print "timeout_wrap_sleep:SLEPT balance=%d" % timeoutChannel.balance
        if timeoutChannel.balance < 0:
            #print "timeout_wrap_sleep:WAKEUP balance=%d" % timeoutChannel.balance
            if args is not None:
                timeoutChannel.send_exception(*args)
            else:
                timeoutChannel.send(None)
    #print "timeout_wrap_sleep:EXIT balance=%d" % timeoutChannel.balance

def main_thread_channel_timeout(seconds, timeoutChannel, args=None):
    #print "main_thread_channel_timeout:ENTER", seconds
    if stackless.current.thread_id == main_thread_id:
        #print "main_thread_channel_timeout:MAIN-THREAD"
        stackless.tasklet(timeout_wrap_sleep)(seconds, timeoutChannel, args)
    else:
        # Avoid creating new tasklets on secondary threads.
        #print "main_thread_channel_timeout:SECONDARY-THREAD"
        workerChannel = workerChannels.pop()
        if workerChannel.balance < 0:
            #print "main_thread_channel_timeout:WORKER-SEND"
            workerChannel.send((seconds, timeoutChannel, args))
            #print "main_thread_channel_timeout:WORKER-SENT"
        else:
            raise RuntimeError("Bad worker tasklet")
    #print "main_thread_channel_timeout:EXIT"

sleep = stacklesslib.main.sleep
class DummyClass:
    pass
time_replacement = DummyClass()
time_replacement.sleep = stacklesslib.magic.time_sleep
asyncore.time = time_replacement

stacklesssocket._sleep_func = sleep
stacklesssocket._timeout_func = main_thread_channel_timeout


##############

# More error context
if False: 
    def serverExplicitReady(self):
        print "self.server_ready.set()"
        print "self.serv", self.serv
        print "self.port", self.port
        self.server_ready.set()

    def clientRun(self, test_func):
        print "self.server_ready.wait()"
        self.server_ready.wait()
        print "self.client_ready.set()"
        self.client_ready.set()
        print "self.clientSetUp()"
        self.clientSetUp()
        if not callable(test_func):
            raise TypeError, "test_func must be a callable function"
        try:
            test_func()
        except Exception, strerror:
            import traceback
            traceback.print_exc()
            self.queue.put(strerror)
        self.clientTearDown()

    from test import test_socket
    test_socket.ThreadableTest.serverExplicitReady = serverExplicitReady
    test_socket.ThreadableTest.clientRun = clientRun

# More error context
if False: 
    import unittest
    OLDTextTestRunner = unittest.TextTestRunner

    class NEW_TextTestResult(unittest._TextTestResult):
        def addError(self, test, err):
            traceback.print_exc()
            return unittest._TextTestResult.addError(self, test, err)

    class NEWTextTestRunner(OLDTextTestRunner):
        def _makeResult(self):
            return NEW_TextTestResult(self.stream, self.descriptions, self.verbosity)

    unittest.TextTestRunner = NEWTextTestRunner


die = False
last_poll_time = time.time()

# Whether to monitor the threads (used by test_socket) in case of deadlock.
if True:
    def thread_name(threadId):
        if threadId == main_thread_id:
            return "main_thread"
        return "unknown"

    def dumpstacks():
        code = []
        for threadId, stack in sys._current_frames().items():
            if threadId == traceback_thread:
                continue
            code.append("\n# Thread: %s(%d)" % (thread_name(threadId), threadId))
            for filename, lineno, name, line in traceback.extract_stack(stack):
                code.append('File: "%s", line %d, in %s' % (filename, lineno, name))
                if line:
                    code.append("  %s" % (line.strip()))
        print "\n".join(code)

    # Add threading debugging support.
    def periodic_traceback():
        while not die:
            time.sleep(1.0)
            if time.time() - last_poll_time > 8.0:
                print "** Printing thread stack traces"
                dumpstacks()
                break
        #print "** Printing socket channel stack traces done, exiting"
        #stacklesssocket.dump_socket_stack_traces()
        print "** Printing thread stack traces done, exiting"
        thread.interrupt_main()
        
    traceback_thread = thread.start_new_thread(periodic_traceback, ())

from test import test_xmlrpc
from test import test_urllib
from test import test_urllib2

# Narrow down testing scope.
def run_unittests(*testNames):
    from test import test_socket
    if len(testNames):
        # For now these have to be socket test names.
        import unittest
        s = unittest.TestSuite()
        for testName in testNames:
            s.addTest(test_socket.BasicTCPTest(testName))
        unittest.TextTestRunner(verbosity=3).run(s)
    else:
        print "** run_unittests.test_socket"
        test_socket.test_main()
        print "** run_unittests.test_urllib"
        test_urllib.test_main()
        print "** run_unittests.test_urllib2"
        test_urllib2.test_main()
        print "** run_unittests.test_xmlrpc"
        test_xmlrpc.test_main()
        print "** run_unittests - done"

#############

def run():
    global last_poll_time

    testNames = [] # [ "testFromFd" ]

    run_unittests_tasklet = stackless.tasklet(new_tasklet)(run_unittests, *testNames)

    while run_unittests_tasklet.alive:
        last_poll_time = time.time()
        try:
            stacklesslib.main.mainloop.pump()
            # print "POLL", len(asyncore.socket_map),
            asyncore.poll(0.05)
            # print "SCHEDULE", stackless.runcount,
            # stackless.schedule()
        except Exception, e:
            if isinstance(e, ReferenceError):
                print "run:EXCEPTION", str(e), asyncore.socket_map
            else:
                print "run:EXCEPTION", asyncore.socket_map
                traceback.print_exc()
            sys.exc_clear()


try:
    run()
except KeyboardInterrupt:
    print "** Ctrl-c pressed"
    dumpstacks()
    # stacklesssocket.dump_socket_stack_traces()
except BaseException:
    print "** Unexpected exit from test execution."
    traceback.print_exc()
finally:
    print "** Exit"
    die = True
