"""LLM analyst: PatternDigest + motifs -> grounded Suggestions (A13-A15).

OpenAI is tried first; a deterministic heuristic generator is the fallback so
the pipeline (and DEMO_MODE) works with no network. workflowKey is assigned
deterministically by the backend — the LLM never invents keys (A12).
"""
import json
import os
import sqlite3
import uuid

from pydantic import ValidationError

from app import miner
from app.db import meta_get, meta_set, now_ms
from app.models import Suggestion

MIN_NEW_EVENTS = 25
ANALYZE_EVERY_MS = 30 * 60 * 1000

# Workflow registry (contract B7): one entry per executable workflowKey.
# Adding a workflow = one registry entry + one Literal member in models.py.
WORKFLOW_REGISTRY: dict[str, dict] = {
    "gmail_to_sheet": {
        "keywords_any": ("gmail", "mail.google", "receipt", "email"),
        "keywords_all": ("sheet", "spreadsheet", "docs.google"),
    },
}

GMAIL_HOSTS = ("mail.google.com", "gmail")
SHEET_HOSTS = ("docs.google.com", "sheets")


def new_events_pending(conn: sqlite3.Connection) -> int:
    watermark = int(meta_get(conn, "analyzed_rowid") or 0)
    row = conn.execute("SELECT COUNT(*) AS c FROM events WHERE rowid > ?", (watermark,)).fetchone()
    return row["c"]


def last_analysis_at(conn: sqlite3.Connection) -> int | None:
    v = meta_get(conn, "last_analysis_at")
    return int(v) if v else None


def should_analyze(conn: sqlite3.Connection) -> bool:
    last = last_analysis_at(conn) or 0
    return new_events_pending(conn) >= MIN_NEW_EVENTS and (now_ms() - last) >= ANALYZE_EVERY_MS


def run_analysis(conn: sqlite3.Connection, use_llm: bool = True) -> list[dict]:
    """Mine -> analyze -> validate -> dedupe -> save. Returns created suggestions."""
    events = miner.fetch_events(conn)
    if not events:
        _mark_analyzed(conn)
        return []
    digest = miner.compute_digest(conn)
    motifs = miner.mine_motifs(events)
    semantic = miner.mine_semantic(events)
    trace = miner.compact_trace(events)
    existing = _existing_summaries(conn)
    feedback = _feedback_rows(conn)

    raw: list[dict] = []
    if use_llm and os.environ.get("OPENAI_API_KEY"):
        try:
            raw = _llm_suggestions(digest, motifs, semantic, trace, existing, feedback)
        except Exception:
            raw = []
    if not raw:
        raw = _heuristic_suggestions(digest, motifs, semantic)

    created = _save_suggestions(conn, raw, digest)
    _mark_analyzed(conn)
    return created


def _mark_analyzed(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT COALESCE(MAX(rowid), 0) AS m FROM events").fetchone()
    meta_set(conn, "analyzed_rowid", str(row["m"]))
    meta_set(conn, "last_analysis_at", str(now_ms()))


# ---------- LLM path ----------

_SYSTEM = (
    "You are Mia's workflow analyst. You receive a PatternDigest of a user's "
    "sanitized browser activity plus mined repeated action sequences. Propose "
    "0-4 automation/workflow/rule suggestions grounded ONLY in the evidence. "
    "Each suggestion must cite 1-3 concrete observations (real counts, hosts, "
    "sequences). Return JSON: {\"suggestions\":[{kind,title,summary,evidence,"
    "steps,trigger,action,buildPrompt,confidence,timeSavedPerWeekMinutes}]}. "
    "title<=60 chars. steps required for kind=workflow, trigger required for "
    "kind=rule. Empty {\"suggestions\":[]} is valid when evidence is weak. "
    "Do not duplicate existing or dismissed suggestions."
)


def _llm_suggestions(digest, motifs, semantic, trace, existing, feedback) -> list[dict]:
    from openai import OpenAI

    client = OpenAI(timeout=20)
    payload = {
        "patternDigest": digest,
        "repeatedActionMotifs": motifs,
        "semanticContext": semantic,
        "recentTrace": trace,
        "existingSuggestions": existing,
        "userFeedback": feedback,
    }
    resp = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps(payload)},
        ],
    )
    data = json.loads(resp.choices[0].message.content or "{}")
    out = data.get("suggestions") or []
    return [s for s in out if isinstance(s, dict)][:4]


# ---------- heuristic fallback ----------

def _is_gmail(host: str) -> bool:
    return any(g in (host or "") for g in GMAIL_HOSTS)


def _is_sheet(host: str) -> bool:
    return any(s in (host or "") for s in SHEET_HOSTS)


