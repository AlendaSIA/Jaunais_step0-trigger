import os
import json
import base64
import requests
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Tuple, Optional

REPO = "AlendaSIA/Jaunais_step0-trigger"
PAYTRAQ_BASE_URL = os.getenv("PAYTRAQ_BASE_URL", "https://go.paytraq.com")


# --------------------------
# GitHub helpers
# --------------------------
def _github_get_sha(token: str, path: str) -> Optional[str]:
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    r = requests.get(url, headers={"Authorization": f"token {token}"}, timeout=20)
    if r.status_code == 200:
        return (r.json() or {}).get("sha")
    return None


def _github_put_file(token: str, path: str, content_bytes: bytes, message: str) -> Tuple[int, str]:
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


# --------------------------
# PayTraq helpers
# --------------------------
def _paytraq_get_xml(path: str, api_key: str, api_token: str) -> Tuple[int, str, str]:
    """
    Returns: (status_code, body_text, auth_used)
    """
    url = f"{PAYTRAQ_BASE_URL}{path}"
    # 1) query params (tas jums jau strādā)
    params = {"APIKey": api_key, "APIToken": api_token}
    r = requests.get(url, params=params, timeout=30)
    if r.status_code == 200:
        return r.status_code, r.text, "query_normal"

    # 2) fallback: headers (dažreiz PayTraq pieņem arī tā)
    headers = {"APIKey": api_key, "APIToken": api_token}
    r2 = requests.get(url, headers=headers, timeout=30)
    return r2.status_code, r2.text, "headers_fallback"


