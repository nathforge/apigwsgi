from flask import Flask, render_template, request

app = Flask(__name__)

# Catch-all URL, see <http://flask.pocoo.org/snippets/57/>
@app.route("/", defaults={"path": ""}, methods=["HEAD", "GET", "POST", "PUT", "DELETE"])
@app.route("/<path:path>", methods=["HEAD", "GET", "POST", "PUT", "DELETE"])
def index(path):
    return render_template("index.html", request=request)

# Add Lambda support
import apigwsgi
lambda_handler = apigwsgi.Handler(app)

# Run a debug server if called on the command-line
if __name__ == "__main__":
    app.run(debug=True)
