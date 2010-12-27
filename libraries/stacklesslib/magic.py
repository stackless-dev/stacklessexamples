#slmagic.py
#See the LICENSE file for copyright information.
#this module switches a threaded program to a tasklet based one
import sys
import os
import time
import imp

import stackless
from stacklesslib import main
try:
    import stacklessio
except:
    stacklessio = False

from  stacklesslib.replacements import thread, threading, popen

def monkeypatch():
    #inject stacklessio
    if stacklessio:
        sys.modules["_socket"] = stacklessio._socket
    
    #inject slthreading as threading
    sys.modules["threading"] = threading
    sys.modules["thread"] = thread
    
    #fudge time.sleep
    time.sleep = main.sleep
    
    #fudge popen4
    os.popen4 = popen.popen4
        

if __name__ == "__main__":
    #shift command line arguments
    me = sys.argv.pop(0)

    #remove our directory from the path, in case we were invoked as a script
    p = os.path.dirname(me)
    if not p:
        p = "."
    try:
        sys.path.remove(os.path.abspath(p))
    except ValueError:
        pass #ok, we were probably run as a -m flag

    #rename ourselves, so we don't get clobbered
    __name__ = "__slmain__"
    sys.modules["__slmain__"] = sys.modules["__main__"]
    del sys.modules["__main__"]

    #run next argument as main:
    if sys.argv:
        p = os.path.dirname(sys.argv[0])
        if not p:
            p = "."
        sys.path.insert(0, os.path.abspath(p))

    #The actual __main__ will be run here in a tasklet
    def Main():
        try:
            if sys.argv:
                imp.load_source("__main__", os.path.abspath(sys.argv[0]))
        except Exception, e:
            main.mainloop.exception = sys.exc_info()
            raise
        finally:
            main.mainloop.running = False

    monkeypatch()
    main.set_scheduling_mode(main.SCHEDULING_ROUNDROBIN)
    stackless.tasklet(Main)()
    main.mainloop.run()