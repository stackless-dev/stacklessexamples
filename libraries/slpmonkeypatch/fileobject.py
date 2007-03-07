import __builtin__

stdfile = file

def stacklessopen(filename, mode='r', bufsize=None):
    return StacklessFile(filename, mode, bufsize)

class StacklessFile(file):
    def __init__(self, filename, mode='r', bufsize=None):
        # Preserve normal behaviour.
        if bufsize is None:
            super(file, self).__init__(filename, mode)
        else:
            super(file, self).__init__(filename, mode, bufsize)
    def xread(self):
        pass
    def xwrite(self):
        pass

def monkeypatch1():
    __builtin__.stdopen = __builtin__.open
    __builtin__.open = stacklessopen
    __builtin__.file = StacklessFile
