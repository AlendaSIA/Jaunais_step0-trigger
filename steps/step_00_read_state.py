import os
import base64
import requests

DEFAULT_OWNER = "AlendaSIA"
DEFAULT_REPO = "Jaunais_step0-trigger"

STATE_LAST_PATH = "state/last_processed_id.txt"
STATE_INPROGRESS_PATH = "state/in_progress_id.txt"


def _repo_full() -> str:
    owner = os.getenv("GITHUB_OWNER") or DEFAULT_OWNER
    repo = os.getenv("GITHUB_REPO") or DEFAULT_REPO
    return f"{owner}/{repo}"


def _github_read_text(token: str, path: str):
    url = f"https://api.github.com/repos/{_repo_full()}/contents/{path}"
    r = requests.get(url, headers={"Authorization": f"token {token}"}, timeout=20)

    if r.status_code == 404:
        return None, 404, None

    data = r.json() or {}
    if "content" not in data:
        return None, r.status_code, data

    content = base64.b64decode(data["content"]).decode().strip()
    return content, r.status_code, None


def run(ctx: dict):
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        ctx["error"] = "Missing env: GITHUB_TOKEN"
        return ctx

    # last_processed_id
    last_text, last_status, last_err = _github_read_text(token, STATE_LAST_PATH)
    ctx["github_state_last_status"] = last_status
    if last_status == 404:
        ctx["last_processed_id"] = 0
    elif last_text is None:
        ctx["error"] = "GitHub state read error (last_processed_id)"
        ctx["github_state_last_body"] = last_err
        return ctx
    else:
        ctx["last_processed_id"] = int(last_text)

    # in_progress_id
    prog_text, prog_status, prog_err = _github_read_text(token, STATE_INPROGRESS_PATH)
    ctx["github_state_in_progress_status"] = prog_status
    if prog_status == 404:
        ctx["in_progress_id"] = 0
    elif prog_text is None:
        ctx["error"] = "GitHub state read error (in_progress_id)"
        ctx["github_state_in_progress_body"] = prog_err
        return ctx
    else:
        ctx["in_progress_id"] = int(prog_text) if prog_text.strip() else 0

    return ctx
