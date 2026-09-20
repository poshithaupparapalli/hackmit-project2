"""Agent HTTP surface — the B4 run contract + B5 approve endpoint.

Runs as its own FastAPI app (agent's slice). Ryan's frontend calls these for
execution; Kathy's detection backend is a separate app. Endpoints are /v1-prefixed
and mirror MIA_CONTRACTS.md exactly:

    POST /v1/workflows/{workflowKey}/run   body {suggestionId}   -> { runId }
    GET  /v1/workflows/runs/{runId}                              -> WorkflowRun
    POST /v1/workflows/runs/{runId}/approve  ?decision=approve|cancel -> WorkflowRun

Run:
    source agent/.venv/bin/activate
    uvicorn agent.server:app --port 8010
(or: python -m agent.server)
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import runner
from .runner import WorkflowRun

app = FastAPI(title="MIA Agent (execution)", version="1.0")

# Auto-discover and register workflow modules in agent/workflows/ on startup, so
# launching normally (uvicorn agent.server:app) picks up every workflow —
# gmail_to_sheet (built into the runner) plus anything under agent/workflows/.
_REGISTERED = runner.discover_workflows()
print(f"[agent] workflows available: {sorted(runner.WORKFLOWS)} "
      f"(discovered from agent/workflows/: {_REGISTERED})")

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


@app.get("/health")
def health() -> dict:
    return {"ok": True, "workflows": list(runner.WORKFLOWS.keys())}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("MIA_AGENT_PORT", "8010"))
    uvicorn.run(app, host="127.0.0.1", port=port)
