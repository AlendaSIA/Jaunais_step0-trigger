import os
import requests
import xml.etree.ElementTree as ET
from flask import Flask, jsonify

app = Flask(__name__)

@app.get("/")
def ok():
    return "OK", 200

@app.post("/run")
def run():
    key = os.getenv("PAYTRAQ_API_KEY")
    token = os.getenv("PAYTRAQ_API_TOKEN")

    if not key or not token:
        return jsonify({"error": "Missing PayTraq credentials"}), 500

    url = f"https://go.paytraq.com/api/sales?APIToken={token}&APIKey={key}"
    r = requests.get(url, timeout=30)

    root = ET.fromstring(r.text)
    ids = [e.text for e in root.findall(".//DocumentID") if e.text]
    last_id = ids[-1] if ids else None

    return jsonify({
        "http_status": r.status_code,
        "document_id": last_id,
        "count": len(ids),
        "preview": r.text[:300]
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
