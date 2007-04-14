#include "sync.h"

#include <stackless_api.h>

//-----------------------------------------------------------------------
// CStacklessSleeper Constructor
//-----------------------------------------------------------------------
CStacklessSleeper::CStacklessSleeper(double fPResumeTime)
{
  _fResumeTime = fPResumeTime;
  
  PyChannelObject* pRawChannel = PyChannel_New(NULL);
  PyChannel_SetPreference(pRawChannel, 0);
  
  _oChannel = boost::python::object(boost::python::handle<>(reinterpret_cast<PyObject*>(pRawChannel)));
}
//-----------------------------------------------------------------------

CStacklessSleeper::~CStacklessSleeper()
{
}
//-----------------------------------------------------------------------

//-----------------------------------------------------------------------
// CStacklessSync Class Implementation
//-----------------------------------------------------------------------
CStacklessSync::CStacklessSync()
{
}
//-----------------------------------------------------------------------

CStacklessSync::~CStacklessSync()
{
}
//-----------------------------------------------------------------------

void CStacklessSync::initialise()
{
    _oNiceChannel = boost::python::object(boost::python::handle<>(reinterpret_cast<PyObject*>(PyChannel_New(NULL))));    
    
    // Set no preference on the channel (i.e. scheduling policy gives same priority to both senders & recievers)
    PyChannel_SetPreference(reinterpret_cast<PyChannelObject*>(_oNiceChannel.ptr()), 0);
}
//-----------------------------------------------------------------------

void CStacklessSync::sleepUntil(double fPSleepTo)
{
    boost::python::handle<> oTaskletHandle(PyStackless_GetCurrent());
    boost::python::object   oCurTasklet(oTaskletHandle);
  
    // Check if this is the main tasklet (it is not allowed to call Sleep!!!)
    if (PyTasklet_IsMain(reinterpret_cast<PyTaskletObject*>(oCurTasklet.ptr())) == 1)
    {   throw std::string("sleepUntil called for main tasklet"); }
  
    CStacklessSleeperPtr oSleeper(new CStacklessSleeper(fPSleepTo));
    addSleeper(oSleeper);
  
    // Apparently GCC does not "anonymous returns", hence the following line (I've only tested in MSVC)
    // The "allow_null" will help the application exit with a channel still blocking
    boost::python::handle<> oAnon(boost::python::allow_null(PyChannel_Receive(oSleeper->getBorrowedChannel())));
}
//-----------------------------------------------------------------------

void CStacklessSync::addSleeper(CStacklessSleeperPtr pPSleeper)
{
    _oSleepersSet.insert(pPSleeper);
}
//-----------------------------------------------------------------------

CStacklessSync::CSleepersSet& CStacklessSync::getSleeperSetRef()
{
    return _oSleepersSet;
}
//-----------------------------------------------------------------------

void CStacklessSync::beNice()
{
  PyChannel_Receive(reinterpret_cast<PyChannelObject*>(_oNiceChannel.ptr()));
}
//-----------------------------------------------------------------------

boost::python::object CStacklessSync::getNiceChannel()
{
    return _oNiceChannel;
}
//-----------------------------------------------------------------------

boost::python::object& CStacklessSync::getNiceChannelRef()
{
    return _oNiceChannel;
}
//-----------------------------------------------------------------------

PyChannelObject* CStacklessSync::getNiceChannelPtr()
{
    return reinterpret_cast<PyChannelObject*>(_oNiceChannel.ptr());
}
//-----------------------------------------------------------------------
