import os
import base64
import requests
import xml.etree.ElementTree as ET
from flask import Flask, jsonify

app = Flask(__name__)

REPO = "AlendaSIA/Jaunais_step0-trigger"
STATE_PATH = "state/last_processed_id.txt"

def read_state():
    token = os.getenv("GITHUB_TOKEN")
    url = f"https://api.github.com/repos/{REPO}/contents/{STATE_PATH}"

    r = requests.get(url, headers={"Authorization": f"token {token}"})
    data = r.json()

    content = base64.b64decode(data["content"]).decode().strip()
    return int(content)

def fetch_sales():
    key = os.getenv("PAYTRAQ_API_KEY")
    token = os.getenv("PAYTRAQ_API_TOKEN")

    url = f"https://go.paytraq.com/api/sales?APIToken={token}&APIKey={key}"
    r = requests.get(url, timeout=30)

    root = ET.fromstring(r.text)
    ids = [int(e.text) for e in root.findall(".//DocumentID") if e.text]
    return sorted(ids)

@app.get("/")
@app.post("/run")
def run():
    last_id = read_state()
    ids = fetch_sales()

    next_id = None
    for i in ids:
        if i > last_id:
            next_id = i
            break

    return jsonify({
        "last_processed_id": last_id,
        "next_document_id": next_id,
        "available_ids": ids[:5]
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
