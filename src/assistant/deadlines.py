"""Deadline audit (SPEC §6.4). The extractor proposes a value; code converts it to an instant with
the message's own offset and checks it against the words the sender used."""
from __future__ import annotations

import re
from datetime import date, timedelta

from . import instants

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december"]
_TIME_WORDS = re.compile(r"\d:|\b(am|pm|noon|morning|afternoon|evening)\b|\d(am|pm)\b")
_EOD = re.compile(r"\beod\b|end of (the )?day")


class DeadlineRefused(ValueError):
    pass


def resolve(text: str, value: str, sent_at: str) -> str:
    """Return the deadline instant, or raise DeadlineRefused with the failed check."""
    t = text.lower()
    off = instants.offset_of(sent_at)
    sent = instants.local_date(sent_at)
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}))?", value)
    if not m:
        raise DeadlineRefused(f"value {value!r} is not YYYY-MM-DD or YYYY-MM-DDTHH:MM")
    d = date.fromisoformat(m.group(1))
    has_time = m.group(2) is not None
    if has_time and not _TIME_WORDS.search(t):
        raise DeadlineRefused("a time of day was added that the text does not state")
    if _EOD.search(t) and has_time:
        raise DeadlineRefused("end of day is a date")
    for i, w in enumerate(WEEKDAYS):
        if re.search(rf"\b{w}\b", t):
            if d.weekday() != i:
                raise DeadlineRefused(f"text says {w}, value is a {WEEKDAYS[d.weekday()]}")
            if not (sent <= d <= sent + timedelta(days=13)):
                raise DeadlineRefused("weekday deadline more than 13 days out")
    if re.search(r"\btoday\b|\btonight\b", t) and d != sent:
        raise DeadlineRefused("text says today")
    if re.search(r"\btomorrow\b", t) and d != sent + timedelta(days=1):
        raise DeadlineRefused("text says tomorrow")
    for i, mon in enumerate(MONTHS):
        mm = re.search(rf"\b({mon}|{mon[:3]})\.?\s+(\d{{1,2}})", t)
        if mm and (d.month != i + 1 or d.day != int(mm.group(2))):
            raise DeadlineRefused(f"text names {mon} {mm.group(2)}")
    md = re.search(r"\b(\d{1,2})/(\d{1,2})\b", t)
    if md and (d.month != int(md.group(1)) or d.day != int(md.group(2))):
        raise DeadlineRefused("text names a different m/d")
    if d < sent:
        raise DeadlineRefused("deadline before the message was sent")
    return f"{m.group(1)}T{m.group(2)}{off}" if has_time else f"{m.group(1)}{off}"
