#
# Stackless compatible file module:
#
# Author: Carlos E. de Paula <carlosedp@gmail.com>
#
# This code was written to serve as an example of Stackless Python usage.
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#
# This wraps the file class in order to have a file module replacement
# that uses channels and a threadpool to allow calls to it to
# block just the calling tasklet until a delayed event occurs.
#
# Not all methods of the file module are wrapped as unbloking by this file.
# Examples of it in use can be seen at the bottom of this file.
#

import threading
import sys
import Queue
import stackless
stdfile = file

class WorkerThread(threading.Thread):
    """Background thread connected to the requests/results queues/channels.

    A worker thread sits in the background and picks up work requests from
    one queue and puts the results in a stackless channel until it is dismissed.
    """

    def __init__(self, requestsQueue, resultsChannel, **kwds):
        """Set up thread in damonic mode and start it immediatedly.

        requestsQueue is an instance of Queue.Queue and and resultQueue
        is a stackless channel passed by the ThreadPool class when
        it creates a new worker thread.
        """
        threading.Thread.__init__(self, **kwds)
        self.setDaemon(1)
        self.workRequestQueue = requestsQueue
        self.resultsChannel = resultsChannel
        self._dismissed = threading.Event()
        self.start()

    def run(self):
        """Repeatedly process the job queue until told to exit.
        """
        while not self._dismissed.isSet():
            # thread blocks here, if queue empty
            request = self.workRequestQueue.get()
            if self._dismissed.isSet():
                # return the work request we just picked up if gets dismissed
                self.workRequestQueue.put(request)
                break # and exit
            # Sends the processed data over the results channel if an error happens
            # send the exception directly to the tasklet via its channel.
            try:
                data = request.callable(*request.args, **request.kwds)
                self.resultsChannel.send((data, request.ch, request.requestID))
            except:
                exc, val, ad = sys.exc_info()
                request.ch.send_exception(exc, val)

    def dismiss(self):
        """Sets a flag to tell the thread to exit when done with current job.
        """
        self._dismissed.set()


class WorkRequest(object):
    """
    A request to execute a callable for putting in the request queue later.
    """

    def __init__(self, callable, args=None, kwds=None, requestID=None, ch=None):
        """A work request consists of the a callable to be executed by a
        worker thread, a list of positional arguments, a dictionary
        of keyword arguments.

        The callback channel is called when the results of the request are
        picked up from the result queue. It must accept two arguments,
        the request object, the request object channel and it's results in
        that order.

        requestID, if given, must be hashable as it is used by the ThreadPool
        class to store the results of that work request in a dictionary.
        It defaults to the return value of id(self).
        """
        if requestID is None:
            self.requestID = id(self)
        else:
            self.requestID = requestID
        self.callable = callable
        self.ch = ch
        self.args = args or []
        self.kwds = kwds or {}

class ThreadPool(object):
    """A thread pool, distributing work requests and collecting results.

    See the module doctring for more information.
    """

    def __init__(self, num_workers, q_size=0):
        """Set up the thread pool and start num_workers worker threads.

        num_workers is the number of worker threads to start initialy.
        If q_size > 0 the size of the work request is limited and the
        thread pool blocks when queue is full and it tries to put more
        work requests in it.
        """
        self.requestsQueue = Queue.Queue(q_size)
        self.resultsChannel = stackless.channel()
        self.workers = []
        self.workRequests = {}
        self.createWorkers(num_workers)
        stackless.tasklet(self.resultsManager)()
        self.managerRunning = True

    def resultsManager(self):
        """
        Manages the results sent by the worker threads. The resultsManager
        Receives the tuple containing the data, the file object callback channel
        and the requestID via its resultsChannel. The data is received and fired
        back to the channel object via its channel.send() unblocking the
        original tasklet.
        The request is then removed from the workRequests dict.
        """
        while self.workRequests:
            data, ch, reqID = self.resultsChannel.receive()
            ch.send(data)
            del self.workRequests[reqID]
            #self.managePoolSize()
            stackless.schedule()
        self.managerRunning = False

    def managePoolSize(self):
        """
        This is called when new requests are added and concluded from the
        processing. It calculates roughly based on workers and work to do and
        adds or removes worker threads.
        """
        work = int(len(self.workRequests) - len(self.workers))/5
        if work > 0:
            #print "Creating %s workers" % work
            self.createWorkers(work)
        elif work < 0 and len(self.workers) > 3:
            #print "Deleting %s workers" % abs(work)
            self.dismissWorkers(abs(work))
        #print "Currently we have %s workers." % len(self.workers)

    def createWorkers(self, num_workers):
        """Add num_workers worker threads to the pool."""

        for i in range(num_workers):
            self.workers.append(WorkerThread(self.requestsQueue, self.resultsChannel))

    def dismissWorkers(self, num_workers):
        """Tell num_workers worker threads to to quit when they're done."""
        for i in range(min(num_workers, len(self.workers))):
            worker = self.workers.pop()
            worker.dismiss()

    def putRequest(self, request):
        """Put work request into work queue and save for later."""
        #self.managePoolSize()
        self.requestsQueue.put(request)
        self.workRequests[request.requestID] = request

