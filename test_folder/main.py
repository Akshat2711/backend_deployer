from flask import Flask

app = Flask(__name__)


@app.route("/")
def home():
    return {
        "message": "Server Rent Alpha working"
    }


@app.route("/health")
def health():
    return {
        "status": "ok"
    }


@app.route("/version")
def version():
    return {
        "version": "1.0.0",
        "name": "Server Rent Alpha"
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)