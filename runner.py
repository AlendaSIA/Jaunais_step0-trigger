from steps import (
    step_00_read_state,
    step_01_fetch_sales_list,
    step_02_pick_next_doc,
    step_03_fetch_full_document,
    step_04_extract_client_data,
    step_05_pipedrive_ping,
    step_06_call_worker,      # <-- JAUNS
    step_08_finalize_state,
)

STEPS = [
    ("00_read_state", step_00_read_state.run),
    ("01_fetch_sales_list", step_01_fetch_sales_list.run),
    ("02_pick_next_doc", step_02_pick_next_doc.run),
    ("03_fetch_full_document", step_03_fetch_full_document.run),
    ("04_extract_client_data", step_04_extract_client_data.run),
    ("05_pipedrive_ping", step_05_pipedrive_ping.run),
    ("06_call_worker", step_06_call_worker.run),   # <-- JAUNS
    ("08_finalize_state", step_08_finalize_state.run),
]


def run_all():
    ctx = {}
    for name, fn in STEPS:
        ctx["current_step"] = name
        ctx = fn(ctx)

        # ja ir kļūda -> stop
        if ctx.get("error"):
            ctx["status"] = "error"
            return ctx

        # ja jābeidz normāli -> stop bez kļūdas
        if ctx.get("halt_pipeline"):
            ctx["status"] = "ok"
            return ctx

    ctx["status"] = "ok"
    return ctx


def run_debug(payload: dict):
    mode = payload.get("mode", "step")
    ctx = payload.get("ctx") or {}

    if mode == "step":
        step = payload.get("step")
        if not step:
            return {"status": "error", "error": "Missing 'step' in payload"}
        return _run_only(step, ctx)

    if mode == "until":
        until = payload.get("until")
        if not until:
            return {"status": "error", "error": "Missing 'until' in payload"}
        return _run_until(until, ctx)

    return {"status": "error", "error": f"Unknown mode: {mode}"}


def _run_only(step_name: str, ctx: dict):
    for name, fn in STEPS:
        if name == step_name:
            ctx["current_step"] = name
            ctx = fn(ctx)
            ctx["status"] = "error" if ctx.get("error") else "ok"
            return ctx
    return {"status": "error", "error": f"Step not found: {step_name}"}


def _run_until(until_name: str, ctx: dict):
    for name, fn in STEPS:
        ctx["current_step"] = name
        ctx = fn(ctx)

        if ctx.get("error"):
            ctx["status"] = "error"
            return ctx

        if ctx.get("halt_pipeline"):
            ctx["status"] = "ok"
            return ctx

        if name == until_name:
            ctx["status"] = "ok"
            return ctx

    return {"status": "error", "error": f"Until-step not found: {until_name}"}
