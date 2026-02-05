import os
import base64
import requests

REPO = "AlendaSIA/Jaunais_step0-trigger"
STATE_PATH = "state/last_processed_id.txt"

def run(ctx: dict):
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        ctx["error"] = "Missing env: GITHUB_TOKEN"
        return ctx

    url = f"https://api.github.com/repos/{REPO}/contents/{STATE_PATH}"
    r = requests.get(url, headers={"Authorization": f"token {token}"}, timeout=20)

    ctx["github_status_code"] = r.status_code

    data = r.json()
    if "content" not in data:
        ctx["error"] = "GitHub response missing 'content'"
        ctx["github_body"] = data
        return ctx

    content = base64.b64decode(data["content"]).decode().strip()
    ctx["last_processed_id"] = int(content)
    return ctx
