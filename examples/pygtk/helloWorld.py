#
# Using PyGTK with Stackless
#
# Authors: Richard Tew <richard.m.tew@gmail.com> (extended and documented)
#          Sebastian de Bellefon (added Stackless scheduling support)
#          PyGTK Tutorial, Chapter 2 / Getting Started
#
# This example is intended to illustrate how to get the PyGTK framework
# main loop to work with the Stackless framework main loop.  It shows
# that as the GTK main loop waits for events for the created window,
# Stackless continues scheduling in the background.
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
import gobject
import gtk
import weakref

class HelloWorld:
       def hello(self, widget, data=None):
              global cnt
              print "There have been", cnt, "schedulings of the other tasklet while you were sitting there!"
              cnt = 0

       def schedule (self):
               gobject.timeout_add(50, self.schedule)
               stackless.schedule()

       def __init__(self):
               self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
               self.window.connect("delete_event", self.delete_event)
               self.window.set_border_width(10)
               self.button = gtk.Button("Hello World")
               self.button.connect("clicked", self.hello, None)
               self.window.add(self.button)
               self.button.show()
               self.window.show()
               ### Here is the trick
               gobject.timeout_add(50, self.schedule)

       def main(self):
              print 'main'
              t = stackless.tasklet(gtk.main)()
              # Keep a reference to this tasklet, but only a weakref.  We can use this
              # to kill it when the window is closed.
              self.taskletRef = weakref.proxy(t)

       def delete_event(self, widget, event, data=None):
              """
              Called when the window gets a close event.  Whether the close button is
              clicked or something similar.
              """
              print 'delete_event', widget, event, data
              # We want to kill the gtk main function call.  Perhaps there is a better way?
              self.taskletRef.kill()
              # Returning False gets the window closed.
              return False

# A global variable to track the number of schedulings of the other tasklet
# while the user was doing nothing.
cnt = 0

def schedule_func():
       """
       The other tasklet.  This runs and increments a counter.  What this is intended to
       show is that the PyGTK main loop is giving the scheduler a chance to run.
       """
       global cnt
       while 1:
              cnt += 1
              stackless.schedule()

if __name__ == "__main__":
       # Start the scheduling proof tasklet.
       stackless.tasklet(schedule_func)()

       # Create the Window and schedule the GTK main loop.
       hw = HelloWorld()
       hw.main()

       # Run the scheduler.  As you know, this will run until there are not tasklets
       # left still scheduled.
       print 'calling stackless.run'
       stackless.run()
       # The user must have closed the window.
       print 'done'

