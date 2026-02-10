import os
import requests
import xml.etree.ElementTree as ET


def _xml_text(root: ET.Element, path: str):
    el = root.find(path)
    if el is None or el.text is None:
        return None
    t = el.text.strip()
    return t if t else None


def run(ctx: dict):
    """
    Step06: call pipedrive-worker.
    Fixes:
      - Uses worker_url from request payload if provided
      - Otherwise uses WORKER_BASE_URL/WORKER_URL env
      - Sends paytraq_full_xml to worker (critical for step02/03)
      - Sets pipedrive_ack=True only on 2xx
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
        ctx["worker_response_text"] = (r.text or "")[:2000]

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
