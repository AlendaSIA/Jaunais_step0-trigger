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
    If success -> sets ctx["pipedrive_ack"]=True so Step08 will clear lock.
    If disabled or worker fails -> DOES NOT ack (lock stays).
    """
    enabled = os.getenv("ENABLE_STEP_06_CALL_WORKER", "0") == "1"
    ctx["step_06_enabled"] = enabled

    if not enabled:
        ctx["worker_call"] = {"skipped": True, "reason": "disabled_by_env"}
        return ctx

    worker_base = os.getenv(
        "WORKER_BASE_URL",
        "https://pipedrive-worker-v2-142693968214.europe-west1.run.app",
    ).rstrip("/")
    url = f"{worker_base}/process"

    doc_id = ctx.get("in_progress_id") or ctx.get("next_document_id")
    sale_xml = ctx.get("paytraq_full_xml")

    if not doc_id:
        ctx["error"] = "Step06: Missing doc id (ctx.in_progress_id/ctx.next_document_id)"
        return ctx
    if not sale_xml:
        ctx["error"] = "Step06: Missing ctx.paytraq_full_xml"
        return ctx

    # parse minimal fields from XML (we don't touch Step04)
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
        }
    }

    try:
        r = requests.post(url, json=payload, timeout=60)
        ctx["worker_status_code"] = r.status_code

        try:
            data = r.json()
        except Exception:
            data = {"non_json_response_snippet": (r.text or "")[:800]}

        ctx["worker_response"] = data

        # If worker is OK -> ACK so Step08 clears lock
        if 200 <= r.status_code < 300:
            ctx["pipedrive_ack"] = True
            ctx["worker_call"] = {"ok": True}
            return ctx

        # If worker failed -> no ACK (lock stays)
        ctx["worker_call"] = {"ok": False}
        ctx["error"] = f"Step06: worker HTTP {r.status_code}"
        return ctx

    except Exception as e:
        ctx["worker_call"] = {"ok": False}
        ctx["error"] = f"Step06: worker exception: {type(e).__name__}: {e}"
        return ctx
