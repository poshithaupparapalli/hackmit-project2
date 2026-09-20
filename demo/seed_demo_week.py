#!/usr/bin/env python3
"""
Seeds Mia with a synthetic executive-assistant workweek through the REAL ingestion API,
then forces analysis and prints resulting suggestions.

Run with the backend already running, normally:
    cd <repo-root>
    source backend/.venv/bin/activate
    python demo/seed_demo_week.py

Environment:
    MIA_DEMO_BASE_URL=http://localhost:8000   (default)
"""

from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
DATASET = HERE / "executive_assistant_week.json"
STATE = HERE / ".demo_seed_state.json"
BASE_URL = os.getenv("MIA_DEMO_BASE_URL", "http://localhost:8000").rstrip("/")

def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def save_state(state: dict):
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")

def get_or_create_install(client: httpx.Client) -> dict:
    if STATE.exists():
        state = load_json(STATE)
        if state.get("installId") and state.get("installToken"):
            return state
    r = client.post(f"{BASE_URL}/v1/install")
    r.raise_for_status()
    state = r.json()
    save_state(state)
    return state

def create_fresh_install(client: httpx.Client) -> dict:
    r = client.post(f"{BASE_URL}/v1/install")
    r.raise_for_status()
    state = r.json()
    save_state(state)
    return state

def prepare_events(install_id: str) -> list[dict]:
    payload = load_json(DATASET)
    events = payload["events"]
    for e in events:
        e["installId"] = install_id
    return events

def post_batches(client: httpx.Client, state: dict, events: list[dict]) -> tuple[int, list]:
    headers = {"Authorization": f"Bearer {state['installToken']}"}
    accepted = 0
    rejected = []
    for i in range(0, len(events), 250):
        batch = events[i:i+250]
        body = {
            "schemaVersion": 1,
            "installId": state["installId"],
            "sentAt": int(time.time() * 1000),
            "events": batch,
        }
        r = client.post(f"{BASE_URL}/v1/events/batch", headers=headers, json=body)
        if r.status_code == 401:
            raise PermissionError("stored demo install token is no longer valid")
        r.raise_for_status()
        data = r.json()
        accepted += len(data.get("accepted", []))
        rejected.extend(data.get("rejected", []))
    return accepted, rejected

def force_analysis(client: httpx.Client):
    before = client.get(f"{BASE_URL}/v1/status").json()
    before_ts = before.get("lastAnalysisAt")

    r = client.post(f"{BASE_URL}/v1/analyze")
    r.raise_for_status()
    print("Analysis queued.")

    deadline = time.time() + 90
    while time.time() < deadline:
        time.sleep(1)
        status = client.get(f"{BASE_URL}/v1/status").json()
        after_ts = status.get("lastAnalysisAt")
        if after_ts and after_ts != before_ts:
            print(f"Analysis finished: {after_ts}")
            return
    print("WARNING: analysis did not report completion within 90 seconds.", file=sys.stderr)

def print_suggestions(client: httpx.Client):
    r = client.get(f"{BASE_URL}/v1/suggestions")
    r.raise_for_status()
    data = r.json()
    suggestions = data if isinstance(data, list) else data.get("suggestions", data)
    print("\n=== Suggestions ===")
    if isinstance(suggestions, list):
        for s in suggestions:
            print(
                f"- [{s.get('kind','?')}] {s.get('title','(untitled)')} "
                f"| workflowKey={s.get('workflowKey')} | status={s.get('status')}"
            )
    else:
        print(json.dumps(data, indent=2))

def main():
    print(f"Mia demo backend: {BASE_URL}")
    with httpx.Client(timeout=30.0) as client:
        try:
            h = client.get(f"{BASE_URL}/health")
            h.raise_for_status()
        except Exception as exc:
            raise SystemExit(f"Backend is not reachable at {BASE_URL}: {exc}")

        state = get_or_create_install(client)
        events = prepare_events(state["installId"])

        try:
            accepted, rejected = post_batches(client, state, events)
        except PermissionError:
            print("Stored demo token is invalid (common after wiping mia.db). Creating a new install...")
            state = create_fresh_install(client)
            events = prepare_events(state["installId"])
            accepted, rejected = post_batches(client, state, events)

        print(f"Posted {len(events)} events; backend accepted/re-accepted {accepted}.")
        if rejected:
            print(f"{len(rejected)} rejected events:")
            for item in rejected:
                print(" ", item)
            raise SystemExit(1)

        force_analysis(client)
        print_suggestions(client)

        print("\nSeed complete.")
        print("If the calendar workflow did not appear, confirm OPENAI_API_KEY is set;")
        print("the backend's heuristic fallback cannot generate email_to_calendar.")

if __name__ == "__main__":
    main()
