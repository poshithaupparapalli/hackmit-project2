# Codex scope — NEW workflow files ONLY

Read first: MIA_CONTRACTS.md (B4 run contract, B5 approval, B7 registry) and CLAUDE.md.

## What I own
ONLY new workflow files under agent/workflows/. I ADD new workflows that plug into the
EXISTING runner (agent/runner.py) via workflowKey dispatch. Build in B7 priority order:
  1. email_to_calendar  (token already has gmail.readonly + calendar.events — most de-risked)
  2. inbox_triage       (gmail.readonly)

## What I must NOT touch
- agent/runner.py, the FastAPI server, extract.py, tools.py — Claude Code owns these.
- backend/ (Kathy), extension/ (Anika), web/ (Ryan).
- I only ADD new files in agent/workflows/. I do not edit shared/core files.

## Contract I must match
Each workflow returns the B4 run shape via the existing runner:
{ runId, workflowKey, status, steps[], result, error }
Match the step-label style Claude Code used, e.g. "Reading email → Extracting → Creating event".
Each workflow registers under its own workflowKey.

## Build rule
One workflow fully working end-to-end before the next. email_to_calendar first.