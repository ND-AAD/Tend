"""Named application interpretations (spec 5.5.3-5.5.4).

The model compares literally (5.5.1). An interpretation declares domain equivalence; it can
make two values equal or unequal, and nothing else. The reference provides only the
fixture interpretations of conformance README §5, each at version ``"1"``:

* ``fixture-fire-rating``: ``"90 min"``, ``"1.5 h"`` and ``90`` are equal.
* ``fixture-set:<property>``: that property's list values are sets, in which order and
  duplicates are ignored.
* ``fixture-accept-empty:<property>``: an explicit empty value (``null``) is an acceptable
  answer to an information request on that property (6.4.4). It changes no equality.

Each covers every value: outside the equivalences it declares, it compares literally (5.5.4).

The name ``literal`` is reserved: a frame that names it requests literal comparison (4.6.1), and
no interpretation has that name.

``retired`` holds, for the operation in progress, the fixture interpretations the reference no
longer has (conformance README §2, ``retire_interpretation``): records written while the
reference had one stay as written, and are read as recorded from then on (7.3.8, 7.6.14). It is
set by ``api.Session`` around each operation, so it never outlives a session.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from .values import canonical, literal_equal

FIRE_RATING_90 = {canonical("90 min"), canonical("1.5 h"), canonical(90)}


@dataclass(frozen=True)
class Interpretation:
    name: str | None
    version: str | None

    def equal(self, a: Any, b: Any, prop: str | None = None) -> bool:
        """Equality of two property values under this interpretation."""
        if self.name is None:
            return literal_equal(a, b)
        if self.name == "fixture-fire-rating":
            ca, cb = canonical(a), canonical(b)
            if ca in FIRE_RATING_90 and cb in FIRE_RATING_90:
                return True
            return ca == cb
        if self.name.startswith("fixture-set:"):
            target = self.name.split(":", 1)[1]
            if prop == target and isinstance(a, list) and isinstance(b, list):
                return {canonical(x) for x in a} == {canonical(x) for x in b}
            return literal_equal(a, b)
        return literal_equal(a, b)

    def accepts_empty_answer(self, prop: str | None = None) -> bool:
        """6.4.4: whether an explicit ``null`` answers an information request on ``prop``."""
        if self.name is not None and self.name.startswith("fixture-accept-empty:"):
            return prop is not None and prop == self.name.split(":", 1)[1]
        return False

    def describe(self) -> dict:
        return {"interpretation": self.name, "interpretation_version": self.version}


LITERAL = Interpretation(None, None)

# 4.6.1: the frame value that requests literal comparison; no interpretation is named so
LITERAL_REQUEST = "literal"

retired: ContextVar[frozenset] = ContextVar("attedra_retired_interpretations", default=frozenset())


def get_interpretation(name: str | None) -> Interpretation | None:
    """The named interpretation, LITERAL for none, or None when it is unavailable (5.5.4):
    one the reference never had, or a fixture interpretation retired in this session."""
    if name is None:
        return LITERAL
    if not isinstance(name, str) or name == LITERAL_REQUEST or name in retired.get():
        return None
    if name == "fixture-fire-rating":
        return Interpretation(name, "1")
    for prefix in ("fixture-set:", "fixture-accept-empty:"):
        if isinstance(name, str) and name.startswith(prefix) and len(name) > len(prefix):
            return Interpretation(name, "1")
    return None
