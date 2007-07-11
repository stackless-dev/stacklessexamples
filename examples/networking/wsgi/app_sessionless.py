#
# An example that shows how Stackless can be utilized in a web-context.
# This example uses the stacklesswsgi server.
#
# The WSGI application implemented here, SessionlessApp, dispatches
# it's requests to a controller method. However, instead of invoking
# the controller method once per HTTP request as is usually the case,
# the controller method is allowed to create a "web continuation".
#
# For the general idea, look at guess_the_number below.
#
# A web continuation is where a controller outputs data to the HTTP client,
# concluding the HTTP request - but instead of returning - it registers
# itself to be continued when a request with a unique "continuation id"
# comes in. This continuation id is embedded in the returned HTML by
# form fields or link URLs.
#
# When a request with such an ID comes in, the application looks up the
# suspended controller and resumes it's operation, possibly with new
# request parameters.
#
# This allows us to write controllers that interact with the client through
# multiple HTTP responses and requests going back and forth. Since the
# controller is run inside a tasklet, there is little overhead in keeping
# suspended controllers around.
#
# If we want to get rid of a stale controller (where the client may have
# lost interest), we raise a TimeoutException on it.
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
import random
import md5
import time

from cgi import parse_qs

_continuation_id = 1
def _get_continuation_id():
    # Generate some pseudo-cryptic unique code
    global _continuation_id
    c = _continuation_id
    _continuation_id += 1
    return md5.new("%d%d" % (c, random.randint(0, 1023))).hexdigest()


class TimeoutException(Exception):
    pass

class SessionlessApp(object):
    """A WSGI application that allows for controllers that span
    multiple requests"""
    
    # Timeout in seconds for continuations
    continuation_timeout = 300
    
    def __init__(self):
        # This dict maps continuation ids to registration times and
        # channels that we must send() on to resume the relevant controller.
        self.continuations = dict()
    
    def __call__(self, environ, start_response):
        """Invokes an application. The request parameters are looked for a parameter
        called "__wc". If found, we see if that is an id of a suspended controller
        and if it is, we wake it up so that it can continue.
        Otherwise, a new tasklet is created and an appropriately selected controller
        is called from that tasklet"""
        
        # Expire old continuations
        self.prune_old_continuations()
        
        # This channel serves the purpose of passing the data to be returned
        # to the HTTP client from the controller to the application. This is
        # because the application must return when the data is sent, but the
        # controller invocation may live longer.
        ch = stackless.channel()
        parameters = parse_qs(environ['QUERY_STRING'])
        if '__wc' in parameters:
            # We have a continuation id, see if we can find a suspended
            # controller associated with it.
            try:
                key = parameters['__wc'][0]
                reg_time, continuation_channel = self.continuations[key]
                
                # Remove the channel from the continuations map and resume
                # it by giving it the new data channel and parameters
                del self.continuations[key]
                continuation_channel.send((parameters, ch))
                
            except KeyError, ValueError:
                # This means no controller was found with this continuation
                # id. For example it may have timed out.
                start_response('500 Error', [])
                return ['Continuation id invalid']
        else:
            # In a real application, url-to-controller mapping would be done
            # here, but since this is just an example - we just hard-code
            # our example controller
            controller = guess_the_number
            
            # Create a new SessionlessRequest - which may live beyond this
            # http request. The SessionlessRequest instance is a callable,
            # a call on it will run the controller.
            req = SessionlessRequest(self, ch, controller, parameters)
            stackless.tasklet(req)()
        
        # Now, wait for the controller to return some data. This can happen
        # in two ways - the controller simply returns (see SessionlessRequest)
        # or it "continues" - meaning it will send data to the client with a
        # continuation id somewhere in a form or a link.
        data = ch.receive()
        
        # Again, since this is just an example - just hard code the content-type.
        # In reality, this would be up to the controller.
        start_response('200 OK', [('Content-type','text/html')])
        
        return [data]

    
    def register_continuation(self, id):
        """Given an id, creates a channel and registers it in the continuation
        map with that id. Returns the channel, which will we will send() on when
        a continuing http request arrives."""
        ch = stackless.channel()
        self.continuations[id] = (time.time(), ch)
        return ch
    
    def prune_old_continuations(self):
        for key in self.continuations.keys():
            t, c = self.continuations[key]
            if t + self.continuation_timeout < time.time():
                c.send_exception(TimeoutException)
                del self.continuations[key]


