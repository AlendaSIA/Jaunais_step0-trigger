import os
import requests
import xml.etree.ElementTree as ET

PAYTRAQ_BASE_URL = "https://go.paytraq.com"

def run(ctx: dict):
    key = os.getenv("PAYTRAQ_API_KEY")
    token = os.getenv("PAYTRAQ_API_TOKEN")

    # Debug: tikai vai ir/ nav, nevis vērtības
    ctx["has_paytraq_key"] = bool(key)
    ctx["has_paytraq_token"] = bool(token)

    if not key or not token:
        ctx["error"] = "Missing env: PAYTRAQ_API_KEY or PAYTRAQ_API_TOKEN"
        return ctx

    url = f"{PAYTRAQ_BASE_URL}/api/sales"
    r = requests.get(
        url,
        headers={
            "X-Consumer-Key": key,
            "X-Access-Token": token,
        },
        timeout=30,
    )

    ctx["paytraq_sales_status_code"] = r.status_code
    if r.status_code != 200:
        ctx["error"] = "PayTraq /api/sales returned non-200"
        ctx["paytraq_body_snippet"] = r.text[:500]
        return ctx

    root = ET.fromstring(r.text)
    ids = []
    for el in root.iter():
        if el.tag.lower() == "documentid" and el.text:
            t = el.text.strip()
            if t.isdigit():
                ids.append(int(t))

    ids = sorted(set(ids))
    ctx["sales_count"] = len(ids)
    ctx["sales_ids"] = ids[-20:]
    return ctx
