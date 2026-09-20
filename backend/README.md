# MIA Detection Backend (Kathy)

FastAPI + SQLite detection pipeline per `MIA_CONTRACTS.md` v1.1 (Part A, D2).

## Setup

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in OPENAI_API_KEY
```

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

Demo mode (seeds prerecorded receipt events, produces the suggestion offline):

```bash
DEMO_MODE=true uvicorn app.main:app --port 8000
```

## Endpoints

- `POST /v1/install` → `{ installId, installToken }`
- `POST /v1/events/batch` (Bearer token) → `{ accepted, rejected, serverTime }`
- `GET /v1/suggestions` · `PATCH /v1/suggestions/:id` `{ status }`
- `POST /v1/suggestions/:id/feedback` `{ decision, userEdits? }`
- `POST /v1/analyze` → `{ queued: true }` · `GET /v1/status`
- `GET /health`

Not here: OAuth endpoints, `POST /v1/workflows/*` (Poshitha's agent).

## Fallback artifacts

- `data/fallback_events.jsonl` — regenerate via `python scripts/gen_fallback.py`
- `data/canned_run.json` — Poshitha overwrites with one real successful run

## Tests

```bash
pytest tests/
```
