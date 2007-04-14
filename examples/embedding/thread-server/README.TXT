Threaded Stackless Application Framework
========================================

This example is based on ideas presented in the embedDemo shipped with Stackless Python (which in turn was based on the excellent presentation by CCP Games at Pycon 2006, the slides for which are still around on the Internet for viewing)

The example is designed to show two things. Firstly, it is an example on how one would create two "sleeping" queues to allow for real-teim vs simulation-time tasklet sleeping. This would (for example) allow for game events to be "delayed" nicely when time slows down for the user, but still allow "real-time response" on GUI events and the like. The second is how one could integrate Stackless Python into a multi-threaded application (where all OS threads are in C++ only). This would appear to be required when multi-threading as Python itself is not truly a threaded application as the GIL will block all other Python threads when doing something useful!

In similar fashion to the inspiration, what follows is a quick disclaimer on the code and architecture used...

Quick Disclaimer:
-----------------
This code borrows it's basic arhitecture from the embedDemo, but has been rewritten from scratch. Too many years in commercial development has given me an allergic reaction to 'non-commercial' open-source licenses (i.e. those that state you can copy/alter the code only for personal use). Given how often this gets in the way of my day-to-day job, nigh on all open-source I release is under BSD/MIT type license. So long as you don't say the code is yours, feel free to use and hack it to your needs (be they commercial, idealistic, or purely for the hell of it). Apologies if this offends, but hey - it's free code :)

On the architecture side, I tried to minimize the amount of dependencies the code has on other libraries. Given that I use Boost.Python for C/C++ & Python embedding/extending - I tried to use the Boost libraries for other platform-dependent functionality (in this instance, threading & thread-safe 'noise' functions/classes). I would have included some "real networking" code in there, but the only cross-platform TCP/IP class library I am familiar with is STL-Plus and I did not want the end-user needing to download & install more than necessary. However, the application is REALLY multi-threaded and, aside from not using real network connections, I think it shows how one would multi-thread a Stackless application when embedding in C++ (the use case I am interested in).