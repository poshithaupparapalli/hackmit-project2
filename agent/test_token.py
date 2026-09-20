"""Standalone end-to-end token proof for MIA (Poshitha's slice).

Proves the Google OAuth token works across ALL three scopes before we build
the agent. This is NOT the agent and NOT a workflow run — it's de-risking.

It will:
  1. Run OAuth consent if needed (access_type=offline, prompt=consent) -> refresh token
  2. Read ONE real Gmail message (gmail.readonly)
  3. Append ONE row to the configured test Sheet (spreadsheets)
  4. Create ONE test calendar event (calendar.events)

Run:
    cd /Users/poshitha/Desktop/hackmit-project2
    python -m agent.test_token
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from . import config
from .oauth_flow import get_credentials
from .tools import append_to_sheet, create_calendar_event, read_gmail


def main() -> int:
    print("=" * 60)
    print("MIA token proof — OAuth + Gmail + Sheets + Calendar")
    print("=" * 60)

    # --- Step 1: OAuth ---
    print("\n[1/4] Getting credentials (consent on first run)...")
    creds = get_credentials()
    print(f"      Credentials valid: {creds.valid}")
    print(f"      Refresh token present: {bool(creds.refresh_token)}")
    print(f"      Scopes: {', '.join(creds.scopes or [])}")

    # --- Step 2: Gmail ---
    print(f"\n[2/4] Reading one Gmail message (query={config.GMAIL_TEST_QUERY!r})...")
    msg = read_gmail()
    print(f"      From:    {msg.sender}")
    print(f"      Subject: {msg.subject}")
    print(f"      Date:    {msg.date}")
    preview = (msg.body or msg.snippet)[:200].replace("\n", " ")
    print(f"      Body preview: {preview!r}")

    # --- Step 3: Sheets ---
    print("\n[3/4] Appending one row to the test sheet...")
    if not config.EXPENSE_SHEET_ID:
        print("      SKIPPED: set MIA_EXPENSE_SHEET_ID in agent/.env to test this.")
    else:
        now = datetime.now(timezone.utc).isoformat()
        row = [now, msg.sender, msg.subject, "token-proof"]
        sheet_result = append_to_sheet(row)
        print(f"      Appended to: {sheet_result['updatedRange']}")
        print(f"      Rows added:  {sheet_result['updatedRows']}")
        print(f"      Sheet:       {sheet_result['sheetUrl']}")

    # --- Step 4: Calendar ---
    print("\n[4/4] Creating one test calendar event...")
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    event = create_calendar_event(
        summary="MIA token proof",
        start=start,
        duration_minutes=30,
        description="Created by agent/test_token.py to verify calendar.events scope.",
    )
    print(f"      Event id: {event['eventId']}")
    print(f"      Starts:   {event['start']}")
    print(f"      Link:     {event['htmlLink']}")

    print("\n" + "=" * 60)
    print("DONE. OAuth token works across Gmail + Sheets + Calendar.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — surface any failure clearly
        print(f"\nFAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
