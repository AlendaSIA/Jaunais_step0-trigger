import os
import base64
import requests

REPO = "AlendaSIA/Jaunais_step0-trigger"
STATE_LAST_PATH = "state/last_processed_id.txt"
STATE_INPROGRESS_PATH = "state/in_progress_id.txt"


def _github_get_sha(token: str, path: str):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    r = requests.get(url, headers={"Authorization": f"token {token}"}, timeout=20)
    if r.status_code == 200:
        return (r.json() or {}).get("sha")
    return None


def _github_put_text(token: str, path: str, text: str, message: str):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode((text or "").encode("utf-8")).decode("utf-8"),
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
    """
    ACK solis: ja ctx["pipedrive_ack"] == True,
    tad:
      - last_processed_id = in_progress_id
      - in_progress_id = 0
    """
    if not ctx.get("pipedrive_ack"):
        # pagaidām neko nedaram
        return ctx

    in_progress = int(ctx.get("in_progress_id") or 0)
    if in_progress <= 0:
        ctx["error"] = "Finalize requested but ctx.in_progress_id is empty"
        return ctx

    gh_token = os.getenv("GITHUB_TOKEN")
    if not gh_token:
        ctx["error"] = "Missing env: GITHUB_TOKEN (needed to finalize state)"
        return ctx

    # 1) last_processed_id = in_progress
    s1, sn1 = _github_put_text(
        gh_token,
        STATE_LAST_PATH,
        str(in_progress),
        message=f"ack: set last_processed_id={in_progress}",
    )
    ctx["github_finalize_last_status"] = s1
    if s1 not in (200, 201):
        ctx["error"] = "Failed to update last_processed_id in GitHub state"
        ctx["github_finalize_last_error_snippet"] = sn1
        return ctx

    # 2) clear in_progress_id
    s2, sn2 = _github_put_text(
        gh_token,
        STATE_INPROGRESS_PATH,
        "0",
        message="ack: clear in_progress_id=0",
    )
    ctx["github_finalize_clear_status"] = s2
    if s2 not in (200, 201):
        ctx["error"] = "Failed to clear in_progress_id in GitHub state"
        ctx["github_finalize_clear_error_snippet"] = sn2
        return ctx

    ctx["last_processed_id"] = in_progress
    ctx["in_progress_id"] = 0
    return ctx
