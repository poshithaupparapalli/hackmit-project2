"""Proof for the gmail_to_sheet agent + B4/B5 run contract.

Exercises the real FastAPI endpoints in-process (TestClient) and checks:
  1. extract_receipt parses amounts from receipt-like text
  2. HAPPY PATH (B4): POST /run -> GET /runs/:id reaches status=done with the
     frozen WorkflowRun shape, and a real row is appended to the sheet
     (Gmail read is stubbed with a synthetic receipt so the path is deterministic
      regardless of what's newest in the inbox)
  3. APPROVAL (B5): a consequential step pauses at needs_approval and resumes
     only after POST /approve; cancel path errors the run
  4. LIVE: a real run against the actual inbox (honest status, may 'error' on
     extraction if the newest email isn't a receipt)

Run:
    source agent/.venv/bin/activate
    python -m agent.test_run
"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from . import runner
from .extract import extract_receipt
from .runner import RunContext, RunStep, WorkflowRun
from .server import app
from .tools import GmailMessage

client = TestClient(app)
EXPECTED_KEYS = {"runId", "workflowKey", "status", "steps", "result", "error", "approvalRequest"}


def _poll(run_id: str, until, timeout=60.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/v1/workflows/runs/{run_id}")
        assert r.status_code == 200, r.text
        run = r.json()
        if until(run):
            return run
        time.sleep(0.25)
    raise TimeoutError(f"run {run_id} did not reach target state in {timeout}s")


def test_extraction() -> None:
    print("\n[1] extract_receipt")
    samples = [
        ("Thanks for your order! Order total: $42.18", "42.18"),
        ("Amount due: USD 1,234.56 by Friday", "1234.56"),
        ("Coffee $4.50\nTax $0.36\nTotal $4.86", "4.86"),
    ]
    for text, expected in samples:
        r = extract_receipt(body=text, sender="Acme <billing@acme.com>")
        print(f"    {text[:40]!r:44} -> {r.currency}{r.amount} (vendor={r.vendor})")
        assert r.amount == expected, f"expected {expected}, got {r.amount}"
    print("    OK")


def test_happy_path() -> None:
    print("\n[2] HAPPY PATH — gmail_to_sheet via HTTP (synthetic receipt, real sheet write)")
    synthetic = GmailMessage(
        id="synthetic-1", thread_id="t1",
        subject="Your Amazon.com order receipt",
        sender="Amazon <auto-confirm@amazon.com>",
        date="Sat, 20 Sep 2026 10:00:00 +0000",
        snippet="Order total $42.18",
        body="Hello,\nThank you for your order.\nOrder total: $42.18\nShip to: ...",
    )
    orig = runner.read_gmail
    runner.read_gmail = lambda *a, **k: synthetic  # stub Gmail read only
    try:
        r = client.post("/v1/workflows/gmail_to_sheet/run", json={"suggestionId": "sug-happy"})
        assert r.status_code == 200, r.text
        run_id = r.json()["runId"]
        print(f"    runId={run_id}")
        run = _poll(run_id, lambda x: x["status"] in ("done", "error"))
    finally:
        runner.read_gmail = orig

    assert set(run.keys()) == EXPECTED_KEYS, f"shape mismatch: {set(run.keys())}"
    print(f"    status={run['status']}")
    for s in run["steps"]:
        print(f"      - {s['state']:7} {s['label']}")
    assert run["status"] == "done", run.get("error")
    assert run["result"]["rowsAppended"] == 1
    print(f"    result: rowsAppended={run['result']['rowsAppended']} "
          f"range={run['result']['updatedRange']} row={run['result']['row']}")
    print("    OK — real row written to the sheet")


def test_approval_mechanism() -> None:
    print("\n[3] APPROVAL BOUNDARY (B5) — consequential step pauses then resumes")

    def _demo(ctx: RunContext, suggestion_id: str) -> dict:
        ctx.start_step("Prepare")
        ctx.finish_step("Prepare")
        ctx.checkpoint("Send confirmation email?",
                       "This would send an email — outside the approved read+append plan.")
        ctx.start_step("Finish")
        ctx.finish_step("Finish")
        return {"approved": True}

    runner.WORKFLOWS["__approval_demo__"] = (["Prepare", "Finish"], _demo)
    try:
        # approve path
        run_id = client.post("/v1/workflows/__approval_demo__/run",
                             json={"suggestionId": "sug-appr"}).json()["runId"]
        run = _poll(run_id, lambda x: x["status"] == "needs_approval")
        assert run["approvalRequest"]["title"] == "Send confirmation email?"
        print(f"    paused: needs_approval — {run['approvalRequest']['title']}")
        client.post(f"/v1/workflows/runs/{run_id}/approve")
        run = _poll(run_id, lambda x: x["status"] in ("done", "error"))
        assert run["status"] == "done", run.get("error")
        print("    approve -> resumed -> done  OK")

        # cancel path
        run_id = client.post("/v1/workflows/__approval_demo__/run",
                             json={"suggestionId": "sug-cancel"}).json()["runId"]
        _poll(run_id, lambda x: x["status"] == "needs_approval")
        client.post(f"/v1/workflows/runs/{run_id}/approve", params={"decision": "cancel"})
        run = _poll(run_id, lambda x: x["status"] in ("done", "error"))
        assert run["status"] == "error" and "cancelled" in (run["error"] or "")
        print(f"    cancel  -> error: {run['error']}  OK")
    finally:
        runner.WORKFLOWS.pop("__approval_demo__", None)


def test_unknown_workflow() -> None:
    print("\n[*] unknown workflowKey rejected (A12 controlled set)")
    r = client.post("/v1/workflows/book_tennis/run", json={"suggestionId": "x"})
    assert r.status_code == 404, r.text
    print(f"    404 as expected: {r.json()['detail']}")


def test_live_inbox() -> None:
    print("\n[4] LIVE — real run against the actual inbox (honest result)")
    run_id = client.post("/v1/workflows/gmail_to_sheet/run",
                         json={"suggestionId": "sug-live"}).json()["runId"]
    run = _poll(run_id, lambda x: x["status"] in ("done", "error"))
    print(f"    status={run['status']}")
    if run["status"] == "done":
        print(f"    row written: {run['result']['row']}")
    else:
        print(f"    error (expected if newest email isn't a receipt): {run['error']}")


if __name__ == "__main__":
    test_extraction()
    test_happy_path()
    test_approval_mechanism()
    test_unknown_workflow()
    test_live_inbox()
    print("\nAll run-contract checks passed.")
