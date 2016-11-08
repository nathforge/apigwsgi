import sys
import unittest

from apigwsgi import Handler

class DummyContext(object):
    pass

class Strings(list):
    def __init__(self, items, set_close_count=None):
        super(Strings, self).__init__(items)

        self.set_close_count = set_close_count
        if self.set_close_count:
            self.close = self._close

    def _close(self):
        obj, attr = self.set_close_count
        setattr(obj, attr, getattr(obj, attr) + 1)

class TestCase(unittest.TestCase):
    def test_kitchen_sink(self):
        """
        Test a lot of stuff - subsequent tests can be more focused.
        """

        def app(environ, start_response):
            app.environ = environ
            start_response("200 Ok", [("Content-Type", "text/plain")])
            return Strings(["Hello world"], set_close_count=(app, "close_count"))

        event = {
            "httpMethod": "POST",
            "path": "/",
            "queryStringParameters": {
                "x": "y"
            },
            "headers": {
                "Host": "localhost",
                "Content-Type": "text/plain",
                "Content-Length": "2"
            },
            "body": "Hi"
        }
        context = DummyContext()

        app.close_count = 0
        result = Handler(app)(event, context)

        self.assertEqual(result, {
            "statusCode": 200,
            "headers": {
                "Content-Type": "text/plain"
            },
            "body": "Hello world"
        })

        wsgi_input = app.environ.pop("wsgi.input")
        self.assertEqual(app.environ, {
            "apigwsgi.event": event,
            "apigwsgi.context": context,
            "HTTP_HOST": "localhost",
            "HTTP_CONTENT_TYPE": "text/plain",
            "HTTP_CONTENT_LENGTH": "2",
            "REQUEST_METHOD": "POST",
            "SCRIPT_NAME": "",
            "PATH_INFO": "/",
            "QUERY_STRING": "x=y",
            "CONTENT_TYPE": "text/plain",
            "CONTENT_LENGTH": "2",
            "SERVER_NAME": "localhost",
            "SERVER_PORT": "443",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "HTTPS": "on",
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": "https",
            "wsgi.errors": sys.stderr,
            "wsgi.multithread": False,
            "wsgi.multiprocess": True,
            "wsgi.run_once": False
        })
        self.assertEqual(wsgi_input.read(), "Hi")
        self.assertEqual(app.close_count, 1)

    def test_close_is_called_on_result_if_available(self):
        """
        Test `close` is called on the WSGI result if available.
        """

        def app(environ, start_response):
            start_response("200 Ok", [("Content-Type", "text/plain")])
            app.result = Strings(["Hello world"], set_close_count=(app, "close_count"))
            return app.result

        event = {
            "httpMethod": "POST",
            "path": "/",
            "queryStringParameters": None,
            "headers": {
                "Host": "localhost",
            },
            "body": None
        }
        context = DummyContext()

        app.close_count = 0
        result = Handler(app)(event, context)
        self.assertTrue(hasattr(app.result, "close"))
        self.assertEqual(app.close_count, 1)

    def test_close_isnt_called_on_result_if_unavailable(self):
        """
        Test `close` *isn't* called on the WSGI result if it doesn't have one.
        """

        def app(environ, start_response):
            start_response("200 Ok", [("Content-Type", "text/plain")])
            app.result = Strings(["Hello world"], set_close_count=None)
            return app.result

        event = {
            "httpMethod": "POST",
            "path": "/",
            "queryStringParameters": None,
            "headers": {
                "Host": "localhost",
            },
            "body": None
        }
        context = DummyContext()

        result = Handler(app)(event, context)
        self.assertFalse(hasattr(app.result, "close"))

    def test_no_headers_sent(self):
        """
        Test a response without headers results in error.
        """

        def app(environ, start_response):
            yield "Hello world"

        event = {
            "httpMethod": "POST",
            "path": "/",
            "queryStringParameters": None,
            "headers": {
                "Host": "localhost",
            },
            "body": None
        }
        context = DummyContext()

        with self.assertRaisesRegexp(Exception, "Headers must be sent before body"):
            Handler(app)(event, context)

    def test_multiple_headers_sent(self):
        """
        Test a response with multiple sets of headers results in error.
        """

        def app(environ, start_response):
            start_response("200 Ok", [("Content-Type", "text/plain")])
            start_response("201 Changed My Mind", [("Content-Type", "text/plain")])
            yield "Hello world"

        event = {
            "httpMethod": "POST",
            "path": "/",
            "queryStringParameters": None,
            "headers": {
                "Host": "localhost",
            },
            "body": None
        }
        context = DummyContext()

        with self.assertRaisesRegexp(Exception, "Second call to start_response must include exc_info"):
            Handler(app)(event, context)

    def test_second_set_of_headers_sent_with_exc_info(self):
        """
        Test headers can be changed if exc_info is set, and the response body
        has not started.
        """

        def app(environ, start_response):
            start_response("200 Ok", [("Content-Type", "text/plain")])
            try:
                raise Exception()
            except Exception:
                start_response("500 Oh no", [("Content-Type", "text/html")], exc_info=sys.exc_info())
                yield "<h1>Error</h1>"

        event = {
            "httpMethod": "POST",
            "path": "/",
            "queryStringParameters": None,
            "headers": {
                "Host": "localhost",
            },
            "body": None
        }
        context = DummyContext()

        result = Handler(app)(event, context)
        self.assertEqual(result, {
            "statusCode": 500,
            "headers": {
                "Content-Type": "text/html"
            },
            "body": "<h1>Error</h1>"
        })

    def test_exc_info_is_reraised_if_headers_already_sent(self):
        """
        Test exc_info is reraised if headers have already been sent as a result
        of yielding body data.
        """

        def app(environ, start_response):
            start_response("200 Ok", [("Content-Type", "text/plain")])
            yield "Everything's fine"
            try:
                raise Exception("Exceptional")
            except Exception:
                start_response("500 Oh no", [("Content-Type", "text/html")], exc_info=sys.exc_info())
                yield "<h1>Error</h1>"

        event = {
            "httpMethod": "POST",
            "path": "/",
            "queryStringParameters": None,
            "headers": {
                "Host": "localhost",
            },
            "body": None
        }
        context = DummyContext()

        with self.assertRaisesRegexp(Exception, "Exceptional"):
            Handler(app)(event, context)

    def test_uncaught_wsgi_exception(self):
        """
        Check uncaught WSGI exceptions are propagated.
        Ensures exception details appear in CloudWatch, and that API Gateway
        does the right thing.
        """

        def app(environ, start_response):
            raise Exception("Oops")

        event = {
            "httpMethod": "POST",
            "path": "/",
            "queryStringParameters": {
                "x": "y"
            },
            "headers": {
                "Host": "localhost",
                "Content-Type": "text/plain",
                "Content-Length": "2"
            },
            "body": "Hi"
        }
        context = DummyContext()

        with self.assertRaisesRegexp(Exception, "Oops"):
            result = Handler(app)(event, context)

        # TODO: Test exc_info is logged somewhere

    def test_TODO_exc_info(self):
        pass
