"""Standalone Google OAuth flow for MIA (Poshitha's slice).

Runs the consent flow with access_type=offline + prompt=consent so we get a
REFRESH TOKEN, then persists credentials to agent/secrets/token.json.

This is a Web-app OAuth client whose registered redirect URI has a path
(/v1/auth/google/callback), so we can't use InstalledAppFlow.run_local_server
(which only serves "/"). Instead we spin up a tiny local server that listens on
exactly that path and captures the ?code=... redirect.

Usage:
    python -m agent.oauth_flow          # force a fresh consent
    from agent.oauth_flow import get_credentials
    creds = get_credentials()           # load token.json, refresh, or run consent
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from . import config


def _save_credentials(creds: Credentials) -> None:
    config.SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    config.TOKEN_FILE.write_text(creds.to_json())
    # token.json is a secret; keep it owner-readable only.
    config.TOKEN_FILE.chmod(0o600)


def _load_saved_credentials() -> Credentials | None:
    if not config.TOKEN_FILE.exists():
        return None
    try:
        return Credentials.from_authorized_user_file(
            str(config.TOKEN_FILE), config.SCOPES
        )
    except (ValueError, json.JSONDecodeError):
        return None


class _CallbackHandler(BaseHTTPRequestHandler):
    """Captures the OAuth redirect and stashes the query on the server."""

    callback_path = urlparse(config.REDIRECT_URI).path

    def do_GET(self):  # noqa: N802 (http.server API)
        parsed = urlparse(self.path)
        if parsed.path != self.callback_path:
            self.send_response(404)
            self.end_headers()
            return

        self.server.auth_query = parse_qs(parsed.query)  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        params = self.server.auth_query  # type: ignore[attr-defined]
        ok = "code" in params and "error" not in params
        msg = (
            "MIA is connected to Google. You can close this tab and return to the terminal."
            if ok
            else f"Authorization failed: {params.get('error', ['unknown'])[0]}"
        )
        self.wfile.write(
            f"<html><body style='font-family:sans-serif;padding:40px'>"
            f"<h2>{'✅ ' if ok else '⚠️ '}{msg}</h2></body></html>".encode()
        )

    def log_message(self, *args):  # silence default request logging
        pass


def run_consent_flow() -> Credentials:
    """Run the full browser consent flow and return fresh credentials."""
    if not config.CLIENT_SECRET_FILE.exists():
        raise FileNotFoundError(
            f"Missing client secret at {config.CLIENT_SECRET_FILE}. "
            "Download the Web OAuth client JSON from the mia-hackmit project."
        )

    flow = Flow.from_client_secrets_file(
        str(config.CLIENT_SECRET_FILE),
        scopes=config.SCOPES,
        redirect_uri=config.REDIRECT_URI,
    )

    # The downloaded client JSON points at the legacy v1 auth endpoint
    # (/o/oauth2/auth), which rejects the modern `prompt` param with a plain
    # "400 malformed" page. Force the current v2 endpoint.
    flow.client_config["auth_uri"] = "https://accounts.google.com/o/oauth2/v2/auth"

    auth_url, _state = flow.authorization_url(
        access_type="offline",       # -> issues a refresh token
        prompt="consent",            # -> forces consent so refresh token is (re)issued
    )

    print("\n=== MIA Google OAuth ===")
    print("1. Open this URL in the browser signed in as the demo TEST USER:\n")
    print(auth_url + "\n")
    print(f"2. Approve the scopes. You'll be redirected to {config.REDIRECT_URI}")
    print(f"   (this script is listening there on port {config.OAUTH_LOCAL_PORT}).\n")

    try:
        import webbrowser

        webbrowser.open(auth_url)
    except Exception:
        pass

    server = HTTPServer(("localhost", config.OAUTH_LOCAL_PORT), _CallbackHandler)
    server.auth_query = None  # type: ignore[attr-defined]
    print("Waiting for Google to redirect back...")
    while server.auth_query is None:  # type: ignore[attr-defined]
        server.handle_request()
    server.server_close()

    query = server.auth_query  # type: ignore[attr-defined]
    if "error" in query:
        raise RuntimeError(f"OAuth error: {query['error'][0]}")
    if "code" not in query:
        raise RuntimeError("OAuth callback did not include an authorization code.")

    flow.fetch_token(code=query["code"][0])
    creds = flow.credentials

    if not creds.refresh_token:
        print(
            "\n[warning] No refresh token returned. Revoke prior access at "
            "https://myaccount.google.com/permissions and re-run to force one."
        )

    _save_credentials(creds)
    print(f"\nSaved credentials to {config.TOKEN_FILE}")
    print(f"Refresh token present: {bool(creds.refresh_token)}")
    return creds


def get_credentials() -> Credentials:
    """Return valid credentials: load token.json, refresh, or run consent."""
    creds = _load_saved_credentials()

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_credentials(creds)
            return creds
        except Exception as exc:  # refresh failed -> fall back to full consent
            print(f"[oauth] Refresh failed ({exc}); running consent flow again.")

    return run_consent_flow()


if __name__ == "__main__":
    creds = run_consent_flow()
    print("\nOAuth complete. Scopes granted:")
    for s in creds.scopes or []:
        print(f"  - {s}")