def _heuristic_suggestions(digest, motifs, semantic) -> list[dict]:
    """Build the receipt-loop suggestion from mined evidence, no LLM needed."""
    cp = next(
        (p for p in digest["copyPaste"] if _is_gmail(p["from"]) and _is_sheet(p["to"])),
        None,
    )
    trans = next(
        (t for t in digest["transitions"]
         if any(_is_gmail(h) for h in t["path"]) and any(_is_sheet(h) for h in t["path"])),
        None,
    )
    if not cp and not trans:
        return []
    count = (cp or trans)["count"]
    days = max((s["days"] for s in digest["hosts"] if _is_gmail(s["host"])), default=1)
    evidence = []
    if cp:
        evidence.append(f"Copied from {cp['from']} and pasted into {cp['to']} {cp['count']} times")
    if trans:
        evidence.append(f"Repeated sequence {' -> '.join(trans['path'])} seen {trans['count']} times")
    semantic_hit = next((s for s in semantic if "receipt" in (s["area"] + s["target"])), None)
    if semantic_hit:
        evidence.append(f"Interacted with '{semantic_hit['area'] or semantic_hit['target']}' {semantic_hit['count']} times across {semantic_hit['days']} days")
    evidence = evidence[:3] or [f"Repeated gmail-to-sheet activity {count} times"]
    return [{
        "kind": "workflow",
        "title": "Log receipt emails to your expense sheet",
        "summary": "Mia noticed you repeatedly copy receipt totals from Gmail into a Google Sheet. She can do this for you when you choose to run it.",
        "evidence": evidence,
        "steps": [
            "Open the receipt email in Gmail",
            "Find and copy the receipt total",
            "Open the expense tracker sheet",
            "Append the total as a new row",
        ],
        "trigger": "",
        "action": "Read the latest receipt email, extract the total, and append a row to the expense sheet.",
        "buildPrompt": "Read receipt emails via Gmail API, extract the amount, append a row via Sheets API.",
        "confidence": min(0.5 + 0.1 * count, 0.95),
        "timeSavedPerWeekMinutes": 5 * count,
    }]


# ---------- workflowKey mapping (A12) ----------

def _determine_workflow_key(s: dict, digest) -> str | None:
    """Backend decides the key (A12) — LLM output is only a hint. A suggestion
    maps to a workflow when its text matches that workflow's keyword profile."""
    text = " ".join(
        [s.get("title", ""), s.get("summary", ""), s.get("action", "")]
        + s.get("steps", []) + s.get("evidence", [])
    ).lower()
    for key, spec in WORKFLOW_REGISTRY.items():
        if any(k in text for k in spec["keywords_any"]) and any(
            k in text for k in spec["keywords_all"]
        ):
            return key
    return None


# ---------- persistence ----------

def _existing_summaries(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT title, status FROM suggestions").fetchall()
    return [{"title": r["title"], "status": r["status"]} for r in rows]


def _feedback_rows(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT suggestion_id, decision, user_edits, created_at "
        "FROM suggestion_feedback ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    return [
        {"suggestionId": r["suggestion_id"], "decision": r["decision"],
         "userEdits": r["user_edits"], "at": r["created_at"]}
        for r in rows
    ]


def _save_suggestions(conn: sqlite3.Connection, raw: list[dict], digest) -> list[dict]:
    existing = {r["title"].strip().lower(): r["status"] for r in _existing_summaries(conn)}
    created: list[dict] = []
    for s in raw[:4]:
        title = str(s.get("title", "")).strip()[:60]
        if not title:
            continue
        key = title.lower()
        if key in existing:
            continue  # covers proposed/accepted/built AND dismissed re-proposals
        now = now_ms()
        candidate = {
            "id": str(uuid.uuid4()),
            "kind": s.get("kind") if s.get("kind") in ("workflow", "automation", "rule") else "workflow",
            "title": title,
            "summary": str(s.get("summary", ""))[:500],
            "evidence": [str(e)[:200] for e in (s.get("evidence") or [])[:3]],
            "steps": [str(x)[:200] for x in (s.get("steps") or [])[:8]],
            "trigger": str(s.get("trigger", ""))[:200],
            "action": str(s.get("action", ""))[:300],
            "buildPrompt": str(s.get("buildPrompt", ""))[:500],
            "workflowKey": _determine_workflow_key(s, digest),
            "confidence": max(0.0, min(1.0, float(s.get("confidence") or 0.0))),
            "timeSavedPerWeekMinutes": float(s.get("timeSavedPerWeekMinutes") or 0.0),
            "status": "proposed",
            "createdAt": now,
            "updatedAt": now,
        }
        try:
            sug = Suggestion.model_validate(candidate)
        except ValidationError:
            continue
        if sug.kind == "workflow" and not sug.steps:
            continue
        if sug.kind == "rule" and not sug.trigger:
            continue
        if not (1 <= len(sug.evidence) <= 3):
            continue
        conn.execute(
            """INSERT INTO suggestions
               (id, install_id, kind, title, summary, evidence_json, steps_json,
                trigger, action, build_prompt, workflow_key, confidence,
                time_saved_per_week_minutes, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sug.id, None, sug.kind, sug.title, sug.summary,
                json.dumps(sug.evidence), json.dumps(sug.steps),
                sug.trigger, sug.action, sug.buildPrompt, sug.workflowKey,
                sug.confidence, sug.timeSavedPerWeekMinutes, sug.status,
                sug.createdAt, sug.updatedAt,
            ),
        )
        existing[key] = "proposed"
        created.append(sug.model_dump())
    conn.commit()
    return created
