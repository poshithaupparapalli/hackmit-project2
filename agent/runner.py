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


def is_known_workflow(workflow_key: str) -> bool:
    return workflow_key in WORKFLOWS


# ---------------------------------------------------------------------------
# Public API used by the FastAPI layer
# ---------------------------------------------------------------------------
def start_run(workflow_key: str, suggestion_id: str) -> str:
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