main = ThreadPool(4)

class stacklessfile(object):
    """
    This class wraps the file module to create nonblocking IO calls for tasklets.
    When a read or write operation is called, only the calling tasklet is
    blocked. In standard file module, the whole interpreter gets blocked until
    the operation is concluded.
    """
    def __init__(self, *args, **kwargs):
        """
        Initializes the file object and creates an internal file object.
        """
        self.f = stdfile(*args, **kwargs)
        self.ch = stackless.channel()
        if not main.managerRunning:
            main.managerRunning = True
            stackless.tasklet(main.resultsManager)()

        # Here the original file() attributes are exported
        self.closed = self.f.closed
        self.encoding = self.f.encoding
        self.mode = self.f.mode
        self.name = self.f.name
        self.newlines = self.f.newlines
        self.softspace  = self.f.softspace


        # Here the original file() methods are exported
        self.close = self.f.close
        self.flush = self.f.flush
        self.fileno = self.f.fileno
        self.isatty = self.f.isatty
        self.readline = self.f.readline
        self.seek = self.f.seek
        self.tell = self.f.tell
        self.truncate = self.f.truncate
        self.writelines = self.f.writelines


    def read(self, *args, **kwargs):
        """
        Wraps the read() call and fire the request to be executed by a threadpool.
        """
        req = WorkRequest(self.f.read, args, kwargs, ch=self.ch)
        main.putRequest(req)
        return self.ch.receive()

    def write(self, *args, **kwargs):
        """
        Wraps the write() call and fire the request to be executed by a threadpool.
        """
        req = WorkRequest(self.f.write, args, kwargs, ch=self.ch)
        main.putRequest(req)
        data = self.ch.receive()
        return data

    def next(self, *args, **kwargs):
        """
        Calls the original file.next() method. This iterator calls the original
        file() iterator so it is advised that calls to the schedule() are made
        during the loop to allow other tasklets run.

        Ex. for line in file:
                print line
                stackless.schedule()
        """
        return self.f.next(*args, **kwargs)

if __name__ == '__main__':
    import time
    import glob
    import os
    file = stacklessfile
    open = file

    # In the app, import stacklessfile class directly like the example below
    #
    # from stacklessfile import stacklessfile as file
    # open = file
    #

    # Function to copy a file
    def copyfile(who, infile, out):
        st = time.time()
        f1 = file(infile, 'rb')
        f2 = file(out, 'wb')
        print "%s started reading %s ..." % (who, infile)
        a = f1.read()
        print "%s started writing %s -> %s ..." % (who, infile, out)
        f2.write(a)
        f1.close()
        f2.close()
        print "Finished tasklet %s (%s) in %s" % (who, infile, time.time()-st)

    # Creating two dummy files
    newfile = stdfile('test.txt','w')
    for x in xrange(10000):
        newfile.write(str(x))
    newfile.close()

    newfile2 = stdfile('test2.txt','w')
    for x in xrange(500000):
        newfile2.write(str(x))
    newfile2.close()

    # Launching tasklets to perform the file copy
    for i in xrange(10):
        stackless.tasklet(copyfile)(i, 'test2.txt','x%s.txt' % i)

    for i in xrange(30):
        stackless.tasklet(copyfile)(i, 'test.txt','xx%s.txt' % i)

    st = time.time()
    stackless.run()
    print "Total time is %s seconds." % (time.time() - st)

    # Cleanup all test files used
    for f in glob.glob('x*.txt'):
        os.unlink(f)
    os.unlink('test.txt')
    os.unlink('test2.txt')
