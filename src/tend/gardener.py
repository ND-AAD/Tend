"""The identity gardener (SPEC §9): finds Items that may be one thing recorded twice, asks a judge,
and merges through the identity map (deviation D2). Within equal scores, pairs holding more best
readings are judged first."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from . import confidence
from .config import Config
from .ledger import Ledger, normalise
from .llm import Judge
from .schema import RESOLVABLE_KINDS

JACCARD_MIN = 0.6


@dataclass
class Pair:
    a: str
    b: str
    score: float
    rule: str
    mass: int = 0


def doubt(ledger: Ledger) -> dict[str, int]:
    """Number of best readings (`low_confidence` claims) on each Item."""
    d: dict[str, int] = {}
    for c in ledger.active_claims():
        if "low_confidence" in c.flags:
            u = ledger.root(c.subject_id)
            d[u] = d.get(u, 0) + 1
    return d


def detect(ledger: Ledger, cfg: Config) -> list[Pair]:
    pairs: dict[tuple[str, str], Pair] = {}

    def offer(a: str, b: str, score: float, rule: str) -> None:
        a, b = sorted((ledger.root(a), ledger.root(b)))
        if a == b:
            return
        ia, ib = ledger.item(a), ledger.item(b)
        if not ia or not ib or ia["kind"] != ib["kind"]:
            return
        cur = pairs.get((a, b))
        if cur is None or score > cur.score:
            pairs[(a, b)] = Pair(a, b, score, rule)

    by_name: dict[str, set[str]] = {}
    for item_id, n in ledger.all_names():
        by_name.setdefault(n, set()).add(ledger.root(item_id))
    for ids_ in by_name.values():
        for a, b in combinations(sorted(ids_), 2):
            offer(a, b, 1.0, "shared_name")

    edges = ledger.graph(exclude={cfg.owner_id})
    items = [i["id"] for i in ledger.active_items() if i["kind"] in RESOLVABLE_KINDS]
    hood = {i: confidence.neighbours(edges, i) for i in items}
    words = {i: _words(ledger, i) for i in items}
    for a, b in combinations(items, 2):
        if not words[a] & words[b]:
            continue     # sharing a correspondent is not evidence of identity without a shared word
        na, nb = hood[a] - {b}, hood[b] - {a}
        if na and nb:
            j = len(na & nb) / len(na | nb)
            if j >= JACCARD_MIN:
                offer(a, b, j, "neighbourhood")

    for r in ledger.revisions("uncertain_write") + ledger.revisions("hold_released"):
        q = r["detail"].get("q", {})
        ranked = sorted(q, key=lambda k: (-q[k], k))
        winner = r["detail"].get("winner")
        others = [k for k in ranked if k != winner]
        if winner and others and ledger.item(others[0]):
            offer(winner, others[0], 0.5, "low_confidence")

    mass = doubt(ledger)
    out = list(pairs.values())
    for p in out:
        p.mass = mass.get(p.a, 0.0) + mass.get(p.b, 0.0)
    out.sort(key=lambda p: (-p.score, -p.mass, p.a, p.b))
    return out


_STOP = {"the", "a", "an", "of", "for", "and", "to", "my", "our", "this", "that", "new", "revised", "final", "draft"}


def _words(ledger: Ledger, item_id: str) -> set[str]:
    it = ledger.item(item_id) or {}
    names = ledger.names_of(item_id) + [normalise(it.get("label") or "")]
    return {w for n in names for w in n.split()} - _STOP


def _judged(ledger: Ledger) -> dict[tuple[str, str], int]:
    """Pairs already judged different, with the evidence count they were judged on."""
    out: dict[tuple[str, str], int] = {}
    for r in ledger.revisions("judged"):
        d = r["detail"]
        if not d.get("same"):
            out[tuple(sorted((d["a"], d["b"])))] = d.get("claims", 0)
    return out


def _claim_count(ledger: Ledger, a: str, b: str) -> int:
    return sum(1 for c in ledger.active_claims() if ledger.root(c.subject_id) in (a, b))


def _evidence(ledger: Ledger, item_id: str) -> dict:
    it = ledger.item(item_id)
    claims = [{"property": c.property, "value": c.value, "kind": c.kind, "quote": c.quote, "thread": m["thread_id"]}
              for c, m in ledger.message_claims() if ledger.root(c.subject_id) == item_id]
    return {"id": item_id, "kind": it["kind"], "label": it["label"], "names": ledger.names_of(item_id),
            "claims": claims[-10:]}


def run(ledger: Ledger, cfg: Config, projector, judge: Judge, limit: int = 10) -> list[tuple[str, str, str]]:
    """Judge the top pairs; merge each `same` pair into the older Item; rebuild once."""
    merged = []
    judged = _judged(ledger)
    asked = 0
    for p in detect(ledger, cfg):
        if asked >= limit:
            break
        a, b = ledger.root(p.a), ledger.root(p.b)
        if a == b:
            continue
        n = _claim_count(ledger, a, b)
        if judged.get(tuple(sorted((a, b)))) == n:
            continue     # judged different on this same evidence: ask again only when it grows
        asked += 1
        same, reason = judge.same(_evidence(ledger, a), _evidence(ledger, b), {"rule": p.rule, "score": p.score})
        ledger.log("gardener", "judged", reason, a=a, b=b, same=same, rule=p.rule, score=p.score, mass=p.mass,
                   claims=n)
        if not same:
            continue
        ages = {r[0]: r[1] for r in ledger._q("SELECT id, created_at FROM ledger.items WHERE id = ANY(%s)", ([a, b],))}
        survivor, absorbed = sorted((a, b), key=lambda i: (ages[i], i))
        with ledger.conn.transaction():
            ledger.merge_items(survivor, absorbed, "gardener", reason)
        merged.append((survivor, absorbed, reason))
    return merged     # merges mark the store stale; the batch rebuild applies them
