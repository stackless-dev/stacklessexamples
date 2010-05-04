#
# Stackless Asynchronous file module:
#
# Author:Richard Tew (IOCP.py)
#        Carlos E. de Paula <carlosedp@gmail.com>
#
# This module has been heavily based on Richard Tew's work on IOCP.py
# Here the manager runs in a tasklet and write function works expectdly.
# I have added a sleep function like the one found on Ed Faulkner as a
# convenience if you dont have one implemented.
#
# This code was written to serve as an example of Stackless Python usage.
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#
# This is an asynchronous file class in order to have a file module replacement
# that uses channels and a windows async API to allow its methods to
# block just the calling tasklet not the entire interpreter.
#
#
import os
import time
import stackless
from heapq import heappush, heappop
from ctypes import *
from ctypes.wintypes import HANDLE, ULONG, DWORD, BOOL, LPCSTR, LPCWSTR, WinError

# Windows structures

class _US(Structure):
    _fields_ = [
        ("Offset",          DWORD),
        ("OffsetHigh",      DWORD),
    ]

class _U(Union):
    _fields_ = [
        ("s",               _US),
        ("Pointer",         c_void_p),
    ]

    _anonymous_ = ("s",)

class OVERLAPPED(Structure):
    _fields_ = [
        ("Internal",        POINTER(ULONG)),
        ("InternalHigh",    POINTER(ULONG)),
        ("u",               _U),
        ("hEvent",          HANDLE),

        # Custom fields.
        ("taskletID",       ULONG),
    ]

    _anonymous_ = ("u",)

# Windows kernel32 API

CreateIoCompletionPort = windll.kernel32.CreateIoCompletionPort
CreateIoCompletionPort.argtypes = (HANDLE, HANDLE, POINTER(c_ulong), DWORD)
CreateIoCompletionPort.restype = HANDLE

GetQueuedCompletionStatus = windll.kernel32.GetQueuedCompletionStatus
GetQueuedCompletionStatus.argtypes = (HANDLE, POINTER(DWORD), POINTER(c_ulong),
                                      POINTER(POINTER(OVERLAPPED)), DWORD)
GetQueuedCompletionStatus.restype = BOOL

ReadFile = windll.kernel32.ReadFile
ReadFile.argtypes = (HANDLE, c_void_p, DWORD, POINTER(DWORD), POINTER(OVERLAPPED))
ReadFile.restype = BOOL

WriteFile = windll.kernel32.WriteFile
WriteFile.argtypes = (HANDLE, c_void_p, DWORD, POINTER(DWORD), POINTER(OVERLAPPED))
WriteFile.restype = BOOL

CreateFileA = windll.kernel32.CreateFileA
CreateFileA.argtypes = (LPCSTR, DWORD, DWORD, c_void_p, DWORD, DWORD, HANDLE)
CreateFileA.restype = HANDLE

CreateFileW = windll.kernel32.CreateFileW
CreateFileW.argtypes = (LPCWSTR, DWORD, DWORD, c_void_p, DWORD, DWORD, HANDLE)
CreateFileW.restype = HANDLE

CloseHandle = windll.kernel32.CloseHandle
CloseHandle.argtypes = (HANDLE,)
CloseHandle.restype = BOOL

GetLastError = windll.kernel32.GetLastError

# Python API

pythonapi.PyErr_SetFromErrno.argtypes = (py_object,)
pythonapi.PyErr_SetFromErrno.restype = py_object

# Windows definitions

INVALID_HANDLE_VALUE    = 0xFFFFFFFF
NULL                    = c_ulong()

WAIT_TIMEOUT            = 0x102
ERROR_IO_PENDING        = 997
FILE_FLAG_RANDOM_ACCESS = 0x10000000
FILE_FLAG_OVERLAPPED    = 0x40000000

GENERIC_READ            = 0x80000000
GENERIC_WRITE           = 0x40000000
FILE_APPEND_DATA                = 0x00000004

FILE_SHARE_READ         = 0x00000001
FILE_SHARE_WRITE        = 0x00000002

OPEN_EXISTING           = 3
OPEN_ALWAYS             = 4
CREATE_ALWAYS           = 2

