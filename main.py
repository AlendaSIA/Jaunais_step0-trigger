from flask import Flask, request, jsonify
from runner import run_pipeline, list_steps

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.get("/")
def root():
    return jsonify({"ok": True}), 200


@app.get("/steps")
def steps():
    return jsonify({"steps": list_steps()}), 200


@app.post("/run")
def run():
    payload = request.get_json(silent=True) or {}
    ctx = run_pipeline(payload)
    return jsonify(ctx), 200


@app.post("/debug")
def debug():
    payload = request.get_json(silent=True) or {}
    # obligāts: payload["step"]
    if not payload.get("step"):
        return jsonify({"status": "error", "error": "Missing 'step' in payload"}), 200
    payload["_debug"] = True
    ctx = run_pipeline(payload)
    return jsonify(ctx), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
