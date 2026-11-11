"""Instants in Attedra 4.2.1 form: ordering for replay, and construction with an offset."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(Z|[+-]\d{2}:\d{2})$")
_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)(Z|[+-]\d{2}:\d{2})$")


def _tz(off: str) -> timezone:
    if off == "Z":
        return timezone.utc
    sign = 1 if off[0] == "+" else -1
    h, m = int(off[1:3]), int(off[4:6])
    return timezone(sign * timedelta(hours=h, minutes=m))


def parse(instant: str) -> tuple[datetime, datetime]:
    """The interval [start, end) the instant denotes (4.2.1), in UTC."""
    m = _DATE.match(instant)
    if m:
        d = datetime.fromisoformat(m.group(1)).replace(tzinfo=_tz(m.group(2)))
        return d.astimezone(timezone.utc), (d + timedelta(days=1)).astimezone(timezone.utc)
    m = _TIME.match(instant)
    if not m:
        raise ValueError(f"not an instant: {instant!r}")
    body = m.group(1)
    d = datetime.fromisoformat(body).replace(tzinfo=_tz(m.group(2)))
    step = timedelta(minutes=1) if body.count(":") == 1 else timedelta(seconds=1)
    return d.astimezone(timezone.utc), (d + step).astimezone(timezone.utc)


def sort_key(instant: str) -> tuple[datetime, datetime]:
    return parse(instant)


def offset_of(instant: str) -> str:
    m = _DATE.match(instant) or _TIME.match(instant)
    if not m:
        raise ValueError(instant)
    return m.group(2)


def local_date(instant: str) -> date:
    m = _DATE.match(instant) or _TIME.match(instant)
    return date.fromisoformat(m.group(1)[:10])


def from_datetime(dt: datetime) -> str:
    """Second precision, with the datetime's own offset."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime")
    return dt.replace(microsecond=0).isoformat()


def add_hours(instant: str, hours: int) -> str:
    start, _ = parse(instant)
    off = _tz(offset_of(instant))
    return from_datetime((start + timedelta(hours=hours)).astimezone(off))


def after(a: str, b: str) -> bool:
    """a is after b (4.2.5): a begins no earlier than b ends."""
    return parse(a)[0] >= parse(b)[1]