# ----------------------------------------------------------------------------

class resultsManager(object):
    """
    Manages the results sent by the CreateIoCompletionPort call.
    The resultsManager dequeues the IO requests and keeps a list of pending handles.
    The taskletID is stored in OVERLAPPED structure so it can be recalled and the
    signalling data sent via its channel unblocking the original tasklet.
    The handle is then removed from the dict.
    """
    def __init__(self, numThreads=NULL):
        self.running = True
        self.handle = CreateIoCompletionPort(INVALID_HANDLE_VALUE, HANDLE(0),
                                             NULL, numThreads)
        if self.handle == 0:
            raise WinError()

        self.numThreads = numThreads
        stackless.tasklet(self.poll)()
        self.overlappedByID = {}
        self._sleepers = []

    def __del__(self):
        if self.handle is None:
            return
        self.overlappedByID.clear()
        CloseHandle(self.handle)

    def _check_running(self):
        if not self.running:
            stackless.tasklet(self.poll)()
            self.running = True
            #print "ERROR - Manager not running"

    def poll(self, timeout=1):
        while self.running and (self.overlappedByID or self._sleepers):
            self._check_sleepers()
            numBytes = DWORD()
            completionKey = c_ulong()
            ovp = POINTER(OVERLAPPED)()

            ret = GetQueuedCompletionStatus(self.handle, byref(numBytes),
                                            byref(completionKey), byref(ovp),
                                            timeout)

            if not ovp and ret == 0:
                if GetLastError() == WAIT_TIMEOUT:
                    stackless.schedule()
                    continue

            if ovp.contents.taskletID in self.overlappedByID:
                #print ovp.contents.taskletID, " tasklet ID IN pool"
                c = self.overlappedByID[ovp.contents.taskletID]
            else:
                #print ovp.contents.taskletID, " tasklet ID NOT in pool"
                continue

            #print "sending data back to channel in ID", ovp.contents.taskletID
            c.send(numBytes)
            #print "sent data to channel in ID", ovp.contents.taskletID, numBytes
            self.UnregisterChannelObject(ovp.contents.taskletID)

        self.running = False

    def _check_sleepers(self):
        now = time.time()
        while self._sleepers and self._sleepers[0][0] < now:
            waketime, chan = heappop(self._sleepers)
            # Only send if someone is waiting to receive (in some
            # cases the tasklet in question will already have been
            # awoken elsewhere)
            if chan.balance < 0:
                chan.send(None)
        #if self._sleepers:
        #    return self._sleepers[0][0]

    def RegisterChannelObject(self, ob, c):
        self.overlappedByID[ob] = c

    def UnregisterChannelObject(self, ob):
        if self.overlappedByID.has_key(ob):
            del self.overlappedByID[ob]

    def sleep(self, seconds, channel = None):
        waketime = time.time() + seconds
        if channel is None:
            channel = stackless.channel()
        heappush(self._sleepers, (waketime, channel))
        self._check_running()
        channel.receive()


mng = resultsManager()

