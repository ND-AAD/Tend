"""Resolution confidence (SPEC §7.2): agreement across K resolver samples, weighted by structural
support in the ledger graph. Confidence is the normalised entropy of the weighted shares."""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

K = 5
EPSILON = 0.05
H_MAX = 0.35
NEW = "__new__"


@dataclass
class Decision:
    write: bool
    winner: str
    q: dict[str, float]
    entropy: float


def weighted_shares(votes: list[str], support: dict[str, float]) -> dict[str, float]:
    counts = Counter(votes)
    total = sum(counts.values())
    raw = {opt: (n / total) * (EPSILON + support.get(opt, 0.0)) for opt, n in counts.items()}
    z = sum(raw.values())
    return {opt: v / z for opt, v in raw.items()}


def entropy(q: dict[str, float]) -> float:
    n = len(q)
    if n <= 1:
        return 0.0
    return -sum(p * math.log2(p) for p in q.values() if p > 0) / math.log2(n)


def decide(votes: list[str], support: dict[str, float]) -> Decision:
    """The winner is the most-voted option; structural weight breaks ties among those and
    shapes q, but never lets a minority of votes win (four votes for new and one supported vote
    is a new Item, not the one vote)."""
    q = weighted_shares(votes, support)
    counts = Counter(votes)
    top = max(counts.values())
    winner = sorted((k for k in q if counts[k] == top), key=lambda k: (-q[k], k))[0]
    h = entropy(q)
    ok = h <= H_MAX and (winner == NEW or support.get(winner, 0.0) > 0)
    return Decision(ok, winner, q, h)


def neighbours(edges: dict[str, set[str]], start: str, hops: int = 2) -> set[str]:
    seen, frontier = {start}, {start}
    for _ in range(hops):
        frontier = {n for f in frontier for n in edges.get(f, ())} - seen
        seen |= frontier
    return seen - {start}


def support(edges: dict[str, set[str]], candidate: str, anchors: set[str]) -> float:
    """Share of the message's anchors within two hops of the candidate."""
    if not anchors or candidate == NEW:
        return 0.0
    near = neighbours(edges, candidate) | {candidate}
    return len(anchors & near) / len(anchors)
