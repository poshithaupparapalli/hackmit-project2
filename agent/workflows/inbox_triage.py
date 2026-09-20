"""Read-only inbox triage; discovered by runner.discover_workflows().

MIA_TRIAGE_MAX_EMAILS (default 20, max 100) and MIA_TRIAGE_RECENT_DAYS
(default 7, max 365) bound reads. Replies are suggested text in B4 result,
not Gmail Draft resources; gmail.readonly is sufficient. No message is sent,
marked read, labeled, or modified. No sending capability is exposed. Any future
send implementation MUST call ctx.checkpoint() with the exact recipient and
message before sending, and respect cancellation (MIA_CONTRACTS.md B5).

Classification is deterministic and heuristic, not an LLM judgment. Email text
is treated only as data. Drafts deliberately leave decisions to the user.
"""
from __future__ import annotations

import os
import re
from email.utils import parseaddr
from html import unescape
from html.parser import HTMLParser

from .. import runner, tools

WORKFLOW_KEY = "inbox_triage"
STEP_LABELS = ["Reading unread emails", "Categorizing emails", "Drafting suggested replies"]
CATEGORIES = ("urgent", "needs-reply", "FYI", "newsletter")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if tag in ("p", "div", "br", "li"):
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _text(value: str) -> str:
    if re.search(r"</?(?:html|body|div|p|br|a|span)\b", value, re.I):
        parser = _Text()
        parser.feed(value)
        value = " ".join(parser.parts)
    return " ".join(unescape(value).split())


def _setting(name: str, default: int, maximum: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}.")
    return value


def read_unread_emails(limit: int, days: int) -> list[dict]:
    """Batch counterpart to tools.read_gmail, sharing its service/body decoder.

    The single-message helper accepts only a search query, not a Gmail ID.
    List/get by ID avoids repeatedly reading the same unread message.
    """
    if not 1 <= limit <= 100 or not 1 <= days <= 365:
        raise ValueError("Invalid triage read bounds.")
    messages = tools._service("gmail", "v1").users().messages()
    result, seen, tokens = [], set(), set()
    page_token = None
    while len(seen) < limit:
        params = dict(userId="me", labelIds=["INBOX", "UNREAD"],
                      q=f"newer_than:{days}d", maxResults=limit - len(seen))
        if page_token:
            params["pageToken"] = page_token
        page = messages.list(**params).execute()
        for item in page.get("messages", []):
            message_id = item["id"]
            if message_id in seen:
                continue
            seen.add(message_id)
            raw = messages.get(userId="me", id=message_id, format="full").execute()
            # A message may have been read/moved between list and get.
            if {"INBOX", "UNREAD"}.issubset(raw.get("labelIds", [])):
                payload = raw.get("payload", {})
                headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
                result.append({
                    "messageId": message_id, "threadId": raw.get("threadId", ""),
                    "subject": headers.get("subject", "(no subject)"),
                    "sender": headers.get("from", ""),
                    "replyTo": headers.get("reply-to", headers.get("from", "")),
                    "headers": headers,
                    "body": tools._extract_body(payload) or raw.get("snippet", ""),
                })
            if len(seen) >= limit:
                break
        page_token = page.get("nextPageToken")
        if not page_token:
            break
        if page_token in tokens:
            raise RuntimeError("Gmail repeated a pagination token.")
        tokens.add(page_token)
    return result


def categorize(email: dict) -> tuple[str, bool, str]:
    headers = email.get("headers", {})
    text = _text(email["subject"] + " " + email["body"]).lower()
    sender = email["sender"].lower()
    newsletter = bool(headers.get("list-unsubscribe") or headers.get("list-id")
                      or re.search(r"\b(newsletter|unsubscribe|weekly digest)\b", text))
    automated = bool(re.search(r"(?:no[-_.]?reply|do[-_.]?not[-_.]?reply)@", sender)
                     or headers.get("auto-submitted", "no").lower() != "no")
    no_reply = bool(re.search(r"\b(no (?:reply|response|action) (?:is )?(?:needed|required)|"
                              r"do not reply|for your information|fyi)\b", text))
    urgent = bool(re.search(r"\b(urgent|asap|time[- ]sensitive|deadline today|"
                            r"due today|by end of day|immediate attention)\b", text))
    request = bool("?" in text or re.search(
        r"\b(please (?:reply|respond|confirm|review|send|approve)|"
        r"let me know|can you|could you|awaiting your|need your)\b", text))
    if newsletter:
        return "newsletter", False, "Mailing-list or newsletter signal."
    needs_reply = (request or urgent) and not automated and not no_reply
    if urgent:
        return "urgent", needs_reply, "Time-sensitive language; review priority manually."
    if needs_reply:
        return "needs-reply", True, "Question or explicit request for a response."
    return "FYI", False, "Automated/informational message or no response request detected."


def draft_reply(email: dict) -> dict:
    """Create editable text only; never invent an answer or promise an action."""
    _, address = parseaddr(email.get("replyTo", email["sender"]))
    valid = bool(re.fullmatch(r"[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+", address))
    subject = email["subject"]
    return {
        "to": address if valid else None,
        "subject": subject if subject.lower().startswith("re:") else f"Re: {subject}",
        "body": "Hi,\n\nThanks for your message.\n\n"
                "[Add your answer or decision here before sending.]\n\nBest,\n[Your name]",
        "status": "suggested", "requiresReview": True,
        "recipientNeedsReview": not valid, "savedToGmail": False,
    }


def execute(ctx: runner.RunContext, suggestion_id: str) -> dict:
    active = STEP_LABELS[0]
    try:
        ctx.start_step(active)
        limit = _setting("MIA_TRIAGE_MAX_EMAILS", 20, 100)
        days = _setting("MIA_TRIAGE_RECENT_DAYS", 7, 365)
        emails = read_unread_emails(limit, days)
        ctx.finish_step(active)
        active = STEP_LABELS[1]
        ctx.start_step(active)
        items, counts = [], dict.fromkeys(CATEGORIES, 0)
        for email in emails:
            category, needs_reply, reason = categorize(email)
            counts[category] += 1
            items.append({"messageId": email["messageId"], "threadId": email["threadId"],
                          "subject": email["subject"], "sender": email["sender"],
                          "category": category, "needsReply": needs_reply,
                          "reason": reason, "suggestedReply": None})
        ctx.finish_step(active)
        active = STEP_LABELS[2]
        ctx.start_step(active)
        for email, item in zip(emails, items):
            if item["needsReply"]:
                item["suggestedReply"] = draft_reply(email)
        ctx.finish_step(active)
        return {"emailsProcessed": len(items), "categoryCounts": counts,
                "draftsSuggested": sum(item["suggestedReply"] is not None for item in items),
                "emails": items, "draftOnly": True, "messagesSent": 0,
                "recentDays": days, "maxEmails": limit}
    except Exception:
        ctx.fail_step(active)
        raise


def register() -> None:
    runner.WORKFLOWS[WORKFLOW_KEY] = (list(STEP_LABELS), execute)


register()