class SessionlessRequest(object):
    
    def __init__(self, app, channel, controller, parameters):
        self._app = app
        self._controller = controller
        self.parameters = parameters
        self._continuation_id = _get_continuation_id()
        self._channel = channel
    
    @property
    def continuation_id(self):
        """The continuation id for the next continuation. Useful to include
        in html forms and/or links."""
        return self._continuation_id
    
    def continue_(self, data):
        """Writes data to client and suspends until we are continued"""
        # Write the data to the data-channel. This will tell the application
        # to write the data out to the client and finish of the current
        # http request.
        self._channel.send(data)
        
        # Request a channel on which we'll be notified when a continuing http
        # request arrives
        continuation_ch = self._app.register_continuation(self.continuation_id)
        
        # When that happens, the application will send a new set of parameters
        # and a new data-channel. This may propogate a TimeoutException to the
        # controller.
        new_parameters, new_channel = continuation_ch.receive()
        self.parameters = new_parameters
        self._channel = new_channel
        
        # Since we used our continuation-id, we will need a new one.
        self._continuation_id = _get_continuation_id()
    
    def __call__(self):
        """Invoke the controller."""
        # The return value of a controller should be written to the
        # http client as a final response.
        try:
            final_data = self._controller(self)
            self._channel.send(final_data)
        except TimeoutException:
            # The controller didn't handle the timeout itself, so we just ignore it
            pass


def guess_the_number(req):
    """A simple "Guess the number" game. A random integer between 1 and 100
    is chosen. The user is then presented with a form to guess a number and
    the controller. When he/she responds, we tell them if the number is to
    high or to low and repeat until they guess the correct number.
    
    This of course calls for multiple HTTP requests and responses going back
    and forth. Note that we don't use a traditional http session - just local
    variables and "web-continuations".
    """
    
    template = """
    %(message)s<br />
    You have guessed %(number_of_guesses)d times.<br />
    <form method="get" action="/">
    <input type="hidden" name="__wc" value="%(cid)s" />
    <input type="text" name="guess" />
    <input type="submit" value="Guess!" />
    </form>
    """
    secret_number = random.randint(1,100)
    guess = None
    number_of_guesses = 0
    message = "Please start guessing numbers between 1 and 100 (both included)"
    
    while True:
        # We render the template to the user and wait for their input
        # Calling req.continue_(x) has the effect of sending x to the http
        # client and suspending the execution of this controller until there
        # is a http request referring to req.continuation_id.
        req.continue_(template % dict(
            message=message,
            number_of_guesses=number_of_guesses,
            cid=req.continuation_id
        ))
        
        # Here, their input has arrived and req.parameters should now contain guess...
        number_of_guesses += 1
        try:
            guess = int(req.parameters.get("guess", [None])[0])
            if guess < secret_number:
                message = "You guessed %d - which is to low" % guess
            elif guess > secret_number:
                message = "You guessed %d - which is to high" % guess
            else:
                # They got it right so we're done
                break
        except TypeError:
            guess = None
            message = "You must guess a number!"
        
    return """Yay - %d is the right number, you made it in %d guesses.<br />
    <a href="/">Play again</a>""" % (guess, number_of_guesses)


if __name__ == '__main__':
    import stacklesswsgi
    s = stacklesswsgi.Server(('127.0.0.1', 8080), SessionlessApp())
    s.start()