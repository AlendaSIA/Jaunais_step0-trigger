import os
import re
import requests
import xml.etree.ElementTree as ET

GITHUB_STATE_URL = os.getenv("GITHUB_STATE_URL")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
PAYTRAQ_BASE_URL = os.getenv("PAYTRAQ_BASE_URL", "https://go.paytraq.com").rstrip("/")
PAYTRAQ_API_KEY = os.getenv("PAYTRAQ_API_KEY")
PAYTRAQ_API_TOKEN = os.getenv("PAYTRAQ_API_TOKEN")


def _github_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def _github_get_state():
    if not GITHUB_STATE_URL or not GITHUB_TOKEN:
        return None, None
    r = requests.get(GITHUB_STATE_URL, headers=_github_headers(), timeout=20)
    return r.status_code, r.text


def _github_put_state(last_processed_id: int, in_progress_id: int | None):
    if not GITHUB_STATE_URL or not GITHUB_TOKEN:
        return None, None
    payload = {
        "last_processed_id": last_processed_id,
        "in_progress_id": in_progress_id,
    }
    r = requests.put(GITHUB_STATE_URL, json=payload, headers=_github_headers(), timeout=20)
    return r.status_code, r.text


def _paytraq_sales_list():
    url = f"{PAYTRAQ_BASE_URL}/api/sales"
    params = {"APIKey": PAYTRAQ_API_KEY, "APIToken": PAYTRAQ_API_TOKEN}
    r = requests.get(url, params=params, timeout=40)
    return r.status_code, r.text


def _paytraq_sale_xml_by_id(doc_id: int):
    url = f"{PAYTRAQ_BASE_URL}/api/sale/{doc_id}"
    params = {"APIKey": PAYTRAQ_API_KEY, "APIToken": PAYTRAQ_API_TOKEN}
    r = requests.get(url, params=params, timeout=60)
    return r.status_code, r.text


def _extract_doc_id_from_sales_xml(sales_xml: str):
    # sales list is XML with multiple <Sale><DocumentID>...</DocumentID>...</Sale>
    try:
        root = ET.fromstring(sales_xml)
    except Exception:
        return []

    ids = []
    for el in root.findall(".//DocumentID"):
        if el is not None and el.text:
            t = el.text.strip()
            if t.isdigit():
                ids.append(int(t))
    return ids


def _doc_ref_from_sale_xml(sale_xml: str):
    try:
        root = ET.fromstring(sale_xml)
    except Exception:
        return None
    el = root.find("./Header/Document/DocumentRef")
    if el is None or not el.text:
        return None
    t = el.text.strip()
    return t if t else None


def _doc_date_from_sale_xml(sale_xml: str):
    try:
        root = ET.fromstring(sale_xml)
    except Exception:
        return None
    el = root.find("./Header/Document/DocumentDate")
    if el is None or not el.text:
        return None
    t = el.text.strip()
    return t if t else None


def run(ctx: dict):
    """
    Step02: pick next document id.

    Supports:
    - normal mode: pick next doc after last_processed_id
    - override: user can request a specific document by document_ref OR by date filters

    Input accepted in ctx (from /run JSON):
      - document_ref or doc_ref (string)  -> find a doc by matching DocumentRef (needs per-doc fetch)
      - date (YYYY-MM-DD) or date_from/date_to -> filter by DocumentDate by fetching per-doc XML
      - skip_state_update (bool) -> don't update last_processed_id/in_progress (for test runs)
    """
    # Read overrides from ctx (provided by /run body)
    override_ref = ctx.get("document_ref") or ctx.get("doc_ref") or ctx.get("override_document_ref")
    override_date = ctx.get("date") or ctx.get("override_date")
    date_from = ctx.get("date_from")
    date_to = ctx.get("date_to")
    skip_state_update = bool(ctx.get("skip_state_update"))

    # Sales list
    sc, sales_xml = _paytraq_sales_list()
    ctx["paytraq_sales_status_code"] = sc
    if sc != 200:
        ctx["_trace"] = (ctx.get("_trace") or []) + [{"step02": f"paytraq sales list error {sc}"}]
        return ctx

    ids = _extract_doc_id_from_sales_xml(sales_xml)
    ctx["sales_count"] = len(ids)
    ctx["sales_ids"] = ids[:100]  # debug visibility

    if not ids:
        ctx["has_next_document"] = False
        ctx["next_document_id"] = None
        return ctx

    # Override by document_ref or date requires fetching per-doc XML (slower, but test-friendly)
    if override_ref or override_date or date_from or date_to:
        want_ref = override_ref.strip() if isinstance(override_ref, str) else None

        # normalize date filters
        if override_date and not date_from and not date_to:
            date_from = override_date
            date_to = override_date

        # scan newest -> oldest so you get the most recent match first
        for doc_id in ids:
            sc2, sale_xml = _paytraq_sale_xml_by_id(doc_id)
            if sc2 != 200:
                continue

            ref = _doc_ref_from_sale_xml(sale_xml)
            dd = _doc_date_from_sale_xml(sale_xml)

            ref_ok = True
            if want_ref:
                ref_ok = (ref == want_ref)

            date_ok = True
            if date_from and date_to and dd:
                date_ok = (date_from <= dd <= date_to)
            elif date_from and dd:
                date_ok = (dd >= date_from)
            elif date_to and dd:
                date_ok = (dd <= date_to)
            elif (date_from or date_to) and not dd:
                date_ok = False

            if ref_ok and date_ok:
                ctx["has_next_document"] = True
                ctx["next_document_id"] = int(doc_id)
                ctx["picked_by"] = "override_ref_or_date"
                # store for next steps
                ctx["paytraq_full_xml"] = sale_xml

                if not skip_state_update:
                    # Mark lock as in_progress for safety during processing
                    ctx["in_progress_id"] = int(doc_id)
                return ctx

        # no match
        ctx["has_next_document"] = False
        ctx["next_document_id"] = None
        ctx["picked_by"] = "override_ref_or_date"
        return ctx

    # Normal mode: pick next doc after last_processed_id
    last_processed_id = ctx.get("last_processed_id")
    if last_processed_id is None:
        # IMPORTANT FIX: do NOT depend on ctx["state"], step00 provides last_processed_id directly
        # If missing, try github state endpoint as fallback
        gsc, gtxt = _github_get_state()
        ctx["github_status_code"] = gsc
        if gsc == 200 and gtxt:
            # very small parsing without strict schema
            m = re.search(r"last_processed_id[^0-9]*(\d+)", gtxt)
            if m:
                last_processed_id = int(m.group(1))

    last_processed_id = int(last_processed_id) if last_processed_id is not None else None

    next_id = None
    if last_processed_id is None:
        # pick newest available
        next_id = ids[0]
    else:
        # pick first id > last_processed_id (ids list is newest->older in our observed outputs)
        # So scan reversed to find the smallest id greater than last_processed_id, or just pick first > last_processed_id
        for doc_id in ids:
            if int(doc_id) > int(last_processed_id):
                next_id = int(doc_id)
                break

    ctx["next_document_id"] = next_id
    ctx["has_next_document"] = bool(next_id)

    if next_id and not skip_state_update:
        ctx["in_progress_id"] = int(next_id)

    return ctx
