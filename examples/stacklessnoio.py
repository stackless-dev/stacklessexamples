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

import gc, sys, types, os
import logging

logging.basicConfig()
log = logging.getLogger("noio")
log.setLevel(logging.DEBUG)

# TODO: The lock object is depended on, and cannot be directly patched.

TYPE_PATCH = 0
TYPE_PROXY = 1

blacklist = [                                           # when the call is okay
    [ "os.fork",                        TYPE_PATCH, ],
    [ "os.read",                        TYPE_PATCH, ],
    [ "os.system",                      TYPE_PATCH, ],
    [ "os.wait",                        TYPE_PATCH, ],
    [ "os.waitpid",                     TYPE_PATCH, ],
    [ "os.wait3",                       TYPE_PATCH, ],
    [ "os.wait4",                       TYPE_PATCH, ],
    [ "os.write",                       TYPE_PATCH, ],
    [ "os.system",                      TYPE_PATCH, ],

    [ "select.epoll",                   TYPE_PATCH, ],
    [ "select.poll",                    TYPE_PATCH, ],
    [ "select.select",                  TYPE_PATCH, ],  # timeout == 0
    
    [ "subprocess.call",                TYPE_PATCH, ],
    [ "subprocess.check_call",          TYPE_PATCH, ],
    [ "subprocess.Popen.wait",          TYPE_PATCH, ],

    [ "threading._Condition.acquire",   TYPE_PROXY, ],
    [ "threading._Condition.wait",      TYPE_PATCH, ],
    [ "threading.Event.wait",           TYPE_PATCH, ],
    [ "threading.Lock.acquire",         TYPE_PROXY, ],  # blocking=0
    [ "threading.RLock.acquire",        TYPE_PROXY, ],  # blocking=0
    [ "threading.Semaphore.acquire",    TYPE_PROXY, ],  # blocking=0
    [ "threading.Thread.join",          TYPE_PATCH, ],

    [ "time.sleep",                     TYPE_PATCH, ],  # delay == 0
]



def install():
    for blacklist_name, blacklist_type in blacklist:
        if blacklist_type == TYPE_PROXY:
            log.debug("Unable to patch proxy type '%s' at this time", blacklist_name)
            continue
    
        import_name, entry_name = blacklist_name.rsplit(".", 1)
        idx = import_name.find(".")
        if idx == -1:
            # module.function
            module_name = import_name
            from_list = []
        else:
            # module.class.function
            module_name = import_name[:idx]
            from_list = [ import_name[idx+1:] ]

        module = __import__(module_name, {}, {}, from_list)
        if len(from_list):
            # module.class
            target = getattr(module, from_list[0])
        else:
            # module
            target = module

        install_count = 0

        if type(target) is types.ModuleType:
            # Get the actual function we are blacklisting.  We do not clobber
            # it directly, as it will get clobbered indirectly.
            unguarded_entry = getattr(target, entry_name, None)
            if unguarded_entry is None:
                log.debug("Failed to locate '%s' on module '%s'", entry_name, module_name)
                continue

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
        elif type(target) in (types.TypeType, types.ClassType):
            if entry_name not in target.__dict__:
                log.debug("Failed to locate '%s' on class '%s.%s'", entry_name, module_name, from_list[0])
                continue

            unguarded_entry = target.__dict__[entry_name]
            setattr(target, entry_name, _make_guarded_call(blacklist_name, unguarded_entry))
        elif type(target) is types.FunctionType:
            pass
        else:
            print target, type(target), entry_name
            raise NotImplemented

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

    if os.name == "nt":
        import subprocess
        fh = open("NUL", "w")
        pio = subprocess.Popen("netstat.exe", stdout=fh)
        pio.wait()
    
    if False:
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

