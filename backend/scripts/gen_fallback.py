"""Generate backend/data/fallback_events.jsonl — the prerecorded demo dataset.

Three repeated pattern families, so the miner -> analyst pipeline produces one
suggestion per B7 workflow with no live capture:

1. receipt loop      Gmail receipt -> copy total -> paste into a Google Sheet
                     (4x over 3 days, varying vendors and sheet IDs so path
                     normalization is exercised)
2. meeting invites   Gmail invitation -> copy "When" -> create a Calendar event
3. inbox triage      unread thread -> reply -> save draft -> archive, Gmail only
"""
import json
import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "fallback_events.jsonl"

GMAIL = "mail.google.com"
SHEETS = "docs.google.com"
CALENDAR = "calendar.google.com"

CAL_PATH = "/calendar/u/0/r"
CAL_TITLE = "Fall 2026 Schedule - Google Calendar"

# Session start times (epoch ms), Sep 16-18 UTC. Sessions are >15 min apart so
# the miner splits them (SESSION_GAP_MS).
RECEIPT_SESSIONS = [
    {"start": 1789549200000, "sessionId": "sess-1", "vendor": "Blue Bottle Coffee",
     "sheetId": "1AbCdEfGhIjKlMnOpQr", "total_len": 5},
    {"start": 1789567200000, "sessionId": "sess-2", "vendor": "Staples",
     "sheetId": "1AbCdEfGhIjKlMnOpQr", "total_len": 7},
    {"start": 1789639200000, "sessionId": "sess-3", "vendor": "Lyft",
     "sheetId": "9ZxYvUtSrQpOnMlKjIh", "total_len": 6},
    {"start": 1789729200000, "sessionId": "sess-4", "vendor": "Blue Bottle Coffee",
     "sheetId": "9ZxYvUtSrQpOnMlKjIh", "total_len": 5},
]

CALENDAR_SESSIONS = [
    {"start": 1789552800000, "sessionId": "sess-5",
     "subject": "Meeting invite: Advisor sync", "event": "Advisor sync"},
    {"start": 1789570800000, "sessionId": "sess-6",
     "subject": "Meeting invite: Advisor sync", "event": "Advisor sync"},
    {"start": 1789642800000, "sessionId": "sess-7",
     "subject": "Invite: HackMIT team standup", "event": "HackMIT team standup"},
]

TRIAGE_SESSIONS = [
    {"start": 1789556400000, "sessionId": "sess-8", "threads": [
        "Unread: Reimbursement question", "Unread: Lab shift swap"]},
    {"start": 1789574400000, "sessionId": "sess-9", "threads": [
        "Unread: Room booking confirmation", "Unread: TA office hours"]},
    {"start": 1789732800000, "sessionId": "sess-10", "threads": [
        "Unread: Reimbursement question", "Unread: Sponsor intro"]},
]


def ev(ts, seq, sid, etype, host, path, title=None, detail=None, context=None):
    e = {
        "schemaVersion": 1, "id": str(uuid.uuid4()), "installId": "demo-install",
        "sessionId": sid, "timestamp": ts, "sequence": seq,
        "tabId": 1, "frameId": 0, "type": etype, "host": host, "path": path,
    }
    if title:
        e["title"] = title
    if detail:
        e["detail"] = detail
    if context:
        e["context"] = context
    return e


def receipt_events(s) -> list[dict]:
    t, sid = s["start"], s["sessionId"]
    sheet_path = f"/spreadsheets/d/{s['sheetId']}/edit"
    return [
        ev(t, 1, sid, "nav", GMAIL, "/mail/u/0/", "Inbox - Gmail",
           {"referrerHost": "google.com"}),
        ev(t + 8_000, 2, sid, "click", GMAIL, "/mail/u/0/",
           f"Receipt from {s['vendor']}",
           {"tag": "DIV", "role": "row", "label": f"Receipt from {s['vendor']}"},
           {"sectionLabel": "Inbox"}),
        ev(t + 20_000, 3, sid, "copy", GMAIL, "/mail/u/0/",
           f"Receipt from {s['vendor']} - Gmail",
           {"length": s["total_len"], "wordCount": 1},
           {"sectionLabel": "Receipt", "targetLabel": "Total"}),
        ev(t + 30_000, 4, sid, "nav", SHEETS, sheet_path, "Expense Tracker",
           {"referrerHost": GMAIL}),
        ev(t + 45_000, 5, sid, "paste", SHEETS, sheet_path, "Expense Tracker",
           {"length": s["total_len"], "targetTag": "INPUT", "targetName": "amount"}),
        ev(t + 60_000, 6, sid, "edit", SHEETS, sheet_path, "Expense Tracker",
           {"tag": "INPUT", "inputType": "text", "name": "amount",
            "length": s["total_len"]}),
        ev(t + 75_000, 7, sid, "edit", SHEETS, sheet_path, "Expense Tracker",
           {"tag": "INPUT", "inputType": "text", "name": "note",
            "length": len(s["vendor"])}),
        ev(t + 90_000, 8, sid, "click", SHEETS, sheet_path, "Expense Tracker",
           {"tag": "BUTTON", "role": "button", "label": "Save"},
           {"formLabel": "Add expense", "targetLabel": "Save"}),
        ev(t + 95_000, 9, sid, "submit", SHEETS, sheet_path, "Expense Tracker",
           {"name": "expense-form", "actionHost": SHEETS,
            "actionPath": "/forms/submit", "fieldCount": 2, "via": "button"}),
    ]


