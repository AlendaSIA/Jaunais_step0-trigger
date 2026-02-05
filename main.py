import os
from flask import Flask, jsonify, request
import runner

app = Flask(__name__)

@app.get("/")
def health():
    return jsonify({"ok": True})

@app.get("/steps")
def steps():
    return jsonify({
        "steps": [name for name, _ in runner.STEPS]
    }), 200

@app.post("/run")
def run():
    ctx = runner.run_all()
    return jsonify(ctx), 200

@app.post("/debug")
def debug():
    payload = request.get_json(silent=True) or {}
    ctx = runner.run_debug(payload)
    return jsonify(ctx), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
