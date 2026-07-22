import os
import base64
import requests

DEFAULT_OWNER = "AlendaSIA"
DEFAULT_REPO = "Jaunais_step0-trigger"

STATE_LAST_PATH = "state/last_processed_id.txt"
STATE_INPROGRESS_PATH = "state/in_progress_id.txt"
STATE_PENDING_PATH = "state/pending_draft_ids.txt"


def _repo_full() -> str:
    owner = os.getenv("GITHUB_OWNER") or DEFAULT_OWNER
    repo = os.getenv("GITHUB_REPO") or DEFAULT_REPO
    return f"{owner}/{repo}"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }


def _commit_message(message: str) -> str:
    msg = (message or "").strip()
    if msg.startswith("[skip ci]"):
        return msg
    return f"[skip ci] {msg}"


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
        "message": _commit_message(message),
        "content": base64.b64encode(text.encode("utf-8")).decode("utf-8"),
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=_headers(token), json=payload, timeout=30)
    return r.json() if r.content else None, r.status_code, None


def _worker_all_steps_ok(ctx: dict) -> bool:
    try:
        code = int(ctx.get("worker_status_code") or 0)
    except Exception:
        code = 0
    if code != 200:
        return False

    wrj = ctx.get("worker_response_json") or {}
    if not isinstance(wrj, dict):
        return False

    status = (wrj.get("status") or "").strip().lower()
    if status not in ("created", "updated"):
        return False

    tr = wrj.get("_trace") or []
    if not isinstance(tr, list) or not tr:
        return False

    for it in tr:
        if not isinstance(it, dict):
            return False
        if it.get("ok") is not True:
            return False

    return True


def run(ctx: dict):
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        ctx["error"] = "Missing env: GITHUB_TOKEN"
        return ctx

    skip_state_update = bool(ctx.get("skip_state_update"))
    if skip_state_update:
        ctx["github_finalize_clear_status"] = "skipped(test_mode)"
        ctx["github_finalize_last_status"] = "skipped(test_mode)"
        return ctx

    ack = _worker_all_steps_ok(ctx)
    ctx["github_finalize_ack"] = ack

    picked_by = ctx.get("picked_by")
    is_pending_pick = (picked_by == "pending_draft_ready")
    # A forward-scan doc that was a draft and got skipped by the worker → defer it.
    is_forward_draft = bool(ctx.get("worker_skipped_draft")) and picked_by == "normal_after_last_processed"

    # ---- pending list maintenance ----
    orig_pending = sorted({int(x) for x in (ctx.get("pending_list") or [])})
    pending = set(orig_pending)
    pending -= {int(x) for x in (ctx.get("pending_drops") or [])}  # voided/gone

    fwd_id = ctx.get("next_document_id")
    if is_forward_draft and fwd_id:
        pending.add(int(fwd_id))  # remember the deferred draft
    if is_pending_pick and ack and fwd_id:
        pending.discard(int(fwd_id))  # processed successfully → stop tracking

    new_pending = sorted(pending)
    if new_pending != orig_pending:
        body = ("\n".join(str(i) for i in new_pending) + "\n") if new_pending else ""
        _, st_pend, _ = _github_put_text(
            token,
            STATE_PENDING_PATH,
            body,
            message=f"state: pending_draft_ids -> {new_pending}",
        )
        ctx["github_finalize_pending_status"] = st_pend

    # ---- cursor rules ----
    # Forward draft: advance the cursor PAST it (never block the queue). The doc is now
    # tracked in pending and will be processed once it books.
    if is_forward_draft and fwd_id:
        _, st_last, _ = _github_put_text(
            token,
            STATE_LAST_PATH,
            str(int(fwd_id)),
            message=f"state: set last_processed_id={int(fwd_id)} (draft deferred)",
        )
        ctx["github_finalize_last_status"] = st_last
        _, st_clear, _ = _github_put_text(
            token, STATE_INPROGRESS_PATH, "0", message="state: clear in_progress_id"
        )
        ctx["github_finalize_clear_status"] = st_clear
        return ctx

    # Pending doc: NEVER touch the forward cursor (its id is already behind it).
    if is_pending_pick:
        if ack:
            _, st_clear, _ = _github_put_text(
                token, STATE_INPROGRESS_PATH, "0",
                message="state: clear in_progress_id (pending processed)",
            )
            ctx["github_finalize_clear_status"] = st_clear
        else:
            ctx["github_finalize_clear_status"] = "kept(pending_not_acked)"
        return ctx

    # Normal booked forward doc: existing behavior (advance cursor on ack).
    doc_id = ctx.get("in_progress_id") or ctx.get("next_document_id")
    if not ack or not doc_id:
        ctx["github_finalize_clear_status"] = "skipped(no_ack_or_no_doc)"
        return ctx

    _, st_last, _ = _github_put_text(
        token,
        STATE_LAST_PATH,
        str(int(doc_id)),
        message=f"state: set last_processed_id={int(doc_id)}",
    )
    ctx["github_finalize_last_status"] = st_last

    _, st_clear, _ = _github_put_text(
        token,
        STATE_INPROGRESS_PATH,
        "0",
        message="state: clear in_progress_id",
    )
    ctx["github_finalize_clear_status"] = st_clear

    return ctx
