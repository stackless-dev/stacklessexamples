// Boost Python, Boost Threading, & System Time Includes
#include <boost/python.hpp>
#include <boost/thread.hpp>
#include <boost/random.hpp>
#include <sys\timeb.h>
//-----------------------------------------------------------------------

// Std Library includes
#include <iostream>
#include <vector>
//-----------------------------------------------------------------------

// Stackless Sleeper, Sync, Network Includes
#include "sync.h"
#include "StringUtil.h"
//-----------------------------------------------------------------------

// Create separate Stackless synchronisation objects for "real time" & "simulated time" tasklet sleeping
CStacklessSync              oRealTimeSynch;
CStacklessSync              oWorldTimeSynch;
//-----------------------------------------------------------------------

// Create & initialise the world time variable (separate from "real time" for simulation purposes
double                      fCurWorldTime = 0.0;
//-----------------------------------------------------------------------

// Network Thread globals
boost::mutex                mNetworkMutex;
std::vector<unsigned int>   vNetworkConnections;
bool                        bTerminateNetThread;
std::list<std::string>      lNetworkMsgQueue;
//-----------------------------------------------------------------------

// TODO: Determine a platform safe method of getting floating point time
double floatTime()
{
    timeb oTimeData; ftime(&oTimeData);
    return (double)oTimeData.time + ( (double)(oTimeData.millitm) / 1000.0);
}
//-----------------------------------------------------------------------

// This function will put a tasklet to sleep for at least the requested milliseconds (clock-time)
void sleepRealTime(int nPMilliSeconds)
{
    double fSleepUntil = floatTime() + ( (double)(nPMilliSeconds) / 1000.0);
   
    oRealTimeSynch.sleepUntil(fSleepUntil);
}
//-----------------------------------------------------------------------

// The following function puts a tasklet to sleep for the specified "simulation time", 
// which is not the same as clock-time (unless the application codes it as such)
void sleepWorldTime(int nPMilliSeconds)
{
    double fSleepUntil = fCurWorldTime + ( (double)nPMilliSeconds / 1000.0 );

    oWorldTimeSynch.sleepUntil(fSleepUntil);
}
//-----------------------------------------------------------------------

// This function will add the calling tasklet to the real-time 'nice' channel for awakening next stacklessTick
void beNiceRealtime()
{
    oRealTimeSynch.beNice();
}
//-----------------------------------------------------------------------

// Called by stacklessTick to wakeup a sleeping tasklets (as stored & sorted in the CSleepersSet parameter)
int wakeUpSleepers(double nPCurrentTime, CStacklessSync::CSleepersSet& oPSleepers)
{
    CStacklessSync::CSleepersSet::iterator iBegin = oPSleepers.begin();
    CStacklessSync::CSleepersSet::iterator iEnd   = oPSleepers.end();

    // Pre-condition: There are actually sleepers in the set
    if (iBegin == iEnd)
    {   return 0; }

    // Pre-condition: Check if any sleepers need to actually be resumed
    if ((*iBegin)->getResumeTime() > nPCurrentTime)
    {   return 0; }

    // Create & initialise iterators (used to step through the sorted set)
    CStacklessSync::CSleepersSet::iterator iCurPos = iBegin;
    CStacklessSync::CSleepersSet::iterator iNextPos;

    // Loop through set awakening tasklets as required
    int  nWakeCount      = 0;
    bool bContinueWaking = true;
    while (bContinueWaking)
    {
        // Increment the 'next sleeper' iterator for the next loop
        iNextPos = iCurPos;
        iNextPos++;

        // Retrieve the sleeper object from the iterator and remove from the sleepers set
        CStacklessSleeperPtr pSleeper = (*iCurPos);
        oPSleepers.erase(iCurPos);

        // Send the "None" object to sleeper channel to "wake it" (could be any value, "None" is just easier)
        boost::python::object oNone;
        PyChannel_Send(pSleeper->getBorrowedChannel(), oNone.ptr());
        nWakeCount++;

        // Terminate the loop if we are at the end of the set or simply have no more sleepers needing activtion
        if (iNextPos == iEnd || (*iNextPos)->getResumeTime() <= nPCurrentTime)
        {   bContinueWaking = false; }

        // Set the current iterator to the next element in the set (as precached above)
        iCurPos = iNextPos;
    }

    return nWakeCount;
}
//-----------------------------------------------------------------------

