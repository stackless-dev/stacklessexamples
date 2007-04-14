#ifndef __PY_STACKLESS_SYNC_H__
#define __PY_STACKLESS_SYNC_H__

#include <boost/python.hpp>
#include <boost/smart_ptr.hpp>
#include <stackless_api.h>
#include <list>
#include <set>

//-----------------------------------------------------------------------
// Required Forward Declarations
//-----------------------------------------------------------------------
class CStacklessSleeper;
typedef boost::shared_ptr<CStacklessSleeper> CStacklessSleeperPtr;

//-----------------------------------------------------------------------
// CStacklessSleeper class declaration
//-----------------------------------------------------------------------
class CStacklessSleeper
{
public:
    // Comparator (for STL/Boost algorithms)
    struct Comparator
    {
        bool operator()(const CStacklessSleeperPtr& a, const CStacklessSleeperPtr& b) const
	    {   return a->_fResumeTime < b->_fResumeTime; }
    };
  
    // Construction / Destruction
    CStacklessSleeper(double fPResumeTime);
    ~CStacklessSleeper();
  
    // Get the Stackless Channel (as a new boost::python::object, i.e. with reference increment)
    boost::python::object getChannel()
    {   return _oChannel; }
  
    // Get the raw Stackless Channel Object (without reference increment)
    PyChannelObject* getBorrowedChannel()
    {   return reinterpret_cast<PyChannelObject*>(_oChannel.ptr()); }

    double getResumeTime() const
    {   return _fResumeTime; }

    // Comparison operator (for sorting)
    bool operator< (const CStacklessSleeper& sleeper) const
    {   return _fResumeTime < sleeper._fResumeTime; }

protected:
    double                  _fResumeTime;
    boost::python::object   _oChannel;
};


//-----------------------------------------------------------------------
// CStacklessSync class declaration
//-----------------------------------------------------------------------
class CStacklessSync
{
public:
    typedef std::multiset<CStacklessSleeperPtr, CStacklessSleeper::Comparator> CSleepersSet;    
    
    CStacklessSync();
    ~CStacklessSync();
  
    // Create the internal variables required for the sync object
    // NOTE: I know there are arguments for doing this all in the 
    //       constructor, however I have a (possibly bad) habit of
    //       doing it in a separate function when exceptions can
    //       be thrown. Worst case scenario, make the function 
    //       private and call in the constructor :)
    void                     initialise();

    // "Sleeping" Functionality
    void                     sleepUntil(double fPSleepTo);
    void                     addSleeper(CStacklessSleeperPtr pPSleeper);
    CSleepersSet&            getSleeperSetRef();

    // "Nice/Polite" Tasklet Functionality
    void                     beNice();    
    boost::python::object    getNiceChannel();
    boost::python::object&   getNiceChannelRef();
    PyChannelObject*         getNiceChannelPtr();

protected:
    boost::python::object    _oNiceChannel;
    CSleepersSet             _oSleepersSet;
};

#endif
