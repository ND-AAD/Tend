"""Instants and their intervals (spec 4.2.1, 4.2.5).

An instant carries an explicit UTC offset and is kept at the precision written: a date
(``2026-05-14-07:00``), a minute (``2026-05-14T09:45-07:00``) or a second or finer
(``2026-05-14T09:45:00.25-07:00``). It denotes the half-open interval its precision covers,
held here as exact rational seconds since the epoch, in UTC.

Relations between instants are three-valued (4.2.5): a relation function returns True when
the relation holds, False when its opposite holds, and None when neither holds, in which
case the order is unspecified and the caller must report ambiguity (4.5.3). The pairs of
opposites are (before, at or after) and (at or before, after).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction

_OFFSET = r"(Z|[+-]\d{2}:\d{2})"
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})" + _OFFSET + r"$")
_MINUTE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})" + _OFFSET + r"$")
_SECOND_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?" + _OFFSET + r"$")

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Instant:
    """An instant as written, with the interval [start, end) it denotes (4.2.1)."""

    text: str
    start: Fraction
    end: Fraction
    precision: str  # "date" | "minute" | "second"

    def __repr__(self) -> str:
        return f"Instant({self.text})"

    @property
    def key(self) -> tuple:
        """A linear sort key, used only where a total order is needed for presentation or
        for a timeline; rules that need an order use the three-valued relations."""
        return (self.start, self.end, self.text)


def _offset(text: str) -> timezone | None:
    if text == "Z":
        return timezone.utc
    sign = 1 if text[0] == "+" else -1
    hh, mm = int(text[1:3]), int(text[4:6])
    if hh > 23 or mm > 59:
        return None
    return timezone(sign * timedelta(hours=hh, minutes=mm))


def _seconds(dt: datetime) -> Fraction:
    delta = dt - _EPOCH
    return Fraction(delta.days * 86400 + delta.seconds) + Fraction(delta.microseconds, 1_000_000)


def parse_instant(text) -> Instant | None:
    """Parse an instant in one of the three forms of 4.2.1; None when malformed."""
    if not isinstance(text, str):
        return None
    return _parse_instant(text)


@lru_cache(maxsize=1 << 16)
def _parse_instant(text: str) -> Instant | None:
    """The parse of one text. An Instant is immutable, so equal texts share one (a read
    parses the same few contexts' times many times)."""
    try:
        m = _SECOND_RE.match(text)
        if m:
            y, mo, d, h, mi, s, frac, off = m.groups()
            tz = _offset(off)
            if tz is None or int(s) > 59:
                return None
            dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), tzinfo=tz)
            start = _seconds(dt)
            if frac:
                digits = frac[1:]
                start += Fraction(int(digits), 10 ** len(digits))
                width = Fraction(1, 10 ** len(digits))
            else:
                width = Fraction(1)
            return Instant(text, start, start + width, "second")
        m = _MINUTE_RE.match(text)
        if m:
            y, mo, d, h, mi, off = m.groups()
            tz = _offset(off)
            if tz is None:
                return None
            start = _seconds(datetime(int(y), int(mo), int(d), int(h), int(mi), tzinfo=tz))
            return Instant(text, start, start + 60, "minute")
        m = _DATE_RE.match(text)
        if m:
            y, mo, d, off = m.groups()
            tz = _offset(off)
            if tz is None:
                return None
            date(int(y), int(mo), int(d))
            start = _seconds(datetime(int(y), int(mo), int(d), tzinfo=tz))
            return Instant(text, start, start + 86400, "date")
    except ValueError:
        return None
    return None


def is_instant(text) -> bool:
    return parse_instant(text) is not None


def now_instant() -> Instant:
    """The evaluation instant for a ``"now"`` cutoff (4.6.1), to the second, in UTC."""
    text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    return parse_instant(text)


def to_datetime(i: Instant) -> datetime:
    """The start of the instant's interval as an aware datetime (bookkeeping only)."""
    whole = int(i.start)
    return _EPOCH + timedelta(seconds=whole, microseconds=int((i.start - whole) * 1_000_000))


# ---------------------------------------------------------------------------------------
# Relations (4.2.5)


def before(a: Instant, b: Instant) -> bool | None:
    """A is before B when A's interval ends before B's begins. Opposite: A at or after B."""
    if a.end <= b.start:
        return True
    if a.start >= b.start:
        return False
    return None


def at_or_after(a: Instant, b: Instant) -> bool | None:
    r = before(a, b)
    return None if r is None else not r


def at_or_before(a: Instant, b: Instant) -> bool | None:
    """A is at or before B when A's interval ends no later than B's ends. Opposite: A after B."""
    if a.end <= b.end:
        return True
    if a.start >= b.end:
        return False
    return None


def after(a: Instant, b: Instant) -> bool | None:
    """A is after B when A's interval begins after B's ends. Opposite: A at or before B."""
    r = at_or_before(a, b)
    return None if r is None else not r


def equal(a: Instant, b: Instant) -> bool:
    """Equal instants denote the same interval (4.5.1)."""
    return a.start == b.start and a.end == b.end


def contains(outer: Instant, inner: Instant) -> bool:
    """True when ``outer``'s interval contains ``inner``'s (used for consistent publication
    instants, 4.4.1)."""
    return outer.start <= inner.start and inner.end <= outer.end


def hull(insts: list[Instant]) -> Instant:
    """The smallest interval covering several instants whose order is not settled (competing
    publication instants, 4.4.1). A relation of 4.2.5 holds for the hull exactly when it
    holds for every one of the instants, and is unspecified otherwise. Its text names the
    earliest-starting and latest-ending instants."""
    first = min(insts, key=lambda i: (i.start, i.end))
    last = max(insts, key=lambda i: (i.end, i.start))
    return Instant(f"{first.text}/{last.text}", first.start, last.end, "competing")


def ordered(a: Instant, b: Instant) -> bool:
    """Two instants are ordered when one is before the other, or they are equal (4.2.5)."""
    return equal(a, b) or before(a, b) is True or before(b, a) is True


def later_of(a: Instant, b: Instant) -> Instant | None:
    """The later of two instants, defined only when they are ordered or equal (4.2.5)."""
    if equal(a, b) or before(b, a) is True:
        return a
    if before(a, b) is True:
        return b
    return None


def earlier_of(a: Instant, b: Instant) -> Instant | None:
    if equal(a, b) or before(a, b) is True:
        return a
    if before(b, a) is True:
        return b
    return None


def duration(seconds: Fraction) -> str:
    """An ISO 8601 duration: ``P<n>D`` for whole days, otherwise ``PT<n>S`` (README §5)."""
    if seconds % 86400 == 0:
        return f"P{int(seconds // 86400)}D"
    if seconds.denominator == 1:
        return f"PT{int(seconds)}S"
    # exact decimal seconds where finite, otherwise a rounded rational
    num, den = seconds.numerator, seconds.denominator
    for k in range(1, 20):
        if (num * 10 ** k) % den == 0:
            whole = num * 10 ** k // den
            s = str(whole).rjust(k + 1, "0")
            return f"PT{s[:-k]}.{s[-k:]}S"
    return f"PT{float(seconds)}S"


def late_by(evidence: Instant, deadline: Instant) -> str:
    """Lateness of evidence against a deadline, between the ends of their intervals (6.5.4)."""
    return duration(evidence.end - deadline.end)
