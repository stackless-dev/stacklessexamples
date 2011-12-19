stacklesslib
============

This is a simple framework that layers useful functionality around the
Stackless scheduler.  It's sole purpose is to implement the logic that
an developer needs to implement themselves, to make best use of
Stackless.

 * A sleep function, to allow a tasklet to sleep for a period of time.
 * Monkeypatching to make blocking IO block tasklets not threads.
 
 