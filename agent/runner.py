"""Workflow runner + run-status state machine (MIA_CONTRACTS.md B4/B5).

Produces the frozen WorkflowRun shape:
    { runId, workflowKey, status, steps[], result, error, approvalRequest }
identical to backend/data/canned_run.json so a live run and the fallback are
interchangeable to the frontend.

Execution runs in a background thread; run state is kept in memory (fine for the
hackathon — not durable across a process restart). The B5 approval boundary is a
first-class feature: a workflow step marked consequential pauses the run at
status="needs_approval" until POST /approve (or /approve?decision=cancel).
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Callable, Literal, Optional

from pydantic import BaseModel

from . import config
from .extract import extract_receipt
from .tools import append_to_sheet, create_calendar_event, read_gmail

RunStatus = Literal["running", "done", "error", "needs_approval"]
StepState = Literal["pending", "running", "done", "error"]


class RunStep(BaseModel):
    label: str
    state: StepState = "pending"


class ApprovalRequest(BaseModel):
    title: str
    description: str


class WorkflowRun(BaseModel):
    runId: str
    workflowKey: str
    status: RunStatus = "running"
    steps: list[RunStep]
    result: Optional[dict] = None
    error: Optional[str] = None
    approvalRequest: Optional[ApprovalRequest] = None
    # Additive fields (not in the original B4 shape) — needed to list run
    # history for the dashboard. Optional so canned_run.json stays valid.
    suggestionId: Optional[str] = None
    startedAt: Optional[int] = None
    triggeredBy: Literal["manual", "auto"] = "manual"


class ApprovalCancelled(Exception):
    """Raised inside a workflow when the user cancels at an approval checkpoint."""


class _RunHandle:
    def __init__(self, run: WorkflowRun):
        self.run = run
        self.approval_event = threading.Event()
        self.approval_decision: Optional[str] = None  # "approve" | "cancel"
        self.thread: Optional[threading.Thread] = None


# ---------------------------------------------------------------------------
# In-memory run store
# ---------------------------------------------------------------------------
_RUNS: dict[str, _RunHandle] = {}
_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunContext:
    """Passed to a workflow function; the only way it mutates run state."""

    def __init__(self, handle: _RunHandle):
        self._h = handle

    @property
    def run(self) -> WorkflowRun:
        return self._h.run

    def _step_index(self, label: str) -> int:
        for i, s in enumerate(self._h.run.steps):
            if s.label == label:
                return i
        raise KeyError(label)

    def start_step(self, label: str) -> None:
        with _LOCK:
            self._h.run.steps[self._step_index(label)].state = "running"

    def finish_step(self, label: str) -> None:
        with _LOCK:
            self._h.run.steps[self._step_index(label)].state = "done"

    def fail_step(self, label: str) -> None:
        with _LOCK:
            self._h.run.steps[self._step_index(label)].state = "error"

    def checkpoint(self, title: str, description: str) -> None:
        """B5 Approval 2: pause on an unexpected consequential action.

        Blocks the worker thread until /approve or /approve?decision=cancel.
        Raises ApprovalCancelled if the user cancels.
        """
        with _LOCK:
            self._h.run.status = "needs_approval"
            self._h.run.approvalRequest = ApprovalRequest(title=title, description=description)
        self._h.approval_event.wait()
        with _LOCK:
            decision = self._h.approval_decision
            self._h.run.approvalRequest = None
            self._h.run.status = "running"
        self._h.approval_event.clear()
        self._h.approval_decision = None
        if decision == "cancel":
            raise ApprovalCancelled(title)


# ---------------------------------------------------------------------------
# Workflows (the "agent choosing the right tool per workflowKey" seam — B7)
# ---------------------------------------------------------------------------
def _gmail_to_sheet(ctx: RunContext, suggestion_id: str) -> dict:
    # Step labels MUST match backend/data/canned_run.json for fallback parity.
    ctx.start_step("Reading receipt email")
    msg = read_gmail(config.GMAIL_TEST_QUERY)
    ctx.finish_step("Reading receipt email")

    ctx.start_step("Extracting amount")
    receipt = extract_receipt(
        body=msg.body or msg.snippet,
        subject=msg.subject,
        sender=msg.sender,
        date_header=msg.date,
    )
    if not receipt.amount:
        ctx.fail_step("Extracting amount")
        raise RuntimeError(
            f"Could not extract an amount from email {msg.subject!r}"
        )
    ctx.finish_step("Extracting amount")

    ctx.start_step("Opening expense tracker")
    # (No consequential action here — read + append are within the approved plan,
    #  so no checkpoint. The mechanism exists; this workflow simply never trips it.)
    ctx.finish_step("Opening expense tracker")

    ctx.start_step("Appending row")
    row = [receipt.date, receipt.vendor,
           f"{receipt.currency}{receipt.amount}".strip(), msg.subject]
    append_result = append_to_sheet(row)
    ctx.finish_step("Appending row")

    return {
        "rowsAppended": append_result["updatedRows"],
        "sheetUrl": append_result["sheetUrl"],
        "updatedRange": append_result["updatedRange"],
        "row": {
            "date": receipt.date,
            "vendor": receipt.vendor,
            "amount": receipt.amount,
            "currency": receipt.currency,
            "sourceSubject": msg.subject,
        },
    }


WorkflowFn = Callable[[RunContext, str], dict]

# workflowKey -> (ordered step labels, execute fn). Only "working" B7 rows appear.
WORKFLOWS: dict[str, tuple[list[str], WorkflowFn]] = {
    "gmail_to_sheet": (
        ["Reading receipt email", "Extracting amount",
         "Opening expense tracker", "Appending row"],
        _gmail_to_sheet,
    ),
}

# workflowKey -> zero-arg function returning the Gmail search query that
# defines "there's new work for this workflow" (autorun.py polls these).
# A workflowKey with no entry here is manual-Run-only — auto-run never picks
# it up. Populated for gmail_to_sheet below; agent/workflows/*.py register
# their own entry from register(), same pattern as WORKFLOWS.
TRIGGER_QUERIES: dict[str, Callable[[], str]] = {
    "gmail_to_sheet": lambda: config.GMAIL_TEST_QUERY,
}


def is_known_workflow(workflow_key: str) -> bool:
    return workflow_key in WORKFLOWS


def is_run_active(workflow_key: str) -> bool:
    """True if some run of this workflow is currently mid-flight — used by
    autorun.py so a slow poll tick never starts a second overlapping run."""
    with _LOCK:
        return any(
            h.run.workflowKey == workflow_key and h.run.status in ("running", "needs_approval")
            for h in _RUNS.values()
        )


def discover_workflows() -> list[str]:
    """Import every module in agent/workflows/ and call its register() if present.

    Lets new workflow files load automatically on server startup with no edits to
    shared code. Only ADDS registrations — gmail_to_sheet (defined in this module)
    is never touched. A broken or import-failing workflow module is skipped with a
    warning rather than taking down the server. Idempotent: safe to call more than
    once, and safe even if a module also self-registers on import.
    """
    import importlib
    import pkgutil

    from . import workflows as workflows_pkg

    discovered: list[str] = []
    for modinfo in pkgutil.iter_modules(workflows_pkg.__path__):
        name = modinfo.name
        if name.startswith("_") or name.startswith("test_"):
            continue
        full = f"{workflows_pkg.__name__}.{name}"
        try:
            module = importlib.import_module(full)
            reg = getattr(module, "register", None)
            if callable(reg):
                reg()
        except Exception as exc:  # noqa: BLE001 — one bad workflow must not break others
            print(f"[workflows] skipped {full}: {type(exc).__name__}: {exc}")
            continue
        discovered.append(name)
    return discovered


# ---------------------------------------------------------------------------
# Public API used by the FastAPI layer
# ---------------------------------------------------------------------------
def start_run(workflow_key: str, suggestion_id: str, triggered_by: Literal["manual", "auto"] = "manual") -> str:
    """Create a run and kick off execution in a background thread. Returns runId."""
    if workflow_key not in WORKFLOWS:
        raise KeyError(workflow_key)

    labels, fn = WORKFLOWS[workflow_key]
    run_id = str(uuid.uuid4())
    run = WorkflowRun(
        runId=run_id,
        workflowKey=workflow_key,
        status="running",
        steps=[RunStep(label=l) for l in labels],
        suggestionId=suggestion_id,
        startedAt=int(datetime.now(timezone.utc).timestamp() * 1000),
        triggeredBy=triggered_by,
    )
    handle = _RunHandle(run)
    with _LOCK:
        _RUNS[run_id] = handle

    def _worker() -> None:
        ctx = RunContext(handle)
        try:
            result = fn(ctx, suggestion_id)
            with _LOCK:
                run.result = result
                run.status = "done"
        except ApprovalCancelled as exc:
            with _LOCK:
                run.status = "error"
                run.error = f"cancelled at approval: {exc}"
        except Exception as exc:  # noqa: BLE001 — surface any tool/exec failure
            with _LOCK:
                run.status = "error"
                run.error = f"{type(exc).__name__}: {exc}"

    t = threading.Thread(target=_worker, daemon=True, name=f"run-{run_id[:8]}")
    handle.thread = t
    t.start()
    return run_id


def get_run(run_id: str) -> Optional[WorkflowRun]:
    with _LOCK:
        handle = _RUNS.get(run_id)
        # return a copy so callers can't mutate live state
        return handle.run.model_copy(deep=True) if handle else None


def list_runs(limit: int = 50) -> list[WorkflowRun]:
    """Most-recent-first run history for the dashboard. In-memory only —
    does not survive an agent process restart (fine for the hackathon)."""
    with _LOCK:
        runs = [h.run.model_copy(deep=True) for h in _RUNS.values()]
    runs.sort(key=lambda r: r.startedAt or 0, reverse=True)
    return runs[:limit]


def approve_run(run_id: str, decision: str = "approve") -> Optional[WorkflowRun]:
    """Resume a run waiting at an approval checkpoint. decision: approve | cancel."""
    with _LOCK:
        handle = _RUNS.get(run_id)
        if handle is None:
            return None
        if handle.run.status != "needs_approval":
            # Idempotent-ish: nothing to approve; return current state.
            return handle.run.model_copy(deep=True)
        handle.approval_decision = "cancel" if decision == "cancel" else "approve"
    handle.approval_event.set()
    return get_run(run_id)
