"""Auto-run: execute an ACCEPTED workflow automatically when new matching
input appears, instead of waiting for a manual Run click.

Scope, deliberately narrow — this only decides WHEN to call the existing
runner.start_run() for a workflow that:
  1. a person has already explicitly accepted (status="accepted" on Kathy's
     backend), and
  2. declares a TRIGGER_QUERIES entry (see runner.py) — a workflow with no
     entry there is manual-Run-only, unchanged from before.
Nothing here invents a new kind of action or bypasses the B5 approval
checkpoint inside a run: gmail_to_sheet and email_to_calendar run exactly
the same code path either way, so a consequential step (e.g. sending
calendar invites) still pauses for a person's decision regardless of
whether the run started from a click or from here.

"New input" = a Gmail message the workflow's query matches that we have not
already started a run for, tracked by a small on-disk watermark
(agent/secrets/auto_run_watermarks.json) so a restart doesn't replay mail
and a quiet inbox doesn't retrigger the same message every tick. The
watermark is recorded as soon as a run is STARTED for that message, not
when it succeeds — simpler, and safe (see GMAIL_TEST_QUERY note in
config.py for why a non-matching email is never actually harmful) — at the
cost of a message not auto-retrying itself if that one run happens to fail;
a person can always still hit Run manually for it from History.
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx

from . import config, runner
from .tools import _service

logger = logging.getLogger("mia.autorun")

WATERMARK_FILE = config.SECRETS_DIR / "auto_run_watermarks.json"


def _load_watermarks() -> dict[str, str]:
    if not WATERMARK_FILE.exists():
        return {}
    try:
        return json.loads(WATERMARK_FILE.read_text())
    except (ValueError, OSError):
        return {}


def _save_watermarks(data: dict[str, str]) -> None:
    config.SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    WATERMARK_FILE.write_text(json.dumps(data))


def _latest_message_id(query: str) -> str | None:
    svc = _service("gmail", "v1")
    listing = svc.users().messages().list(userId="me", q=query, maxResults=1).execute()
    messages = listing.get("messages", [])
    return messages[0]["id"] if messages else None


async def _accepted_workflow_keys() -> dict[str, str]:
    """workflowKey -> one accepted suggestionId with that key (for correlation).

    Read-only call to Kathy's public API — never Kathy's DB directly (B7).
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{config.BACKEND_URL}/v1/suggestions")
            resp.raise_for_status()
            suggestions = resp.json()
    except Exception as exc:  # backend down/unreachable this tick — try again next time
        logger.debug("auto-run: backend unreachable (%s)", exc)
        return {}
    out: dict[str, str] = {}
    for s in suggestions:
        key = s.get("workflowKey")
        if key and s.get("status") == "accepted" and key not in out:
            out[key] = s["id"]
    return out


async def _tick() -> None:
    accepted = await _accepted_workflow_keys()
    if not accepted:
        return
    watermarks = _load_watermarks()
    loop = asyncio.get_event_loop()
    changed = False
    for workflow_key, suggestion_id in accepted.items():
        get_query = runner.TRIGGER_QUERIES.get(workflow_key)
        if not get_query or not runner.is_known_workflow(workflow_key):
            continue  # accepted but not auto-runnable (e.g. no trigger query registered)
        if runner.is_run_active(workflow_key):
            continue  # already mid-run (manual or a previous auto tick) — don't overlap
        try:
            query = get_query()
            latest_id = await loop.run_in_executor(None, _latest_message_id, query)
        except Exception as exc:  # Gmail/API hiccup this tick — try again next tick
            logger.warning("auto-run: trigger check failed for %s: %s", workflow_key, exc)
            continue
        if not latest_id or watermarks.get(workflow_key) == latest_id:
            continue  # nothing new
        watermarks[workflow_key] = latest_id
        changed = True
        logger.info("auto-run: new input for %s (message %s) — starting run", workflow_key, latest_id)
        runner.start_run(workflow_key, suggestion_id, triggered_by="auto")
    if changed:
        _save_watermarks(watermarks)


async def loop() -> None:
    if not config.AUTO_RUN_ENABLED:
        logger.info("auto-run: disabled (MIA_AUTO_RUN_ENABLED=false)")
        return
    logger.info("auto-run: polling every %ss for accepted workflows with new input", config.AUTO_RUN_INTERVAL_S)
    while True:
        await asyncio.sleep(config.AUTO_RUN_INTERVAL_S)
        try:
            await _tick()
        except Exception:
            logger.exception("auto-run: tick failed")
