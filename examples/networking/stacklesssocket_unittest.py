import thread
import stackless


import stacklessthread
stacklessthread.install()

import stacklesssocket
stacklesssocket.install()
stacklesssocket.managerRunning = True


import asyncore, traceback, sys, time, threading
main_thread = threading.currentThread()

#import stacklessthread
#stacklessthread.install()

from test import test_socket, test_support

sleepingTasklets = []

def sleep(secondsToWait):
    """ Put the current tasklet to sleep for a number of seconds. """
    channel = stackless.channel()
    endTime = time.time() + secondsToWait
    sleepingTasklets.append((endTime, channel))
    sleepingTasklets.sort()
    # Block until we get sent an awakening notification.
    channel.receive()

def manage_sleeping_tasklets():
    """ Awaken all tasklets which are due to be awakened. """
    while True:
        while len(sleepingTasklets):
            endTime = sleepingTasklets[0][0]
            if endTime > time.time():
                break
            channel = sleepingTasklets[0][1]
            del sleepingTasklets[0]
            # It does not matter what we send as it is not used.
            channel.send(None)
        stackless.schedule()

stacklesssocket._sleep_func = sleep


##############

# More error context
if True: 
    def clientRun(self, test_func):
        print test_func, "A"
        self.server_ready.wait()
        print test_func, "B"
        self.client_ready.set()
        print test_func, "C"
        self.clientSetUp()
        print test_func, "D"
        if not callable(test_func):
            raise TypeError, "test_func must be a callable function"
        try:
            test_func()
            print test_func, "E"
        except Exception, strerror:
            traceback.print_exc()
            self.queue.put(strerror)
        print test_func, "F"
        self.clientTearDown()
        print test_func, "G"

    test_socket.ThreadableTest.clientRun = clientRun

# More error context
if True: 
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

# Remove UDP tests for now.
for k in test_socket.BasicUDPTest.__dict__.keys():
    if k.startswith("test"):
        delattr(test_socket.BasicUDPTest, k)

for k in test_socket.UDPTimeoutTest.__dict__.keys():
    if k.startswith("test"):
        delattr(test_socket.UDPTimeoutTest, k)


die = False
last_poll_time = time.time()

# Whether to monitor the threads (used by test_socket) in case of deadlock.
if False:
    def thread_name(threadId):
        if threadId == main_thread.ident:
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
        print "** Printing thread stack traces done, exiting"
        thread.interrupt_main()
        
    traceback_thread = thread.start_new_thread(periodic_traceback, ())

#############

def run_tasklet(f, *args, **kwargs):
    try:
        f(*args, **kwargs)
    except Exception:
        traceback.print_exc()

def run():
    stackless.tasklet(run_tasklet)(manage_sleeping_tasklets)
    stackless.tasklet(run_tasklet)(test_socket.test_main)

    while len(asyncore.socket_map) or stackless.runcount:
        last_poll_time = time.time()
        try:
            print "POLL", len(asyncore.socket_map),
            asyncore.poll(0.05)
            print "SCHEDULE", stackless.runcount,
            stackless.schedule()
        except Exception, e:
            traceback.print_exc()
            sys.exc_clear()


try:
    run()
except BaseException:
    print "** Unexpected exit from test execution."
    traceback.print_exc()
finally:
    print "** Exit"
    die = True
