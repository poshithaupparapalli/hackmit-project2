# Mia Demo Seed Package

This package seeds a **clean normal Mia backend on `http://localhost:8000`** with a synthetic week of executive-assistant browser activity.

It does NOT insert fake suggestions. It sends canonical `MiaEvent`s through the real `/v1/events/batch` endpoint and then calls the real analyzer.

## Assumption

You have intentionally reset/wiped the working Mia DB before seeding.

The backend default DB is normally `backend/data/mia.db` unless `MIA_DB_PATH` overrides it.

## 1. Start backend

From the repo:

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Make sure the backend environment contains a real `OPENAI_API_KEY`.

This is especially important because the backend's heuristic fallback can produce a Gmail→Sheets-style suggestion, but it cannot generate `email_to_calendar`.

## 2. Put this folder in the repo

Recommended:

```text
<repo-root>/demo/
```

The script uses only `httpx` plus the Python standard library. `httpx` is already installed by the backend requirements.

## 3. Seed the week

From the repo root, while the backend virtual environment is active:

```bash
python demo/seed_demo_week.py
```

The script:

1. checks `/health`,
2. calls `/v1/install` and persists a local demo install/token,
3. replaces `__INSTALL_ID__` in the dataset at runtime,
4. posts canonical events to `/v1/events/batch`,
5. calls `/v1/analyze`,
6. polls `/v1/status`,
7. prints the resulting suggestions.

The state file is:

```text
demo/.demo_seed_state.json
```

Add it to `.gitignore`.

If the DB was wiped but this state file remains, the script detects the invalid token and automatically creates a new install.

## 4. Dataset

`executive_assistant_week.json` contains synthetic history from September 14–18, 2026.

It is designed to produce evidence for:
- Gmail receipt → expense spreadsheet
- meeting-request email → Calendar event
- an early-meeting scheduling preference / possible investor exception

See `demo_ground_truth.md`.

## 5. Rehearsal Gmail configuration

The current agent otherwise searches the newest message matching a broad Gmail query.

For a deterministic demo, create two Gmail labels:

```text
mia-demo-receipts
mia-demo-calendar
```

Then configure the agent:

```bash
MIA_GMAIL_TEST_QUERY="label:mia-demo-receipts"
MIA_CALENDAR_GMAIL_QUERY="label:mia-demo-calendar"
```

This prevents an unrelated incoming hackathon email from becoming the "newest inbox message" during the demo.

## 6. Sheet configuration

The Gmail→Sheets workflow requires:

```bash
MIA_EXPENSE_SHEET_ID="<your sheet id>"
MIA_EXPENSE_SHEET_RANGE="Sheet1!A:D"
```

The current runner appends:

```text
date | vendor | amount | subject
```

For `receipt_demo_email.txt`, the important parseable line is:

```text
Total: $42.18
```

## 7. Calendar fixture

Use `calendar_demo_email.txt`.

Before the live demo, replace:

```text
REPLACE_WITH_YOUR_CONTROLLED_EMAIL@example.com
```

with an email address you control.

The Calendar workflow requires at least one attendee and pauses for approval immediately before `calendar.events.insert(..., sendUpdates="all")`.

## 8. If a suggestion does not become runnable

Workflow-key assignment happens after LLM suggestion generation via keyword matching.

For `gmail_to_sheet`, the generated suggestion must contain:
- one of `gmail`, `mail.google`, `receipt`, `email`
- AND one of `sheet`, `spreadsheet`, `docs.google`

For `email_to_calendar`, it must contain:
- one of `gmail`, `mail.google`, `email`, `meeting`, `invite`, `invitation`
- AND one of `calendar`, `event`, `schedule`

The dataset is deliberately worded to make these natural, but exact LLM output is not guaranteed.

## Files

- `executive_assistant_week.json` — canonical historical events
- `seed_demo_week.py` — executable loader
- `demo_ground_truth.md` — intended learned patterns
- `receipt_demo_email.txt` — fresh receipt for the live execution
- `calendar_demo_email.txt` — fresh scheduling request
- `DEMO_RUNBOOK.md` — suggested live presentation flow
