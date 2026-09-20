"""Generate backend/data/fallback_events.jsonl — a prerecorded receipt/expense
workflow: Gmail receipt -> copy total -> paste into Google Sheet, repeated 4x
across 3 days with varying vendors and sheet IDs (path-normalization exercise).
"""
import json
import uuid
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "fallback_events.jsonl"

# session start times (epoch ms): Sep 16 09:00, Sep 16 14:00, Sep 17 10:00, Sep 18 11:00 UTC
SESSIONS = [
    {"start": 1789549200000, "sessionId": "sess-1", "vendor": "Blue Bottle Coffee",
     "sheetId": "1AbCdEfGhIjKlMnOpQr", "total_len": 5},
    {"start": 1789567200000, "sessionId": "sess-2", "vendor": "Staples",
     "sheetId": "1AbCdEfGhIjKlMnOpQr", "total_len": 7},
    {"start": 1789639200000, "sessionId": "sess-3", "vendor": "Lyft",
     "sheetId": "9ZxYvUtSrQpOnMlKjIh", "total_len": 6},
    {"start": 1789729200000, "sessionId": "sess-4", "vendor": "Blue Bottle Coffee",
     "sheetId": "9ZxYvUtSrQpOnMlKjIh", "total_len": 5},
]

GMAIL = "mail.google.com"
SHEETS = "docs.google.com"


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


def main() -> None:
    events = []
    for s in SESSIONS:
        t, sid = s["start"], s["sessionId"]
        sheet_path = f"/spreadsheets/d/{s['sheetId']}/edit"
        events += [
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
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    print(f"wrote {len(events)} events -> {OUT}")


if __name__ == "__main__":
    main()
