import threading
import stackless

# We need the "socket" name for the function we export.
import stdsocket

# If we are to masquerade as the socket module, we need to provide the constants.
for k, v in stdsocket.__dict__.iteritems():
    if k.upper() == k:
        globals()[k] = v
error = stdsocket.error
timeout = stdsocket.timeout

# WARNING: this function blocks and is not thread safe.
# The only solution is to spawn a thread to handle all
# getaddrinfo requests.  Implementing a stackless DNS
# lookup service is only second best as getaddrinfo may
# use other methods.
getaddrinfo = stdsocket.getaddrinfo

_config = stackless._config

def socket(*args):
    if getattr(_config, "using_stackless"):
        return stackless.socket(*args)
    else:
        return stdsocket.socket(*args)
