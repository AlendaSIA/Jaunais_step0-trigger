import os
import base64
import requests

# Defaults (ja env nav uzlikts)
DEFAULT_OWNER = "AlendaSIA"
DEFAULT_REPO = "Jaunais_step0-trigger"

STATE_LAST_PATH = "state/last_processed_id.txt"
STATE_INPROGRESS_PATH = "state/in_progress_id.txt"


def _repo_full() -> str:
    owner = os.getenv("GITHUB_OWNER") or DEFAULT_OWNER
    repo = os.getenv("GITHUB_REPO") or DEFAULT_REPO
    return f"{owner}/{repo}"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }


def _github_get_sha(token: str, path: str):
    url = f"https://api.github.com/repos/{_repo_full()}/contents/{path}"
    r = requests.get(url, headers=_headers(token), timeout=20)

    if r.status_code == 404:
        return None, 404, None

    data = r.json() or {}
    sha = data.get("sha")
    if not sha:
        return None, r.status_code, data

    return sha, r.status_code, None


def _github_put_text(token: str, path: str, text: str, message: str):
    sha, st, err = _github_get_sha(token, path)
    if st not in (200, 404):
        return None, st, err

    url = f"https://api.github.com/repos/{_repo_full()}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(text.encode("utf-8")).decode("utf-8"),
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=_headers(token), json=payload, timeout=30)
    return r.json() if r.content else None, r.status_code, None


def run(ctx: dict):
    """
    Step08: finalize state.
    Ja ctx["pipedrive_ack"] True -> ieraksta last_processed_id un notīra in_progress_id (0).

    Ja ctx["skip_state_update"] True -> neraksta neko (test mode).
    """
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        ctx["error"] = "Missing env: GITHUB_TOKEN"
        return ctx

    skip_state_update = bool(ctx.get("skip_state_update"))
    if skip_state_update:
        ctx["github_finalize_clear_status"] = "skipped(test_mode)"
        ctx["github_finalize_last_status"] = "skipped(test_mode)"
        return ctx

    ack = bool(ctx.get("pipedrive_ack"))
    doc_id = ctx.get("in_progress_id") or ctx.get("next_document_id")

    if not ack or not doc_id:
        ctx["github_finalize_clear_status"] = "skipped(no_ack_or_no_doc)"
        return ctx

    # 1) set last_processed_id.txt
    _, st_last, _ = _github_put_text(
        token,
        STATE_LAST_PATH,
        str(int(doc_id)),
        message=f"state: set last_processed_id={int(doc_id)}",
    )
    ctx["github_finalize_last_status"] = st_last

    # 2) clear in_progress_id.txt
    _, st_clear, _ = _github_put_text(
        token,
        STATE_INPROGRESS_PATH,
        "0",
        message="state: clear in_progress_id",
    )
    ctx["github_finalize_clear_status"] = st_clear

    return ctx
