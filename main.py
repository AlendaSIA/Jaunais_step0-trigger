from flask import Flask, request, jsonify
from runner import run_pipeline

app = Flask(__name__)

@app.get("/health")
def health():
    return jsonify({"status": "ok"})

@app.get("/")
def root():
    return jsonify({"status": "ok"})

@app.get("/steps")
def steps():
    return jsonify({
        "steps": [
            "01_load_secrets",
            "02_pick_next_doc",
            "03_fetch_sale_full",
            "04_extract_all_fields",
            "05_fetch_client_bundle",
            "06_call_worker",
            "07_debug_write_files",
            "08_finalize_state",
        ]
    })

@app.post("/run")
def run():
    payload = request.get_json(silent=True) or {}
    ctx = run_pipeline(payload)
    return jsonify(ctx)

@app.post("/debug")
def debug():
    payload = request.get_json(silent=True) or {}
    payload["_debug"] = True
    ctx = run_pipeline(payload)
    return jsonify(ctx)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
