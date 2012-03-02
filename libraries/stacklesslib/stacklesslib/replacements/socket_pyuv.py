"""
Stackless compatible socket module (pyuv based).

Author: Richard Tew <richard.m.tew@gmail.com>
This is licensed under the MIT open source license.

Feel free to email me with any questions, comments, or suggestions for
improvement.

Implementation notes:
- libuv is rather arcane in some of its design decisions and this forces the
  code in this module to be even more arcane, in order for it to work:
  - loop.run_once does some strange arbitrary calculations to determine
    whether it should block forever waiting for events.  There is no way for
    the caller to pass in a max timeout.
- 'errno' error codes.  There are special Winsock variants which are expected
  on Windows.  In the case of EWOULDBLOCK, this is okay as this value is the
  correct value (the Winsock value) on Windows.  But in the case of EINVAL,
  the value is not that of WSAEINVAL.  So we need special casing..
- os.strerror().  This does not return useful messages on my computer.
  So messages are hard-coded for now.

Todo list:
- TODO: Exceptions raised out of pyuv are custom ones that present custom
        libuv error codes.  We have a mapping of some of these to Windows
        error codes below, but the exceptions need to be caught and
        translated to the standard Python socket ones.
"""

import errno
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
def adopt_stdsocket_constants():
    for k, v in stdsocket.__dict__.iteritems():
        if k in __all__:
            globals()[k] = v
        elif k == "EBADF":
            globals()[k] = v
adopt_stdsocket_constants()

_TCP_KEEPALIVE = 3
def getsockopt_default(level, optname):
    s = stdsocket.socket()
    return s.getsockopt(level, optname)
DEFAULT_KEEPALIVE_FLAG = getsockopt_default(stdsocket.SOL_SOCKET, stdsocket.SO_KEEPALIVE)
DEFAULT_NODELAY_FLAG = getsockopt_default(stdsocket.IPPROTO_TCP, stdsocket.TCP_NODELAY)
DEFAULT_KEEPALIVE_DELAY = getsockopt_default(stdsocket.IPPROTO_TCP, _TCP_KEEPALIVE)

# uv -> windows compatibility: Map UV errnos to Windows errnos.
def convert_uv_errnos():
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
_errno_map = convert_uv_errnos()
_EWOULDBLOCK_text = "The socket operation could not complete without blocking"

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
            _pyuv_loop.run_once()
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