// Called once every main loop to awaken sleeping tasklets & resume tasklets that have called "beNice"
void stacklessTick()
{
    // Resume/"reschedule" all tasklets on the "nice" channel
    try
    {
        int nBalance                = boost::python::extract<int>(oRealTimeSynch.getNiceChannelRef().attr("balance"));
        PyChannelObject* pChannel   = oRealTimeSynch.getNiceChannelPtr();

        for (int nSendIdx = nBalance; nSendIdx < 0; nSendIdx++)
        {   PyChannel_Send(pChannel, Py_None); }

    }
    catch (boost::python::error_already_set&)
    {
        std::cerr << "Stackless 'rescheduling' error reawakening 'nice' tasklets" << std::endl;
        PyErr_Print();
        PyErr_Clear();
    }

    // Wake up "real-time" sleeping tasklets
    wakeUpSleepers(floatTime(), oRealTimeSynch.getSleeperSetRef() );

    // Wake up "simulation time" sleeping tasklets
    // NOTE: Current time is a global, not calculated on the fly!
    wakeUpSleepers(fCurWorldTime, oWorldTimeSynch.getSleeperSetRef() );

    // Loop through all waiting tasklets and run them (with the watchdog to ensure no runaway 'microthreads')
    boost::python::handle<> hStacklessWatchdog;
    do
    {
        try
        {
            hStacklessWatchdog = boost::python::handle<>(boost::python::allow_null(PyStackless_RunWatchdog(1000)));

            boost::python::object oRunAwayTasklet(hStacklessWatchdog);
            if (oRunAwayTasklet.ptr() != Py_None)
            {
                // TODO: Work out how to log the stacktrace of runaway tasklet!!!

                // Log the fact we killed the runaway tasklet
                std::cerr << "Stackless Watchdog interrupted long running tasklet ('beNice' Stackless function not called)" << std::endl;
                int nRetVal = PyTasklet_Kill(reinterpret_cast<PyTaskletObject*>(oRunAwayTasklet.ptr()));
                std::cerr << "Killing this tasklet, Return Value: " << nRetVal << " (expecting 0)" << std::endl;
            }
        }
        catch (boost::python::error_already_set&)
        {
            // Other errors need to be logged here            
            std::cerr << "Received an error from Stackless Tasklet" << std::endl;
            PyErr_Print();
            PyErr_Clear();
        }
    }
    while (!hStacklessWatchdog);

}
//-----------------------------------------------------------------------

// This function creates a boost::xtime that can be used to delay for X millseconds
// Based on test code from Boost Thread Library, but the function is pretty straight 
// forward for those that are interested in it's makeup
boost::xtime delayMilliSec(int nPMilliSec)
{
    // Time Division constants
    const int MILLISECONDS_PER_SECOND     = 1000;
    const int NANOSECONDS_PER_SECOND      = 1000000000;
    const int NANOSECONDS_PER_MILLISECOND = 1000000;

    // Get the current time
    boost::xtime xt;
    boost::xtime_get(&xt, boost::TIME_UTC);

    // Get the "additional" time to add to the "Now" variable
    unsigned int nSeconds   = nPMilliSec / MILLISECONDS_PER_SECOND;
    unsigned int nNanoSecs  = xt.nsec + ( (nPMilliSec % MILLISECONDS_PER_SECOND) * NANOSECONDS_PER_MILLISECOND);
    
    // Fill in the boost::xtime with new time (i.e. 'now + delay')
    xt.nsec = nNanoSecs % NANOSECONDS_PER_SECOND;
    xt.sec += nSeconds + (nNanoSecs / NANOSECONDS_PER_SECOND);

    // Guess what this does!
    return xt;
}
//-----------------------------------------------------------------------

