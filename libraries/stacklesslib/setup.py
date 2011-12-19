from setuptools import setup

setup(
    name = "stacklesslib",
    packages = ["stacklesslib", "stacklesslib.replacements"],
    version = "1.0.3",
    description = "Standard Stackless Python supporting functionality",
    author = "Richard Tew",
    author_email = "richard.m.tew@gmail.com",
    url = "http://pypi.python.org/pypi/stacklesslib",
    keywords = ["microthreads", "coroutines", "stackless", "monkeypatching"],
    classifiers = [
        "Programming Language :: Python",
        "Programming Language :: Python :: 2",
        "Development Status :: 5 - Production/Stable",
        "Environment :: Other Environment",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Topic :: Software Development :: Libraries :: Python Modules",
        ],
    long_description = """\
stacklesslib
============

Stackless Python by itself only provides a basic set of functionality,
allowing either cooperative or preemptive scheduling of microthreads
within the same operating system thread.  This framework provides the
additional support that anyone developing an application using Stackless
Python will end up eventually implementing.

The most useful aspect is the monkey-patching support.  Much of the
code in the standard library does blocking operations, or perhaps
is even written to make use of threads.  If the monkey-patching is
installed, then these blocking operations are converted to be
"Stackless friendly".  Threads will actually be tasklets.  Operations
that block the operating system thread (and therefore the Stackless
scheduler) will be converted to simply block the tasklet that is
standing in for the threads that would otherwise be used.

Even if an application developer does not wish to make use of
monkey-patching, they can still make use the framework provided
so that they do not need to implement the standard supporting
functionality themselves.

Useful supporting functionality:

 * Concurrency-related primitives corresponding to those that the
   standard library threading module provides for real threads.
 * Ability to put tasklets to sleep for a set amount of time.
 * Ability to specify timeouts for blocking operations.

Changes
-------

Version 1.0.3:

 * All previous versions had broken eggs.  This was because the manifest was not
   correctly configured to recursively include the source directory.
 """
)