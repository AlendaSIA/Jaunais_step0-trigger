import os
import json
import base64
import requests
import xml.etree.ElementTree as ET

REPO = "AlendaSIA/Jaunais_step0-trigger"


def _github_get_sha(token: str, path: str):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    r = requests.get(url, headers={"Authorization": f"token {token}"}, timeout=20)
    if r.status_code == 200:
        return (r.json() or {}).get("sha")
    return None


def _github_put_file(token: str, path: str, content_bytes: bytes, message: str):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content_bytes).decode("utf-8"),
    }

    sha = _github_get_sha(token, path)
    if sha:
        payload["sha"] = sha

    r = requests.put(
        url,
        headers={"Authorization": f"token {token}"},
        json=payload,
        timeout=30,
    )
    return r.status_code, (r.text or "")[:500]


def _findtext(root: ET.Element, path: str):
    el = root.find(path)
    if el is None or el.text is None:
        return None
    t = el.text.strip()
    return t if t != "" else None


def run(ctx: dict):
    ctx["step_04_version"] = "v2026-02-05-01"

    doc_id = ctx.get("next_document_id")
    xml_text = ctx.get("paytraq_full_xml")

    if not doc_id:
        ctx["error"] = "Missing ctx.next_document_id (run step 02/03 first)"
        return ctx
    if not xml_text:
        ctx["error"] = "Missing ctx.paytraq_full_xml (run step 03 first)"
        return ctx

    try:
        root = ET.fromstring(xml_text)
    except Exception as e:
        ctx["error"] = f"XML parse error: {type(e).__name__}"
        ctx["xml_snippet"] = (xml_text or "")[:400]
        return ctx

    # pamata dokumenta dati
    data = {
        "document_id": doc_id,
        "document_date": _findtext(root, "./Header/Document/DocumentDate"),
        "document_ref": _findtext(root, "./Header/Document/DocumentRef"),
        "document_status": _findtext(root, "./Header/Document/DocumentStatus"),
        "sale_type": _findtext(root, "./Header/SaleType"),
        "operation": _findtext(root, "./Header/Operation"),
        "currency": _findtext(root, "./Header/Currency"),
        "total": _findtext(root, "./Header/Total"),
        "amount_due": _findtext(root, "./Header/AmountDue"),
        "issued_by": _findtext(root, "./Header/IssuedBy"),
        "comment": _findtext(root, "./Header/Comment"),

        # klients (no sale XML)
        "client_id": _findtext(root, "./Header/Document/Client/ClientID"),
        "client_name": _findtext(root, "./Header/Document/Client/ClientName"),

        # piegāde (ja ir)
        "ship_to": _findtext(root, "./Header/ShippingData/ShippingAddress/ShipTo"),
        "ship_address": _findtext(root, "./Header/ShippingData/ShippingAddress/Address"),
        "ship_zip": _findtext(root, "./Header/ShippingData/ShippingAddress/Zip"),
        "ship_country": _findtext(root, "./Header/ShippingData/ShippingAddress/Country"),
    }

    ctx["client_data"] = data

    # Debug: saglabājam GitHub kā JSON + HTML, ko vari atvērt pārlūkā
    gh_token = os.getenv("GITHUB_TOKEN")
    if gh_token:
        json_path = f"state/debug/client_{doc_id}.json"
        html_path = f"state/debug/client_{doc_id}.html"

        pretty = json.dumps(data, ensure_ascii=False, indent=2)
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>client_{doc_id}</title></head><body>"
            f"<h1>client_{doc_id}</h1><pre>{pretty}</pre></body></html>"
        )

        st1, sn1 = _github_put_file(gh_token, json_path, pretty.encode("utf-8"), f"debug: client json {doc_id}")
        st2, sn2 = _github_put_file(gh_token, html_path, html.encode("utf-8"), f"debug: client html {doc_id}")

        ctx["github_client_json_path"] = json_path
        ctx["github_client_json_status"] = st1
        if st1 not in (200, 201):
            ctx["github_client_json_error_snippet"] = sn1

        ctx["github_client_html_path"] = html_path
        ctx["github_client_html_status"] = st2
        if st2 not in (200, 201):
            ctx["github_client_html_error_snippet"] = sn2

    return ctx
