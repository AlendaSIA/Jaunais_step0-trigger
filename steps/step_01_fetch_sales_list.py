import os
import requests

PAYTRAQ_BASE_URL = "https://go.paytraq.com"

def run(ctx: dict):
    key = os.getenv("PAYTRAQ_API_KEY")
    token = os.getenv("PAYTRAQ_API_TOKEN")

    ctx["has_paytraq_key"] = bool(key)
    ctx["has_paytraq_token"] = bool(token)

    if not key or not token:
        ctx["error"] = "Missing env: PAYTRAQ_API_KEY or PAYTRAQ_API_TOKEN"
        return ctx

    url = f"{PAYTRAQ_BASE_URL}/api/sales"

    attempts = [
        ("query_normal",  {"params": {"APIKey": key,   "APIToken": token}}),
        ("query_swapped", {"params": {"APIKey": token, "APIToken": key}}),
        ("query_case_alt", {"params": {"APIKEY": key, "APITOKEN": token}}),
    ]

    last_text = ""
    for name, kwargs in attempts:
        r = requests.get(url, timeout=30, **kwargs)
        ctx["paytraq_auth_used"] = name
        ctx["paytraq_sales_status_code"] = r.status_code
        last_text = r.text or ""
        if r.status_code == 200:
            ctx["ok"] = True
            return ctx

    ctx["error"] = "PayTraq /api/sales returned non-200"
    ctx["paytraq_body_snippet"] = last_text[:500]
    return ctx
