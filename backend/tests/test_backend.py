"""Acceptance tests for Kathy's detection backend (contract Part H)."""
import json
import os
import sqlite3
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MIA_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # deterministic, offline
    from app.db import reset_conn
    from app.main import app

    reset_conn()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth(client):
    r = client.post("/v1/install")
    assert r.status_code == 200
    data = r.json()
    return {"Authorization": f"Bearer {data['installToken']}"}, data["installId"]


def _ev(i, ts, etype="nav", host="example.com", path="/", **kw):
    return {
        "schemaVersion": 1, "id": str(uuid.uuid4()), "installId": "x",
        "sessionId": "s1", "timestamp": ts, "sequence": i,
        "tabId": 1, "frameId": 0, "type": etype, "host": host, "path": path,
        **kw,
    }


def _batch(install_id, events):
    return {"schemaVersion": 1, "installId": install_id, "sentAt": 1, "events": events}


# --- test 1: reposting a batch does not duplicate events ---

def test_repost_no_duplicates(client, auth):
    headers, install_id = auth
    events = [_ev(i, 1000 + i) for i in range(5)]
    r1 = client.post("/v1/events/batch", json=_batch(install_id, events), headers=headers)
    r2 = client.post("/v1/events/batch", json=_batch(install_id, events), headers=headers)
    assert r1.status_code == 200 and r2.status_code == 200
    assert len(r2.json()["accepted"]) == 5  # still accepted so queue clears
    from app.db import get_conn
    n = get_conn().execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
    assert n == 5


def test_requires_auth(client):
    r = client.post("/v1/events/batch", json=_batch("x", []))
    assert r.status_code == 401


# --- tests 7/9/10: privacy — no query strings, oversized detail rejected ---

def test_query_string_rejected(client, auth):
    headers, install_id = auth
    r = client.post("/v1/events/batch", json=_batch(
        install_id, [_ev(1, 1, path="/search?q=secret")]), headers=headers)
    assert r.json()["rejected"][0]["reason"].startswith("path contains")


def test_fragment_rejected(client, auth):
    headers, install_id = auth
    r = client.post("/v1/events/batch", json=_batch(
        install_id, [_ev(1, 1, path="/mail/u/0/#inbox")]), headers=headers)
    assert len(r.json()["rejected"]) == 1


# --- tests 11/12: repeated receipt runs -> grounded suggestion ---

def _seed_receipt_events(client, headers, install_id):
    from app.demo import seed_demo_events
    from app.db import get_conn
    seed_demo_events(get_conn())


def test_receipt_suggestion(client, auth):
    headers, install_id = auth
    _seed_receipt_events(client, headers, install_id)
    from app.analyst import run_analysis
    from app.db import get_conn
    created = run_analysis(get_conn(), use_llm=False)
    assert len(created) >= 1
    sug = created[0]
    assert sug["workflowKey"] == "gmail_to_sheet"
    assert "Expense Tracker" in sug["title"]
    assert 1 <= len(sug["evidence"]) <= 3
    assert sug["kind"] == "workflow" and sug["steps"]

    r = client.get("/v1/suggestions")
    assert r.status_code == 200
    titles = [s["title"] for s in r.json()]
    assert sug["title"] in titles


# --- tests 13/14/15: status + feedback persistence ---

def test_dismiss_restore_persists(client, auth):
    headers, _ = auth
    _seed_receipt_events(client, headers, _)
    from app.analyst import run_analysis
    from app.db import get_conn
    created = run_analysis(get_conn(), use_llm=False)
    sid = created[0]["id"]

    r = client.patch(f"/v1/suggestions/{sid}", json={"status": "dismissed"})
    assert r.json()["status"] == "dismissed"
    r = client.patch(f"/v1/suggestions/{sid}", json={"status": "accepted"})
    assert r.json()["status"] == "accepted"


def test_feedback_persists_edits(client, auth):
    headers, _ = auth
    _seed_receipt_events(client, headers, _)
    from app.analyst import run_analysis
    from app.db import get_conn
    conn = get_conn()
    created = run_analysis(conn, use_llm=False)
    sid = created[0]["id"]

    r = client.post(f"/v1/suggestions/{sid}/feedback", json={
        "decision": "edit",
        "userEdits": "Only do this for reimbursement receipts over $25.",
    })
    assert r.status_code == 200
    row = conn.execute(
        "SELECT * FROM suggestion_feedback WHERE suggestion_id = ?", (sid,)
    ).fetchone()
    assert row["decision"] == "edit"
    assert "$25" in row["user_edits"]


def test_analyze_and_status_endpoints(client, auth):
    r = client.post("/v1/analyze")
    assert r.status_code == 200 and r.json()["queued"] is True
    r = client.get("/v1/status")
    assert set(r.json()) == {
        "observerOnline", "paused", "lastEventAt", "lastAnalysisAt", "newEventsPending"
    }


def test_llm_shape_drift_does_not_crash_analysis(client, auth, monkeypatch):
    """A model returning strings for array fields is still safely handled."""
    _seed_receipt_events(client, *auth)
    from app import analyst
    from app.db import get_conn

    raw = [{
        "kind": "workflow",
        "title": "Copy receipts into a sheet",
        "summary": "Repeated Gmail to Sheets activity.",
        "evidence": "Copied from Gmail and pasted into Sheets.",
        "steps": "Open Gmail, then open Sheets.",
        "confidence": "0.8",
        "timeSavedPerWeekMinutes": "10",
    }]
    created = analyst._save_suggestions(get_conn(), raw, {})
    assert created and created[0]["workflowKey"] == "gmail_to_sheet"
    assert created[0]["evidence"] == ["Copied from Gmail and pasted into Sheets."]


def test_rich_context_round_trips_into_digest_and_trace(client, auth):
    headers, install_id = auth
    from app.db import now_ms
    event = _ev(
        1, now_ms(), etype="copy", host="mail.google.com", path="/mail/u/0/",
        title="Gmail", detail={"length": 5}, context={
            "pageTitle": "Gmail", "itemTitle": "Receipt from Uber",
            "sectionLabel": "September", "targetLabel": "Total",
            "nearbyText": "Receipt from Uber — Sep 19", "semanticType": "currency",
        },
    )
    event2 = {**event, "id": str(uuid.uuid4()), "sequence": 2, "timestamp": event["timestamp"] + 1}
    response = client.post("/v1/events/batch", json=_batch(install_id, [event, event2]), headers=headers)
    assert response.status_code == 200 and response.json()["accepted"] == [event["id"], event2["id"]]
    from app.db import get_conn
    from app.miner import compact_trace, compute_digest, fetch_events, mine_semantic
    row = get_conn().execute("SELECT context_json FROM events WHERE id = ?", (event["id"],)).fetchone()
    stored = json.loads(row["context_json"])
    assert stored["itemTitle"] == "Receipt from Uber"
    digest = compute_digest(get_conn())
    assert any(
        hint["itemTitle"] == "Receipt from Uber"
        and hint["nearbyText"] == "Receipt from Uber — Sep 19"
        for hint in digest["contextHints"]
    )
    semantic = mine_semantic(fetch_events(get_conn()))
    assert any(item["itemTitle"] == "receipt from uber" and item["semanticType"] == "currency" for item in semantic)
    trace = compact_trace(fetch_events(get_conn()))
    assert any('copied currency value labeled "Total" from "Receipt from Uber"' in line for line in trace)
