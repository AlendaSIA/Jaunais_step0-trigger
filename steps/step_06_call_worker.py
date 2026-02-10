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
    If disabled or no next_document_id -> no-op.
    """
    enabled = os.getenv("ENABLE_STEP_06_CALL_WORKER", "0") == "1"
    if not enabled:
        ctx["_trace"] = (ctx.get("_trace") or []) + [{"step06": "disabled"}]
        return ctx

    worker_base = os.getenv("WORKER_BASE_URL") or os.getenv("WORKER_URL")
    if not worker_base:
        ctx["_trace"] = (ctx.get("_trace") or []) + [{"step06": "missing WORKER_BASE_URL/WORKER_URL"}]
        return ctx

    doc_id = ctx.get("next_document_id")
    if not doc_id:
        ctx["_trace"] = (ctx.get("_trace") or []) + [{"step06": "no next_document_id"}]
        return ctx

    # IMPORTANT: Worker needs paytraq_full_xml for step02/03 (line items + products sync)
    sale_xml = ctx.get("paytraq_full_xml")
    if not sale_xml:
        ctx["_trace"] = (ctx.get("_trace") or []) + [{"step06": "missing paytraq_full_xml in ctx"}]
        return ctx

    try:
        root = ET.fromstring(sale_xml)
    except Exception as e:
        ctx["_trace"] = (ctx.get("_trace") or []) + [{"step06": f"invalid xml: {e}"}]
        return ctx

    document_ref = _xml_text(root, "./Header/Document/DocumentRef")
    client_name = _xml_text(root, "./Header/Client/ClientName")
    total_sum = _xml_text(root, "./Header/Document/TotalSum")
    currency = _xml_text(root, "./Header/Document/Currency") or "EUR"

    pipeline_id = int(os.getenv("PIPEDRIVE_PIPELINE_ID", "7"))
    stage_id = int(os.getenv("PIPEDRIVE_STAGE_ID", "50"))

    title = f"{document_ref} / {doc_id}" if document_ref else f"PayTraq {doc_id}"

    payload = {
        "document": {
            "id": int(doc_id),
            "client": {
                "name": client_name,
                "email": None,
                "phone": None,
            },
            "deal": {
                "title": title,
                "pipeline_id": pipeline_id,
                "stage_id": stage_id,
                "value": float(total_sum) if total_sum else None,
                "currency": currency,
            },
            "meta": {
                "paytraq_document_ref": document_ref,
            },
            # <-- CRITICAL FIX: pass full XML to worker so steps 02/03 can run
            "paytraq_full_xml": sale_xml,
        }
    }

    # normalize /process endpoint
    if worker_base.endswith("/process"):
        url = worker_base
    else:
        url = worker_base.rstrip("/") + "/process"

    try:
        r = requests.post(url, json=payload, timeout=60)
        ctx["worker_status_code"] = r.status_code
        ctx["worker_response_text"] = r.text[:2000]

        if 200 <= r.status_code < 300:
            ctx["pipedrive_ack"] = True
            ctx["_trace"] = (ctx.get("_trace") or []) + [{"step06": "ok"}]
        else:
            ctx["_trace"] = (ctx.get("_trace") or []) + [{"step06": f"worker error {r.status_code}"}]
    except Exception as e:
        ctx["worker_status_code"] = None
        ctx["_trace"] = (ctx.get("_trace") or []) + [{"step06": f"exception: {e}"}]

    return ctx