// This function is run in another thread to simulate the monitoring of 
// network connections. In reality, this would be accepting, monitoring, 
// and closing TCP/IP and/or UDP network connections
void networkThread()
{
    // To avoid multi-threadinig issues associated with sharing rand() across 
    // threads, I use the Boost.Random template classes to produce my 'noise'.
    // This has the added advantage of consistent reproducibility
    // I highly recommend game & simulation developers look into Boost.Random!
    boost::minstd_rand                                                    gBaseGen;  
    boost::uniform_real<>                                                 dRandomDist(0,1);
    boost::uniform_int<>                                                  dIntegerDist(0, 100);
    boost::variate_generator<boost::minstd_rand&, boost::uniform_real<> > gPercentageGen(gBaseGen, dRandomDist);
    boost::variate_generator<boost::minstd_rand&, boost::uniform_int<> >  gIndexGen(gBaseGen, dIntegerDist);

    unsigned int nNetworkConnectNum = 0;

    // Loop around while the main thread has not notified us to terminate
    while (!bTerminateNetThread)
    {
        // Sleep for 200 milliseconds between checks - this is too high for 
        // "real world" usage, but good enough for the test applicaton
        boost::thread::sleep(delayMilliSec(200));

        // Instead of monitoring actual TCP connections (the only 
        // cross-platform method I _personally_ know being STL-Plus),
        // I simulate the connection, incoming data, & disconnections
        // with random numbers & "percentage probability"

        // NOTE: I use a boost::mutex::scoped_lock in order to prevent
        //       race-conditions with the message queue. Given there are 
        //       three different "events" here - we could use three 
        //       different locks/queues (for less contention), but I 
        //       tried to make things simple.
        
        // 20% chance of new connection
        if (gPercentageGen() < 0.2 && vNetworkConnections.size() < 100)
        {
            boost::mutex::scoped_lock lScopedLock(mNetworkMutex);

            // Simulate connection state with a simple integer (i.e. to identify individual connections)
            vNetworkConnections.push_back(++nNetworkConnectNum);

            // Add message to queue to let Python know the connection has been established
            lNetworkMsgQueue.push_back("New Network Connection " + to_string(nNetworkConnectNum));
        }

        // 20% chance of removing an old connection
        if (gPercentageGen() < 0.2 && vNetworkConnections.size() > 0)
        {
            boost::mutex::scoped_lock lScopedLock(mNetworkMutex);

            unsigned int nDropIdx = (gIndexGen() % (unsigned int)vNetworkConnections.size());

            // Add message to queue to let Python know the connection is dead
            lNetworkMsgQueue.push_back("Network disconnect for Connection " + to_string(vNetworkConnections[nDropIdx]));

            // Here we would delete the "network object" properly (I assume a pointer is used in the vector) 
            vNetworkConnections.erase(vNetworkConnections.begin() + nDropIdx);

        }

        // Each connection has a 20% chance of a message being received
        for (unsigned int nIdx = 0; nIdx < vNetworkConnections.size(); nIdx++)
        {
            if (gPercentageGen() < 0.2)
            {
                boost::mutex::scoped_lock lScopedLock(mNetworkMutex);
                
                // Here we would push new messages from individual connections onto a queue for processing in "stacklessMain"
                lNetworkMsgQueue.push_back("New Message from Connection " + to_string(vNetworkConnections[nIdx]));
            }
        }
    }
}
//-----------------------------------------------------------------------

void stacklessMain()
{
    // Watchdog test
    {
        // TODO: Implement a Watchdog test!
    }

    // Sleeping ('Real-time' vs 'World-time') & Multi-threading test
    {
        // Create the Python code to execute
        std::string sCode = "import time\n"
                            "print 'Sleeping Test'\n"
                            "def sleepRealTest():\n"
                            "   startTime = time.time()\n"
                            "   loopCount = 0\n"
                            "   while 1:\n"
                            "       StacklessSync.sleepRealTime(1000)\n"
                            "       print 'Real:  ' + str(time.time() - startTime)\n"
                            "       loopCount = loopCount + 1\n"
                            "       pass\n"
                            "def sleepWorldTest():\n"
                            "   startTime = time.time()\n"
                            "   loopCount = 0\n"
                            "   while 1:\n"
                            "       StacklessSync.sleepWorldTime(2000)\n"
                            "       print 'World: ' + str(time.time() - startTime)\n"
                            "       loopCount = loopCount + 1\n"
                            "       pass\n"
                            "def printMsg(msgString):\n"
                            "    print 'Msg: ' + str(msgString)\n"
                            "stackless.tasklet(sleepRealTest)()\n"
                            "stackless.tasklet(sleepWorldTest)()\n";

        // Run the code to schedule & put to sleep the tasklets
        PyRun_SimpleString(sCode.c_str());

        // Retrieve the 'printMsg' function object from the main context (i.e. the context we are currently running in)
        boost::python::handle<> hMainHandle(boost::python::borrowed(PyImport_ImportModule("__main__")));
        boost::python::object   oMainModule(hMainHandle);
        boost::python::object   oPrintFunc = oMainModule.attr("printMsg");

        // Initialise time tracking variables (I use doubles to allow for millisecond time periods over a month)
        double fStartTime   = floatTime();
        double fLastUpdate  = fStartTime;
        double fCurrentTime = fStartTime;
        fCurrentTime        = 0.0;
        do 
        {   
            // Run the stackless tick (i.e. wake sleepers & "nice" tsaklets)
            stacklessTick();

            // Update the "World Time" every half second
            double fDeltaTime = fCurrentTime - fLastUpdate;
            if (fCurrentTime - fLastUpdate > 0.5)
            {
                fCurWorldTime += 0.2;
                fLastUpdate = fCurrentTime;
            }

            // Process network messages
            while (lNetworkMsgQueue.size() > 0)
            {
                // Lock the message queue
                boost::mutex::scoped_lock lScopedLock(mNetworkMutex);

                // Call the "handler method" (there is most likely a more efficient method than below, but this works)
                boost::python::tuple oMsg = boost::python::make_tuple(lNetworkMsgQueue.front());
                PyEval_CallObject(oPrintFunc.ptr(), oMsg.ptr());

                // Remove message from the queue
                lNetworkMsgQueue.pop_front();
            }

            // Sleep for a millisecond to prevent spin-locked CPU
            boost::thread::sleep(delayMilliSec(1));

            fCurrentTime = floatTime();
        } while (22.0 > (fCurrentTime - fStartTime ));
    }
}
//-----------------------------------------------------------------------

