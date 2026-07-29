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


def _read_last_processed(token: str):
    """Fresh read of the current forward cursor (int), or None if unavailable."""
    url = f"https://api.github.com/repos/{_repo_full()}/contents/{STATE_LAST_PATH}"
    try:
        r = requests.get(url, headers=_headers(token), timeout=20)
        if r.status_code != 200:
            return None
        data = r.json() or {}
        raw = base64.b64decode(data.get("content") or "").decode().strip()
        return int(raw) if raw else None
    except Exception:
        return None


def _advance_cursor(token: str, ctx: dict, new_id, note: str = ""):
    """Monotonic forward cursor: NEVER move last_processed_id backwards.

    Root-cause guard for the 'booking an old draft rolls the cursor back' bug:
    under concurrent /run executions (scheduler + Mozello webhook, no lock) a
    stale in_progress_id could be written as the cursor, dropping it to an old
    draft's id and forcing step0 to re-process every later order one-by-one.
    We only ever advance; any id <= the current cursor is ignored.
    """
    try:
        new_id = int(new_id)
    except Exception:
        ctx["github_finalize_last_status"] = "skipped(bad_id)"
        return

    floor = 0
    for cand in (_read_last_processed(token), ctx.get("github_state_last_processed_id")):
        try:
            if cand is not None and int(cand) > floor:
                floor = int(cand)
        except Exception:
            pass

    if new_id <= floor:
        ctx["github_finalize_last_status"] = f"skipped(monotonic {new_id}<={floor})"
        ctx["cursor_rollback_prevented"] = {"attempted": new_id, "floor": floor}
        return

    _, st_last, _ = _github_put_text(
        token,
        STATE_LAST_PATH,
        str(new_id),
        message=f"state: set last_processed_id={new_id}{note}",
    )
    ctx["github_finalize_last_status"] = st_last


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
    # tracked in pending and will be processed once it books. (Monotonic: only forward.)
    if is_forward_draft and fwd_id:
        _advance_cursor(token, ctx, int(fwd_id), note=" (draft deferred)")
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

    # Normal booked forward doc: advance cursor on ack. Prefer the freshly-picked
    # forward doc id; only fall back to in_progress_id if next_document_id is missing
    # (a stale in_progress_id must never become the cursor — that was the rollback bug).
    doc_id = ctx.get("next_document_id") or ctx.get("in_progress_id")
    if not ack or not doc_id:
        ctx["github_finalize_clear_status"] = "skipped(no_ack_or_no_doc)"
        return ctx

    _advance_cursor(token, ctx, int(doc_id), note="")

    _, st_clear, _ = _github_put_text(
        token,
        STATE_INPROGRESS_PATH,
        "0",
        message="state: clear in_progress_id",
    )
    ctx["github_finalize_clear_status"] = st_clear

    return ctx
