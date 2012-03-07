# If we are using making threads into tasklets and other fancy
# mucking with the natural order of things, then we need to ensure
# that blocking operations do not block the thread a tasklet is
# running on.  Otherwise, they block the scheduler that tasklet
# is running within.  To this end, we make blocking calls to select
# actually get delegated to another REAL thread.

from __future__ import absolute_import

import stackless
import stacklesslib.util

import select as real_select

error = real_select.error
__doc__ = real_select.__doc__

_main_thread_id = stackless.main.thread_id


def select(*args, **kwargs):
    # If it blocks until it gets a result, or for longer than a nominal
    # amount, then farm it off onto another thread.
    if stackless.current.thread_id == _main_thread_id:
        if len(args) == 3 or len(args) == 4 and (args[3] is None or args[3] > 0.05) or \
             "timeout" in kwargs and (kwargs["timeout"] is None or kwargs["timeout"] > 0.05):
            return stacklesslib.util.call_on_thread(real_select.select, args, kwargs)

    # Otherwise, do it inline and expect to return effectively immediately.
    return real_select.select(*args)

select.__doc__ = real_select.select.__doc__
