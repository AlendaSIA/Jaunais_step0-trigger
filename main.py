import json
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.get("/")
def healthcheck():
    # Pārlūks un healthchecki trāpīs šeit
    return "OK", 200

@app.post("/webhook")
def webhook():
    # Scheduler / curl trāpīs šeit
    payload = request.get_json(silent=True) or {}

    print("=== STEP0-TRIGGER: POST /webhook received ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    return jsonify({
        "status": "received",
        "route": "/webhook",
        "payload_keys": list(payload.keys())
    }), 200


# Cloud Run/production vidē parasti WSGI serveris (gunicorn) pats palaiž app
# Bet lokālam testam var palaist ar: python main.py
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
