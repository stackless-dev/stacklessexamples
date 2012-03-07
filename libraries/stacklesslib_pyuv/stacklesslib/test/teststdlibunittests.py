"""
This unit test script should not implement any unit tests of its own.
Its goal is to wrap the running of standard library unit tests again the
monkey-patched environment that stacklesslib provides.

TODO:
- pump() blocks for at least a second.  why?  where?
"""

from __future__ import absolute_import

# Ruin wonderful PEP-8 ordering with pre-emptive monkey-patch.
import stacklesslib.magic
stacklesslib.magic.monkeypatch()


import asyncore
import traceback
import sys

import stackless

import stacklesslib.main


elapsed_time = stacklesslib.main.elapsed_time


def run_unittests():
    from test import test_socket
    from test import test_urllib
    from test import test_urllib2
    from test import test_xmlrpc

    print "** run_unittests.test_socket"
    test_socket.test_main()
    print "** run_unittests.test_urllib"
    test_urllib.test_main()
    print "** run_unittests.test_urllib2"
    test_urllib2.test_main()
    print "** run_unittests.test_xmlrpc"
    test_xmlrpc.test_main()
    print "** run_unittests - done"


def new_tasklet(f, *args, **kwargs):
    try:
        f(*args, **kwargs)
    except Exception:
        traceback.print_exc()


if __name__ == "__main__":
    run_unittests_tasklet = stackless.tasklet(new_tasklet)(run_unittests)

    while run_unittests_tasklet.alive:
        tick_time = elapsed_time()

        wait_time = stacklesslib.main.mainloop.get_wait_time(tick_time)

        try:
            stacklesslib.main.mainloop.pump()
            asyncore.poll(0.05)
        except Exception, e:
            import asyncore
            if isinstance(e, ReferenceError):
                print "run:EXCEPTION", str(e), asyncore.socket_map
            else:
                print "run:EXCEPTION", asyncore.socket_map
                traceback.print_exc()
            sys.exc_clear()

        if False and elapsed_time() - tick_time > 0.1:
            print "Pump took too long: %0.5f" % (elapsed_time() - tick_time)