class stacklessfileIOCP(object):
    """
    stacklessfile(name[, mode[, buffering]]) -> stackless file object

    This class creates a new file module permitting nonblocking IO calls
    for tasklets using windows IOCP functionality.
    When a read or write operation is called, only the calling tasklet is
    blocked. In standard file module, the whole interpreter gets blocked
    until the operation is concluded.

    Open a file.  The mode can be 'r', 'w' or 'a' for reading (default),
    writing or appending.  The file will be created if it doesn't exist
    when opened for writing or appending; it will be truncated when
    opened for writing.  Add a 'b' to the mode for binary files.
    Add a '+' to the mode to allow simultaneous reading and writing.
    If the buffering argument is given, 0 means unbuffered, 1 means line
    buffered, and larger numbers specify the buffer size.
    Add a 'U' to mode to open the file for input with universal newline
    support.  Any line ending in the input file will be seen as a \'\\n\'
    in Python.  Also, a file so opened gains the attribute 'newlines';
    the value for this attribute is one of None (no newline read yet),
    \'\\r\', \'\\n\', \'\\r\\n\' or a tuple containing all the newline types seen.
    """
    closed = True
    def __init__(self, name, mode='r', buffering=-1):
        """
        Initializes the file object and creates an internal file object.
        """
        if not self.closed:
            self.close()
        self.name = name
        self.mode = mode
        self.softspace = 0
        self.offset = 0
        self.iocpLinked = False
        mng._check_running()
        self.open_handle()
        self.closed = False

    def __repr__(self):
        return "<%s file '%s', mode '%s' at 0x%08X>" % ([ "open", "closed" ][self.closed], self.name, self.mode, id(self))

    def __del__(self):
        self.close()

    def __exit__(self, *args):
        self.close()

    def _check_still_open(self):
        if self.closed:
            raise ValueError("I/O operation on closed file")

    def _ensure_iocp_association(self):
        if not self.iocpLinked:
            CreateIoCompletionPort(self.handle, mng.handle, NULL, mng.numThreads)
            self.iocpLinked = True

    def close(self):
        """
        close() -> None or (perhaps) an integer.  Close the file.

        Sets data attribute .closed to True.  A closed file canno
        further I/O operations.  close() may be called more than
        error.  Some kinds of file objects (for example, opened b
        may return an exit status upon closing.
        """
        if not self.closed:
            CloseHandle(self.handle)
            del self.handle
            self.closed = True

    def open_handle(self):
        self.binary = 'b' in self.mode
        access = GENERIC_READ
        if 'w' in self.mode or ('r' in self.mode and '+' in self.mode):
            access |= GENERIC_WRITE
        if 'a' in self.mode:
            access |= FILE_APPEND_DATA

        share = FILE_SHARE_READ | FILE_SHARE_WRITE

        if 'w' in self.mode:
            disposition = CREATE_ALWAYS
        elif 'r' in self.mode and '+' in self.mode:
            disposition = OPEN_ALWAYS
        else:
            disposition = OPEN_EXISTING

        flags = FILE_FLAG_RANDOM_ACCESS | FILE_FLAG_OVERLAPPED

        if isinstance(self.name, unicode):
            func = CreateFileW
        else:
            func = CreateFileA

        self.handle = func(self.name, access,
                              share, c_void_p(), disposition,
                              flags, HANDLE(0) )

        if self.handle == INVALID_HANDLE_VALUE:
            raise WinError()

        self.iocpLinked = False

    def read(self, size=None):
        """
        read([size]) -> read at most size bytes, returned as a string.
        """
        self._check_still_open()
        maxBytesToRead = int(os.path.getsize(self.name)) - self.offset
        if (size is None) or (maxBytesToRead < size):
            size = maxBytesToRead

        bytesRead = DWORD()
        self.o = OVERLAPPED()
        self.o.Offset = self.offset
        self.o.taskletID = id(self)
        self.buffer = create_string_buffer(size)
        self.channel = stackless.channel()
        self._ensure_iocp_association()
        mng._check_running()

        #print self.o.taskletID, "ID on read", self.name
        #print "firing ReadFile", self.name

        r = ReadFile(self.handle, self.buffer,
                     size, byref(bytesRead), byref(self.o));
        #print "fired ReadFile", self.name

        if r == 0:
            if GetLastError() != ERROR_IO_PENDING:
                pythonapi.PyErr_SetExcFromWindowsErrWithFilename(py_object(IOError),
                                                                 0, c_char_p(self.name))
            mng.RegisterChannelObject(self.o.taskletID, self.channel)
            #print "blocked on channel",self.channel, self.name, self.o.taskletID
            self.channel.receive()
            #print "returned from channel",self.channel, self.name, self.o.taskletID

        self.offset += size
        return self.buffer[:size]

    def write(self, data):
        """
        write(str) -> None.  Write string str to file.
        """
        self._check_still_open()
        bytesToWrite = c_int()
        writeBufferPtr = c_char_p()
        bytesWritten = DWORD()
        self.o = OVERLAPPED()
        self.o.Offset = self.offset
        self.o.taskletID = id(self)
        self.channel = stackless.channel()
        self._ensure_iocp_association()
        mng._check_running()
        #print self.o.taskletID, "ID on write", self.name

        fmt = self.binary and "s#" or "t#"
        ret = pythonapi.PyArg_ParseTuple(py_object((data,)), c_char_p(fmt),
                                         byref(writeBufferPtr), byref(bytesToWrite))
        if ret == 0:
            raise WinError()

        #print "firing WriteFile", self.name
        r = WriteFile(self.handle, writeBufferPtr,
                      bytesToWrite.value, byref(bytesWritten), byref(self.o))
        #print "fired WriteFile", self.name

        if r == 0:
            if GetLastError() != ERROR_IO_PENDING:
                pythonapi.PyErr_SetExcFromWindowsErrWithFilename(py_object(IOError),
                                                                 0, c_char_p(self.name))

            mng.RegisterChannelObject(self.o.taskletID, self.channel)
            #print "blocked on channel",self.channel, self.name, self.o.taskletID
            written = self.channel.receive()
            #print "returned from channel",self.channel, self.name, self.o.taskletID
        else:
            written = bytesWritten
        #print "Checking contents...", bytesToWrite.value, written.value, self.name

        if bytesToWrite.value != written.value:
            # Check if the quantity of bytes sent has been written to the file
            #print self.o.taskletID, "size mismatch"
            raise WinError()

    def tell(self):
        """
        tell() -> current file position, an integer (may be a long integer).
        """
        return self.offset

    def flush(self):
        """
        flush() -> None.  Flush the internal I/O buffer.
        """
        pass

    def seek(self, offset, whence=os.SEEK_SET):
        """
        seek(offset[, whence]) -> None.  Move to new file position.

        Argument offset is a byte count.  Optional argument whence defaults to
        0 (offset from start of file, offset should be >= 0); other values are 1
        (move relative to current position, positive or negative), and 2 (move
        relative to end of file, usually negative, although many platforms allow
        seeking beyond the end of a file).  If the file is opened in text mode,
        only offsets returned by tell() are legal.  Use of other offsets causes
        undefined behavior.
        Note that not all file objects are seekable.
        """
        self._check_still_open()
        if whence == os.SEEK_SET:
            self.offset = offset
        elif whence == os.SEEK_CUR:
            self.offset += offset
        elif whence == os.SEEK_END:
            raise RuntimeError("SEEK_END unimplemented")

    def flush(self):
        pass

    def isatty(self):
        """
        isatty() -> true or false.  True if the file is connected to a tty device.
        """
        self._check_still_open()
        return False

    def isatty(self):
        self._check_still_open()
        return False


