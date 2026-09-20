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
# Order matters: entries are tried top-down, so the most specific (two-app)
# profiles come first. "keywords_all" is a second required keyword group; an
# empty group means the profile is decided by "keywords_any" alone.
WORKFLOW_REGISTRY: dict[str, dict] = {
    "gmail_to_sheet": {
        "keywords_any": ("gmail", "mail.google", "receipt", "email"),
        "keywords_all": ("sheet", "spreadsheet", "docs.google"),
    },
    "email_to_calendar": {
        # No bare "event": it matches "Gmail events" in unrelated evidence.
        "keywords_any": ("calendar", "meeting", "invite", "invitation"),
        "keywords_all": (),
    },
    "inbox_triage": {
        "keywords_any": ("unread", "triage", "inbox", "reply", "draft", "archive"),
        "keywords_all": (),
    },
}

GMAIL_HOSTS = ("mail.google.com", "gmail")
SHEET_HOSTS = ("docs.google.com", "sheets")
CALENDAR_HOSTS = ("calendar.google.com", "calendar")


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
    "You are Mia's workflow analyst. Mia's whole purpose is to notice a "
    "person's repeated, unwritten workflows and explain WHAT they accomplish "
    "— not just which apps were used or how many times. You receive a "
    "PatternDigest of sanitized browsing activity plus mined repeated action "
    "sequences. Propose 0-4 automation/workflow/rule suggestions grounded "
    "ONLY in the evidence given.\n"
    "Semantic fields — page titles, item titles, section names, labels, "
    "nearby snippets, semantic value categories (currency/email/datetime/etc) "
    "— are the PRIMARY evidence: they say what the user was actually "
    "doing. Repetition counts and host-transition counts are SUPPORTING "
    "detail only, never the headline. Name the workflow by the user's "
    "apparent goal, not the applications. Prefer 'Log receipt totals from "
    "receipt emails into Fall 2026 Expenses' over 'Move data from Gmail to "
    "Sheets'.\n"
    "Every evidence line must read as a plain-language description of what "
    "was observed, e.g. 'Copied a currency value labeled \"Total\" from "
    "\"Receipt from Uber\" in Gmail, then pasted it into \"Amount\" in \"Fall "
    "2026 Expenses\" (seen 9 times)' — NOT a bare mechanical count like "
    "'9 copy-paste events between mail.google.com and docs.google.com'. If no "
    "semantic field is available for a pattern, say so plainly instead of "
    "inventing one; a mechanical count with no semantic grounding is weak "
    "evidence and should lower confidence, not be dressed up as a finding.\n"
    "steps must be a short, plain-language, ordered walkthrough of what Mia "
    "would actually do, one step per array item, written for someone "
    "non-technical — required for kind=workflow. The UI numbers the array "
    "for you: do NOT prefix step text with '1.', '2)', etc. yourself. "
    "trigger required for kind=rule. Distinguish "
    "evidence from inference and never invent names, amounts, or details not "
    "present in the input. Return JSON: {\"suggestions\":[{kind,title,summary,"
    "evidence,steps,trigger,action,buildPrompt,confidence,"
    "timeSavedPerWeekMinutes}]}. title<=60 chars. Empty {\"suggestions\":[]} "
    "is valid when evidence is weak. Do not duplicate existing or dismissed "
    "suggestions."
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


def _is_calendar(host: str) -> bool:
    return any(c in (host or "") for c in CALENDAR_HOSTS)


_HINT_KEYS = ("pageTitle", "itemTitle", "sectionLabel", "formLabel",
              "targetLabel", "nearbyText", "semanticType")


def _specific_destination(digest, host_test, generic: set[str]) -> str:
    """Choose a bounded observed title for a host family (e.g. the sheet name)."""
    for hint in digest.get("contextHints", []):
        if not host_test(hint.get("host", "")):
            continue
        for key in ("pageTitle", "itemTitle"):
            value = str(hint.get(key) or "").strip()
            if value and value.lower() not in generic:
                return value
    for host in digest.get("hosts", []):
        if not host_test(host.get("host", "")):
            continue
        for value in host.get("topTitles", []):
            value = str(value or "").strip()
            if value and value.lower() not in generic:
                return value
    return ""


def _specific_sheet_name(digest) -> str:
    return _specific_destination(
        digest, _is_sheet, {"google sheets", "sheets", "spreadsheet"}
    )


def _matching_hints(digest, host_test, keywords) -> list[dict]:
    """contextHints on a host family whose bounded labels mention a keyword."""
    out = []
    for hint in digest.get("contextHints", []):
        if not host_test(hint.get("host", "")):
            continue
        text = " ".join(str(hint.get(k) or "") for k in _HINT_KEYS).lower()
        if any(k in text for k in keywords):
            out.append(hint)
    return out


