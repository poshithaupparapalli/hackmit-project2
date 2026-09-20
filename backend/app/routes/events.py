import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from app.auth import require_install
from app.db import get_conn, meta_set, now_ms
from app.models import EventBatchRequest, EventBatchResponse, MiaEvent, RejectedEvent

router = APIRouter()

MAX_DETAIL_BYTES = 2048


def _reject_reason(raw: dict) -> str | None:
    """Defense-in-depth checks beyond schema validation (privacy contract A5)."""
    try:
        ev = MiaEvent.model_validate(raw)
    except ValidationError as e:
        return f"schema: {e.errors()[0]['msg']}"
    if "?" in ev.path or "#" in ev.path:
        return "path contains query string or fragment"
    if ev.detail is not None and len(json.dumps(ev.detail)) > MAX_DETAIL_BYTES:
        return "detail exceeds 2KB"
    label = (ev.detail or {}).get("label")
    if isinstance(label, str) and len(label) > 80:
        return "label exceeds 80 chars"
    return None


@router.post("/events/batch", response_model=EventBatchResponse)
def ingest_batch(
    body: dict,
    install_id: str = Depends(require_install),
) -> EventBatchResponse:
    try:
        req = EventBatchRequest.model_validate(body)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())
    if len(req.events) > 250:
        raise HTTPException(status_code=400, detail="max 250 events per batch")

    conn = get_conn()
    accepted: list[str] = []
    rejected: list[RejectedEvent] = []
    received = now_ms()

    for raw in req.events:
        event_id = str(raw.get("id", ""))
        reason = _reject_reason(raw)
        if reason:
            rejected.append(RejectedEvent(id=event_id or "unknown", reason=reason))
            continue
        ev = MiaEvent.model_validate(raw)
        cur = conn.execute(
            """INSERT OR IGNORE INTO events
               (id, install_id, session_id, timestamp, sequence, tab_id, frame_id,
                type, host, path, title, detail_json, context_json, received_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ev.id,
                install_id,
                ev.sessionId,
                ev.timestamp,
                ev.sequence,
                ev.tabId,
                ev.frameId,
                ev.type,
                ev.host,
                ev.path,
                ev.title,
                json.dumps(ev.detail) if ev.detail is not None else None,
                ev.context.model_dump_json() if ev.context else None,
                received,
            ),
        )
        # INSERT OR IGNORE rowcount=0 means duplicate (installId, id) — still
        # "accepted" so the extension removes it from its queue on retry.
        accepted.append(ev.id)
    conn.commit()

    meta_set(conn, "last_event_at", str(received))
    return EventBatchResponse(accepted=accepted, rejected=rejected, serverTime=now_ms())
