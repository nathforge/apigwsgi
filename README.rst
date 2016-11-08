APIG WSGI
=========

Makes Python WSGI apps compatible with AWS’ API Gateway proxy resources.

Example
-------

.. code:: python

    from flask import Flask
    import apigwsgi

    app = Flask(__name__)

    @app.route("/")
    def index():
        return "Hello from Flask!"

    handler = apigwsgi.Handler(app.wsgi_app)

Full example
------------

Full example including deployment scripts can be found in the
``examples`` directory.

To deploy:

.. code:: shell

    $ pip install boto3
    $ examples/flask_handler/bin/deploy
    [...]
    Uploaded Flask example to https://xxxxx.execute-api.us-east-1.amazonaws.com/live/

When you’re done, remove it with:

.. code:: shell

    $ examples/flask_handler/bin/destroy

Limitations
-----------

API Gateway doesn’t currently support binary responses, and will fail if
your application sends non-unicode data.

See also
--------

-  `API Gateway proxy resource docs`_
-  `WSGI spec`_

.. _API Gateway proxy resource docs: https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-set-up-simple-proxy.html#api-gateway-proxy-resource?icmpid=docs_apigateway_console
.. _WSGI spec: https://www.python.org/dev/peps/pep-3333/
