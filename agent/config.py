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
# Defaults to the most recent message in the inbox.
GMAIL_TEST_QUERY = os.getenv("MIA_GMAIL_TEST_QUERY", "in:inbox")
