#
# Stackless no-IO module.
#
# Author: Richard Tew <richard.m.tew@gmail.com>
#
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#
#
# The goal of this module is to isolate all function calls that would
# block the entire thread, and prevent them from being called.  These
# calls would have to be explicitly allowed.  In this way, a Stackless
# programmer would know what resources they rely on, that they would
# need to make available in a different way.
#

import gc, sys
import logging

logging.basicConfig()
log = logging.getLogger("noio")
log.setLevel(logging.DEBUG)


blacklist = [
    "time.sleep",
    "select.select",
]


def install():
    for blacklist_name in blacklist:
        module_name, entry_name = blacklist_name.rsplit(".", 1)
        module = __import__(module_name)

        # Get the actual function we are blacklisting.  We do not clobber
        # it directly, as it will get clobbered indirectly.
        unguarded_entry = getattr(module, entry_name)

        install_count = 0
        for referrer in gc.get_referrers(unguarded_entry):
            # At this time, dictionaries are our only known locations.
            if type(referrer) is not dict:
                continue

            # Find the key the entry is stored under, and replace the entry.
            for k, v in referrer.iteritems():
                if v is unguarded_entry:
                    referrer[k] = _make_guarded_call(blacklist_name, unguarded_entry)
                    install_count += 1
                    break

        log.info("Installed call guard for '%s' (%d references)", blacklist_name, install_count)

def uninstall():
    pass


class NoioException(Exception):
    pass

def _check_unguarded():
    f = sys._getframe()
    # Walk up the call stack looking for 'unguarded'.
    while f is not None:
        if f.f_code is unguarded.func_code:
            return True
        f = f.f_back
    # Not found.  Indicate the call should not take place.
    return False

def _make_guarded_call(k, f):
    def guarded_call(*args, **kwargs):
        if not _check_unguarded():
            raise NoioException("Blocking call to %s" % k)
        return f(*args, **kwargs)
    return guarded_call

def unguarded(f, *args, **kwargs):
    return f(*args, **kwargs)


import time

if __name__ == "__main__":
    install()
    
    def test():
        time.sleep(5.0)

    # Make an access when it is guarded.
    try:
        test()
        raise Exception("Did not raise NoioException")
    except NoioException:
        pass

    # Make an unguarded access.
    unguarded(test)

