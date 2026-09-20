"""Pending triggers — the "ask every time" half of auto-run.

When a suggestion's runMode is "auto", autorun.py starts a run the moment it
finds new matching input (see runner.start_run). When runMode is "ask", it
raises a PendingTrigger here instead — nothing runs yet. The dashboard shows
these as a small "Mia found new input for X — run it now?" prompt; approving
one starts the exact same run a manual Run click would (runner.start_run,
triggered_by="auto"); dismissing one just clears the prompt. Either way,
autorun.py's watermark already moved past that message, so it won't ask
about the same one twice.

In-memory only, like runner.py's run store — fine for the hackathon, not
durable across an agent restart.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel


class PendingTrigger(BaseModel):
    id: str
    workflowKey: str
    suggestionId: str
    title: str
    description: str
    createdAt: int


_LOCK = threading.Lock()
_PENDING: dict[str, PendingTrigger] = {}


def create(workflow_key: str, suggestion_id: str, title: str, description: str) -> PendingTrigger:
    pending = PendingTrigger(
        id=str(uuid.uuid4()),
        workflowKey=workflow_key,
        suggestionId=suggestion_id,
        title=title,
        description=description,
        createdAt=int(datetime.now(timezone.utc).timestamp() * 1000),
    )
    with _LOCK:
        _PENDING[pending.id] = pending
    return pending


def list_pending() -> list[PendingTrigger]:
    with _LOCK:
        return sorted(_PENDING.values(), key=lambda p: p.createdAt, reverse=True)


def has_pending_for(workflow_key: str) -> bool:
    """True if workflow_key already has an unanswered prompt — autorun.py
    uses this so a quiet-but-not-yet-answered prompt doesn't pile up
    duplicates tick after tick."""
    with _LOCK:
        return any(p.workflowKey == workflow_key for p in _PENDING.values())


def resolve(pending_id: str) -> Optional[PendingTrigger]:
    """Remove and return a pending trigger; the caller decides whether that
    means starting a run (approve) or just discarding it (dismiss)."""
    with _LOCK:
        return _PENDING.pop(pending_id, None)