int main (int argc, char** argv)
{
    // Initialize Python
    Py_SetProgramName(argv[0]);
    Py_InitializeEx(0);

    if (!Py_IsInitialized())
    {
        std::cerr << "Python initialization failed" << std::endl;
        return -1;
    }

    // Initialise the synchronisation globals (should this be done in constructor???)
    oRealTimeSynch.initialise();
    oWorldTimeSynch.initialise();

    // Copy the argc/argv variables into the Python context
    PySys_SetArgv(argc, argv);

    // Prevent main (this) tasklet from being blocked
    PyRun_SimpleString("import stackless\n"
                       "stackless.getcurrent().block_trap = True");

    // Set this up as the "main module" (i.e. the root module from which other modules are loaded & code executed)
    boost::python::handle<> hMainHandle(boost::python::borrowed(PyImport_AddModule("__main__")));
    boost::python::object   oMainModule(hMainHandle);
    
    // NOTE: I am not sure why the following line is required, but without it - the appliication crashes in
    //       Boost.Python code. This must be a Boost.Python or simply Python quirk I have yet to grok...
    boost::python::scope    oMainScope(oMainModule);

    // Register the "StacklessSync" class/module into Python
    // NOTE: We can use 'non-class' methods as the static methods, making it simple to instantiate globals
    //       only in the main C++ module (i.e. this one). I dislike static globals scattered through-out the code-base!
    boost::python::object   oClassSync = boost::python::class_<CStacklessSync, boost::noncopyable>("StacklessSync")
                                            .def("beNice", &beNiceRealtime)
                                            .staticmethod("beNice")
                                            .def("sleepRealTime", &sleepRealTime)
                                            .staticmethod("sleepRealTime")
                                            .def("sleepWorldTime", &sleepWorldTime)
                                            .staticmethod("sleepWorldTime");

    // Register the "stacklessMain" function into Python ('__main__' context)
    boost::python::def("stacklessMain", &stacklessMain);

    // Start the network thread using Boost.Thread
    // NOTE: I am not terribly familiar with Boost.Thread, but wanted to create an example using
    //       the smallest amount of dependencies possible. We're already using Boost.Python, so 
    //       Boost.Threads was a minimal "extra hit" in this regard.
    boost::thread oNetworkThread(networkThread);

    // Start the stacklessMain method inside stackless context
    // This function call will block until the stacklessMain method is done
    PyStackless_CallMethod_Main(oMainModule.ptr(), "stacklessMain", 0);

    // Stackless main has exited - time to close the network thread
    bTerminateNetThread = true;
    oNetworkThread.join();

    // Wait for user input (makes it easier to debug for me!)
    PyRun_SimpleString("raw_input('Press any key to exit...')");

    // At this point, the "stacklessMain" method has finished, there are no threads running, 
    // and hence we can finalise/close the application
    Py_Finalize();
}
//-----------------------------------------------------------------------