def calendar_events(s) -> list[dict]:
    t, sid, subject = s["start"], s["sessionId"], s["subject"]
    return [
        ev(t, 1, sid, "nav", GMAIL, "/mail/u/0/", "Inbox - Gmail",
           {"referrerHost": "google.com"},
           {"pageTitle": "Inbox - Gmail", "sectionLabel": "Inbox"}),
        ev(t + 8_000, 2, sid, "click", GMAIL, "/mail/u/0/", subject,
           {"tag": "DIV", "role": "row", "label": subject},
           {"sectionLabel": "Inbox", "itemTitle": subject}),
        # The copy is the meeting time: category only, never the value itself.
        ev(t + 20_000, 3, sid, "copy", GMAIL, "/mail/u/0/", f"{subject} - Gmail",
           {"length": 21, "wordCount": 5},
           {"sectionLabel": "Invitation", "targetLabel": "When",
            "semanticType": "datetime"}),
        ev(t + 30_000, 4, sid, "nav", CALENDAR, CAL_PATH, CAL_TITLE,
           {"referrerHost": GMAIL}),
        ev(t + 45_000, 5, sid, "click", CALENDAR, CAL_PATH, CAL_TITLE,
           {"tag": "BUTTON", "role": "button", "label": "Create"},
           {"pageTitle": "Fall 2026 Schedule", "formLabel": "Create event",
            "targetLabel": "Create"}),
        ev(t + 60_000, 6, sid, "edit", CALENDAR, CAL_PATH, CAL_TITLE,
           {"tag": "INPUT", "inputType": "text", "name": "title",
            "length": len(s["event"])},
           {"formLabel": "Create event", "targetLabel": "Add title",
            "itemTitle": s["event"]}),
        ev(t + 75_000, 7, sid, "paste", CALENDAR, CAL_PATH, CAL_TITLE,
           {"length": 21, "targetTag": "INPUT", "targetName": "when"},
           {"formLabel": "Create event", "targetLabel": "When",
            "semanticType": "datetime"}),
        ev(t + 90_000, 8, sid, "click", CALENDAR, CAL_PATH, CAL_TITLE,
           {"tag": "BUTTON", "role": "button", "label": "Save"},
           {"formLabel": "Create event", "targetLabel": "Save"}),
        ev(t + 95_000, 9, sid, "submit", CALENDAR, CAL_PATH, CAL_TITLE,
           {"name": "event-form", "actionHost": CALENDAR,
            "actionPath": "/calendar/event/save", "fieldCount": 3, "via": "button"}),
    ]


def triage_events(s) -> list[dict]:
    t, sid = s["start"], s["sessionId"]
    events = [
        ev(t, 1, sid, "nav", GMAIL, "/mail/u/0/", "Inbox - Gmail",
           {"referrerHost": "google.com"},
           {"pageTitle": "Inbox - Gmail", "sectionLabel": "Unread"}),
    ]
    seq = 2
    for i, thread in enumerate(s["threads"]):
        off = (10 + i * 70) * 1000
        events += [
            ev(t + off, seq, sid, "click", GMAIL, "/mail/u/0/", thread,
               {"tag": "DIV", "role": "row", "label": thread},
               {"pageTitle": "Inbox - Gmail", "sectionLabel": "Unread",
                "targetLabel": "Unread thread", "itemTitle": thread}),
            ev(t + off + 15_000, seq + 1, sid, "click", GMAIL, "/mail/u/0/", thread,
               {"tag": "BUTTON", "role": "button", "label": "Reply"},
               {"formLabel": "Reply", "targetLabel": "Reply"}),
            ev(t + off + 40_000, seq + 2, sid, "edit", GMAIL, "/mail/u/0/", thread,
               {"tag": "DIV", "inputType": "textarea", "name": "reply-body",
                "length": 142},
               {"formLabel": "Reply", "targetLabel": "Message body",
                "semanticType": "text"}),
            ev(t + off + 55_000, seq + 3, sid, "click", GMAIL, "/mail/u/0/", thread,
               {"tag": "BUTTON", "role": "button", "label": "Save draft"},
               {"formLabel": "Reply", "targetLabel": "Save draft"}),
            ev(t + off + 62_000, seq + 4, sid, "click", GMAIL, "/mail/u/0/", thread,
               {"tag": "BUTTON", "role": "button", "label": "Archive"},
               {"sectionLabel": "Unread", "targetLabel": "Archive"}),
        ]
        seq += 5
    return events


def main() -> None:
    events: list[dict] = []
    for s in RECEIPT_SESSIONS:
        events += receipt_events(s)
    for s in CALENDAR_SESSIONS:
        events += calendar_events(s)
    for s in TRIAGE_SESSIONS:
        events += triage_events(s)
    events.sort(key=lambda e: (e["timestamp"], e["sequence"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    print(f"wrote {len(events)} events -> {OUT}")


if __name__ == "__main__":
    main()
