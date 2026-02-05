import os
import base64
import requests

REPO = "AlendaSIA/Jaunais_step0-trigger"
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
    last_id = ctx.get("last_processed_id")
    in_progress = int(ctx.get("in_progress_id") or 0)

    ids = ctx.get("sales_ids_full") or ctx.get("sales_ids")

    if last_id is None:
        ctx["error"] = "Missing ctx.last_processed_id"
        return ctx
    if not ids:
        # nav ko apstrādāt -> beidzam bez kļūdas
        ctx["has_next_document"] = False
        ctx["next_document_id"] = None
        ctx["halt_pipeline"] = True
        ctx["halt_reason"] = "No sales IDs returned from PayTraq"
        return ctx

    # Ja jau ir dokuments apstrādē, NEDODAM nākamo
    if in_progress and in_progress > 0:
        ctx["has_next_document"] = False
        ctx["next_document_id"] = None
        ctx["halt_pipeline"] = True
        ctx["halt_reason"] = f"LOCKED: in_progress_id={in_progress}"
        return ctx

    ids_sorted = sorted(ids)
    next_id = None
    for i in ids_sorted:
        if i > int(last_id):
            next_id = int(i)
            break

    ctx["next_document_id"] = next_id
    ctx["has_next_document"] = next_id is not None

    # Ja nav nākamā dokumenta -> beidzam bez kļūdas
    if next_id is None:
        ctx["halt_pipeline"] = True
        ctx["halt_reason"] = "No next unprocessed document"
        return ctx

    # Uzliekam LOCK uzreiz GitHub state, lai neviens paralēls izsaukums nepaņem nākamo
    gh_token = os.getenv("GITHUB_TOKEN")
    if not gh_token:
        ctx["error"] = "Missing env: GITHUB_TOKEN (needed to set lock)"
        return ctx

    status_g, snippet = _github_put_text(
        gh_token,
        STATE_INPROGRESS_PATH,
        str(next_id),
        message=f"lock: set in_progress_id={next_id}",
    )
    ctx["github_lock_status"] = status_g
    if status_g not in (200, 201):
        ctx["error"] = "Failed to set lock (in_progress_id) in GitHub state"
        ctx["github_lock_error_snippet"] = snippet
        return ctx

    ctx["in_progress_id"] = next_id
    return ctx
