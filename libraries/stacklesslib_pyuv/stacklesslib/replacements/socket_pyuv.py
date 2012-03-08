"""
Stackless compatible socket module (pyuv based).

Author: Richard Tew <richard.m.tew@gmail.com>
See the COPYING file for the open source license.

Feel free to email me with any questions, comments, or suggestions for
improvement.

Todo list:
- TODO: When libuv supports run_once direct timeout, remove timer..
- TODO: When libuv supports ipv6, remove getaddrinfo hack..
- TODO: setsockopt/getsockopt SO_REUSEADDRESS is a test passing sham..
- TODO: Exceptions raised out of pyuv are custom ones that present custom
        libuv error codes.  We have a mapping of some of these to Windows
        error codes below, but the exceptions need to be caught and
        translated to the standard Python socket ones.
"""

import errno
import random
import socket as stdsocket # We need the "socket" name for the function we export.
import sys
import weakref

# Locally import and adjust error numbers.
from errno import EALREADY, EINPROGRESS, EWOULDBLOCK, ECONNRESET, \
     ENOTCONN, ESHUTDOWN, EINTR, EISCONN, EBADF, ECONNABORTED, \
     ECONNREFUSED, EWOULDBLOCK, EINVAL
if sys.platform == "win32":
    EINVAL = errno.WSAEINVAL

import pyuv
import stackless

__all__ = stdsocket.__all__
def _adopt_stdsocket_constants():
    for k, v in stdsocket.__dict__.iteritems():
        if k in __all__ and k.upper() == k:
            globals()[k] = v
        elif k == "EBADF":
            globals()[k] = v
    globals()["error"] = stdsocket.error
    globals()["timeout"] = stdsocket.timeout
_adopt_stdsocket_constants()

_TCP_KEEPALIVE = 3
def _getsockopt_default(level, optname):
    s = stdsocket.socket()
    return s.getsockopt(level, optname)
DEFAULT_NODELAY_FLAG = _getsockopt_default(stdsocket.IPPROTO_TCP, stdsocket.TCP_NODELAY)
DEFAULT_KEEPALIVE_FLAG = _getsockopt_default(stdsocket.SOL_SOCKET, stdsocket.SO_KEEPALIVE)
DEFAULT_KEEPALIVE_DELAY = _getsockopt_default(stdsocket.IPPROTO_TCP, _TCP_KEEPALIVE)
DEFAULT_REUSE_FLAG = _getsockopt_default(stdsocket.SOL_SOCKET, stdsocket.SO_REUSEADDR)

_fileobject = stdsocket._fileobject

# uv -> windows compatibility: Map UV errnos to Windows errnos.
# TODO: Evaluate whethe this is actually useful (do not believe is currently used).
def _convert_uv_errnos():
    d = {}
    for k, v in pyuv.errno.__dict__.iteritems():
        if k.startswith("UV_E"):
            rk = k[3:]
            try:
                d[v] = getattr(errno, rk)
            except AttributeError:
                # Unix, or special cases.  Ignore for now.
                pass
    return d
_errno_map = _convert_uv_errnos()
_EWOULDBLOCK_text = "The socket operation could not complete without blocking"


def socket(*args, **kwargs):
    import sys
    if "socket" in sys.modules and sys.modules["socket"] is not stdsocket:
        raise RuntimeError("Use 'socket_pyuv.install' instead of replacing the 'socket' module")
    raise RuntimeError("'socket_pyuv.socket' erroneously called")

# Store the original socket module objects, so we can unclobber what we
# monkey-patched if we need to.
_realsocket_old = stdsocket._realsocket
_getaddrinfo_old = stdsocket.getaddrinfo
#_socketobject_old = stdsocket._socketobject

# libuv workaround: no ipv6 support.  ignore ipv6 addresses until there is.
def _getaddrinfo(*args):
    for ret in _getaddrinfo_old(*args):
        if len(ret[-1]) == 2:
            yield ret

def install(poll_interval=None):
    """ Call this to add this module's monkey-patching to the standard library. """
    global _poll_interval
    if stdsocket._realsocket is socket:
        raise StandardError("Still installed")
    stdsocket._realsocket = _fakesocket
    stdsocket.getaddrinfo = _getaddrinfo
    if poll_interval is not None:
        _poll_interval = poll_interval

def uninstall():
    """ Call this to remove this module's monkey-patching of the standard library. """
    stdsocket._realsocket = _realsocket_old
    stdsocket.getaddrinfo = _getaddrinfo_old


_poll_interval = 0.05
_pumping = False
_pyuv_loop = pyuv.Loop.default_loop()
_socket_map = weakref.WeakValueDictionary()

