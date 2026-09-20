import sqlite3

from fastapi import APIRouter, HTTPException

from app import chat as chat_logic
from app.db import get_conn
from app.models import ChatMessage, ChatRequest, ChatResponse

router = APIRouter()


def _get_suggestion_row(conn: sqlite3.Connection, suggestion_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="suggestion not found")
    return row


@router.get("/suggestions/{suggestion_id}/chat", response_model=list[ChatMessage])
def get_chat(suggestion_id: str) -> list[ChatMessage]:
    conn = get_conn()
    _get_suggestion_row(conn, suggestion_id)
    return [ChatMessage(**m) for m in chat_logic.list_messages(conn, suggestion_id)]


@router.post("/suggestions/{suggestion_id}/chat", response_model=ChatResponse)
def post_chat(suggestion_id: str, body: ChatRequest) -> ChatResponse:
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message must not be blank")
    conn = get_conn()
    row = _get_suggestion_row(conn, suggestion_id)
    reply = chat_logic.send_message(conn, row, message)
    messages = chat_logic.list_messages(conn, suggestion_id)
    return ChatResponse(reply=ChatMessage(**reply), messages=[ChatMessage(**m) for m in messages])