#----------------------------------------------------------------------------
# Verify module compatibility

if os.name == 'nt':
    stacklessfile = stacklessfileIOCP
else:
    raise ImportError('Your operating system is not supported.')

#----------------------------------------------------------------------------

if __name__ == '__main__':
    import time
    import glob
    import os
    stdfile = file

    # On your stackless apps, use these 2 lines below
    
    #from stacklessfileIOCP import stacklessfile as file
    #open = file

    file = stacklessfile
    open = file
    sleep = mng.sleep
    
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
    newfile = stdfile('test-small.txt','w')
    for x in xrange(10000):
        newfile.write(str(x))
    newfile.close()

    newfile2 = stdfile('test-big.txt','w')
    for x in xrange(500000):
        newfile2.write(str(x))
    newfile2.close()

    # Launching tasklets to perform the file copy
    for i in xrange(1,11):
        stackless.tasklet(copyfile)(i, 'test-big.txt','big%s.txt' % i)

    for i in xrange(1,21):
        stackless.tasklet(copyfile)(i, 'test-small.txt','sm%s.txt' % i)

    def sl(s):
        st = time.time()
        print "Sleeping for %s seconds" % s
        sleep(s)
        print "returned %s seconds later (real: %s)" % (s, time.time()-st)
        
    #stackless.tasklet(sl)(3)

    st = time.time()
    stackless.run()
    print "Total time is %s seconds." % (time.time() - st)

    # Cleanup all test files used
    for f in glob.glob('test*.txt'):
        os.unlink(f)
    for f in glob.glob('sm*.txt'):
        os.unlink(f)
    for f in glob.glob('big*.txt'):
        os.unlink(f)