def pump_pyuv():
    global _pumping
    global _pyuv_loop
    global _schedule_func
    global _socket_map
    _pumping = True
    # Force the libuv run mechanic to exit with a timeout.
    def pointless_callback(redundant_timer_handle):
        pass
    timer = pyuv.Timer(_pyuv_loop)
    timer.start(pointless_callback, 0.0, _poll_interval)
    # Loop until no more sockets exist.
    try:
        while len(_socket_map):
            # Ensure the timeout is from the start of our run call.
            timer.again()
            #print >>sys.xstdout, "_pyuv_loop.run_once.call"
            _pyuv_loop.run_once()
            #print >>sys.xstdout, "_pyuv_loop.run_once.called"
            _schedule_func()
    finally:
        _pumping = False
        timer.stop()

def start_pumping():
    global _pumping
    if not _pumping:
        _pumping = True
        return stackless.tasklet(pump_pyuv)()

_schedule_func = stackless.schedule
_sleep_func = None
_timeout_func = None

def can_timeout():
    return _sleep_func is not None or _timeout_func is not None


_next_fileno = 10101000

class _fakesocket(object):
    # Optionally overriden variables.
    _blocking = True
    _connected = False
    _listening = False
    _opt_keepalive = DEFAULT_KEEPALIVE_FLAG
    _opt_keepalive_delay = DEFAULT_KEEPALIVE_DELAY
    _opt_nodelay = DEFAULT_NODELAY_FLAG
    _opt_reuseaddr = DEFAULT_REUSE_FLAG
    _rchannel = None
    _timeout = None
    _was_connected = False
    _wchannel = None
    # Official socket object functions.
    def __init__(self, family=AF_INET, type=SOCK_STREAM, proto=0):
        global _next_fileno
        global _pyuv_loop
        global _socket_map
        # Make underlying pyuv "socket" object.
        if type == SOCK_STREAM:
            self._socket = self._tcp_socket = pyuv.TCP(_pyuv_loop)
        elif type == SOCK_DGRAM:
            self._socket = self._udp_socket = pyuv.UDP(_pyuv_loop)
        else:
            raise RuntimeError("Unsupported socket family: %s" % type)
        # Property variables.
        self._family = family
        self._type = type
        self._proto = proto
        # Internal support.
        self._fileno = _next_fileno
        _next_fileno += 1
        if can_timeout():
            self._timeout = stdsocket.getdefaulttimeout()
        _socket_map[id(self)] = self
        start_pumping()
    def accept(self): # TCP
        def accept_result(_new_tcp_socket):
            _new_tcp_socket._was_connected = True
            # Emulate the standard 'socket.accept' return value.
            return _new_tcp_socket, _new_tcp_socket.getpeername()
        channel = self._get_rchannel()
        # First actually try and do an accept.
        _new_tcp_socket = _fakesocket()
        try:
            self._tcp_socket.accept(_new_tcp_socket._tcp_socket)
            return accept_result(_new_tcp_socket)
        except pyuv.error.TCPError:
            # If listen has not been called yet.
            if not self._listening:
                raise stdsocket.error(EINVAL)
            # If the socket is set to non-blocking.
            if not self._blocking or self._timeout == 0.0:
                raise stdsocket.error(EWOULDBLOCK, _EWOULDBLOCK_text)
            # Otherwise, assume all is well and block on a channel.
            sys.exc_clear()
        # Block until there is an incoming connection.
        self._receive_with_timeout(channel)
        self._tcp_socket.accept(_new_tcp_socket._tcp_socket)
        return accept_result(_new_tcp_socket)
    def bind(self, address): # TCP / UDP
        # TODO: Should do some generic lookup?
        address = self._resolve_address(address)
        # pyuv workaround: standard library socket function raises Overflow, not ValueError.
        try:
            self._socket.bind(address)
        except ValueError, e:
            if e.message == "port must be between 0 and 65536":
                raise OverflowError("getsockaddrarg: port must be 0-65535.")
            raise e
    def close(self): # TCP / UDP
        """
        Blocks until the close has completed.. correct behaviour?
        """
        channel = stackless.channel()
        channel.preference = 1
        def close_callback(_socket_handle):
            channel.send(None)
        self._socket.close(close_callback)
        channel.receive()
    def connect(self, address): # TCP
        address = self._resolve_address(address)
        err = self.connect_ex(address)
        if err:
            raise stdsocket.error(err, "")
    def connect_ex(self, address):
        channel = self._get_wchannel()
        def connect_callback(_tcp_handle, err):
            if channel.balance < 0:
                if err is not None:
                    err = _errno_map[err]
                    channel.send(err)
                else:
                    channel.send(err)
        self._tcp_socket.connect(address, connect_callback)
        err = self._receive_with_timeout(channel)
        if err is None:
            err = 0
            self._connected = True
            self._was_connected = True
        return err
    def fileno(self):
        return self._fileno
    def getpeername(self): # TCP
        return self._tcp_socket.getpeername()
    def getsockname(self): # TCP
        return self._socket.getsockname()
    def ioctl(self, control, option): # ?? HOW?
        raise NotImplementedError("socket.ioctl")
    def listen(self, backlog): # TCP
        if backlog < 1:
            raise RuntimeError("Not supported by libuv at this time")
        channel = self._get_rchannel()
        def listen_callback(_listen_tcp_socket, err):
            while channel.balance < 0:
                if err is None:
                    channel.send(None)
                else:
                    # TODO: Really should be able to pass multiple arguments to the exception type..
                    channel.send_exception(stdsocket.error, _errno_map[err])
        self._tcp_socket.listen(listen_callback, backlog)
        self._listening = True
    def makefile(self, mode, bufsize): # ?? HOW?
        raise NotImplementedError("socket.makefile")
    def recv(self, bufsize, flags=0): # TCP?
        """
        TODO: Deal with the 'bufsize' constraint.  Currently data returned
              can be larger than this size.
        """
        if self.type != SOCK_DGRAM and not self._connected:
            # Sockets which have never been connected do this.
            if not self._was_connected:
                raise stdsocket.error(ENOTCONN, 'Socket is not connected')

        channel = self._get_rchannel()
        if (not self._blocking or self._timeout == 0.0) and channel.balance < 1:
            raise stdsocket.error(EWOULDBLOCK, _EWOULDBLOCK_text)

        if self.type == SOCK_STREAM:
            def tcp_callback(redundant_handle, data, err):
                self._tcp_socket.stop_read()
                if channel.balance < 0:
                    if err == pyuv.errno.UV_EOF:
                        err = None
                        data = ""
                    if err is None:
                        channel.send(data)
                    else:
                        channel.send_exception(stdsocket.error, _errno_map[err])
            self._tcp_socket.start_read(tcp_callback)
        else:
            def udp_callback(redundant_handle, address, data, err):
                self._udp_socket.stop_recv()
                if channel.balance < 0:
                    if err is None:
                        channel.send(data)
                    else:
                        channel.send_exception(stdsocket.error, _errno_map[err])
            self._udp_socket.start_recv(udp_callback)
        return self._receive_with_timeout(channel)
    def recvfrom(self, bufsize, flags=0): # UDP?
        """
        TODO: Deal with the 'bufsize' constraint.  Currently data returned
              can be larger than this size.
        """
        if self.type == SOCK_DGRAM:
            if bufsize < 0:
                raise ValueError("negative buffersize in recvfrom")
            channel = self._get_rchannel()
            if (not self._blocking or self._timeout == 0.0) and channel.balance < 1:
                raise stdsocket.error(EWOULDBLOCK, _EWOULDBLOCK_text)

            def udp_callback(redundant_handle, address, data, err):
                self._udp_socket.stop_recv()
                while channel.balance < 0:
                    if err == pyuv.errno.UV_EOF:
                        err = None
                        data = ""
                    if err is None:
                        channel.send((data, address))
                    else:
                        channel.send_exception(stdsocket.error, _errno_map[err])
            self._udp_socket.start_recv(udp_callback)
            return self._receive_with_timeout(channel)
        else:
            return self.recv(bufsize, flags), self.getpeername()
    def recvfrom_into(self, buffer, nbytes=0, flags=0):
        raise NotImplementedError("socket.recvfrom_into")
    def recv_into(self, buffer, nbytes=0, flags=0):
        raise NotImplementedError("socket.recv_into")
    def send(self, string, flags=0): # TCP / UDP
        channel = self._get_wchannel()
        if (not self._blocking or self._timeout == 0.0) and channel.balance < 1:
            raise stdsocket.error(EWOULDBLOCK, _EWOULDBLOCK_text)
        def send_callback(redundant_tcp_handle, err):
            while channel.balance < 0:
                if err is None:
                    channel.send(None)
                else:
                    # TODO: Really should be able to pass multiple arguments to the exception type..
                    channel.send_exception(stdsocket.error, _errno_map[err])
        self._socket.write(string, send_callback)
        self._receive_with_timeout(channel)
        return len(string)
    def sendall(self, string, flags=0):
        return self.send(string, flags)
    def sendto(self, string, *args):
        if type(string) is unicode:
            # TODO: Either..
            # a) Actually do the conversion.
            # b) Move conversion down into pyuv.
            raise UnicodeEncodeError("ascii", string, 0, 1, "ouch")
        elif type(string) is complex:
            raise TypeError("must be string or buffer, not complex")

        # Handle weird Python stdlib argument ordering.
        if len(args) == 2:
            flags, address = args
        elif len(args) == 1:
            flags = 0
            address = args[0]            
        else:
            raise TypeError("sendto() takes 2 or 3 arguments (%d given)" % (1 + len(args)))

        if type(flags) is not int:
            raise TypeError("an integer is required")
        if address is None:
            raise TypeError("getsockaddrarg: AF_INET address must be tuple, not NoneType")

        address = self._resolve_address(address)

        channel = self._get_wchannel()
        if (not self._blocking or self._timeout == 0.0) and channel.balance < 1:
            raise stdsocket.error(EWOULDBLOCK, _EWOULDBLOCK_text)

        def send_callback(redundant_tcp_handle, err):
            if channel.balance < 0:
                if err is None:
                    channel.send(None)
                else:
                    # TODO: Really should be able to pass multiple arguments to the exception type..
                    channel.send_exception(stdsocket.error, _errno_map[err])        
        self._udp_socket.send(address, string, send_callback)
        self._receive_with_timeout(channel)
        return len(string)
    def setblocking(self, flag):
        self._blocking = flag
    def settimeout(self, value):
        if value and not can_timeout():
            raise RuntimeError("This is a stackless socket - to have timeout support you need to provide a sleep function")
        self._timeout = value
    def gettimeout(self):
        if self._timeout is None:
            return stdsocket.getdefaulttimeout()
        return self._timeout
    def getsockopt(self, level, optname, buflen=None):
        if level == stdsocket.IPPROTO_TCP:
            if optname == stdsocket.TCP_NODELAY:
                return self._opt_nodelay
            elif optname == _TCP_KEEPALIVE:
                return self._opt_keepalive_delay
        if level == SOL_SOCKET:
            if optname == SO_KEEPALIVE:
                return self._opt_keepalive
            elif optname == SO_REUSEADDR:
                return self._opt_reuseaddr
    def setsockopt(self, level, optname, value):
        if level == stdsocket.IPPROTO_TCP:
            if optname == stdsocket.TCP_NODELAY:
                self._opt_nodelay = bool(value)
                self._tcp_socket.nodelay(self._opt_nodelay)
            elif optname == _TCP_KEEPALIVE:
                self._opt_keepalive_delay = value
                self._tcp_socket.keep_alive(self._opt_keepalive, self._opt_keepalive_delay)
        if level == stdsocket.SOL_SOCKET:
            if optname == stdsocket.SO_KEEPALIVE:
                self._opt_keepalive = bool(value)
                self._tcp_socket.keep_alive(self._opt_keepalive, self._opt_keepalive_delay)
            elif optname == SO_REUSEADDR:
                self._opt_reuseaddr = bool(value)
    def shutdown(self, how): # TCP
        if how == stdsocket.SHUT_WR:
            channel = stackless.channel()
            channel.preference = 1
            def shutdown_callback(tcp_handle):
                channel.send(None)
            self._tcp_socket.shutdown(shutdown_callback)
            channel.receive()
    # Official socket object read-only properties.
    @property
    def family(self):
        return self._family
    @property
    def type(self):
        return self._type
    @property
    def proto(self):
        return self._proto
    # Custom internal logic.
    def _receive_with_timeout(self, channel):
        if self._timeout is not None:
            # Start a timing out process.
            # a) Engage a pre-existing external tasklet to send an exception on our channel if it has a receiver, if we are still there when it times out.
            # b) Launch a tasklet that does a sleep, and sends an exception if we are still waiting, when it is awoken.
            # Block waiting for a send.
            if _timeout_func is not None:
                # You will want to use this if you are using sockets in a different thread from your sleep functionality.
                _timeout_func(self._timeout, channel, (timeout, "timed out"))
            elif _sleep_func is not None:
                stackless.tasklet(self._manage_receive_with_timeout)(channel)
            else:
                raise NotImplementedError("should not be here")
            try:
                ret = channel.receive()
            except BaseException, e:
                raise e
            return ret
        else:
            return channel.receive()
    def _manage_receive_with_timeout(self, channel):
        if channel.balance < 0:
            _sleep_func(self._timeout)
            if channel.balance < 0:
                channel.send_exception(timeout, "timed out")
    @classmethod
    def _resolve_address(klass, address):
        if address[0] == "":
            address = ("0.0.0.0", address[1])
        elif address[0] == "localhost":
            address = ("127.0.0.1", address[1])
        return address
    def _get_rchannel(self):
        if self._rchannel is None:
            self._rchannel = stackless.channel()
            self._rchannel.preference = 1
        return self._rchannel
    def _get_wchannel(self):
        if self._wchannel is None:
            self._wchannel = stackless.channel()
            self._wchannel.preference = 1
        return self._wchannel

def test():
    #sock = _fakesocket()
    #reuse = sock.getsockopt(SOL_SOCKET, SO_REUSEADDR)
    #print reuse
    s = _fakesocket()

if __name__ == "__main__":
    test()
