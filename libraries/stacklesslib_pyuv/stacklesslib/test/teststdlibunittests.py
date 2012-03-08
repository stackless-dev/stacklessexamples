"""
This unit test script should not implement any unit tests of its own.
Its goal is to wrap the running of standard library unit tests again the
monkey-patched environment that stacklesslib provides.

TODO:
- pump() blocks for at least a second.  why?  where?
"""

from __future__ import absolute_import

import sys
#sys.path.append(r"D:\VCS\SVN\stacklessexamples\libraries\stacklesslib_pyuv")
#sys.xstdout = sys.stdout

try:
    import pyuv
except:
    pyuv = None

asyncore = None
if not pyuv:
    import asyncore

# Ruin wonderful PEP-8 ordering with pre-emptive monkey-patch.
import stacklesslib.magic
stacklesslib.magic.patch_all(autonomous=False)


import traceback
import sys
import unittest

import stackless

import stacklesslib.main


elapsed_time = stacklesslib.main.elapsed_time


def run_unittests():
    from test import test_socket
    test_socket.GeneralModuleTests.test_sock_ioctl = unittest.skip("ioctl not supportable")(test_socket.GeneralModuleTests.test_sock_ioctl)
    test_socket.GeneralModuleTests.testListenBacklog0 = unittest.skip("libuv pending issue resolution")(test_socket.GeneralModuleTests.testListenBacklog0)
    test_socket.NonBlockingTCPTests.testAccept = unittest.skip("select.select not yet supported")(test_socket.NonBlockingTCPTests.testAccept)
    test_socket.TCPCloserTest.testClose = unittest.skip("select.select not yet supported")(test_socket.TCPCloserTest.testClose)
    test_socket.FileObjectClassTestCase.testFullRead = unittest.skip("write+memoryview not yet supported")(test_socket.FileObjectClassTestCase.testFullRead)
    test_socket.FileObjectClassTestCase.testReadline = unittest.skip("write+memoryview not yet supported")(test_socket.FileObjectClassTestCase.testReadline)
    test_socket.FileObjectClassTestCase.testReadlineAfterRead = unittest.skip("write+memoryview not yet supported")(test_socket.FileObjectClassTestCase.testReadlineAfterRead)
    test_socket.FileObjectClassTestCase.testReadlineAfterReadNoNewline = unittest.skip("write+memoryview not yet supported")(test_socket.FileObjectClassTestCase.testReadlineAfterReadNoNewline)
    test_socket.FileObjectClassTestCase.testSmallRead = unittest.skip("write+memoryview not yet supported")(test_socket.FileObjectClassTestCase.testSmallRead)
    test_socket.FileObjectClassTestCase.testUnbufferedRead = unittest.skip("write+memoryview not yet supported")(test_socket.FileObjectClassTestCase.testUnbufferedRead)
    test_socket.UnbufferedFileObjectClassTestCase.testUnbufferedReadline = unittest.skip("write+memoryview not yet supported")(test_socket.UnbufferedFileObjectClassTestCase.testUnbufferedReadline)
    test_socket.NonBlockingTCPTests.testRecv = unittest.skip("select.select not yet supported")(test_socket.NonBlockingTCPTests.testRecv)
    test_socket.BufferIOTest.testRecvFromIntoArray = unittest.skip("recvfrom_into not yet supported")(test_socket.BufferIOTest.testRecvFromIntoArray)
    test_socket.BufferIOTest.testRecvFromIntoBytearray = unittest.skip("recvfrom_into not yet supported")(test_socket.BufferIOTest.testRecvFromIntoBytearray)
    test_socket.BufferIOTest.testRecvFromIntoMemoryview = unittest.skip("recvfrom_into not yet supported")(test_socket.BufferIOTest.testRecvFromIntoMemoryview)
    test_socket.BufferIOTest.testRecvIntoArray = unittest.skip("recvfrom_into not yet supported")(test_socket.BufferIOTest.testRecvIntoArray)    
    test_socket.BufferIOTest.testRecvIntoBytearray = unittest.skip("recvfrom_into not yet supported")(test_socket.BufferIOTest.testRecvIntoBytearray)    
    test_socket.BufferIOTest.testRecvIntoMemoryview = unittest.skip("recvfrom_into not yet supported")(test_socket.BufferIOTest.testRecvIntoMemoryview)
    from test import test_urllib
    from test import test_urllib2
    from test import test_xmlrpc
    test_xmlrpc.SimpleServerTestCase.test_dotted_attribute = unittest.skip("select.select not yet supported")(test_xmlrpc.SimpleServerTestCase.test_dotted_attribute)
    test_xmlrpc.SimpleServerTestCase.test_introspection1 = unittest.skip("select.select not yet supported")(test_xmlrpc.SimpleServerTestCase.test_introspection1)
    test_xmlrpc.SimpleServerTestCase.test_introspection2 = unittest.skip("select.select not yet supported")(test_xmlrpc.SimpleServerTestCase.test_introspection2)
    test_xmlrpc.SimpleServerTestCase.test_introspection3 = unittest.skip("select.select not yet supported")(test_xmlrpc.SimpleServerTestCase.test_introspection3)
    test_xmlrpc.SimpleServerTestCase.test_introspection4 = unittest.skip("select.select not yet supported")(test_xmlrpc.SimpleServerTestCase.test_introspection4)
    test_xmlrpc.SimpleServerTestCase.test_multicall = unittest.skip("select.select not yet supported")(test_xmlrpc.SimpleServerTestCase.test_multicall)
    test_xmlrpc.SimpleServerTestCase.test_non_existing_multicall = unittest.skip("select.select not yet supported")(test_xmlrpc.SimpleServerTestCase.test_non_existing_multicall)
    test_xmlrpc.SimpleServerTestCase.test_nonascii = unittest.skip("select.select not yet supported")(test_xmlrpc.SimpleServerTestCase.test_nonascii)
    test_xmlrpc.SimpleServerTestCase.test_simple1 = unittest.skip("select.select not yet supported")(test_xmlrpc.SimpleServerTestCase.test_simple1)
    test_xmlrpc.KeepaliveServerTestCase1.test_two = unittest.skip("select.select not yet supported")(test_xmlrpc.KeepaliveServerTestCase1.test_two)
    test_xmlrpc.KeepaliveServerTestCase2.test_close = unittest.skip("select.select not yet supported")(test_xmlrpc.KeepaliveServerTestCase2.test_close)
    test_xmlrpc.KeepaliveServerTestCase2.test_transport = unittest.skip("select.select not yet supported")(test_xmlrpc.KeepaliveServerTestCase2.test_transport)
    test_xmlrpc.GzipServerTestCase.test_bad_gzip_request = unittest.skip("select.select not yet supported")(test_xmlrpc.GzipServerTestCase.test_bad_gzip_request)
    test_xmlrpc.GzipServerTestCase.test_gsip_response = unittest.skip("select.select not yet supported")(test_xmlrpc.GzipServerTestCase.test_gsip_response)
    test_xmlrpc.GzipServerTestCase.test_gzip_request = unittest.skip("select.select not yet supported")(test_xmlrpc.GzipServerTestCase.test_gzip_request)
    test_xmlrpc.MultiPathServerTestCase.test_path1 = unittest.skip("select.select not yet supported")(test_xmlrpc.MultiPathServerTestCase.test_path1)
    test_xmlrpc.MultiPathServerTestCase.test_path2 = unittest.skip("select.select not yet supported")(test_xmlrpc.MultiPathServerTestCase.test_path2)
    test_xmlrpc.FailingServerTestCase.test_basic = unittest.skip("select.select not yet supported")(test_xmlrpc.FailingServerTestCase.test_basic)
    test_xmlrpc.FailingServerTestCase.test_fail_no_info = unittest.skip("select.select not yet supported")(test_xmlrpc.FailingServerTestCase.test_fail_no_info)
    test_xmlrpc.FailingServerTestCase.test_fail_with_info = unittest.skip("select.select not yet supported")(test_xmlrpc.FailingServerTestCase.test_fail_with_info)

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
            if asyncore is not None:
                asyncore.poll(0.05)
        except Exception, e:
            if isinstance(e, ReferenceError):
                print "run:EXCEPTION", str(e), asyncore.socket_map if asyncore is not None else None
            else:
                print "run:EXCEPTION", asyncore.socket_map if asyncore is not None else None
                traceback.print_exc()
            sys.exc_clear()

        if False and elapsed_time() - tick_time > 0.1:
            print "Pump took too long: %0.5f" % (elapsed_time() - tick_time)
