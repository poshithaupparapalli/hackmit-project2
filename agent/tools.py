"""Google API tools for MIA's agent (Poshitha's slice).

Each function is a small, hand-built capability the agent can call. The LLM can
only do what these tools expose. Targets (sheet id, calendar id) come from
config/env, never from a suggestion.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build

from . import config
from .oauth_flow import get_credentials


# --- Service builders (cache_discovery off to avoid noisy warnings) ---
def _service(name: str, version: str):
    return build(name, version, credentials=get_credentials(), cache_discovery=False)


# ---------------------------------------------------------------------------
# read_gmail
# ---------------------------------------------------------------------------
@dataclass
class GmailMessage:
    id: str
    thread_id: str
    subject: str
    sender: str
    date: str
    snippet: str
    body: str


def _decode_part(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", "replace")


def _extract_body(payload: dict) -> str:
    """Walk the MIME tree and pull the best-effort plain-text body."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return _decode_part(payload["body"]["data"])

    for part in payload.get("parts", []) or []:
        text = _extract_body(part)
        if text:
            return text

    # Fall back to any html body if no plain text found.
    if payload.get("mimeType") == "text/html" and payload.get("body", {}).get("data"):
        return _decode_part(payload["body"]["data"])
    return ""


def read_gmail(query: str | None = None) -> GmailMessage:
    """Read ONE Gmail message matching `query` (defaults to config query).

    Returns the newest matching message with headers + decoded body.
    """
    query = query or config.GMAIL_TEST_QUERY
    svc = _service("gmail", "v1")

    listing = (
        svc.users()
        .messages()
        .list(userId="me", q=query, maxResults=1)
        .execute()
    )
    messages = listing.get("messages", [])
    if not messages:
        raise RuntimeError(f"No Gmail message matched query: {query!r}")

    msg = (
        svc.users()
        .messages()
        .get(userId="me", id=messages[0]["id"], format="full")
        .execute()
    )

    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
    return GmailMessage(
        id=msg["id"],
        thread_id=msg.get("threadId", ""),
        subject=headers.get("subject", "(no subject)"),
        sender=headers.get("from", "(unknown)"),
        date=headers.get("date", ""),
        snippet=msg.get("snippet", ""),
        body=_extract_body(msg["payload"]).strip(),
    )


# ---------------------------------------------------------------------------
# append_to_sheet
# ---------------------------------------------------------------------------
def append_to_sheet(
    values: list, sheet_id: str | None = None, sheet_range: str | None = None
) -> dict:
    """Append ONE row to the configured expense sheet.

    `values` is a flat list of cell values for the row.
    Target sheet comes from config/env, not the caller's suggestion.
    """
    sheet_id = sheet_id or config.EXPENSE_SHEET_ID
    sheet_range = sheet_range or config.EXPENSE_SHEET_RANGE
    if not sheet_id:
        raise RuntimeError(
            "No sheet id configured. Set MIA_EXPENSE_SHEET_ID in agent/.env."
        )

    svc = _service("sheets", "v4")
    result = (
        svc.spreadsheets()
        .values()
        .append(
            spreadsheetId=sheet_id,
            range=sheet_range,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [values]},
        )
        .execute()
    )
    updates = result.get("updates", {})
    return {
        "updatedRange": updates.get("updatedRange"),
        "updatedRows": updates.get("updatedRows", 0),
        "sheetUrl": f"https://docs.google.com/spreadsheets/d/{sheet_id}",
    }


# ---------------------------------------------------------------------------
# create_calendar_event
# ---------------------------------------------------------------------------
def create_calendar_event(
    summary: str,
    start: datetime | None = None,
    duration_minutes: int = 30,
    description: str = "",
    calendar_id: str | None = None,
) -> dict:
    """Create ONE calendar event. Defaults to a 30-min event starting now."""
    calendar_id = calendar_id or config.CALENDAR_ID
    start = start or datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    end = start + timedelta(minutes=duration_minutes)

    svc = _service("calendar", "v3")
    event = (
        svc.events()
        .insert(
            calendarId=calendar_id,
            body={
                "summary": summary,
                "description": description,
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": end.isoformat()},
            },
        )
        .execute()
    )
    return {
        "eventId": event.get("id"),
        "htmlLink": event.get("htmlLink"),
        "start": event.get("start", {}).get("dateTime"),
    }
