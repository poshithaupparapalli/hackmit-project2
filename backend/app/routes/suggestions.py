import json

from fastapi import APIRouter, HTTPException

from app.db import get_conn, now_ms
from app.models import (
    Suggestion, SuggestionFeedbackRequest, SuggestionPatchRequest,
)

router = APIRouter()


def _row_to_suggestion(r) -> Suggestion:
    return Suggestion(
        id=r["id"], kind=r["kind"], title=r["title"], summary=r["summary"] or "",
        evidence=json.loads(r["evidence_json"] or "[]"),
        steps=json.loads(r["steps_json"] or "[]"),
        trigger=r["trigger"] or "", action=r["action"] or "",
        buildPrompt=r["build_prompt"] or "", workflowKey=r["workflow_key"],
        confidence=r["confidence"] or 0.0,
        timeSavedPerWeekMinutes=r["time_saved_per_week_minutes"] or 0.0,
        status=r["status"], createdAt=r["created_at"], updatedAt=r["updated_at"],
    )


@router.get("/suggestions", response_model=list[Suggestion])
def list_suggestions() -> list[Suggestion]:
    rows = get_conn().execute(
        "SELECT * FROM suggestions ORDER BY created_at DESC"
    ).fetchall()
    return [_row_to_suggestion(r) for r in rows]


@router.patch("/suggestions/{suggestion_id}", response_model=Suggestion)
def patch_suggestion(suggestion_id: str, body: SuggestionPatchRequest) -> Suggestion:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="suggestion not found")
    conn.execute(
        "UPDATE suggestions SET status = ?, updated_at = ? WHERE id = ?",
        (body.status, now_ms(), suggestion_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
    ).fetchone()
    return _row_to_suggestion(row)


@router.post("/suggestions/{suggestion_id}/feedback")
def suggestion_feedback(suggestion_id: str, body: SuggestionFeedbackRequest) -> dict:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="suggestion not found")
    now = now_ms()
    conn.execute(
        "INSERT INTO suggestion_feedback(suggestion_id, decision, user_edits, created_at) "
        "VALUES (?,?,?,?)",
        (suggestion_id, body.decision, body.userEdits, now),
    )
    # reflect accept/dismiss on the suggestion row; "edit" keeps status but
    # stores the correction for future analysis (A14/F4)
    new_status = {"accept": "accepted", "dismiss": "dismissed"}.get(body.decision)
    if new_status:
        conn.execute(
            "UPDATE suggestions SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, suggestion_id),
        )
    conn.commit()
    return {"ok": True}
