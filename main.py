import os
from flask import Flask, jsonify, request
from runner import run_all, run_debug

app = Flask(__name__)

@app.get("/")
def health():
    return jsonify({"ok": True})

@app.post("/run")
def run():
    # pilns cikls (vēlāk: 1 dokuments end-to-end)
    ctx = run_all()
    return jsonify(ctx), 200

@app.post("/debug")
def debug():
    """
    Body piemēri:
      {"mode":"step","step":"00_read_state"}
      {"mode":"until","until":"00_read_state"}
    """
    payload = request.get_json(silent=True) or {}
    ctx = run_debug(payload)
    return jsonify(ctx), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
