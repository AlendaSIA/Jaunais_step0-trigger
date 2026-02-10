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
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def _get_state(ctx):
    return ctx.get("state") or {}


def _lock_in_progress(doc_id: int):
    # original behavior: writes lock to GitHub
    url = f"{GITHUB_STATE_URL}/in_progress"
    r = requests.put(url, headers=_github_headers(), json={"in_progress_id": int(doc_id)}, timeout=30)
    return r.status_code


def _paytraq_get_sale_xml(doc_id: int):
    url = f"{PAYTRAQ_BASE_URL}/api/sale/{int(doc_id)}"
    params = {"APIKey": PAYTRAQ_API_KEY, "APIToken": PAYTRAQ_API_TOKEN}
    r = requests.get(url, params=params, timeout=60)
    return r.status_code, (r.text or "")


def _xml_text(root: ET.Element, path: str):
    el = root.find(path)
    if el is None or el.text is None:
        return None
    t = el.text.strip()
    return t if t else None


def _matches_title_or_comment(s: str, document_ref: str | None, comment: str | None):
    if not s:
        return False
    s_norm = s.strip().lower()
    for candidate in [document_ref, comment]:
        if not candidate:
            continue
        if s_norm in candidate.strip().lower():
            return True
    return False


def _matches_date(doc_date: str | None, date_eq: str | None, date_from: str | None, date_to: str | None):
    # dates are YYYY-MM-DD in PayTraq XML
    if not doc_date:
        return False

    if date_eq:
        return doc_date == date_eq

    if date_from and doc_date < date_from:
        return False
    if date_to and doc_date > date_to:
        return False

    return bool(date_from or date_to)


def run(ctx: dict):
    """
    Step02: choose next document id.
    Default: original "next doc after last_processed" behavior + writes lock.

    New (safe test overrides):
      - ctx["override_doc_id"] -> use that doc id
      - ctx["override_doc_title"] -> scan sales list, fetch sale XML, match against DocumentRef or Comment
      - ctx["override_date"] or ctx["override_date_from"/"override_date_to"] -> scan & pick first matching date

    Important:
      - If ctx["skip_state_update"] is True -> we DO NOT write GitHub lock in this step.
    """
    state = _get_state(ctx)
    sales_ids = ctx.get("sales_ids") or []

    skip_state_update = bool(ctx.get("skip_state_update"))
    force_lock = bool(ctx.get("force_lock"))  # optional: allow locking even in test mode

    override_doc_id = ctx.get("override_doc_id")
    override_title = ctx.get("override_doc_title")
    override_date = ctx.get("override_date")
    override_date_from = ctx.get("override_date_from")
    override_date_to = ctx.get("override_date_to")

    # 1) Explicit doc_id override
    if override_doc_id is not None:
        doc_id = int(override_doc_id)
        ctx["has_next_document"] = True
        ctx["next_document_id"] = doc_id
        ctx["in_progress_id"] = doc_id
        ctx["picked_mode"] = "override_doc_id"
        if (not skip_state_update) or force_lock:
            ctx["github_lock_status"] = _lock_in_progress(doc_id)
        else:
            ctx["github_lock_status"] = "skipped(test_mode)"
        return ctx

    # 2) If title/date filters are provided -> scan sales list (fetch xml per id until match)
    if override_title or override_date or override_date_from or override_date_to:
        wanted = (override_title or "").strip()
        date_eq = (override_date or "").strip() or None
        date_from = (override_date_from or "").strip() or None
        date_to = (override_date_to or "").strip() or None

        scan_limit = int(ctx.get("scan_limit") or 200)
        scanned = 0

        for doc_id in sales_ids[:scan_limit]:
            scanned += 1
            st, xml_text = _paytraq_get_sale_xml(int(doc_id))
            if st < 200 or st >= 300 or not xml_text:
                continue

            try:
                root = ET.fromstring(xml_text)
            except Exception:
                continue

            document_ref = _xml_text(root, "./Header/Document/DocumentRef")
            comment = _xml_text(root, "./Header/Comment")
            doc_date = _xml_text(root, "./Header/Document/DocumentDate")

            title_ok = True
            date_ok = True

            if wanted:
                title_ok = _matches_title_or_comment(wanted, document_ref, comment)

            if date_eq or date_from or date_to:
                date_ok = _matches_date(doc_date, date_eq, date_from, date_to)

            if title_ok and date_ok:
                ctx["has_next_document"] = True
                ctx["next_document_id"] = int(doc_id)
                ctx["in_progress_id"] = int(doc_id)
                ctx["picked_mode"] = "scan_match"
                ctx["picked_scan_count"] = scanned
                ctx["picked_document_ref"] = document_ref
                ctx["picked_comment"] = comment
                ctx["picked_document_date"] = doc_date

                if (not skip_state_update) or force_lock:
                    ctx["github_lock_status"] = _lock_in_progress(int(doc_id))
                else:
                    ctx["github_lock_status"] = "skipped(test_mode)"
                return ctx

        ctx["has_next_document"] = False
        ctx["error"] = f"Step02: no match found (title/date) after scanning {scanned} docs"
        return ctx

    # 3) Default original behavior
    last_processed_id = int(state.get("last_processed_id") or 0)
    next_id = None

    for doc_id in sales_ids:
        if int(doc_id) > last_processed_id:
            next_id = int(doc_id)
            break

    if not next_id:
        ctx["has_next_document"] = False
        return ctx

    ctx["has_next_document"] = True
    ctx["next_document_id"] = next_id
    ctx["in_progress_id"] = next_id

    if not skip_state_update:
        ctx["github_lock_status"] = _lock_in_progress(next_id)
    else:
        ctx["github_lock_status"] = "skipped(test_mode)"

    return ctx
