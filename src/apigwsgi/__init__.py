"""
Makes Python WSGI apps compatible with AWS' API Gateway proxy resources.
"""

import cStringIO
import re
import sys
import urllib

class Handler(object):
    """
    AWS Lambda handler. Adapts API Gateway Proxy resources to WSGI
    requests/responses.
    """

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, event, context):
        bytestrings = []

        # "The environ parameter is a dictionary object, containing
        #  CGI-style environment variables. This object must be a builtin
        #  Python dictionary (not a subclass, UserDict or other dictionary
        #  emulation), and the application is allowed to modify the dictionary
        #  in any way it desires. The dictionary must also include certain
        #  WSGI-required variables (described in a later section), and may also
        #  include server-specific extension variables, named according to a
        #  convention that will be described below."
        environ = self.get_wsgi_environ(event, context)

        # "The start_response callable must return a write(body_data) callable
        #  that takes one positional parameter: a bytestring to be written as
        #  part of the HTTP response body. (Note: the write() callable is
        #  provided only to support certain existing frameworks' imperative
        #  output APIs; it should not be used by new applications or frameworks
        #  if it can be avoided."
        start_response = WSGIStartResponse(write=bytestrings.append)

        # "The application object must accept two positional arguments. [...]
        #  A server or gateway must invoke the application object using
        #  positional (not keyword) arguments."
        # "When called by the server, the application object must return an
        #  iterable yielding zero or more bytestrings."
        result = self.wsgi_app(environ, start_response)
        try:
            for bytestring in result:
                # "Note: the application must invoke the start_response()
                #  callable before the iterable yields its first body
                #  bytestring, so that the server can send the headers before
                #  any body content. However, this invocation may be performed
                #  by the iterable's first iteration, so servers must not
                #  assume that start_response() has been called before they
                #  begin iterating over the iterable."
                if not start_response.headers_set:
                    raise Exception("Headers must be sent before body")

                bytestrings.append(bytestring)
                start_response.body_started = True
        finally:
            # "If the iterable returned by the application has a close() method,
            #  the server or gateway must call that method upon completion of
            #  the current request, whether the request was completed normally,
            #  or terminated early due to an application error during iteration
            #  or an early disconnect of the browser."
            if hasattr(result, "close"):
                result.close()

        if not start_response.headers_set:
            raise Exception("Application didn't send headers")

        return {
            "statusCode": start_response.status_code,
            "headers": dict(start_response.response_headers),
            "body": "".join(bytestrings)
        }

    def get_wsgi_environ(self, event, context):
        # Docs:
        # * Environ variables: <https://www.python.org/dev/peps/pep-3333/#environ-variables>
        # * Event format: <https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-set-up-simple-proxy.html#api-gateway-simple-proxy-for-lambda-input-format>

        environ = {}

        # "the environ dictionary may [...] contain server-defined variables.
        #  These variables should be named using only lower-case letters,
        #  numbers, dots, and underscores, and should be prefixed with a name
        #  that is unique to the defining server or gateway. For example,
        #  mod_python might define variables with names like
        #  mod_python.some_variable."
        environ["apigwsgi.event"] = event
        environ["apigwsgi.context"] = context

        # Start by populating the variables from HTTP headers. This has
        # the side effect of normalising header case, which will be useful
        # further down the function.
        #
        # "Variables corresponding to the client-supplied HTTP request headers
        #  (i.e., variables whose names begin with "HTTP_" ). The presence or
        #  absence of these variables should correspond with the presence or
        #  absence of the appropriate HTTP header in the request."
        environ.update({
            "HTTP_{}".format(key.upper().replace("-", "_")): value
            for key, value in (event["headers"] or {}).iteritems()
        })

        # Construct a Content-Length header. API Gateway doesn't seem to forward
        # this.
        environ["HTTP_CONTENT_LENGTH"] = len(event["body"] or "")

        # "The HTTP request method, such as "GET" or "POST" . This cannot ever
        #  be an empty string, and so is always required."
        environ["REQUEST_METHOD"] = event["httpMethod"]

        # "The initial portion of the request URL's "path" that corresponds to
        #  the application object, so that the application knows its virtual
        #  "location". This may be an empty string, if the application
        #  corresponds to the "root" of the server."
        environ["SCRIPT_NAME"] = ""

        # "The remainder of the request URL's "path", designating the virtual
        #  "location" of the request's target within the application. This may
        #  be an empty string, if the request URL targets the application root
        #  and does not have a trailing slash."
        environ["PATH_INFO"] = event["path"]

        # "The portion of the request URL that follows the "?" , if any. May be
        #  empty or absent."
        environ["QUERY_STRING"] = urllib.urlencode(event["queryStringParameters"] or {})

        # "The contents of any Content-Type fields in the HTTP request. May be
        #  empty or absent."
        if "HTTP_CONTENT_TYPE" in environ:
            environ["CONTENT_TYPE"] = environ["HTTP_CONTENT_TYPE"]

        # "The contents of any Content-Length fields in the HTTP request. May be
        #  empty or absent."
        environ["CONTENT_LENGTH"] = environ["HTTP_CONTENT_LENGTH"]

        # "When combined with SCRIPT_NAME and PATH_INFO , these two strings can
        #  be used to complete the URL. Note, however, that HTTP_HOST , if
        #  present, should be used in preference to SERVER_NAME for
        #  reconstructing the request URL. See the URL Reconstruction section
        #  below for more detail. SERVER_NAME and SERVER_PORT can never be empty
        #  strings, and so are always required."
        environ["SERVER_NAME"] = environ["HTTP_HOST"]
        environ["SERVER_PORT"] = environ.get("HTTP_X_FORWARDED_PORT") or {
            "https": "443",
            "http": "80"
        }[environ.get("HTTP_X_FORWARDED_PROTO", "https")]

        # "The version of the protocol the client used to send the request.
        #  Typically this will be something like "HTTP/1.0" or "HTTP/1.1" and
        #  may be used by the application to determine how to treat any HTTP
        #  request headers."
        environ["SERVER_PROTOCOL"] = "HTTP/1.1"

        # "if SSL is in use, the server or gateway should also provide as many
        #  of the Apache SSL environment variables [5] as are applicable, such
        #  as HTTPS=on and SSL_PROTOCOL"
        if environ.get("HTTP_X_FORWARDED_PROTO", "https") == "https":
            environ["HTTPS"] = "on"

        # "The tuple (1, 0) , representing WSGI version 1.0."
        environ["wsgi.version"] = (1, 0)

        # "A string representing the "scheme" portion of the URL at which the
        #  application is being invoked. Normally, this will have the value
        #  "http" or "https" , as appropriate."
        environ["wsgi.url_scheme"] = environ.get("HTTP_X_FORWARDED_PROTO", "https")

        # "An input stream (file-like object) from which the HTTP request body
        #  bytes can be read."
        environ["wsgi.input"] = cStringIO.StringIO(event["body"])

        # "An output stream (file-like object) to which error output can be
        #  written, for the purpose of recording program or other errors in a
        #  standardized and possibly centralized location. This should be a
        #  "text mode" stream; i.e., applications should use "\n" as a line
        #  ending [...]"
        environ["wsgi.errors"] = sys.stderr

        # "This value should evaluate true if the application object may be
        #  simultaneously invoked by another thread in the same process, and
        #  should evaluate false otherwise."
        environ["wsgi.multithread"] = False

        # "This value should evaluate true if an equivalent application object
        #  may be simultaneously invoked by another process, and should evaluate
        #  false otherwise."
        environ["wsgi.multiprocess"] = True

        # "This value should evaluate true if the server or gateway expects
        #  (but does not guarantee!) that the application will only be invoked
        #  this one time during the life of its containing process. Normally,
        #  this will only be true for a gateway based on CGI (or something
        #  similar)."
        environ["wsgi.run_once"] = False

        return environ

