"""Mia's per-suggestion chat: edits and questions about a specific suggestion.

Replaces a single "what should Mia change?" textarea with an actual back-
and-forth, grounded in that suggestion's own title/summary/steps/evidence so
Mia can answer questions about why she suggested it, not just take dictation.

OpenAI is tried first; an offline reply is the fallback so the thread still
works (and the message still gets recorded) with no network. Every user
message is also written to suggestion_feedback (decision="edit") so the
existing correction/rule-learning path in analyst.py keeps working exactly
as it did with the old textarea — the chat is a friendlier way to write the
same correction, not a separate feature.
"""
import json
import os
import sqlite3
from typing import List

from app.db import now_ms

MAX_HISTORY_TURNS = 20

_SYSTEM_TEMPLATE = (
    "You are Mia, discussing ONE specific automation suggestion with the "
    "person deciding whether to run it. Mia notices repeated, unwritten "
    "workflows by watching sanitized browser activity and proposes them; "
    "she never runs anything without explicit approval. Be warm but concise "
    "and factual: describe what was observed, never judge the person, no "
    "exclamation points, no hedging, no filler. Answer questions about why "
    "this was suggested using only the evidence given below — never "
    "invent details. If they ask for a change (a scope limit, a different "
    "destination, an exception), acknowledge it plainly and confirm it has "
    "been noted as a correction on this suggestion; do not claim to have "
    "edited the suggestion's fields yourself, since only the person decides "
    "what actually runs. Keep replies to 2-3 sentences unless asked for "
    "more.\n\nThe suggestion being discussed (JSON):\n{context}"
)


def _suggestion_context(row: sqlite3.Row) -> str:
    return json.dumps({
        "title": row["title"],
        "summary": row["summary"],
        "kind": row["kind"],
        "steps": json.loads(row["steps_json"] or "[]"),
        "evidence": json.loads(row["evidence_json"] or "[]"),
        "trigger": row["trigger"],
        "action": row["action"],
        "workflowKey": row["workflow_key"],
        "status": row["status"],
    })


def list_messages(conn: sqlite3.Connection, suggestion_id: str) -> List[dict]:
    rows = conn.execute(
        "SELECT role, content, created_at FROM suggestion_chat "
        "WHERE suggestion_id = ? ORDER BY created_at",
        (suggestion_id,),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"], "createdAt": r["created_at"]} for r in rows]


def _append(conn: sqlite3.Connection, suggestion_id: str, role: str, content: str) -> dict:
    created = now_ms()
    conn.execute(
        "INSERT INTO suggestion_chat(suggestion_id, role, content, created_at) VALUES (?,?,?,?)",
        (suggestion_id, role, content, created),
    )
    conn.commit()
    return {"role": role, "content": content, "createdAt": created}


def _reply_offline(message: str) -> str:  # noqa: ARG001 — kept for a consistent signature
    return (
        "Got it — I've saved that as a note on this suggestion. "
        "(Live replies need an OPENAI_API_KEY configured on the backend; "
        "your message is still recorded as a correction.)"
    )


def _reply_llm(context: str, history: List[dict], message: str) -> str:
    from openai import OpenAI

    client = OpenAI(timeout=20)
    messages = [{"role": "system", "content": _SYSTEM_TEMPLATE.format(context=context)}]
    for m in history[-MAX_HISTORY_TURNS:]:
        messages.append({"role": "user" if m["role"] == "user" else "assistant", "content": m["content"]})
    messages.append({"role": "user", "content": message})
    resp = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        messages=messages,
    )
    text = (resp.choices[0].message.content or "").strip()
    return text or _reply_offline(message)


def send_message(conn: sqlite3.Connection, suggestion_row: sqlite3.Row, message: str) -> dict:
    """Append the user's message, record it as a correction, and return Mia's reply."""
    suggestion_id = suggestion_row["id"]
    history = list_messages(conn, suggestion_id)
    _append(conn, suggestion_id, "user", message)
    conn.execute(
        "INSERT INTO suggestion_feedback(suggestion_id, decision, user_edits, created_at) VALUES (?,?,?,?)",
        (suggestion_id, "edit", message, now_ms()),
    )
    conn.commit()

    context = _suggestion_context(suggestion_row)
    if os.environ.get("OPENAI_API_KEY"):
        try:
            reply_text = _reply_llm(context, history, message)
        except Exception:
            reply_text = _reply_offline(message)
    else:
        reply_text = _reply_offline(message)
    return _append(conn, suggestion_id, "mia", reply_text)