def _hint_label(hint) -> str:
    for key in ("itemTitle", "targetLabel", "formLabel", "sectionLabel", "pageTitle"):
        value = str(hint.get(key) or "").strip()
        if value:
            return value
    return ""


def _copy_paste(digest, from_test, to_test) -> dict | None:
    return next(
        (p for p in digest["copyPaste"] if from_test(p["from"]) and to_test(p["to"])),
        None,
    )


def _transition(digest, a_test, b_test) -> dict | None:
    return next(
        (t for t in digest["transitions"]
         if any(a_test(h) for h in t["path"]) and any(b_test(h) for h in t["path"])),
        None,
    )


def _host_stat(digest, host_test) -> dict | None:
    return next((s for s in digest["hosts"] if host_test(s["host"])), None)


def _heuristic_suggestions(digest, motifs, semantic) -> list[dict]:
    """Offline analyst: one suggestion per pattern family present in the digest.

    Each generator returns None when its evidence is absent, so a digest with
    only receipt activity still yields exactly the receipt suggestion.
    """
    out = [
        _receipt_suggestion(digest, semantic),
        _calendar_suggestion(digest),
        _triage_suggestion(digest),
    ]
    return [s for s in out if s][:4]


def _receipt_suggestion(digest, semantic) -> dict | None:
    """Build the receipt-loop suggestion from mined evidence, no LLM needed."""
    cp = _copy_paste(digest, _is_gmail, _is_sheet)
    trans = _transition(digest, _is_gmail, _is_sheet)
    if not cp and not trans:
        return None
    count = (cp or trans)["count"]
    # Semantic evidence leads (what the user was actually doing); mechanical
    # counts are supporting detail only, appended after — never the headline.
    evidence = []
    semantic_hit = next((s for s in semantic if "receipt" in " ".join(str(s.get(key, "")) for key in ("pageTitle", "itemTitle", "area", "target", "nearbyText"))), None)
    if semantic_hit:
        identity = semantic_hit.get("itemTitle") or semantic_hit.get("area") or semantic_hit.get("target")
        target = semantic_hit.get("target")
        value_type = semantic_hit.get("semanticType")
        if target and value_type and identity:
            evidence.append(f"Copied a {value_type} value labeled '{target}' from '{identity}' (seen {semantic_hit['count']} times across {semantic_hit['days']} days)")
        elif identity:
            evidence.append(f"Repeatedly opened and acted on '{identity}' ({semantic_hit['count']} times across {semantic_hit['days']} days)")
    if cp:
        evidence.append(f"Supporting pattern: copied from {cp['from']} and pasted into {cp['to']} ({cp['count']} times)")
    if trans and not cp:
        evidence.append(f"Supporting pattern: moved from {' to '.join(trans['path'])} repeatedly ({trans['count']} times)")
    evidence = evidence[:3] or [f"Repeated Gmail-to-Sheets activity {count} times, but no page titles or labels were specific enough to describe the content"]
    sheet_name = _specific_sheet_name(digest)
    destination = f'"{sheet_name}"' if sheet_name else "your expense sheet"
    title = f"Log receipt totals into {sheet_name}" if sheet_name else "Log receipt emails to your expense sheet"
    return {
        "kind": "workflow",
        "title": title,
        "summary": f"Mia noticed you repeatedly copy receipt totals from Gmail into {destination}. She can do this for you when you choose to run it.",
        "evidence": evidence,
        "steps": [
            "Open the receipt email in Gmail",
            "Find and copy the receipt total",
            "Open the expense tracker sheet",
            "Append the total as a new row",
        ],
        "trigger": "",
        "action": f"Read the latest receipt email, extract the total, and append a row to {destination}.",
        "buildPrompt": f"Read receipt emails via Gmail API, extract the amount, append a row via Sheets API to {destination}.",
        "confidence": min(0.5 + 0.1 * count, 0.95),
        "timeSavedPerWeekMinutes": 5 * count,
    }


