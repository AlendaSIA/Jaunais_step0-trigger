from typing import Callable, Dict, Any, List, Tuple
from fastapi import HTTPException

StepFn = Callable[[Dict[str, Any]], Dict[str, Any]]

class Runner:
    def __init__(self, steps: List[Tuple[str, StepFn]]):
        self.steps = steps

    def list_steps(self) -> List[str]:
        return [name for name, _ in self.steps]

    def run_all(self, ctx: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if ctx is None:
            ctx = {}
        trace = []
        for name, fn in self.steps:
            try:
                ctx = fn(ctx)
                trace.append({"step": name, "ok": True})
            except HTTPException:
                trace.append({"step": name, "ok": False})
                raise
            except Exception as e:
                trace.append({"step": name, "ok": False, "error": str(e)})
                raise HTTPException(status_code=500, detail={"step": name, "error": str(e)})
        ctx["_trace"] = trace
        return ctx