class WSGIStartResponse(object):
    def __init__(self, write):
        self.write = write

        self.headers_set = False
        self.body_started = False

        self.status = None
        self.response_headers = None
        self.exc_info = None

    def __call__(self, status, response_headers, exc_info=None):
        # "The start_response parameter is a callable accepting two required
        #  positional arguments, and one optional argument.  For the sake of
        #  illustration, we have named these arguments status, response_headers,
        #  and exc_info [...]"
        # "The status parameter is a status string of the form "999 Message here",
        #  and response_headers is a list of (header_name, header_value) tuples
        #  describing the HTTP response header. The optional exc_info parameter is
        #  described below in the sections on The start_response() Callable and
        #  Error Handling . It is used only when the application has trapped an
        #  error and is attempting to display an error message to the browser."

        # "The application may call start_response more than once, if and only
        #  if the exc_info argument is provided. More precisely, it is a fatal
        #  error to call start_response without the exc_info argument if
        #  start_response has already been called within the current invocation
        #  of the application. This includes the case where the first call to
        #  start_response raised an error."
        if self.headers_set and not exc_info:
            raise Exception("Second call to start_response must include exc_info")

        self.headers_set = True

        # "if exc_info is provided, and the HTTP headers have already been sent,
        #  start_response must raise an error, and should raise the exc_info
        #  tuple."
        if exc_info and self.body_started:
            raise exc_info[0], exc_info[1], exc_info[2]

        # "The status argument is an HTTP "status" string like "200 OK" or
        #  "404 Not Found" . That is, it is a string consisting of a
        #  Status-Code and a Reason-Phrase, in that order and separated by a
        #  single space, with no surrounding whitespace or other characters.
        #  [...] The string must not contain control characters, and must not
        #  be terminated with a carriage return, linefeed, or combination
        #  thereof."
        match = re.search(r"^(\d+) .+$", status)
        if not match:
            raise Exception("Application sent malformed status line {!r}".format(status))
        else:
            self.status_code = int(match.group(1))

        # "The response_headers argument is a list of (header_name, header_value)
        #  tuples. It must be a Python list; i.e. type(response_headers) is
        #  ListType , and the server may change its contents in any way it
        #  desires. Each header_name must be a valid HTTP header field-name
        #  (as defined by RFC 2616 , Section 4.2), without a trailing colon or
        #  other punctuation."
        # "Each header_value must not include any control characters, including
        #  carriage returns or linefeeds, either embedded or at the end. (These
        #  requirements are to minimize the complexity of any parsing that must
        #  be performed by servers, gateways, and intermediate response
        #  processors that need to inspect or modify response headers.)"
        self.response_headers = response_headers

        # "The exc_info argument, if supplied, must be a Python sys.exc_info()
        #  tuple."
        self.exc_info = exc_info

        # "The start_response callable must return a write(body_data) callable
        #  that takes one positional parameter: a bytestring to be written as
        #  part of the HTTP response body. (Note: the write() callable is
        #  provided only to support certain existing frameworks' imperative
        #  output APIs; it should not be used by new applications or frameworks
        #  if it can be avoided."
        return self.write