def _calendar_suggestion(digest) -> dict | None:
    """Gmail invite -> Google Calendar event loop (B7 email_to_calendar)."""
    cp = _copy_paste(digest, _is_gmail, _is_calendar)
    trans = _transition(digest, _is_gmail, _is_calendar)
    if not cp and not trans:
        return None
    count = (cp or trans)["count"]
    evidence = []
    if cp:
        evidence.append(f"Copied from {cp['from']} and pasted into {cp['to']} {cp['count']} times")
    if trans:
        evidence.append(f"Repeated sequence {' -> '.join(trans['path'])} seen {trans['count']} times")
    invite = next(
        (h for h in _matching_hints(digest, _is_gmail, ("invite", "invitation", "meeting"))
         if h.get("itemTitle")),
        None,
    )
    if invite:
        evidence.append(
            f"Opened invitation '{invite['itemTitle']}' in Gmail {invite['count']} times"
        )
    evidence = evidence[:3] or [f"Repeated gmail-to-calendar activity {count} times"]
    cal_name = _specific_destination(digest, _is_calendar, {"google calendar", "calendar"})
    destination = f'"{cal_name}"' if cal_name else "your Google Calendar"
    title = f"Add meeting invites to {cal_name}" if cal_name else "Create calendar events from meeting emails"
    return {
        "kind": "workflow",
        "title": title,
        "summary": f"Mia noticed you retype meeting details from Gmail invites into {destination}. She can create the event for you when you choose to run it.",
        "evidence": evidence,
        "steps": [
            "Open the meeting invitation email in Gmail",
            "Read the title, date and time",
            "Open Google Calendar",
            "Create the event with those details",
        ],
        "trigger": "",
        "action": f"Read the latest meeting invitation email and create the matching event in {destination}.",
        "buildPrompt": f"Read invitation emails via Gmail API, extract title/start/end, create an event via Calendar API in {destination}.",
        "confidence": min(0.5 + 0.1 * count, 0.9),
        "timeSavedPerWeekMinutes": 4 * count,
    }


def _triage_suggestion(digest) -> dict | None:
    """Unread-inbox read/reply/file loop, single app (B7 inbox_triage)."""
    hits = _matching_hints(digest, _is_gmail, ("unread", "reply", "draft", "archive", "triage"))
    total = sum(h["count"] for h in hits)
    if total < 3:
        return None
    stat = _host_stat(digest, _is_gmail)
    evidence, seen = [], set()
    for hint in hits:
        label = _hint_label(hint)
        if not label or label.lower() in seen or len(evidence) >= 2:
            continue
        seen.add(label.lower())
        evidence.append(f"Used '{label}' in Gmail {hint['count']} times")
    if stat and len(evidence) < 3:
        evidence.append(f"{stat['events']} Gmail actions across {stat['days']} days")
    evidence = evidence[:3] or [f"Repeated unread-inbox handling {total} times"]
    return {
        "kind": "workflow",
        "title": "Triage unread mail and draft the replies",
        "summary": "Mia noticed you work through unread threads the same way: read, reply, file. She can sort them and draft the replies for you — drafts only, never sent without your approval.",
        "evidence": evidence,
        "steps": [
            "List the unread threads in the inbox",
            "Group them by what they need",
            "Draft a reply for the ones that need an answer",
            "Leave every draft for you to review before sending",
        ],
        "trigger": "",
        "action": "Read unread Gmail threads, categorize them, and save a draft reply for each one that needs an answer.",
        "buildPrompt": "Read unread threads via Gmail API, categorize them, create draft replies via Gmail API. Never send without explicit approval.",
        "confidence": min(0.45 + 0.02 * total, 0.85),
        "timeSavedPerWeekMinutes": min(2 * total, 40),
    }


# ---------- workflowKey mapping (A12) ----------

def _string_list(value) -> list[str]:
    """Normalize permissive model JSON before applying the frozen schema.

    Models occasionally emit one string where the prompt asked for an array.
    Treat that as one item instead of allowing an analysis task to crash the
    backend worker. Non-string values are converted only after truncation at
    the schema boundary below.
    """
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _determine_workflow_key(s: dict, digest) -> str | None:
    """Backend decides the key (A12) — LLM output is only a hint. A suggestion
    maps to a workflow when its text matches that workflow's keyword profile.

    Rules never get a workflowKey. A rule describes a standing condition
    ("only for receipts over $25"), but the registered tools (gmail_to_sheet,
    email_to_calendar) execute one concrete action and have no way to read or
    enforce that condition — Run would silently ignore it. Offering Run on a
    rule would be misleading, not just mislabeled, so kind=workflow/automation
    are the only executable kinds until conditional execution actually exists.
    """
    if s.get("kind") == "rule":
        return None
    text = " ".join(
        [str(s.get("title", "")), str(s.get("summary", "")), str(s.get("action", ""))]
        + _string_list(s.get("steps")) + _string_list(s.get("evidence"))
    ).lower()
    for key, spec in WORKFLOW_REGISTRY.items():
        if not any(k in text for k in spec["keywords_any"]):
            continue
        required = spec.get("keywords_all") or ()
        if required and not any(k in text for k in required):
            continue
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
        try:
            candidate = {
                "id": str(uuid.uuid4()),
                "kind": s.get("kind") if s.get("kind") in ("workflow", "automation", "rule") else "workflow",
                "title": title,
                "summary": str(s.get("summary", ""))[:500],
                "evidence": [item[:200] for item in _string_list(s.get("evidence"))[:3]],
                "steps": [item[:200] for item in _string_list(s.get("steps"))[:8]],
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
        except (TypeError, ValueError):
            # One malformed candidate must not discard valid suggestions or
            # terminate the periodic analysis loop.
            continue
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
