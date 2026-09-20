"""DEMO_MODE support (B6). Prerecorded receipt-run events are seeded into the
event DB so the miner -> analyst pipeline produces the suggestion with no live
capture. Default analysis in demo mode uses the heuristic analyst so the demo
works with no network; set DEMO_LLM=true to opt back into OpenAI.
"""
import json
import os
import sqlite3
from pathlib import Path

from app import analyst
from app.auth import create_install
from app.db import meta_set, now_ms

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FALLBACK_EVENTS = DATA_DIR / "fallback_events.jsonl"

DEMO_INSTALL_ID = "demo-install"
DEMO_TOKEN = "demo-token"


def demo_mode() -> bool:
    return os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")


def seed_demo_events(conn: sqlite3.Connection) -> int:
    """Insert prerecorded events under the demo install. Idempotent."""
    create_install(conn, DEMO_INSTALL_ID, DEMO_TOKEN, now_ms())
    if not FALLBACK_EVENTS.exists():
        return 0
    inserted = 0
    for line in FALLBACK_EVENTS.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        ev = json.loads(line)
        detail = ev.pop("detail", None)
        context = ev.pop("context", None)
        cur = conn.execute(
            """INSERT OR IGNORE INTO events
               (id, install_id, session_id, timestamp, sequence, tab_id, frame_id,
                type, host, path, title, detail_json, context_json, received_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ev["id"], DEMO_INSTALL_ID, ev["sessionId"], ev["timestamp"],
                ev["sequence"], ev["tabId"], ev["frameId"], ev["type"],
                ev["host"], ev["path"], ev.get("title"),
                json.dumps(detail) if detail else None,
                json.dumps(context) if context else None,
                now_ms(),
            ),
        )
        inserted += cur.rowcount
    conn.commit()
    meta_set(conn, "last_event_at", str(now_ms()))
    return inserted


def bootstrap_demo(conn: sqlite3.Connection) -> dict:
    """Seed events + run analysis so suggestions exist at startup."""
    n = seed_demo_events(conn)
    use_llm = os.environ.get("DEMO_LLM", "").lower() in ("1", "true", "yes")
    created = analyst.run_analysis(conn, use_llm=use_llm)
    return {"seededEvents": n, "suggestionsCreated": len(created)}
