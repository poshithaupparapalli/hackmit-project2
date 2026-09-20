"""Deterministic pattern miner.

Two layers:
1. Contract PatternDigest fields (A11) — frozen schema.
2. Generalization layer — normalized event signatures, n-gram motifs across ALL
   event types, semantic-context grouping, session fingerprints. These are not
   contract fields; they feed the analyst prompt via A15's trace/context channel.
"""
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone

SESSION_GAP_MS = 15 * 60 * 1000
COPY_PASTE_WINDOW_MS = 120 * 1000
MIN_MOTIF_COUNT = 2


# ---------- helpers ----------

_DIGIT_RUN = re.compile(r"\d+")
_WS = re.compile(r"\s+")


def normalize_path(path: str) -> str:
    """Collapse digits/UUID-ish segments so /receipt/123 == /receipt/456."""
    return _DIGIT_RUN.sub("#", path or "")


def _norm_label(value) -> str:
    if not value:
        return ""
    s = _WS.sub(" ", str(value)).strip().lower()
    return _DIGIT_RUN.sub("#", s)[:60]


def _event_context(ev: sqlite3.Row) -> dict:
    try:
        value = json.loads(ev["context_json"]) if ev["context_json"] else {}
        return value if isinstance(value, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _friendly_host(host: str) -> str:
    return {
        "mail.google.com": "Gmail",
        "docs.google.com": "Google Sheets",
        "calendar.google.com": "Google Calendar",
    }.get(host, host)


def _quoted(value: str) -> str:
    return f'"{value}"' if value else ""


def event_signature(ev: sqlite3.Row) -> str:
    """Canonical `{type}:{host}:{label}` signature for motif mining."""
    detail = json.loads(ev["detail_json"]) if ev["detail_json"] else {}
    ctx = _event_context(ev)
    label = ""
    t = ev["type"]
    if t == "click":
        label = detail.get("label") or detail.get("role") or detail.get("tag") or ""
    elif t in ("edit", "submit"):
        label = detail.get("name") or detail.get("actionPath") or ""
    elif t == "paste":
        label = detail.get("targetName") or detail.get("targetTag") or ""
    elif t == "shortcut":
        label = detail.get("key") or ""
    elif t == "nav":
        label = normalize_path(ev["path"] or "")
    elif t == "scroll":
        label = str(detail.get("depth") or "")
    if not label:
        label = ctx.get("targetLabel") or ctx.get("itemTitle") or ctx.get("sectionLabel") or ctx.get("pageTitle") or ""
    return f"{t}:{ev['host']}:{_norm_label(label)}"


def fetch_events(conn: sqlite3.Connection, window_days: int = 7) -> list[sqlite3.Row]:
    cutoff = int(datetime.now(tz=timezone.utc).timestamp() * 1000) - window_days * 86400_000
    return conn.execute(
        "SELECT * FROM events WHERE timestamp >= ? ORDER BY timestamp, sequence",
        (cutoff,),
    ).fetchall()


def split_sessions(events: list[sqlite3.Row]) -> list[list[sqlite3.Row]]:
    sessions: list[list[sqlite3.Row]] = []
    current: list[sqlite3.Row] = []
    for ev in events:
        if current and ev["timestamp"] - current[-1]["timestamp"] > SESSION_GAP_MS:
            sessions.append(current)
            current = []
        current.append(ev)
    if current:
        sessions.append(current)
    return sessions


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


# ---------- contract digest (A11) ----------

def compute_digest(conn: sqlite3.Connection, window_days: int = 7) -> dict:
    events = fetch_events(conn, window_days)
    sessions = split_sessions(events)
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

    # hosts
    host_stats: dict[str, dict] = {}
    for ev in events:
        h = ev["host"]
        s = host_stats.setdefault(
            h, {"host": h, "events": 0, "navigations": 0, "minutes": 0.0,
                "days_set": set(), "paths": Counter(), "titles": Counter()}
        )
        s["events"] += 1
        if ev["type"] == "nav":
            s["navigations"] += 1
        s["days_set"].add(_day(ev["timestamp"]))
        if ev["path"]:
            s["paths"][ev["path"]] += 1
        if ev["title"]:
            s["titles"][ev["title"]] += 1
    # minutes: per session, per host, sum consecutive same-host gaps (< gap threshold)
    for sess in sessions:
        prev_by_host: dict[str, int] = {}
        for ev in sess:
            h = ev["host"]
            if h in prev_by_host:
                gap = ev["timestamp"] - prev_by_host[h]
                if 0 < gap < SESSION_GAP_MS:
                    host_stats[h]["minutes"] += gap / 60000.0
            prev_by_host[h] = ev["timestamp"]
    hosts = [
        {
            "host": s["host"], "events": s["events"], "navigations": s["navigations"],
            "minutes": round(s["minutes"], 1), "days": len(s["days_set"]),
            "topPaths": [p for p, _ in s["paths"].most_common(5)],
            "topTitles": [t for t, _ in s["titles"].most_common(5)],
        }
        for s in sorted(host_stats.values(), key=lambda x: -x["events"])
    ]

    # transitions: deduped-consecutive host sequences within sessions, n-grams 2..3
    trans_counts: Counter = Counter()
    for sess in sessions:
        host_seq: list[str] = []
        for ev in sess:
            if not host_seq or host_seq[-1] != ev["host"]:
                host_seq.append(ev["host"])
        for n in (2, 3):
            for i in range(len(host_seq) - n + 1):
                gram = tuple(host_seq[i : i + n])
                if len(set(gram)) > 1:
                    trans_counts[gram] += 1
    transitions = [
        {"path": list(g), "count": c}
        for g, c in trans_counts.most_common(20) if c >= 2
    ]

    # repeatedForms: submit grouped by (host, normalized path, form name)
    form_stats: dict[tuple, dict] = {}
    for ev in events:
        if ev["type"] != "submit":
            continue
        detail = json.loads(ev["detail_json"]) if ev["detail_json"] else {}
        key = (ev["host"], normalize_path(ev["path"] or ""), str(detail.get("name") or detail.get("actionPath") or "form"))
        f = form_stats.setdefault(key, {"count": 0, "days": set()})
        f["count"] += 1
        f["days"].add(_day(ev["timestamp"]))
    repeated_forms = [
        {"host": k[0], "path": k[1], "form": k[2], "count": f["count"], "days": len(f["days"])}
        for k, f in form_stats.items() if f["count"] >= 2
    ]

    # repeatedFields: edit grouped by (host, field name)
    field_counts: Counter = Counter()
    for ev in events:
        if ev["type"] == "edit":
            detail = json.loads(ev["detail_json"]) if ev["detail_json"] else {}
            name = detail.get("name") or detail.get("inputType") or "field"
            field_counts[(ev["host"], str(name))] += 1
    repeated_fields = [
        {"host": k[0], "field": k[1], "count": c}
        for k, c in field_counts.most_common(20) if c >= 2
    ]

    # copyPaste: copy → next paste within window, per session
    cp_counts: Counter = Counter()
    for sess in sessions:
        last_copy: sqlite3.Row | None = None
        for ev in sess:
            if ev["type"] == "copy":
                last_copy = ev
            elif ev["type"] == "paste" and last_copy is not None:
                if ev["timestamp"] - last_copy["timestamp"] <= COPY_PASTE_WINDOW_MS:
                    cp_counts[(last_copy["host"], ev["host"])] += 1
                last_copy = None
    copy_paste = [
        {"from": k[0], "to": k[1], "count": c}
        for k, c in cp_counts.most_common(20) if c >= 1
    ]

    session_dicts = [
        {
            "start": s[0]["timestamp"], "end": s[-1]["timestamp"],
            "events": len(s), "hosts": sorted({e["host"] for e in s}),
        }
        for s in sessions
    ]

    # Keep a small deterministic semantic digest alongside the frozen A11
    # structural fields. Repeated labels/titles are more useful to the analyst
    # than a raw event dump, and the list is capped to keep prompts bounded.
    hint_counts: Counter = Counter()
    for ev in events:
        ctx = _event_context(ev)
        identity = tuple(ctx.get(key, "") for key in ("pageTitle", "itemTitle", "sectionLabel", "formLabel", "targetLabel", "nearbyText", "semanticType"))
        if any(identity):
            hint_counts[(ev["host"], identity)] += 1
    context_hints = [
        {
            "host": host,
            "pageTitle": values[0] or None,
            "itemTitle": values[1] or None,
            "sectionLabel": values[2] or None,
            "formLabel": values[3] or None,
            "targetLabel": values[4] or None,
            "nearbyText": values[5] or None,
            "semanticType": values[6] or None,
            "count": count,
        }
        for (host, values), count in hint_counts.most_common(40)
    ]

    return {
        "computedAt": now_ms,
        "eventCount": len(events),
        "windowDays": window_days,
        "hosts": hosts,
        "transitions": transitions,
        "repeatedForms": repeated_forms,
        "repeatedFields": repeated_fields,
        "copyPaste": copy_paste,
        "sessions": session_dicts,
        "contextHints": context_hints,
    }


# ---------- generalization layer ----------

def mine_motifs(events: list[sqlite3.Row], n_max: int = 5) -> list[dict]:
    """Repeated n-grams over event signatures across ALL event types."""
    sessions = split_sessions(events)
    gram_sessions: dict[tuple, set] = defaultdict(set)
    gram_days: dict[tuple, set] = defaultdict(set)
    for si, sess in enumerate(sessions):
        sigs = [event_signature(e) for e in sess]
        for n in range(2, min(n_max, len(sigs)) + 1):
            for i in range(len(sigs) - n + 1):
                gram = tuple(sigs[i : i + n])
                if len(set(gram)) == 1:
                    continue
                gram_sessions[gram].add(si)
                gram_days[gram].add(_day(sess[i]["timestamp"]))
    motifs = [
        {"sequence": list(g), "count": len(sis), "days": len(gram_days[g])}
        for g, sis in gram_sessions.items()
        if len(sis) >= MIN_MOTIF_COUNT
    ]
    # prefer longer, more frequent motifs; drop motifs fully contained in a longer one
    motifs.sort(key=lambda m: (-m["count"], -len(m["sequence"])))
    kept: list[dict] = []
    for m in motifs:
        seq = m["sequence"]
        contained = any(
            len(k["sequence"]) > len(seq)
            and _is_subsequence(seq, k["sequence"])
            and k["count"] >= m["count"]
            for k in kept
        )
        if not contained:
            kept.append(m)
        if len(kept) >= 20:
            break
    return kept


def _is_subsequence(needle: list[str], hay: list[str]) -> bool:
    n = len(needle)
    return any(hay[i : i + n] == needle for i in range(len(hay) - n + 1))


def mine_semantic(events: list[sqlite3.Row]) -> list[dict]:
    """Task-level patterns via bounded titles, labels and value categories."""
    counts: Counter = Counter()
    days: dict[tuple, set] = defaultdict(set)
    for ev in events:
        ctx = _event_context(ev)
        area = ctx.get("formLabel") or ctx.get("sectionLabel") or ""
        target = ctx.get("targetLabel") or ""
        item = ctx.get("itemTitle") or ""
        page = ctx.get("pageTitle") or ""
        nearby = ctx.get("nearbyText") or ""
        semantic_type = ctx.get("semanticType") or ""
        if not (area or target or item or page or nearby):
            continue
        key = (ev["host"], _norm_label(page), _norm_label(item), _norm_label(area), _norm_label(target), _norm_label(nearby), semantic_type)
        counts[key] += 1
        days[key].add(_day(ev["timestamp"]))
    return [
        {
            "host": k[0], "pageTitle": k[1], "itemTitle": k[2],
            "area": k[3], "target": k[4], "nearbyText": k[5], "semanticType": k[6],
            "count": c, "days": len(days[k]),
        }
        for k, c in counts.most_common(20) if c >= 2
    ]


def compact_trace(events: list[sqlite3.Row], limit: int = 80) -> list[str]:
    """Human-readable, bounded trace that keeps task identity visible."""
    tail = events[-limit:]
    out = []
    for ev in tail:
        detail = json.loads(ev["detail_json"]) if ev["detail_json"] else {}
        ctx = _event_context(ev)
        site = _friendly_host(ev["host"])
        item = ctx.get("itemTitle") or ctx.get("pageTitle") or ev["title"] or ""
        target = ctx.get("targetLabel") or detail.get("label") or detail.get("name") or detail.get("targetName") or ""
        kind = ctx.get("semanticType")
        ts = datetime.fromtimestamp(ev["timestamp"] / 1000, tz=timezone.utc).strftime("%m-%d %H:%M")
        if ev["type"] in ("nav", "tabopen"):
            text = f"{ts} opened {site}"
            if item: text += f" — {_quoted(item)}"
        elif ev["type"] == "copy":
            text = f"{ts} {site} — copied {kind or 'a'} value"
            if target: text += f" labeled {_quoted(target)}"
            if item: text += f" from {_quoted(item)}"
        elif ev["type"] == "paste":
            text = f"{ts} {site} — pasted"
            if target: text += f" into {_quoted(target)}"
            if item: text += f" in {_quoted(item)}"
        elif ev["type"] == "edit":
            text = f"{ts} {site} — edited"
            if target: text += f" {_quoted(target)}"
            if kind: text += f" ({kind})"
        elif ev["type"] == "click":
            text = f"{ts} {site} — interacted with"
            if target: text += f" {_quoted(target)}"
            if item: text += f" in {_quoted(item)}"
        elif ev["type"] == "submit":
            text = f"{ts} {site} — submitted"
            if target: text += f" {_quoted(target)}"
            if item: text += f" in {_quoted(item)}"
        else:
            label = target or detail.get("key") or detail.get("depth") or ""
            text = f"{ts} {ev['type']} {site} {label}".strip()
        out.append(text[:500])
    return out
