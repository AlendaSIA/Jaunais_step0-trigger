import os
from flask import Flask, request, jsonify

app = Flask(__name__)

# Neliec ārā vērtības, tikai to, vai mainīgie eksistē
SAFE_ENV_KEYS = [
    "PAYTRAQ_API_KEY",
    "PAYTRAQ_API_TOKEN",
]

@app.get("/")
def healthcheck():
    return "OK", 200

@app.post("/")
def webhook():
    payload = request.get_json(silent=True)

    print("=== STEP0-TRIGGER: POST received ===")
    print(f"Content-Type: {request.headers.get('Content-Type')}")
    print(f"Has JSON body: {payload is not None}")

    # Parādām tikai to, vai secrets ir piesaistīti (True/False), ne vērtības
    env_presence = {k: bool(os.environ.get(k)) for k in SAFE_ENV_KEYS}
    print(f"Env presence (no values): {env_presence}")

    # Parādām top-level atslēgas (ja ir JSON), lai redzi ko atnāca
    if isinstance(payload, dict):
        print(f"JSON keys: {list(payload.keys())}")
    else:
        print("JSON keys: [] (no JSON object)")

    return jsonify({"status": "received", "env_presence": env_presence}), 200


if __name__ == "__main__":
    # Cloud Run lieto PORT env
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
