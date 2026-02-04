import os
import re
from datetime import datetime
import requests
from flask import Flask, Response

app = Flask(__name__)

PAYTRAQ_BASE = "https://go.paytraq.com/api"
API_KEY = os.environ.get("PAYTRAQ_API_KEY")
API_TOKEN = os.environ.get("PAYTRAQ_API_TOKEN")

def paytraq_get_sales(params: dict) -> str:
    r = requests.get(
        f"{PAYTRAQ_BASE}/sales",
        headers={
            "APIKey": API_KEY,
            "APIToken": API_TOKEN,
        },
        params=params,
        timeout=30,
    )
    r.raise_for_status()
    return r.text  # PayTraq atdod XML

def extract_document_ids(xml: str) -> list[int]:
    return [int(x) for x in re.findall(r"<DocumentID>(\d+)</DocumentID>", xml)]

def today_ymd() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")

@app.get("/")
def health():
    return "OK"

@app.post("/trigger")
def trigger():
    if not API_KEY or not API_TOKEN:
        return Response("Missing PAYTRAQ_API_KEY or PAYTRAQ_API_TOKEN\n", status=500)

    today = today_ymd()

    xml = paytraq_get_sales({
        "date_from": today,
        "date_till": today,
    })

    ids = extract_document_ids(xml)

    if not ids:
        return Response("No documents today\n", mimetype="text/plain")

    ids.sort()

    lines = ["Today's PayTraq document IDs:"]
    lines.extend(str(i) for i in ids)

    return Response("\n".join(lines) + "\n", mimetype="text/plain")

