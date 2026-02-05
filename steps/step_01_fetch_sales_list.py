import os
import requests
import xml.etree.ElementTree as ET

PAYTRAQ_BASE_URL = "https://go.paytraq.com"

def _extract_document_ids(xml_text: str):
    root = ET.fromstring(xml_text)
    ids = []
    for el in root.iter():
        if el.tag.lower() == "documentid" and el.text:
            t = el.text.strip()
            if t.isdigit():
                ids.append(int(t))
    return sorted(set(ids))

def run(ctx: dict):
    key = os.getenv("PAYTRAQ_API_KEY")
    token = os.getenv("PAYTRAQ_API_TOKEN")

    ctx["has_paytraq_key"] = bool(key)
    ctx["has_paytraq_token"] = bool(token)

    if not key or not token:
        ctx["error"] = "Missing env: PAYTRAQ_API_KEY or PAYTRAQ_API_TOKEN"
        return ctx

    url = f"{PAYTRAQ_BASE_URL}/api/sales"
    r = requests.get(url, params={"APIKey": key, "APIToken": token}, timeout=30)

    ctx["paytraq_auth_used"] = "query_normal"
    ctx["paytraq_sales_status_code"] = r.status_code

    if r.status_code != 200:
        ctx["error"] = "PayTraq /api/sales returned non-200"
        ctx["paytraq_body_snippet"] = (r.text or "")[:500]
        return ctx

    ids = _extract_document_ids(r.text)
    ctx["sales_count"] = len(ids)
    ctx["sales_ids"] = ids          # pilnais saraksts 02 solim
    ctx["sales_ids_last20"] = ids[-20:]  # tikai debugam
    return ctx
