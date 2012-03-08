#monkeypatch.py
#

import sys
import threading as real_threading
from . import main
from .replacements import thread, threading, popen

# Use stacklessio if available
try:
    import stacklessio
except ImportError:
    stacklessio = False
try:
    import pyuv
except ImportError:
    pyuv = None



def patch_all(autonomous=True):
    patch_misc()
    
    patch_thread()
    patch_threading()
    
    #patch_select()
    patch_socket()
    
    if autonomous:
        main.mainloop.start()
    

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

def patch_socket(autononous=True):
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
        if pyuv:
            from stacklesslib.replacements import socket_pyuv as socket
        else:
            from stacklesslib.replacements import socket_asyncore as socket

        socket._sleep_func = main.sleep
        socket._schedule_func = lambda: main.sleep(0)
        # If the user plans to pump themselves, disable auto-pumping.
        if not pyuv and not autononous:
            socket._manage_sockets_func = lambda: None
        socket.install()
       
