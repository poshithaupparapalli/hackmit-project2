# MIA — Agent slice (Poshitha)

Google OAuth + tools + workflow runner. Work only in `agent/`.

## One-time setup

```bash
cd /Users/poshitha/Desktop/hackmit-project2
python3 -m venv agent/.venv
source agent/.venv/bin/activate
pip install -r agent/requirements.txt
cp agent/.env.example agent/.env   # then fill in MIA_EXPENSE_SHEET_ID
```

`agent/secrets/client_secret.json` (the Web OAuth client) must be present. Both
`agent/secrets/` and `agent/.env` are gitignored.

## Prove the token works (do this first — de-risks OAuth)

```bash
source agent/.venv/bin/activate
python -m agent.test_token
```

On first run it opens Google consent (`access_type=offline`, `prompt=consent`),
saves a **refresh token** to `agent/secrets/token.json`, then:
1. reads one real Gmail message,
2. appends one row to your test Sheet,
3. creates one test calendar event.

Sign in as the demo **test user** added to the OAuth consent screen.

To force a fresh consent (e.g. to re-issue a refresh token):

```bash
python -m agent.oauth_flow
```

If no refresh token comes back, revoke prior access at
https://myaccount.google.com/permissions and re-run.

## Files

| File | Purpose |
|------|---------|
| `config.py` | Env-based config: scopes, redirect URI, sheet/calendar targets |
| `oauth_flow.py` | Standalone OAuth consent + token load/refresh (`get_credentials()`) |
| `tools.py` | `read_gmail()`, `append_to_sheet()`, `create_calendar_event()` |
| `test_token.py` | End-to-end token proof across all three scopes |
| `secrets/` | `client_secret.json` + `token.json` (gitignored) |

## Scopes

- `gmail.readonly`
- `spreadsheets`
- `calendar.events`

Targets (sheet id, calendar id) come from env, **not** from a suggestion —
`suggestionId` is correlation-only; the agent does not read Kathy's DB.
