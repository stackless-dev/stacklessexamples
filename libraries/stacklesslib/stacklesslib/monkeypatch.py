#monkeypatch.py
#

import sys
import threading as real_threading
from . import main
from . import util
from .replacements import thread, threading, popen

# Use stacklessio if available
try:
    import stacklessio
except ImportError:
    stacklessio = False



def patch_all():

    patch_misc()

    patch_thread()
    patch_threading()

    patch_select()
    patch_socket()
    patch_ssl()


def patch_misc():
    # Fudge time.sleep.
    import time
    time.sleep = main.sleep

    # Fudge popen4 (if it exists).
    import os
    if hasattr(os, "popen4"):
        os.popen4 = popen.popen4

def patch_thread():
    sys.modules["thread"] = thread

def patch_threading():
    threading.real_threading = real_threading
    sys.modules["threading"] = threading

def patch_select():
    """ Selectively choose to monkey-patch the 'select' module. """
    if stacklessio:
        from stacklessio import select
    else:
        from stacklesslib.replacements import select
    sys.modules["select"] = select

def patch_socket(will_be_pumped=True):
    """
    Selectively choose to monkey-patch the 'socket' module.

    If 'will_be_pumped' is set to False, the patched socket module will take
    care of polling networking events in a scheduled tasklet.  Otherwise, the
    controlling application is responsible for pumping these events.
    """

    if stacklessio:
        from stacklessio import _socket
        sys.modules["_socket"] = _socket
    else:
        # Fallback on the generic 'stacklesssocket' module.
        from stacklesslib.replacements import socket
        socket._sleep_func = main.sleep
        socket._schedule_func = lambda: main.sleep(0)
        if will_be_pumped:
            #We will pump it somehow.  Tell the mainloop to pump it too.
            socket.stacklesssocket_manager(lambda: None)
            main.mainloop.add_pump(socket.pump)
        socket.install()

def patch_ssl():
    """
    Patch using a modified _ssl module which allows wrapping any
    Python object, not just sockets.
    """
    try:
        import _ssl
        import socket
        import errno
        from cStringIO import StringIO
    except ImportError:
        return

    class SocketBio(object):
        """This PyBio for the builtin SSL module implements receive buffering
           for performance"""

        default_bufsize = 8192 #read buffer size
        def __init__(self, sock, rbufsize=-1):
            self.sock = sock
            self.bufsize = self.default_bufsize if rbufsize < 0 else rbufsize
            if self.bufsize:
                self.buf = StringIO()

        def write(self, data):
            return self.wrap_errors("write", self.sock.send, (data,))

        def read(self, want):
            if self.bufsize:
                data = self.buf.read(want)
                if not data:
                    buf = self.wrap_errors("read", self.sock.recv, (self.bufsize,))
                    self.buf = StringIO(buf)
                    data = self.buf.read(want)
            else:
                data = self.wrap_errors("read", self.sock.recv, (want,))
            return data

        def wrap_errors(self, name, call, args):
            try:
                return call(*args)
            except socket.timeout:
                if self.sock.gettimeout() == 0.0:
                    return None if name=="read" else 0 #signal EWOULDBLOCK
                #create the exact same error as the _ssl module would
                raise _ssl.SSLError, "The %s operation timed out" % (name,)
            except socket.error, e:
                #signal EWOULDBLOCK
                if e.errno == errno.EWOULDBLOCK:
                    return None if name=="read" else 0
                raise

        #pass on stuff to the internal sock object, so that
        #unwrapping works
        def __getattr__(self, attr):
            return getattr(self.sock, attr)

    realwrap = _ssl.sslwrap
    def wrapbio(sock, *args, **kwds):
        bio = SocketBio(sock)
        return util.call_on_thread(realwrap, (bio,)+args, kwds)
    _ssl.sslwrap = wrapbio