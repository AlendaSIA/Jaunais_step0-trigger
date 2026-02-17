import os
import base64
import json
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


def _xml_text(root: ET.Element, path: str):
    el = root.find(path)
    if el is None or el.text is None:
        return None
    t = el.text.strip()
    return t if t else None


def run(ctx: dict):
    """Step06: call pipedrive-worker.

    Fixes:
      - Uses worker_url from request payload if provided
      - Otherwise uses WORKER_BASE_URL/WORKER_URL env
      - Sends paytraq_full_xml to worker (critical for step02/03)
      - Sets pipedrive_ack=True only on 2xx

    Debug improvements:
      - Do NOT truncate worker response (was cutting at 2000 chars)
      - Parse JSON into ctx.worker_response_json when possible
      - Save full worker response to GitHub state/debug/worker_<doc_id>.json (if GITHUB_TOKEN is set)
    """

    enabled = os.getenv("ENABLE_STEP_06_CALL_WORKER", "0") == "1"
    ctx["step_06_enabled"] = enabled
    if not enabled:
        ctx["worker_call"] = {"skipped": True, "reason": "disabled_by_env"}
        return ctx

    # 1) prefer per-request override
    worker_url = (ctx.get("worker_url") or "").strip()

    # 2) fallback to env
    if not worker_url:
        base = (os.getenv("WORKER_BASE_URL") or os.getenv("WORKER_URL") or "").strip()
        if base:
            base = base.rstrip("/")
            worker_url = base + ("" if base.endswith("/process") else "/process")

    if not worker_url:
        ctx["worker_call"] = {"ok": False, "reason": "missing worker_url/WORKER_BASE_URL"}
        ctx["error"] = "Step06: missing worker_url (payload) and WORKER_BASE_URL/WORKER_URL (env)"
        return ctx

    doc_id = ctx.get("in_progress_id") or ctx.get("next_document_id")
    sale_xml = ctx.get("paytraq_full_xml")

    if not doc_id:
        ctx["error"] = "Step06: Missing doc id (ctx.in_progress_id/ctx.next_document_id)"
        return ctx
    if not sale_xml:
        ctx["error"] = "Step06: Missing ctx.paytraq_full_xml (Step03 should fetch it)"
        return ctx

    try:
        root = ET.fromstring(sale_xml)
    except Exception as e:
        ctx["error"] = f"Step06: XML parse error: {type(e).__name__}: {e}"
        return ctx

    document_ref = _xml_text(root, "./Header/Document/DocumentRef")
    client_name = _xml_text(root, "./Header/Document/Client/ClientName")
    currency = _xml_text(root, "./Header/Currency") or "EUR"
    total = _xml_text(root, "./Header/Total")

    pipeline_id = int(os.getenv("PIPEDRIVE_PIPELINE_ID", "7"))
    stage_id = int(os.getenv("PIPEDRIVE_STAGE_ID", "50"))
    title = f"PT {doc_id} {document_ref or ''}".strip()

    payload = {
        "document": {
            "id": int(doc_id),
            "client": {"name": client_name, "email": None, "phone": None},
            "deal": {
                "title": title,
                "pipeline_id": pipeline_id,
                "stage_id": stage_id,
                "value": float(total) if total else None,
                "currency": currency,
            },
            "meta": {"paytraq_document_ref": document_ref},
            # CRITICAL: worker needs this for parsing line items + products sync
            "paytraq_full_xml": sale_xml,
        }
    }

    try:
        r = requests.post(worker_url, json=payload, timeout=90)
        ctx["worker_status_code"] = r.status_code

        # IMPORTANT: do NOT truncate worker response.
        ctx["worker_response_text"] = r.text or ""

        # Parse JSON if possible
        worker_json = None
        try:
            worker_json = r.json()
        except Exception:
            worker_json = None

        if isinstance(worker_json, dict):
            ctx["worker_response_json"] = worker_json
            ctx["worker_summary"] = {
                "status": worker_json.get("status"),
                "deal_id": worker_json.get("deal_id"),
                "title": worker_json.get("title"),
                "document_id": worker_json.get("document_id"),
                "line_items_count": worker_json.get("line_items_count"),
                "attached_count": (worker_json.get("step_03") or {}).get("attached_count"),
            }

        # Debug: save full worker response into GitHub (same pattern as step_03/04)
        gh_token = os.getenv("GITHUB_TOKEN")
        if gh_token:
            path = f"state/debug/worker_{doc_id}.json"
            try:
                content_bytes = (
                    json.dumps(worker_json, ensure_ascii=False, indent=2).encode("utf-8")
                    if isinstance(worker_json, (dict, list))
                    else (r.text or "").encode("utf-8")
                )
            except Exception:
                content_bytes = (r.text or "").encode("utf-8")

            st, sn = _github_put_file(gh_token, path, content_bytes, f"debug: worker response {doc_id}")
            ctx["github_worker_json_path"] = path
            ctx["github_worker_json_status"] = st
            if st not in (200, 201):
                ctx["github_worker_json_error_snippet"] = sn

        if 200 <= r.status_code < 300:
            ctx["pipedrive_ack"] = True
            ctx["worker_call"] = {"ok": True, "url": worker_url}
            return ctx

        ctx["worker_call"] = {"ok": False, "url": worker_url}
        ctx["error"] = f"Step06: worker HTTP {r.status_code}"
        return ctx

    except Exception as e:
        ctx["worker_call"] = {"ok": False, "url": worker_url}
        ctx["error"] = f"Step06: worker exception: {type(e).__name__}: {e}"
        return ctx
