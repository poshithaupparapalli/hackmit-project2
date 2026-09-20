"""Deterministic receipt extraction for the gmail_to_sheet workflow.

Regex-based on purpose: for the demo the extraction must be reliable and offline,
not dependent on an LLM round-trip. Pulls amount (+currency), date, and vendor
from a receipt email's body/headers. Returns best-effort fields; `amount` is None
when nothing plausible is found (the runner treats that as an error rather than
writing a junk row).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime


@dataclass
class Receipt:
    amount: str | None          # e.g. "42.18"
    currency: str               # e.g. "$" or "USD" ("" if unknown)
    date: str                   # ISO date if known, else ""
    vendor: str                 # best-effort vendor/sender name

    def as_dict(self) -> dict:
        return asdict(self)


# "total", "amount due", "grand total", "amount paid", "you paid", "charged"
_TOTAL_HINT = re.compile(
    r"(grand\s+total|amount\s+due|amount\s+paid|total\s+paid|you\s+paid|"
    r"total\s+amount|order\s+total|total|charged|amount)\b[^\d$€£]{0,20}"
    r"(?P<cur>[$€£]|USD|EUR|GBP)?\s?(?P<val>\d[\d,]*(?:\.\d{1,2})?)",
    re.IGNORECASE,
)

# Any currency-prefixed number, as a fallback.
_ANY_MONEY = re.compile(
    r"(?P<cur>[$€£]|USD|EUR|GBP)\s?(?P<val>\d[\d,]*(?:\.\d{1,2})?)",
    re.IGNORECASE,
)

_CUR_NORMAL = {"$": "$", "€": "€", "£": "£", "usd": "USD", "eur": "EUR", "gbp": "GBP"}


def _clean_amount(raw: str) -> str:
    return raw.replace(",", "")


def _pick_amount(text: str) -> tuple[str | None, str]:
    """Prefer an amount next to a 'total'-like word; else the largest money value."""
    m = _TOTAL_HINT.search(text)
    if m and m.group("val"):
        cur = (m.group("cur") or "").lower()
        return _clean_amount(m.group("val")), _CUR_NORMAL.get(cur, m.group("cur") or "")

    best_val: float | None = None
    best_raw: str | None = None
    best_cur = ""
    for m in _ANY_MONEY.finditer(text):
        raw = _clean_amount(m.group("val"))
        try:
            val = float(raw)
        except ValueError:
            continue
        if best_val is None or val > best_val:
            best_val, best_raw, best_cur = val, raw, m.group("cur")
    if best_raw is not None:
        return best_raw, _CUR_NORMAL.get(best_cur.lower(), best_cur)
    return None, ""


def _vendor_from_sender(sender: str) -> str:
    """'Amazon <ship@amazon.com>' -> 'Amazon'; else the domain's second-level name."""
    name, addr = parseaddr(sender)
    if name:
        return name.strip()
    if "@" in addr:
        domain = addr.split("@", 1)[1]
        parts = domain.split(".")
        if len(parts) >= 2:
            return parts[-2].capitalize()
        return domain
    return sender.strip() or "Unknown"


def _date_from_header(date_header: str) -> str:
    if not date_header:
        return ""
    try:
        dt = parsedate_to_datetime(date_header)
        if dt is None:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.date().isoformat()
    except (TypeError, ValueError):
        return ""


def extract_receipt(body: str, subject: str = "", sender: str = "",
                    date_header: str = "") -> Receipt:
    """Extract receipt fields from an email. Amount search covers subject + body."""
    haystack = f"{subject}\n{body}"
    amount, currency = _pick_amount(haystack)
    return Receipt(
        amount=amount,
        currency=currency,
        date=_date_from_header(date_header) or datetime.now(timezone.utc).date().isoformat(),
        vendor=_vendor_from_sender(sender),
    )
