import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))

from flask import Flask, request

from src.functions.gemini_tts_batch.functions.main import handle_tts_batch

app = Flask(__name__)


@app.route("/", methods=["POST", "OPTIONS"])
def index():
    return handle_tts_batch(request)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
