#!/usr/bin/env python

import code
import threading
import traceback
import sys
import time
import socket

# load following in python2 and python3 compatible way.
if sys.version_info.major == 2:
    import SocketServer as ss
    from StringIO import StringIO as StringIO
else:
    import socketserver as ss
    from io import StringIO as StringIO

# Create a function that is available from the shell to gracefully exit server
# after disconnect.
should_exit = False


def halt():
    global should_exit
    sys.displayhook("Shutting down after all clients disconnect.")
    should_exit = True

# Update the displayhook such that it redirects data to the appropriate stream
# if the errors and such are printed by code.interact. This does not capture
# print() itself.
thread_scope = threading.local()


def new_displayhook(data):
    if (data is None):
        return

    if hasattr(thread_scope, "displayhook"):
        thread_scope.displayhook(data)
    else:
        print(data)
sys.displayhook = new_displayhook

# For python 3 we also have to setup an excepthook capturing
# the stack trace and printing it via the displayhook works.


def new_excepthook(type, value, tb):
    z = StringIO()
    traceback.print_exception(type, value, tb, file=z)
    new_displayhook("{}".format(z.getvalue()))
    z.close()
sys.excepthook = new_excepthook

# Relevant links:
# https://docs.python.org/2/library/code.html
# https://github.com/python/cpython/blob/2.7/Lib/code.py


class InteractiveSocket(code.InteractiveConsole):
    def __init__(self, rfile, wfile, locals=None):
        """
            This class actually creates the interactive session and ties it
            to the socket by reading input from the socket and writing output
            that's passed through the Print() function back into the socket.
        """
        code.InteractiveConsole.__init__(self, locals)
        self.rfile = rfile
        self.wfile = wfile

        # This is called before the banner, we can use it to print this note:
        thread_scope.displayhook("Use Print() to ensure printing to stream.")
        # print() always outputs to the stdout of the interpreter.

    def write(self, data):
        # Write data to the stream.
        if not self.wfile.closed:
            self.wfile.write(data.encode('ascii'))
            self.wfile.flush()

    def raw_input(self, prompt=""):
        # Try to read data from the stream.
        if (self.wfile.closed):
            raise EOFError("Socket closed.")

        # print the prompt.
        self.write(prompt)

        # Process the input.
        raw_value = self.rfile.readline()
        r = raw_value.rstrip()

        try:
            r = r.decode('ascii')
        except:
            pass

        # The default repl quits on control+d, control+d causes the line that
        # has been typed so far to be sent by netcat. That means that pressing
        # control+D without anything having been typed in results in a ''
        # to be read into raw_value.
        # But when '' is read we know control+d has been sent, we raise
        # EOFError to gracefully close the connection.
        if (len(raw_value) == 0):
            raise EOFError("Empty line, disconnect requested with control-D.")

        return r


class RequestPythonREPL(ss.StreamRequestHandler):
    """
        THis is the entry point for connections from the socketserver.
    """
    def handle(self):
        # Actually handle the request from socketserver, every connection is
        # handled in a different thread.

        # Create a new Print() function that outputs to the stream.
        def Print(f):
            f = str(f)
            try:
                f = bytes(f, 'ascii')
            except:
                pass

            self.wfile.write(f)
            self.wfile.write(b"\n")
            self.wfile.flush()

        # Add that function to the thread's scope.
        thread_scope.displayhook = Print
        thread_scope.rfile = self.rfile
        thread_scope.wfile = self.wfile

        # Set up the environment for the repl, this makes halt() and Print()
        # available.
        repl_scope = dict(globals(), **locals())

        # Create the console object and pass the stream's rfile and wfile.
        self.console = InteractiveSocket(self.rfile, self.wfile,
                                         locals=repl_scope)

        # All errors except SystemExit are caught inside interact(), only
        # sys.exit() is escalated, in this situation we want to close the
        # connection, not kill the server ungracefully. We have halt()
        # to do that gracefully.
        try:
            self.console.interact()
        except SystemExit:
            Print("SystemExit reached, closing the connection.")
            self.finish()


class ThreadedTCPServer(ss.ThreadingMixIn, ss.TCPServer):
    # from https://stackoverflow.com/a/18858817
    # Ensures that the socket is available for rebind immediately.
    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(self.server_address)

if __name__ == "__main__":
    # Create the server object and a thread to serve.
    server = ThreadedTCPServer(("127.0.0.1", 1337), RequestPythonREPL)
    server_thread = threading.Thread(target=server.serve_forever)

    # Exit the server thread when the main thread terminates
    server_thread.daemon = True

    # Start the server thread, which serves the RequestPythonREPL.
    server_thread.start()

    # Ensure main thread does not quit unless we want it to.
    while not should_exit:
        time.sleep(1)

    # If we reach this point we are really shutting down the server.
    print("Shutting down.")
    server.server_close()
    server.shutdown()
    server_thread.join()
    # This does not always correctly release the socket, hence SO_REUSEADDR.
