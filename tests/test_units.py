"""SPEC §12 case 4 (deadlines) and the confidence arithmetic of §7.2."""
from __future__ import annotations

import pytest

from assistant import confidence, deadlines
from assistant.deadlines import DeadlineRefused

SENT = "2026-11-10T09:00:00-08:00"   # a Tuesday


@pytest.mark.parametrize("text,value,want", [
    ("by Friday", "2026-11-13", "2026-11-13-08:00"),
    ("tomorrow at 3pm", "2026-11-11T15:00", "2026-11-11T15:00-08:00"),
    ("today", "2026-11-10", "2026-11-10-08:00"),
    ("by Nov 20", "2026-11-20", "2026-11-20-08:00"),
    ("by 11/20", "2026-11-20", "2026-11-20-08:00"),
    ("EOD Thursday", "2026-11-12", "2026-11-12-08:00"),
])
def test_deadline_accepts(text, value, want):
    assert deadlines.resolve(text, value, SENT) == want


@pytest.mark.parametrize("text,value", [
    ("by Friday", "2026-11-14"),            # a Saturday
    ("by Friday", "2026-11-13T17:00"),      # time added
    ("tomorrow", "2026-11-12"),
    ("by Nov 20", "2026-11-21"),
    ("by 11/20", "2026-12-20"),
    ("EOD", "2026-11-10T17:00"),
    ("next Friday", "2026-11-27"),          # more than 13 days out
    ("by the 1st", "2026-11-01"),           # before the message
    ("Friday", "Friday"),
])
def test_deadline_refuses(text, value):
    with pytest.raises(DeadlineRefused):
        deadlines.resolve(text, value, SENT)


def test_confidence_rule():
    assert confidence.decide(["a"] * 5, {"a": 0.5}).write
    assert not confidence.decide(["a"] * 5, {"a": 0.0}).write          # no structural support
    assert confidence.decide([confidence.NEW] * 5, {}).write
    split = confidence.decide(["a", "a", "a", "b", "b"], {"a": 0.0, "b": 0.0})
    assert not split.write and split.winner == "a" and split.entropy > 0.9
    # support breaks a split: a is near the anchors, b is not
    lifted = confidence.decide(["a", "a", "a", "b", "b"], {"a": 1.0, "b": 0.0})
    assert lifted.write and lifted.q["a"] > 0.95


def test_support_and_entropy():
    edges = {"x": {"t"}, "t": {"x", "p"}, "p": {"t"}}
    assert confidence.support(edges, "x", {"t", "p"}) == 1.0
    assert confidence.support(edges, "y", {"t"}) == 0.0
    assert confidence.structural_entropy({"a": 1, "b": 1}) == 1.0


def test_minority_never_wins():
    """Review defect 7: four votes for new and one supported vote is new, and not confident."""
    d = confidence.decide([confidence.NEW] * 4 + ["a"], {"a": 1.0})
    assert d.winner == confidence.NEW and not d.write
    assert confidence.decide(["a"] * 4 + ["b"], {"a": 0.34, "b": 1.0}).winner == "a"
