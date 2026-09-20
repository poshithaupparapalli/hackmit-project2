"""Agent HTTP surface — the B4 run contract + B5 approve endpoint.

Runs as its own FastAPI app (agent's slice). Ryan's frontend calls these for
execution; Kathy's detection backend is a separate app. Endpoints are /v1-prefixed
and mirror MIA_CONTRACTS.md exactly:

    POST /v1/workflows/{workflowKey}/run   body {suggestionId}   -> { runId }
    GET  /v1/workflows/runs/{runId}                              -> WorkflowRun
    GET  /v1/workflows/runs?limit=50                             -> [WorkflowRun] (history)
    POST /v1/workflows/runs/{runId}/approve  ?decision=approve|cancel -> WorkflowRun

Plus the "ask every time" half of auto-run (pending.py) — a suggestion whose
runMode is "ask" doesn't run on new input, it raises a prompt instead:

    GET  /v1/workflows/pending                        -> [PendingTrigger]
    POST /v1/workflows/pending/{pendingId}/approve     -> { runId }
    POST /v1/workflows/pending/{pendingId}/dismiss     -> { ok: true }

Plus the Google OAuth web flow the dashboard's "Integrations" panel drives —
the browser-based counterpart to `python -m agent.oauth_flow`'s CLI flow:

    GET /v1/auth/google/status    -> { configured, connected }
    GET /v1/auth/google/start     -> 302 to Google's consent screen
    GET /v1/auth/google/callback  -> exchanges ?code=..., then 302 back to the dashboard

    NOTE: config.REDIRECT_URI must match wherever this app actually runs. It
    defaults to http://localhost:8000/... (see agent/config.py); if you serve
    this app on its usual port 8010 instead, set MIA_OAUTH_REDIRECT_URI to
    match and add that exact URI to the OAuth client's registered redirects
    in Google Cloud Console (you can register more than one).

Plus autorun.py's background loop (started in lifespan, below): once a
workflow is ACCEPTED, it runs on its own when new matching input shows up —
no manual Run click needed. See autorun.py's docstring for exactly what that
does and doesn't change; set MIA_AUTO_RUN_ENABLED=false to turn it off.

Run:
    source agent/.venv/bin/activate
    uvicorn agent.server:app --port 8010
(or: python -m agent.server)
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from . import autorun, config, oauth_flow, pending, runner
from .pending import PendingTrigger
from .runner import WorkflowRun

# Where the dashboard lives — the OAuth callback redirects back here.
DASHBOARD_URL = os.getenv("MIA_DASHBOARD_URL", "http://localhost:5173/")

# Auto-discover and register workflow modules in agent/workflows/ on startup, so
# launching normally (uvicorn agent.server:app) picks up every workflow —
# gmail_to_sheet (built into the runner) plus anything under agent/workflows/.
_REGISTERED = runner.discover_workflows()
print(f"[agent] workflows available: {sorted(runner.WORKFLOWS)} "
      f"(discovered from agent/workflows/: {_REGISTERED})")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(autorun.loop())
    yield
    task.cancel()


app = FastAPI(title="MIA Agent (execution)", version="1.0", lifespan=lifespan)

# Ryan's frontend calls this directly; wide-open CORS is fine for the demo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunRequest(BaseModel):
    suggestionId: str  # correlation only — the agent never reads Kathy's DB (B7)


class RunAccepted(BaseModel):
    runId: str


@app.post("/v1/workflows/{workflow_key}/run", response_model=RunAccepted)
def run_workflow(workflow_key: str, body: RunRequest) -> RunAccepted:
    if not runner.is_known_workflow(workflow_key):
        # Controlled set (A12): only executable workflowKeys are accepted.
        raise HTTPException(status_code=404, detail=f"unknown workflowKey: {workflow_key}")
    run_id = runner.start_run(workflow_key, body.suggestionId)
    return RunAccepted(runId=run_id)


@app.get("/v1/workflows/runs", response_model=list[WorkflowRun])
def list_runs(limit: int = 50) -> list[WorkflowRun]:
    return runner.list_runs(limit=limit)


@app.get("/v1/workflows/runs/{run_id}", response_model=WorkflowRun)
def get_run(run_id: str) -> WorkflowRun:
    run = runner.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@app.post("/v1/workflows/runs/{run_id}/approve", response_model=WorkflowRun)
def approve_run(run_id: str, decision: str = "approve") -> WorkflowRun:
    run = runner.approve_run(run_id, decision=decision)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@app.get("/v1/workflows/pending", response_model=list[PendingTrigger])
def list_pending() -> list[PendingTrigger]:
    return pending.list_pending()


@app.post("/v1/workflows/pending/{pending_id}/approve", response_model=RunAccepted)
def approve_pending(pending_id: str) -> RunAccepted:
    trigger = pending.resolve(pending_id)
    if trigger is None:
        raise HTTPException(status_code=404, detail="pending trigger not found")
    run_id = runner.start_run(trigger.workflowKey, trigger.suggestionId, triggered_by="auto")
    return RunAccepted(runId=run_id)


@app.post("/v1/workflows/pending/{pending_id}/dismiss")
def dismiss_pending(pending_id: str) -> dict:
    trigger = pending.resolve(pending_id)
    if trigger is None:
        raise HTTPException(status_code=404, detail="pending trigger not found")
    return {"ok": True}


@app.get("/v1/auth/google/status")
def google_auth_status() -> dict:
    configured = oauth_flow.is_configured()
    return {"configured": configured, "connected": configured and oauth_flow.is_connected()}


@app.get("/v1/auth/google/start")
def google_auth_start() -> RedirectResponse:
    try:
        auth_url, _state = oauth_flow.get_authorization_url()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return RedirectResponse(auth_url)


@app.get("/v1/auth/google/callback")
def google_auth_callback(code: str | None = None, error: str | None = None) -> RedirectResponse:
    if error or not code:
        return RedirectResponse(f"{DASHBOARD_URL}?connected=0&error={error or 'missing_code'}")
    try:
        oauth_flow.exchange_code(code)
    except Exception as exc:  # noqa: BLE001 — surface any failure to the dashboard, never crash
        return RedirectResponse(f"{DASHBOARD_URL}?connected=0&error={type(exc).__name__}")
    return RedirectResponse(f"{DASHBOARD_URL}?connected=1")


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "workflows": list(runner.WORKFLOWS.keys()),
        "autoRunEnabled": config.AUTO_RUN_ENABLED,
        "autoRunWorkflows": list(runner.TRIGGER_QUERIES.keys()),
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("MIA_AGENT_PORT", "8010"))
    uvicorn.run(app, host="127.0.0.1", port=port)
