#
# An example that shows how Stackless can be utilized in a web-context.
# This example uses the stacklesswsgi server.
#
# Traditional threaded web-servers have a hard time with long-running requests.
# A common way of faking server-push in HTTP is to use long-polling, often
# referred to as Comet. In that technique, the client makes a HTTP request
# to the server which is kept alive until the server has data it wants to
# "push" to the client. This kind of request can live for several seconds or
# even longer.
#
# Tying up a thread for several seconds does not scale well. Tasklets on the
# other hand are light-weight enough that we can easily handle tens of thousands
# of simultaneous tasklets.
#
# The stacklesswsgi module implements a WSGI server that handles each request
# in a seperate tasklet. Here we show a small WSGI app that simulates long-polling,
# by grabbing the connection until some event occurs - possibly several seconds
# later.
#
# Author: Arnar Birgisson <arnarbi@gmail.com>
#
# This code was written to serve as an example of Stackless Python usage.
# Feel free to email me with any questions, comments, or suggestions for
# improvement.
#
# But a better place to discuss Stackless Python related matters is the
# mailing list:
#
#   http://www.tismer.com/mailman/listinfo/stackless
#

import stackless
import time

# Nice way to put the tasklet to sleep - from stackless.com wiki/Idioms
##########################################################
sleepingTasklets = []

def sleep(secondsToWait):
    channel = stackless.channel()
    endTime = time.time() + secondsToWait
    sleepingTasklets.append((endTime, channel))
    sleepingTasklets.sort()
    # Block until we get sent an awakening notification.
    channel.receive()

def ManageSleepingTasklets():
    while True:
        if len(sleepingTasklets):
            endTime = sleepingTasklets[0][0]
            if endTime <= time.time():
                channel = sleepingTasklets[0][1]
                del sleepingTasklets[0]
                # We have to send something, but it doesn't matter what as it is not used.
                channel.send(None)
            elif stackless.getruncount() == 1:
                # We are the only tasklet running, the rest are blocked on channels sleeping.
                # We can call time.sleep until the first awakens to avoid a busy wait.
                delay = endTime - time.time()
                #print "wait delay", delay
                time.sleep(max(delay,0))
        stackless.schedule()

stackless.tasklet(ManageSleepingTasklets)()

##########################################################

# Create some sort of an event source. Since this is an example, just
# make something up - say, fire an event whenever time.time() is divisble
# by 10.

fake_event_listeners = []
def fake_event_source():
    """This function loops indefinately, and on every 10 second boundary
    from the epoch, it dispatches an event to a list of listeners. The listeners
    are called with the current timestamp as the sole argument."""
    while 1:
        if len(fake_event_listeners):
            now = int(time.time())
            if now % 10 == 0:
                for f in fake_event_listeners:
                    f(now)
        sleep(1)
        
stackless.tasklet(fake_event_source)()


def wsgi_app(environ, start_response):
    
    # Set up a channel and an event listener that will send() on that
    # channel when the event occurs.
    ch = stackless.channel()
    def evt(timestamp):
        stackless.tasklet(ch.send)(timestamp)
    fake_event_listeners.append(evt)
    
    # Then we suspend until that happens, meanwhile the client waits
    timestamp = ch.receive()
    fake_event_listeners.remove(evt)
    
    start_response('200 OK', [('Content-type','text/plain')])
    return ['The time is %s\n' % time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(timestamp))]


if __name__ == '__main__':
    import stacklesswsgi
    s = stacklesswsgi.Server(('127.0.0.1', 8080), wsgi_app)
    s.start()