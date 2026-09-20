# MIA — Project Context (read before generating any code)

## What MIA is
MIA is an AI companion for non-technical people (small-business owners, executive
assistants, an inventory manager — "Susan, 45") who can't design AI agents because
they don't think in workflows. MIA watches their permitted browser activity, NOTICES
repeated workflows, and OFFERS to automate them. The user never describes an agent;
MIA notices the work they already do and does it for them, after approval.

## The one-sentence thesis
People shouldn't have to recognize, describe, and configure automation. MIA learns
from the work you already do, shows you what it noticed, and does it for you — after
you approve.

## CRITICAL design boundary — NOTICING is general, DOING is one workflow
The product has two halves with very different costs. Do not confuse them.

- NOTICING (detection) is GENERAL and basically free: the pattern miner counts
  repeated sequences/clicks/copy-paste pairs. It works on ANY workflow already.
- DOING (execution) is SPECIFIC and expensive: to actually perform a workflow, we
  must write integration code for that exact app (Gmail API, Sheets API, etc). There
  is NO general "do anything it noticed" function — it does not exist for anyone.
  Each executable workflow is hand-written integration code.

Therefore, for the hackathon:
- We build EXECUTION for exactly ONE workflow, real and flawless.
- We let DETECTION look general (because it is).
- Every other workflow is a "coming soon" vision-slide item.

DO NOT try to build an agent that executes arbitrary detected workflows. It is
impossible in the time we have and will produce a vague, broken demo. Build one real
integration + an architecture that clearly generalizes.

Say it like this: "MIA notices ANY workflow; tonight it fully DOES one of them."

## Architecture
Chrome extension (eyes + popup)  →  Backend (brain + agent)  →  Google APIs (hands)

  Extension:
    content script → captures SANITIZED events
    service worker → batches, POSTs to backend
    popup → "MIA noticed a pattern" → opens the workflows web page
  Backend (FastAPI + SQLite):
    /events/batch  → ingest events
    pattern miner  → deterministic repeated-sequence detection
    LLM analyst    → turns patterns into suggestions
    /suggestions   → list / keep / dismiss
    OAuth          → Google connection, stores token server-side
    agent runner   → executes the ONE workflow via Google APIs
  Workflows web page (part of FRONTEND, NOT in the extension):
    login → connect Google → see suggested workflows → click Run → watch it run

## Where the agent lives
The agent runs on the BACKEND, not in the extension. The extension is eyes-only.
The agent acts through Google APIs (Gmail read + Sheets append), NOT by clicking the
page DOM. API execution is reliable; DOM automation is not.

## The ONE demo workflow (default — Poshitha confirms by midnight)
Gmail → Google Sheets "receipt/expense loop": read a receipt email, extract the
amount, append a row to a sheet. One Google OAuth covers both Gmail + Sheets. The
copy/paste + repeated-form detectors already fire on it.

## Privacy rules (load-bearing for the pitch — enforce in code)
Record ONLY sanitized structure:
  field NAME, input TYPE, char COUNT, button LABEL, host, path, copy/paste host pairs.
NEVER record:
  form values, passwords, clipboard contents, full keystrokes, query strings, page
  HTML, or screenshots.
The UI must ALWAYS show: a live "observing" indicator, a pause button, and an
excluded-domains list.

## Roles
- Poshitha (lead): agent runner + Google API execution. Owns the ONE workflow.
  Co-owns Google OAuth with Ryan (first hour, hard dependency).
- Kathy: backend pipeline — /events/batch, SQLite, pattern miner, LLM analyst,
  /suggestions, OAuth token storage. Owns the FALLBACK DATASET + demo-mode toggle.
  NO UI.
- Anika: Chrome extension — content script, service worker, batching, popup.
- Ryan: ALL frontend — the workflows web page + any dashboard, calling Kathy's
  endpoints. Co-owns Google OAuth setup with Poshitha (first hour). NO backend logic.

NOTE: The workflows page is Ryan's UI calling Kathy's endpoints. Kathy writes no UI;
Ryan writes no backend logic. Do not both build the page.

## Stack
FastAPI + SQLite (backend). Manifest V3 (extension). React (frontend). Google API
client libraries (agent). Keep it minimal. No accounts/billing/teams. No general
automation platform.

## Scope discipline (~13 hours)
- First hour: Poshitha + Ryan get Google OAuth working (token that reads Gmail +
  appends to Sheets). Until this exists, nothing else matters.
- Poshitha locks the ONE workflow by MIDNIGHT so the team can build against it.
- Build ONE workflow end to end + a fallback dataset so the demo works with live
  capture OFF.
- Create a project in Plume BEFORE midnight tonight (required to be judged Sunday).
- Stop adding features ~90 min before the hard stop. Last stretch = rehearsal + submit.

## Submissions this build targets
Long Lake (skeptic→conversion framing), Maximor (point the agent at a finance
workflow), Warp (dev tool), Cognition/OpenAI (built with Devin/Codex). No HackMIT
track — this is known and accepted.
