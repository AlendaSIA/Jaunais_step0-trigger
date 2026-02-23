import os
import json
import base64
import requests
from typing import Any, Dict, Optional, Tuple, List

REPO = "AlendaSIA/Jaunais_step0-trigger"

WORKER_URL = os.getenv("WORKER_URL", "").strip()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()


def _trace(ctx: Dict[str, Any], step: str, ok: bool, extra: Optional[Dict[str, Any]] = None) -> None:
    payload = {"step": step, "ok": ok}
    if extra:
        payload.update(extra)
    ctx.setdefault("_trace", []).append(payload)


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
    payload: Dict[str, Any] = {
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
# Flatten helper for payload dump
# --------------------------
def _flatten(obj: Any, prefix: str = "") -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    if isinstance(obj, dict):
        if not obj:
            out.append({"field": prefix, "value": None})
            return out
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            out.extend(_flatten(v, p))
        return out

    if isinstance(obj, list):
        if not obj:
            out.append({"field": prefix, "value": []})
            return out
        for i, v in enumerate(obj):
            p = f"{prefix}[{i}]"
            out.extend(_flatten(v, p))
        return out

    out.append({"field": prefix, "value": obj})
    return out


def run(ctx: dict) -> dict:
    step_name = "06_call_worker"

    if not WORKER_URL:
        ctx["worker_status_code"] = 0
        ctx["worker_response_text"] = "Missing env WORKER_URL"
        _trace(ctx, step_name, False, {"error": "Missing env WORKER_URL"})
        return ctx

    doc_id = ctx.get("next_document_id")
    xml = ctx.get("paytraq_full_xml") or ""
    xml_len = len(xml) if isinstance(xml, str) else 0

    # Build payload to worker (source of truth)
    payload: Dict[str, Any] = {
        "document": {
            "id": doc_id,
            "client": ctx.get("client") or {},
            "deal": ctx.get("deal") or {},
            "meta": {
                "document_ref": ctx.get("document_ref"),
                "picked_by": ctx.get("picked_by"),
                "paytraq_full_endpoint": ctx.get("paytraq_full_endpoint"),
            },
            "paytraq_full_xml": xml,
        }
    }

    # If requested, expose full list of payload fields (for mapping)
    if ctx.get("dump_worker_fields") is True:
        dump_payload = json.loads(json.dumps(payload))  # deep copy
        dump_payload["document"]["paytraq_full_xml"] = f"<xml len={xml_len}>"

        flat = _flatten(dump_payload, "")
        worker_fields = []
        for i, row in enumerate(flat, start=1):
            val = row.get("value")
            if isinstance(val, str) and len(val) > 200:
                val = val[:200] + "…"
            worker_fields.append({"id": i, "field": row.get("field"), "value": val})

        ctx["worker_field_count"] = len(worker_fields)
        ctx["worker_fields"] = worker_fields

    # Call worker
    try:
        r = requests.post(WORKER_URL.rstrip("/") + "/process", json=payload, timeout=120)
        ctx["worker_status_code"] = r.status_code
        ctx["worker_response_text"] = (r.text or "")[:200000]

        try:
            ctx["worker_response_json"] = r.json()
        except Exception:
            ctx["worker_response_json"] = None

        # store worker response debug to GitHub (optional)
        if GITHUB_TOKEN and doc_id:
            out_path = f"state/debug/worker_{doc_id}.json"
            pretty = json.dumps(
                {
                    "payload_meta": {"doc_id": doc_id, "xml_len": xml_len},
                    "worker_response": ctx.get("worker_response_json"),
                },
                ensure_ascii=False,
                indent=2,
            )
            st, sn = _github_put_file(GITHUB_TOKEN, out_path, pretty.encode("utf-8"), f"debug: worker response {doc_id}")
            ctx["github_worker_json_path"] = out_path
            ctx["github_worker_json_status"] = st
            if st not in (200, 201):
                ctx["github_worker_json_error_snippet"] = sn

        ok = (r.status_code < 300)
        _trace(ctx, step_name, ok, {"status_code": r.status_code})
        return ctx

    except Exception as e:
        ctx["worker_status_code"] = 0
        ctx["worker_response_text"] = f"ERROR: {e}"
        _trace(ctx, step_name, False, {"error": str(e)})
        return ctx
