"""Email -> Calendar, registered into the existing B4 runner on import.

Launch without modifying shared files:
    uvicorn agent.workflows.email_to_calendar:app --port 8010

Or import this module once before using agent.runner.start_run(). The stock
agent.server entry point does not discover workflow modules automatically.

Set MIA_CALENDAR_GMAIL_QUERY to select the source email (falls back to the
existing Gmail query). Supported email format, for example:
    Start: 2026-09-21T14:00:00-04:00
    End: 2026-09-21T14:45:00-04:00
    Attendees: Alice <alice@example.com>, bob@example.com
Also accepts Date: September 21, 2026 with Time: 2:00 PM and
Timezone: America/New_York. An explicit Duration: 45 minutes can replace End.
Missing or ambiguous meeting fields fail before any Calendar write.
Guest invitations pause at the existing B5 approval checkpoint.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build

from .. import config, runner
from ..oauth_flow import get_credentials
from ..tools import read_gmail

WORKFLOW_KEY = "email_to_calendar"
STEP_LABELS = ["Reading email", "Extracting meeting details", "Creating event"]
_EMAIL = re.compile(r"[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+")


def _fields(body: str) -> dict[str, str]:
    fields = {}
    for line in body.splitlines():
        match = re.fullmatch(
            r"\s*(start|end|date|time|timezone|duration|attendees|location|title)\s*:\s*(.+?)\s*",
            line, re.IGNORECASE,
        )
        if match:
            key, value = match.group(1).lower(), match.group(2)
            if key in fields:
                raise ValueError(f"Multiple {key} fields; select one meeting email.")
            fields[key] = value
    return fields


def _datetime(value: str, zone: str | None) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not re.search(r"[T ]\d{2}:\d{2}", value):
            raise ValueError("A meeting time is required.")
    except ValueError:
        result = None
        for fmt in ("%B %d, %Y %I:%M %p", "%b %d, %Y %I:%M %p",
                    "%Y-%m-%d %I:%M %p", "%B %d, %Y %I %p"):
            try:
                result = datetime.strptime(value, fmt)
                break
            except ValueError:
                pass
        if result is None:
            raise ValueError("Use an explicit meeting date and time, preferably ISO 8601.")
    if result.tzinfo is None:
        if not zone:
            raise ValueError("Meeting time needs a UTC offset or Timezone field.")
        tz = ZoneInfo(zone)
        first, second = result.replace(tzinfo=tz, fold=0), result.replace(tzinfo=tz, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise ValueError("Ambiguous or nonexistent daylight-saving time; specify a UTC offset.")
        result = first
    return result


def extract_meeting(body: str, subject: str = "") -> dict:
    """Conservative, offline extraction; never guess dates, guests or duration."""
    fields = _fields(body)
    zone = fields.get("timezone") or os.getenv("MIA_CALENDAR_TIMEZONE")
    start_text = fields.get("start")
    if not start_text and fields.get("date") and fields.get("time"):
        start_text = f"{fields['date']} {fields['time']}"
    # Ordinary prose with a single explicit ISO start/end also works.
    if not start_text:
        stamps = re.findall(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})", body)
        if len(stamps) != 2:
            raise ValueError("Email must identify one meeting start and end (or duration).")
        start_text, fields["end"] = stamps
    start = _datetime(start_text, zone)
    if "end" in fields:
        end = _datetime(fields["end"], zone)
    else:
        duration = re.fullmatch(r"(\d+)\s*(?:minutes?|mins?)", fields.get("duration", ""), re.I)
        if not duration:
            raise ValueError("Email needs an explicit End or Duration in minutes.")
        end = start.astimezone(timezone.utc) + timedelta(minutes=int(duration.group(1)))
    if end.astimezone(timezone.utc) <= start.astimezone(timezone.utc):
        raise ValueError("Meeting end must be after start.")
    attendees = []
    if "attendees" in fields:
        for name, address in getaddresses([fields["attendees"].replace(";", ",")]):
            if not _EMAIL.fullmatch(address):
                raise ValueError("Each attendee must have an explicit email address.")
            address = address.lower()
            if not any(a["email"] == address for a in attendees):
                attendees.append({"email": address, **({"displayName": name} if name else {})})
    else:
        raise ValueError("Email needs an Attendees field with explicit email addresses.")
    if not attendees:
        raise ValueError("No attendees found.")
    return {
        "summary": fields.get("title") or subject or "Meeting",
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "attendees": attendees,
        **({"location": fields["location"]} if "location" in fields else {}),
    }


def create_event(event: dict) -> dict:
    """Use existing OAuth/config; the shared Calendar helper has no guests argument."""
    service = build("calendar", "v3", credentials=get_credentials(), cache_discovery=False)
    return service.events().insert(
        calendarId=config.CALENDAR_ID, body=event, sendUpdates="all",
    ).execute()


def execute(ctx: runner.RunContext, suggestion_id: str) -> dict:
    """Return result only: the existing runner owns the complete B4 run envelope."""
    active = STEP_LABELS[0]
    try:
        ctx.start_step(active)
        # Calendar has its own safe default; never fall back to the receipt
        # query or a broad inbox search when the demo env is not configured.
        query = os.getenv("MIA_CALENDAR_GMAIL_QUERY", "subject:meeting")
        msg = read_gmail(query)
        ctx.finish_step(active)
        active = STEP_LABELS[1]
        ctx.start_step(active)
        event = extract_meeting(msg.body or msg.snippet, msg.subject)
        ctx.finish_step(active)
        active = STEP_LABELS[2]
        ctx.start_step(active)
        ctx.checkpoint(
            "Send meeting invitations",
            f"Create {event['summary']!r} at {event['start']['dateTime']} and email "
            + ", ".join(a["email"] for a in event["attendees"]) + ".",
        )
        created = create_event(event)
        ctx.finish_step(active)
        return {
            "eventsCreated": 1, "eventId": created.get("id"),
            "calendarUrl": created.get("htmlLink"), "htmlLink": created.get("htmlLink"),
            "start": event["start"]["dateTime"], "end": event["end"]["dateTime"],
            "attendees": event["attendees"], "sourceMessageId": msg.id,
        }
    except Exception:
        ctx.fail_step(active)
        raise


def register() -> None:
    """Add only our key; preserve gmail_to_sheet's dispatch and implementation."""
    runner.WORKFLOWS[WORKFLOW_KEY] = (list(STEP_LABELS), execute)
    runner.TRIGGER_QUERIES[WORKFLOW_KEY] = lambda: os.getenv("MIA_CALENDAR_GMAIL_QUERY") or config.GMAIL_TEST_QUERY


register()


def __getattr__(name: str):
    # Optional ASGI entry point; importing the workflow alone need not load FastAPI.
    if name == "app":
        from ..server import app
        return app
    raise AttributeError(name)
