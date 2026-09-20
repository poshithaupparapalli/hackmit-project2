"""Central config for MIA's agent slice (Poshitha).

Everything sensitive or environment-specific lives here so tools never
hardcode targets. Target sheet/calendar come from env, NOT from a suggestion
(per MIA_CONTRACTS.md: suggestionId is correlation-only).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# agent/ directory
BASE_DIR = Path(__file__).resolve().parent
SECRETS_DIR = BASE_DIR / "secrets"

# Load agent/.env if present (does not override real environment vars)
load_dotenv(BASE_DIR / ".env")

# --- OAuth files ---
CLIENT_SECRET_FILE = SECRETS_DIR / "client_secret.json"
TOKEN_FILE = SECRETS_DIR / "token.json"

# Must EXACTLY match a redirect URI registered on the Web OAuth client
# in the mia-hackmit Google Cloud project.
REDIRECT_URI = os.getenv(
    "MIA_OAUTH_REDIRECT_URI",
    "http://localhost:8000/v1/auth/google/callback",
)

# Port the standalone OAuth flow listens on (must match REDIRECT_URI's port).
OAUTH_LOCAL_PORT = int(os.getenv("MIA_OAUTH_LOCAL_PORT", "8000"))

# --- Scopes (exactly what the console consent screen was configured for) ---
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar.events",
]

# --- Execution targets (from env, not from suggestions) ---
# The expense sheet the gmail_to_sheet workflow appends to.
EXPENSE_SHEET_ID = os.getenv("MIA_EXPENSE_SHEET_ID", "")
EXPENSE_SHEET_RANGE = os.getenv("MIA_EXPENSE_SHEET_RANGE", "Sheet1!A:D")

# Calendar to write test/agent events to ("primary" is the demo account's own).
CALENDAR_ID = os.getenv("MIA_CALENDAR_ID", "primary")

# Optional: a Gmail search query to pick the message to read in the test.
# Defaults to the most recent message in the inbox. NOTE: this same query is
# also what autorun.py polls to decide "is there new work" (see TRIGGER_QUERIES
# in runner.py) — for real unattended use, narrow it (e.g. "in:inbox (receipt
# OR invoice OR total)") so a quiet inbox doesn't attempt a run on every email.
# A non-matching email still fails safely (extract_receipt just errors, never
# writes bad data) but it's noisy and burns API calls for no reason.
# Keep the receipt workflow deterministic by default. A broad inbox query can
# select an unrelated newsletter and make a valid run fail during extraction.
# Override this for a custom demo mailbox with MIA_GMAIL_TEST_QUERY.
GMAIL_TEST_QUERY = os.getenv("MIA_GMAIL_TEST_QUERY", "subject:receipt")

# --- Auto-run (B2 extension: execute an ACCEPTED workflow automatically when
# new matching input appears, instead of waiting for a manual Run click).
# The B5 approval checkpoint inside a run is untouched either way — a
# consequential step (e.g. sending calendar invites) still pauses for a
# person's decision regardless of whether the run started manually or here.
AUTO_RUN_ENABLED = os.getenv("MIA_AUTO_RUN_ENABLED", "true").strip().lower() not in ("false", "0", "no")
AUTO_RUN_INTERVAL_S = int(os.getenv("MIA_AUTO_RUN_INTERVAL_S", "60"))

# Where autorun.py asks "which workflows has a person actually accepted?"
# (Kathy's detection API — read-only, over HTTP, same as the dashboard uses;
# the agent still never touches her SQLite DB directly, per B7.)
BACKEND_URL = os.getenv("MIA_BACKEND_URL", "http://localhost:8000")
