from fastapi import FastAPI, Request
from runner import Runner

from steps import step_00_read_state
from steps import step_01_fetch_sales_list
from steps import step_02_pick_next_doc
from steps import step_03_fetch_full_document
from steps import step_04_extract_client_data
from steps import step_05_pipedrive_ping
from steps import step_06_call_worker
from steps import step_08_finalize_state

app = FastAPI()

runner = Runner(steps=[
    ("00_read_state", step_00_read_state.run),
    ("01_fetch_sales_list", step_01_fetch_sales_list.run),
    ("02_pick_next_doc", step_02_pick_next_doc.run),
    ("03_fetch_full_document", step_03_fetch_full_document.run),
    ("04_extract_client_data", step_04_extract_client_data.run),
    ("05_pipedrive_ping", step_05_pipedrive_ping.run),
    ("06_call_worker", step_06_call_worker.run),
    ("08_finalize_state", step_08_finalize_state.run),
])


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/run")
async def run(request: Request):
    """
    Default (no JSON body): same as before -> processes "next doc" using GitHub state.

    Optional JSON body for SAFE TEST RUNS (default skip_state_update=True when any filter is used):
      {
        "doc_id": 15560678,
        "doc_title": "M-860325-29886",
        "date": "2026-02-09",
        "date_from": "2026-02-09",
        "date_to": "2026-02-10",
        "scan_limit": 200,
        "update_state": false
      }

    Note:
      - doc_id is best (fastest).
      - doc_title scans and matches against DocumentRef or Comment (substring).
      - date/date_from/date_to scan and pick FIRST matching doc (single-run).
    """
    payload = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    if payload is None:
        payload = {}

    ctx = {}

    # If any filter is used, default to test mode (don't modify GitHub state)
    has_filter = any([
        payload.get("doc_id") is not None,
        payload.get("doc_title"),
        payload.get("date"),
        payload.get("date_from"),
        payload.get("date_to"),
    ])

    update_state = bool(payload.get("update_state")) if "update_state" in payload else (not has_filter)
    ctx["skip_state_update"] = (not update_state)

    # Pass overrides to Step02
    if payload.get("doc_id") is not None:
        ctx["override_doc_id"] = int(payload["doc_id"])

    if payload.get("doc_title"):
        ctx["override_doc_title"] = str(payload["doc_title"]).strip()

    if payload.get("date"):
        ctx["override_date"] = str(payload["date"]).strip()

    if payload.get("date_from"):
        ctx["override_date_from"] = str(payload["date_from"]).strip()

    if payload.get("date_to"):
        ctx["override_date_to"] = str(payload["date_to"]).strip()

    if payload.get("scan_limit"):
        ctx["scan_limit"] = int(payload["scan_limit"])

    # Run pipeline
    return runner.run_all(ctx)
