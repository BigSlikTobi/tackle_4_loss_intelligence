import os
import sys

# Add the project root to the python path so imports work
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))

from flask import Flask, request
from src.functions.youtube_search.functions.main import youtube_search_http

app = Flask(__name__)


@app.route("/", methods=["POST", "OPTIONS"])
def index():
    return youtube_search_http(request)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
