from typing import Any, Dict, List, Tuple, Callable

from steps import (
    step_00_read_state,
    step_01_fetch_sales_list,
    step_02_pick_next_doc,
    step_03_fetch_full_document,
    step_04_extract_client_data,
    step_05_pipedrive_ping,
    step_06_call_worker,
    step_08_finalize_state,
)

StepFn = Callable[[Dict[str, Any]], Dict[str, Any]]

STEPS: List[Tuple[str, StepFn]] = [
    ("00_read_state", step_00_read_state.run),
    ("01_fetch_sales_list", step_01_fetch_sales_list.run),
    ("02_pick_next_doc", step_02_pick_next_doc.run),
    ("03_fetch_full_document", step_03_fetch_full_document.run),
    ("04_extract_client_data", step_04_extract_client_data.run),
    ("05_pipedrive_ping", step_05_pipedrive_ping.run),
    ("06_call_worker", step_06_call_worker.run),
    ("08_finalize_state", step_08_finalize_state.run),
]


def list_steps() -> List[str]:
    return [name for name, _ in STEPS]


def _merge_payload_into_ctx(ctx: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ļauj debug/testos iedot override laukus top-level:
      {"last_processed_id":123, "skip_state_update":true, ...}
    """
    for k, v in (payload or {}).items():
        if k in ("step", "_debug", "mode"):
            continue
        ctx[k] = v
    return ctx


def run_pipeline(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    /run:
      payload = {}  -> pilns pipeline
    /debug:
      payload = {"step":"02_pick_next_doc"} -> palaidīs 00..02
    """
    payload = payload or {}
    debug_step = payload.get("step")

    ctx: Dict[str, Any] = {}
    ctx = _merge_payload_into_ctx(ctx, payload)

    trace = []
    for name, fn in STEPS:
        ctx["current_step"] = name
        try:
            ctx = fn(ctx) or ctx
            trace.append({"step": name, "ok": True})
        except Exception as e:
            ctx["status"] = "error"
            ctx["error"] = str(e)
            trace.append({"step": name, "ok": False, "error": str(e)})
            break

        # Zapier-stils: steps var uzlikt error/halt_pipeline bez exception
        if ctx.get("error"):
            ctx["status"] = ctx.get("status") or "error"
            break
        if ctx.get("halt_pipeline"):
            ctx["status"] = ctx.get("status") or "ok"
            break

        # DEBUG: ja prasīts konkrēts solis, apstājies uz tā
        if debug_step and name == debug_step:
            ctx["status"] = ctx.get("status") or "ok"
            break

    ctx["_trace"] = trace
    if "status" not in ctx:
        ctx["status"] = "ok"
    return ctx
