#
# Factorial example using stackless to break Python's recustion limit of 1000
#
# by Andrew Dalke
#
# If you have any questions related to this example:
#
# - If they are related to how Twisted works, please contact the
#   Twisted mailing list:
#
#     http://twistedmatrix.com/cgi-bin/mailman/listinfo/twisted-python
#
# - If they are related to how Stackless works, please contact
#   the Stackless mailing list:
#
#     http://www.tismer.com/mailman/listinfo/stackless
#

import stackless
import time

def call_wrapper(f, args, kwargs, result_ch):
    result_ch.send(f(*args, **kwargs))

def call(f, *args, **kwargs):
    result_ch= stackless.channel()
    stackless.tasklet(call_wrapper)(f, args, kwargs, result_ch)
    return result_ch.receive()
def factorial(n):
    if n <= 1:
        return 1
    return n * call(factorial, n-1)

st = time.time()

factorial(1000)
print time.time() - st
