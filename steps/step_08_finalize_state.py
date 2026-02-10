import os
import requests

GITHUB_STATE_URL = os.getenv("GITHUB_STATE_URL")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")


def _headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def run(ctx: dict):
    """
    Step08: finalize state.
    Default: if ctx["pipedrive_ack"] True -> set last_processed_id and clear in_progress lock.

    NEW:
      if ctx["skip_state_update"] True -> do NOT write anything to GitHub.
      (safe for tests so we don't mess with normal "next doc" flow)
    """
    skip_state_update = bool(ctx.get("skip_state_update"))

    if skip_state_update:
        ctx["github_state_last_status"] = "skipped(test_mode)"
        ctx["github_finalize_clear_status"] = "skipped(test_mode)"
        ctx["github_finalize_last_status"] = "skipped(test_mode)"
        return ctx

    ack = bool(ctx.get("pipedrive_ack"))
    doc_id = ctx.get("in_progress_id") or ctx.get("next_document_id")

    if not ack or not doc_id:
        ctx["github_finalize_clear_status"] = "skipped(no_ack_or_no_doc)"
        return ctx

    # set last_processed_id
    url_last = f"{GITHUB_STATE_URL}/last_processed"
    r1 = requests.put(url_last, headers=_headers(), json={"last_processed_id": int(doc_id)}, timeout=30)
    ctx["github_finalize_last_status"] = r1.status_code

    # clear in_progress lock
    url_clear = f"{GITHUB_STATE_URL}/in_progress"
    r2 = requests.put(url_clear, headers=_headers(), json={"in_progress_id": 0}, timeout=30)
    ctx["github_finalize_clear_status"] = r2.status_code

    return ctx