# --------------------------
# XML flattening
# --------------------------
def _text(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    t = v.strip()
    return t if t != "" else None


def _flatten_xml(elem: ET.Element, prefix: str = "") -> List[Tuple[str, str]]:
    """
    Flatten all leaf nodes into (path, value).
    Includes attributes too (path@attr).
    Handles repeated tags by indexing siblings: Tag[0], Tag[1], ...
    """
    out: List[Tuple[str, str]] = []

    # attributes
    if elem.attrib:
        for k, v in elem.attrib.items():
            if v is not None and str(v).strip() != "":
                out.append((f"{prefix}@{k}" if prefix else f"@{k}", str(v)))

    children = list(elem)
    has_children = len(children) > 0
    val = _text(elem.text)

    if not has_children:
        if val is not None:
            out.append((prefix, val) if prefix else (elem.tag, val))
        return out

    # group siblings by tag to index repeats
    counts: Dict[str, int] = {}
    for ch in children:
        counts[ch.tag] = counts.get(ch.tag, 0) + 1

    seen: Dict[str, int] = {}
    for ch in children:
        idx = seen.get(ch.tag, 0)
        seen[ch.tag] = idx + 1

        tag_name = ch.tag
        if counts.get(tag_name, 0) > 1:
            tag_name = f"{tag_name}[{idx}]"

        new_prefix = f"{prefix}/{tag_name}" if prefix else tag_name
        out.extend(_flatten_xml(ch, new_prefix))

    # sometimes parent has text + children (rare); keep it if meaningful
    if val is not None:
        out.append((f"{prefix}#text" if prefix else f"{elem.tag}#text", val))

    return out


def _parse_line_items(root: ET.Element) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for li in root.findall("./LineItems/LineItem"):
        # Paņemam visu, ko var, bet ieliekam strukturēti (flatten iekš line item)
        flat = _flatten_xml(li, "LineItem")
        row = {"_flat": [{"field": k, "value": v} for k, v in flat]}

        # vēl ērtībai: tipiskie lauki (ja ir)
        def ft(p: str) -> Optional[str]:
            el = li.find(p)
            return _text(el.text) if el is not None else None

        row["item_code"] = ft("./Item/ItemCode")
        row["item_name"] = ft("./Item/ItemName")
        row["qty"] = ft("./Qty")
        row["price"] = ft("./Price")
        row["line_total"] = ft("./LineTotal")
        row["tax"] = ft("./TaxKey/TaxKeyName")
        items.append(row)
    return items


# --------------------------
# Main
# --------------------------
def run(ctx: dict):
    ctx["step_04_version"] = "v2026-02-05-02"

    doc_id = ctx.get("next_document_id")
    sale_xml = ctx.get("paytraq_full_xml")

    if not doc_id:
        ctx["error"] = "Missing ctx.next_document_id (run step 02/03 first)"
        return ctx
    if not sale_xml:
        ctx["error"] = "Missing ctx.paytraq_full_xml (run step 03 first)"
        return ctx

    try:
        root = ET.fromstring(sale_xml)
    except Exception as e:
        ctx["error"] = f"XML parse error: {type(e).__name__}"
        ctx["sale_xml_snippet"] = (sale_xml or "")[:500]
        return ctx

    # 1) SALE: pilnais flatten (viss ko var)
    sale_fields = _flatten_xml(root, "Sale")
    sale_fields_kv = [{"field": k, "value": v} for k, v in sale_fields]

    # 2) Produktsaraksts
    line_items = _parse_line_items(root)

    # 3) Klienta ID no sale XML
    client_id = None
    el = root.find("./Header/Document/Client/ClientID")
    if el is not None:
        client_id = _text(el.text)

    # 4) PILNS KLIENTS no PayTraq (best-effort: client + contacts + shippingAddresses + banks)
    api_key = os.getenv("PAYTRAQ_API_KEY") or os.getenv("PAYTRAQ_KEY") or ""
    api_token = os.getenv("PAYTRAQ_API_TOKEN") or os.getenv("PAYTRAQ_TOKEN") or ""

    client_bundle: Dict[str, Any] = {"client_id": client_id}
    if client_id and api_key and api_token:
        # endpoints pēc PayTraq API docs:
        # GET /api/client/{ClientID}
        # GET /api/client/contacts/{ClientID}
        # GET /api/client/shippingAddresses/{ClientID}
        # GET /api/client/banks/{ClientID}
        # (katrs var arī nebūt aizpildīts, bet API tomēr atgriež XML)
        endpoints = {
            "client": f"/api/client/{client_id}",
            "contacts": f"/api/client/contacts/{client_id}",
            "shipping_addresses": f"/api/client/shippingAddresses/{client_id}",
            "banks": f"/api/client/banks/{client_id}",
        }

        for key, path in endpoints.items():
            st, body, auth_used = _paytraq_get_xml(path, api_key, api_token)
            client_bundle[f"{key}_endpoint"] = path
            client_bundle[f"{key}_status_code"] = st
            client_bundle[f"{key}_auth_used"] = auth_used

            if st == 200 and body and body.lstrip().startswith("<"):
                try:
                    rroot = ET.fromstring(body)
                    flat = _flatten_xml(rroot, key)
                    client_bundle[f"{key}_fields"] = [{"field": k, "value": v} for k, v in flat]
                except Exception:
                    client_bundle[f"{key}_parse_error"] = True
                    client_bundle[f"{key}_body_snippet"] = (body or "")[:400]
            else:
                # ja nav 200, saglabājam snippet (bieži tur ir HTML vai error xml)
                client_bundle[f"{key}_body_snippet"] = (body or "")[:400]
    else:
        client_bundle["note"] = "Client fetch skipped (missing PAYTRAQ credentials or client_id)"

    # 5) Saliekam rezultātu vienā lielā objektā (un uz GitHub)
    result = {
        "document_id": doc_id,
        "client_id": client_id,
        "sale_fields": sale_fields_kv,          # VISS
        "line_items": line_items,               # produkti + katram _flat
        "client_bundle": client_bundle,         # pilnais klients + listi
    }

    ctx["extract_all"] = {
        "document_id": doc_id,
        "client_id": client_id,
        "sale_field_count": len(sale_fields_kv),
        "line_items_count": len(line_items),
        "client_bundle_keys": list(client_bundle.keys()),
        # lai debug atbilde nepaliek milzīga:
        "sale_fields_preview_30": sale_fields_kv[:30],
    }

    gh_token = os.getenv("GITHUB_TOKEN")
    if gh_token:
        json_path = f"state/debug/extract_all_{doc_id}.json"
        html_path = f"state/debug/extract_all_{doc_id}.html"

        pretty = json.dumps(result, ensure_ascii=False, indent=2)
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>extract_all_{doc_id}</title></head><body>"
            f"<h1>extract_all_{doc_id}</h1>"
            f"<p><b>Sale fields:</b> {len(sale_fields_kv)} | <b>Line items:</b> {len(line_items)}</p>"
            f"<pre>{pretty}</pre></body></html>"
        )

        st1, sn1 = _github_put_file(gh_token, json_path, pretty.encode("utf-8"), f"debug: extract_all json {doc_id}")
        st2, sn2 = _github_put_file(gh_token, html_path, html.encode("utf-8"), f"debug: extract_all html {doc_id}")

        ctx["github_extract_all_json_path"] = json_path
        ctx["github_extract_all_json_status"] = st1
        if st1 not in (200, 201):
            ctx["github_extract_all_json_error_snippet"] = sn1

        ctx["github_extract_all_html_path"] = html_path
        ctx["github_extract_all_html_status"] = st2
        if st2 not in (200, 201):
            ctx["github_extract_all_html_error_snippet"] = sn2

    return ctx
