#ifndef __STRING_UTIL_H__
#define __STRING_UTIL_H__

#include <string>
#include <sstream>

template<class T> std::string to_string (const T &t)
{
    std::stringstream ss;
    ss << t;
    return ss.str();
};

template <class S, class T> S string_cast(T const& t) 
{
    std::stringstream stream;
    stream << t;
    S rc;
    stream >> rc;
    return rc;
};

#endif