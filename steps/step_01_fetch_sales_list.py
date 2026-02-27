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
    # If user forces a specific document, don't waste a PayTraq list call.
    override_id = ctx.get("document_id") or ctx.get("override_document_id") or ctx.get("force_document_id")
    if override_id is not None:
        ctx["sales_count"] = 0
        ctx["sales_ids"] = []
        ctx["sales_ids_last20"] = []
        ctx["paytraq_sales_skipped"] = True
        return ctx

    key = os.getenv("PAYTRAQ_API_KEY")
    token = os.getenv("PAYTRAQ_API_TOKEN")

    ctx["has_paytraq_key"] = bool(key)
    ctx["has_paytraq_token"] = bool(token)

    if not key or not token:
        ctx["error"] = "Missing env: PAYTRAQ_API_KEY or PAYTRAQ_API_TOKEN"
        return ctx

    # We want OLDEST -> NEWEST processing by DocumentID.
    # PayTraq supports incremental listing with id_after, which also orders by ID ascending.
    last_processed_id = ctx.get("last_processed_id")
    try:
        last_processed_id = int(last_processed_id) if last_processed_id is not None else 0
    except Exception:
        last_processed_id = 0

    date_from = ctx.get("date_from") or os.getenv("PAYTRAQ_DATE_FROM")
    params = {
        "APIKey": key,
        "APIToken": token,
        "id_after": last_processed_id,
        "page": 0,
    }
    if date_from:
        params["date_from"] = str(date_from)

    url = f"{PAYTRAQ_BASE_URL}/api/sales"
    r = requests.get(url, params=params, timeout=30)

    ctx["paytraq_auth_used"] = "query_id_after"
    ctx["paytraq_sales_params"] = {k: v for k, v in params.items() if k not in ("APIKey", "APIToken")}
    ctx["paytraq_sales_status_code"] = r.status_code

    if r.status_code != 200:
        ctx["error"] = "PayTraq /api/sales returned non-200"
        ctx["paytraq_body_snippet"] = (r.text or "")[:500]
        return ctx

    ids = _extract_document_ids(r.text)
    ctx["sales_count"] = len(ids)
    ctx["sales_ids"] = ids               # pilnais saraksts 02 solim (ID asc)
    ctx["sales_ids_last20"] = ids[-20:]  # debugam
    return ctx
