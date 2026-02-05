import os
import base64
import requests

PAYTRAQ_BASE_URL = "https://go.paytraq.com"
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


def run(ctx: dict):
    key = os.getenv("PAYTRAQ_API_KEY")
    token = os.getenv("PAYTRAQ_API_TOKEN")

    ctx["has_paytraq_key"] = bool(key)
    ctx["has_paytraq_token"] = bool(token)

    if not key or not token:
        ctx["error"] = "Missing env: PAYTRAQ_API_KEY or PAYTRAQ_API_TOKEN"
        return ctx

    doc_id = ctx.get("next_document_id")
    if not doc_id:
        ctx["error"] = "Missing ctx.next_document_id (run step 02 first)"
        return ctx

    url = f"{PAYTRAQ_BASE_URL}/api/sales/{doc_id}"
    r = requests.get(url, params={"APIKey": key, "APIToken": token}, timeout=30)

    ctx["paytraq_full_status_code"] = r.status_code

    if r.status_code != 200:
        ctx["error"] = "PayTraq /api/sales/{id} returned non-200"
        ctx["paytraq_full_body_snippet"] = (r.text or "")[:800]
        return ctx

    xml_text = r.text or ""
    ctx["paytraq_full_xml_len"] = len(xml_text)
    ctx["paytraq_full_xml"] = xml_text  # Step04 vajadzēs parsēšanai

    # Debug: saglabājam GitHub, lai viegli testēt (atverams repo UI)
    gh_token = os.getenv("GITHUB_TOKEN")
    if gh_token:
        path = f"state/debug/sales_{doc_id}.xml"
        status, snippet = _github_put_file(
            gh_token,
            path,
            xml_text.encode("utf-8"),
            message=f"debug: save PayTraq sales XML {doc_id}",
        )
        ctx["github_debug_xml_path"] = path
        ctx["github_debug_xml_status"] = status
        if status not in (200, 201):
            ctx["github_debug_xml_error_snippet"] = snippet

    return ctx
