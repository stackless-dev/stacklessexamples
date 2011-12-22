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

Version 1.0.4:

 * Modified monkey-patching to by default run a tasklet to pump
   the scheduler.  The ideal goal is that a user just needs to install
   the monkey-patching and a non-Stackless standard library dependent
   module should be able to be run without further modifications.
 * Removed duplicate sleep method.

Version 1.0.3:

 * All previous versions had broken eggs.  This was because the manifest was not
   correctly configured to recursively include the source directory.