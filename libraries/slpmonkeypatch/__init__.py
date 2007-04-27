import os
import sys
import stackless
import threading
import socket as stdsocket

def register_thread_for_stackless():
    _config = getattr(stackless, "_config", None)
    if _config is None:
        _config = stackless._config = threading.local()
    _config.using_stackless = True
    _config.emulation_timeout = 0.1

def monkeypatch():
    # This thread is the only automatically registered one.
    stackless.register_thread = register_thread_for_stackless
    stackless.register_thread()

    # Go through some shenanigans to get the path to the 'examples'
    # directory in the SVN 'sandbox' directory structure.
    filePath = os.path.join(os.getcwd(), __file__)
    dirPath = os.path.split(filePath)[0]
    dirPath = os.path.join(dirPath, os.path.pardir)
    dirPath = os.path.join(dirPath, os.path.pardir)
    dirPath = os.path.normpath(dirPath)
    dirPath = os.path.join(dirPath, "examples")

    # Add the 'examples' directory to the import path.
    if dirPath not in sys.path:
        sys.path.append(dirPath)

    # Install the import reference to the normal python socket module.
    import socket
    sys.modules["stdsocket"] = __import__(socket.__name__)
    del socket

    # Obtain the asyncore-based socket module and put its 'socket' in place.
    import stacklesssocket
    stackless.socket = stacklesssocket.socket
    del stacklesssocket

    import socketmodule
    sys.modules["socket"] = socketmodule
