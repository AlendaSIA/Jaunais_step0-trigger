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


def _fetch_xml(path: str, key: str, token: str, timeout_s: int = 30):
    url = f"{PAYTRAQ_BASE_URL}{path}"
    r = requests.get(url, params={"APIKey": key, "APIToken": token}, timeout=timeout_s)
    return r.status_code, (r.text or ""), path


def run(ctx: dict):
    # versijas marķieris, lai uzreiz redzētu ka mākonī ir jaunais kods
    ctx["step_03_version"] = "v2026-02-05-01"

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

    # 1) primārais: /api/sale/{id}
    status, body, used_path = _fetch_xml(f"/api/sale/{doc_id}", key, token)
    ctx["paytraq_full_status_code"] = status
    ctx["paytraq_full_endpoint"] = used_path

    # 2) fallback, ja /api/sale/{id} nav pieejams: mēģinām /api/saleUBL/{id}
    if status != 200:
        status2, body2, used_path2 = _fetch_xml(f"/api/saleUBL/{doc_id}", key, token)
        ctx["paytraq_full_status_code_2"] = status2
        ctx["paytraq_full_endpoint_2"] = used_path2
        if status2 == 200:
            status, body, used_path = status2, body2, used_path2
            ctx["paytraq_full_status_code"] = status
            ctx["paytraq_full_endpoint"] = used_path

    if status != 200:
        ctx["error"] = "PayTraq full document returned non-200"
        ctx["paytraq_full_body_snippet"] = (body or "")[:800]
        return ctx

    xml_text = body or ""
    ctx["paytraq_full_xml_len"] = len(xml_text)
    ctx["paytraq_full_xml"] = xml_text

    # Debug: saglabājam GitHub, lai viegli testēt (repo UI)
    gh_token = os.getenv("GITHUB_TOKEN")
    if gh_token:
        path = f"state/debug/sales_{doc_id}.xml"
        status_g, snippet = _github_put_file(
            gh_token,
            path,
            xml_text.encode("utf-8"),
            message=f"debug: save PayTraq XML {doc_id} ({used_path})",
        )
        ctx["github_debug_xml_path"] = path
        ctx["github_debug_xml_status"] = status_g
        if status_g not in (200, 201):
            ctx["github_debug_xml_error_snippet"] = snippet

    return ctx