class socket(object):
    # Optionally overriden variables.
    _accept_channel = None
    _blocking = True
    _connected = False
    _listening = False
    _opt_keepalive = DEFAULT_KEEPALIVE_FLAG
    _opt_keepalive_delay = DEFAULT_KEEPALIVE_DELAY
    _opt_nodelay = DEFAULT_NODELAY_FLAG
    _timeout = None
    _was_connected = False
    # Official socket object functions.
    def __init__(self, family=AF_INET, type=SOCK_STREAM, proto=0):
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
        _socket_map[id(self)] = self
        start_pumping()
    def accept(self): # TCP # COMPLETE
        """
        """
        def accept_result(_new_tcp_socket):
            _new_tcp_socket._was_connected = True
            # Emulate the standard 'socket.accept' return value.
            return _new_tcp_socket, _new_tcp_socket.getpeername()
        self._accept_channel = stackless.channel()
        self._accept_channel.preference = 1
        try:
            # First actually try and do an accept.
            _new_tcp_socket = socket()
            try:
                self._tcp_socket.accept(_new_tcp_socket._tcp_socket)
                return accept_result(_new_tcp_socket)
            except pyuv.error.TCPError:
                # If listen has not been called yet.
                if not self._listening:
                    raise stdsocket.error(EINVAL)
                # If the socket is set to non-blocking.
                if not self._blocking:
                    raise stdsocket.error(EWOULDBLOCK, _EWOULDBLOCK_text)
                # Otherwise, assume all is well and block on a channel.
                sys.exc_clear()
            # Block until there is an incoming connection.
            self._accept_channel.receive()
            self._tcp_socket.accept(_new_tcp_socket._tcp_socket)
            return accept_result(_new_tcp_socket)
        finally:
            self._accept_channel = None
    def bind(self, address): # TCP / UDP # COMPLETE
        self._socket.bind(address)
    def close(self): # TCP / UDP # COMPLETE
        """
        Blocks until the close has completed.. correct behaviour?
        """
        channel = stackless.channel()
        channel.preference = 1
        def close_callback(_socket_handle):
            channel.send(None)
        self._socket.close(close_callback)
        channel.receive()
    def connect(self, address): # TCP # COMPLETE
        err = self.connect_ex(address)
        if err:
            raise stdsocket.error(err)
    def connect_ex(self, address): # COMPLETE
        channel = stackless.channel()
        channel.preference = 1
        def connect_callback(_tcp_handle, err):
            channel.send(err)
        self._tcp_socket.connect(address, connect_callback)
        err = channel.receive()
        if err is None:
            err = 0
            self._connected = True
            self._was_connected = True
        return err
    def fileno(self):
        pass
    def getpeername(self): # TCP # COMPLETE
        return self._tcp_socket.getpeername()
    def getsockname(self): # TCP # COMPLETE
        return self._tcp_socket.getsockname()
    def ioctl(self, control, option):
        pass
    def listen(self, backlog): # TCP
        def listen_callback(_listen_tcp_socket, err):
            if self._accept_channel:
                if err is None:
                    self._accept_channel.send(None)
                else:
                    # TODO: Really should be able to pass multiple arguments to the exception type..
                    self._accept_channel.send_exception(stdsocket.error, errno_map[err])
        self._tcp_socket.listen(listen_callback, backlog)
        self._listening = True
    def makefile(self, mode, bufsize):
        pass
    def recv(self, bufsize, flags=0):
        if self.type != SOCK_DGRAM and not self._connected:
            # Sockets which have never been connected do this.
            if not self._was_connected:
                raise stdsocket.error(ENOTCONN, 'Socket is not connected')

        channel = stackless.channel()
        channel.preference = 1
        if self.type == SOCK_STREAM:
            def tcp_callback(redundant_handle, data, err):
                self._tcp_socket.stop_read()
                if err is None:
                    channel.send(data)
                else:
                    channel.send_exception(stdsocket.error, errno_map[err])
            self._tcp_socket.start_read(tcp_callback)
        else:
            raise RuntimeError("No UDP handling yet")
        return channel.receive()
    def recvfrom(self, bufsize, flags=0):
        channel = stackless.channel()
        channel.preference = 1
        if self.type == SOCK_DGRAM:
            def udp_callback(redundant_handle, address, data, err):
                self._udp_socket.stop_recv()
                if err is None:
                    channel.send((data, address))
                else:
                    channel.send_exception(stdsocket.error, errno_map[err])
            self._udp_socket.start_recv(udp_callback)
        else:
            raise RuntimeError("No TCP handling yet")
        return channel.receive()
    def recvfrom_into(self, buffer, nbytes, flags=0):
        pass
    def recv_into(self, buffer, nbytes, flags=0):
        pass
    def send(self, string, flags=0): # TCP / UDP # COMPLETE
        channel = stackless.channel()
        channel.preference = 1
        def write_callback(redundant_tcp_handle, err):
            if err is None:
                channel.send(None)
            else:
                # TODO: Really should be able to pass multiple arguments to the exception type..
                channel.send_exception(stdsocket.error, errno_map[err])
        self._socket.write(string, write_callback)
        channel.receive()
        return len(string)
    def sendall(self, string, flags=0): # COMPLETE
        return self.send(string, flags)
    def sendto(self, string, flags=0, address=None):
        pass
    def setblocking(self, flag): # COMPLETE
        self._blocking = flag
    def settimeout(self, value): # COMPLETE
        if value and not can_timeout():
            raise RuntimeError("This is a stackless socket - to have timeout support you need to provide a sleep function")
        self._timeout = value
    def gettimeout(self): # COMPLETE
        return self._timeout
    def getsockopt(self, level, optname, buflen=None): # COMPLETE
        if level == stdsocket.IPPROTO_TCP:
            if optname == stdsocket.TCP_NODELAY:
                return self._opt_nodelay
            elif optname == _TCP_KEEPALIVE:
                return self._opt_keepalive_delay
        if level == socket.SOL_SOCKET:
            if optname == socket.SO_KEEPALIVE:
                return self._opt_keepalive
    def setsockopt(self, level, optname, value): # COMPLETE
        if level == stdsocket.IPPROTO_TCP:
            if optname == stdsocket.TCP_NODELAY:
                self._opt_nodelay = bool(value)
                self._tcp_socket.nodelay(self._opt_nodelay)
            elif optname == _TCP_KEEPALIVE:
                self._opt_keepalive_delay = bool(value)
                self._tcp_socket.keep_alive(self._opt_keepalive, self._opt_keepalive_delay)
        if level == stdsocket.SOL_SOCKET:
            if optname == stdsocket.SO_KEEPALIVE:
                self._opt_keepalive = bool(value)
                self._tcp_socket.keep_alive(self._opt_keepalive, self._opt_keepalive_delay)
    def shutdown(self, how): # TCP # COMPLETE
        if how != stdsocket.SHUT_WR:
            raise RuntimeError("Not supported")
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
    def _is_non_blocking(self):
        return not self._blocking or self._timeout == 0.0
