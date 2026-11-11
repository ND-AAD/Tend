"""Normalizations and the interpretation in force (spec 7.3.8, 5.5.3-5.5.4, 4.6.1).

A normalization is an act ``@action: "reinterpret"`` with exactly one target, an Item
reference naming a scope Item (2.1.5), and ``@interpretation``: ``{"name", "version"}`` or
``null`` for literal comparison. It takes effect at its effective time (8.4.1) and applies to
an Item while the Item is a member of its scope, with membership taken at each instant from
the Connections active then.

The interpretation in force for an Item over event time is held as a ``Schedule``: a list of
segments, each starting at an instant and carrying an ``InForce`` state, the first starting
before every instant. A state is definite (an interpretation and the normalizations that put
it in force, none for literal comparison when no normalization applies) or ambiguous (several
candidate interpretations, 4.5.3): normalizations of one scope Item tied or unordered at an
instant that name different interpretations, or normalized scopes of the Item whose
interpretations in force differ. A fixed interpretation (one a frame or an expectation context
names) is a schedule of one segment with no normalization, so that only a normalization is
ever cited as the reason two values match (5.5.4).

Timelines (stories, expectations) read a schedule in the linear order of instants the rest of
the derivation uses (start, then end of the interval); a read at a cutoff reads it with the
three-valued relations of 4.2.5 (``Schedule.at_cutoff``).

Locality (9.10.1): membership is decided from the Connections into the subject and its
ancestors (those a read already holds, and those entering them from elsewhere,
``Store.load_normalizations``), and the normalizations read are those whose scope Item is the
subject or one of those ancestors (``Store.normalization_rows_for_scopes``), never from a
traversal of the store or the normalizations of unrelated scopes.

Two expectations are compared each under its own interpretation (7.2.4): ``pair_schedule``
gives that comparison over event time, the interpretation where the two are the same, and
otherwise the pair, an ambiguous state whose resolutions (``PairInterp``) take each side's
verdict where the two disagree, so that the derivation runs under each and an ambiguous content
lists the two expectations (7.6.6).
"""
from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from . import instants as T
from .instants import Instant
from .interpretations import LITERAL, Interpretation, get_interpretation
from .model import Rec, act_targets
from .values import assertion_ref, compact, is_item_ref


def _k(i: Instant | None) -> tuple:
    return (float("-inf"), float("-inf")) if i is None else (i.start, i.end)


def ikey(i: Interpretation | None) -> tuple | None:
    """Two interpretations are the same when they have the same name and version (7.3.8)."""
    return None if i is None else (i.name, i.version)


def available(i: Interpretation | None) -> bool:
    """Whether the reference has the interpretation (5.5.4): literal comparison, or a fixture
    interpretation at the version it provides (README §5, *Interpretations*). A pair of two
    expectations' interpretations (``PairInterp``) is available when both are."""
    if i is None:
        return False
    if isinstance(i, PairInterp):
        return available(i.a.interp) and available(i.b.interp)
    if i.name is None:
        return True
    got = get_interpretation(i.name)
    return got is not None and (i.version is None or i.version == got.version)


@dataclass(frozen=True)
class InForce:
    """The interpretation in force at an instant (7.3.8). ``norms`` are the normalizations that
    put it in force, sorted by identifier (7.6.6); none for literal comparison when no
    normalization applies, and none for a fixed interpretation. ``interp`` is None when the
    state is ambiguous: ``candidates`` then pairs each candidate interpretation with the
    normalizations naming it, and ``records`` lists every normalization concerned."""

    interp: Interpretation | None
    norms: tuple = ()
    candidates: tuple = ()
    records: tuple = ()

    @property
    def ambiguous(self) -> bool:
        return self.interp is None

    @property
    def key(self) -> tuple:
        if self.interp is None:
            return ("ambiguous", tuple((ikey(i), tuple(n.triple for n in ns)) for i, ns in self.candidates))
        return (ikey(self.interp), tuple(n.triple for n in self.norms))

    @property
    def interp_key(self) -> tuple:
        if self.interp is None:
            return ("ambiguous", tuple(sorted({ikey(i) for i, _ns in self.candidates}, key=repr)))
        return ikey(self.interp)

    def matched_by(self, a, b, prop: str | None, literal_equal) -> tuple:
        """5.5.4: the normalizations that are the reason two values match: those that put the
        interpretation in force when the values are equal under it and unequal literally."""
        if isinstance(self.interp, PairInterp):
            return self.interp.matched_by(a, b, prop, literal_equal)
        if self.interp is None or not self.norms or self.interp.name is None:
            return ()
        if literal_equal(a, b):
            return ()
        return self.norms if self.interp.equal(a, b, prop) else ()


LITERAL_STATE = InForce(LITERAL)


@dataclass(frozen=True)
class PairInterp:
    """One resolution of the comparison of two expectations whose own interpretations differ
    at an instant (7.2.4): equal when equal under both sides' interpretations, unequal when
    unequal under both, and otherwise, where the two disagree, as side ``prefer`` (0 or 1) says.
    The derivation runs under each ``prefer`` and an ambiguous content stands for the
    differences, listing the two expectations (7.6.6). ``a`` and ``b`` are the sides' definite
    states."""

    a: InForce
    b: InForce
    prefer: int

    @property
    def name(self) -> str:
        return f"pair:{self.a.interp.name}|{self.b.interp.name}#{self.prefer}"

    @property
    def version(self) -> str:
        return f"{self.a.interp.version}|{self.b.interp.version}"

    def equal(self, x, y, prop: str | None = None) -> bool:
        ea, eb = self.a.interp.equal(x, y, prop), self.b.interp.equal(x, y, prop)
        if ea == eb:
            return ea
        return ea if self.prefer == 0 else eb

    def accepts_empty_answer(self, prop: str | None = None) -> bool:
        return False

    def matched_by(self, x, y, prop: str | None, literal_equal) -> tuple:
        """5.5.4: the normalizations that put a side's interpretation in force under which the
        values are equal while they are unequal literally: of both sides where both say equal,
        of the preferred side where only it does."""
        if literal_equal(x, y) or not self.equal(x, y, prop):
            return ()
        sides = [self.a, self.b]
        ea, eb = self.a.interp.equal(x, y, prop), self.b.interp.equal(x, y, prop)
        if ea != eb:
            sides = [sides[self.prefer]]
        out: dict = {}
        for st in sides:
            for r in st.matched_by(x, y, prop, literal_equal):
                out[r.triple] = r
        return tuple(out[t] for t in sorted(out))


def _definite(st: InForce) -> list[InForce]:
    if st.interp is not None:
        return [st]
    return [InForce(i, tuple(ns)) for i, ns in st.candidates]


def pair_state(sa: InForce, sb: InForce, sides: tuple) -> InForce:
    """7.2.4: the state under which two expectations, whose own interpretations at an instant
    are ``sa`` and ``sb``, are compared. When the two are the same interpretation, that one,
    with the normalizations of either that put it in force; otherwise the pair, as an ambiguous
    state whose resolutions are ``PairInterp`` (one for each side's verdict where they disagree),
    whose records are the two expectations (``sides``) and any normalizations concerned."""
    if sa.interp is not None and sb.interp is not None and ikey(sa.interp) == ikey(sb.interp):
        norms = {r.triple: r for r in sa.norms + sb.norms}
        return InForce(sa.interp, tuple(norms[t] for t in sorted(norms)))
    cands: dict = {}
    records: dict = {r.triple: r for r in sides if r is not None}
    for st in (sa, sb):
        for r in st.records:
            records[r.triple] = r
    for a in _definite(sa):
        for b in _definite(sb):
            if ikey(a.interp) == ikey(b.interp):
                norms = {r.triple: r for r in a.norms + b.norms}
                cands.setdefault(ikey(a.interp), (a.interp, tuple(norms[t] for t in sorted(norms))))
                continue
            for prefer in (0, 1):
                pi = PairInterp(a, b, prefer)
                norms = {r.triple: r for r in a.norms + b.norms}
                cands.setdefault(ikey(pi), (pi, tuple(norms[t] for t in sorted(norms))))
    candidates = tuple(cands[k] for k in sorted(cands, key=repr))
    return InForce(None, (), candidates, tuple(records[t] for t in sorted(records)))


def pair_schedule(sa: Schedule, sb: Schedule, sides: tuple) -> Schedule:
    """7.2.4: the comparison of two expectations over event time, each under its own
    interpretation (``pair_state`` at each instant)."""
    points: dict = {}
    for sch in (sa, sb):
        for t, _st in sch.changes():
            points[t.text] = t
    segs = [(None, pair_state(sa.initial, sb.initial, sides))]
    for t in sorted(points.values(), key=_k):
        st = pair_state(sa.at(t), sb.at(t), sides)
        if st.key != segs[-1][1].key:
            segs.append((t, st))
    return Schedule(segs)


@dataclass
class Schedule:
    """The interpretation in force for one Item over event time."""

    segments: list = field(default_factory=lambda: [(None, LITERAL_STATE)])

    @staticmethod
    def fixed(interp: Interpretation) -> "Schedule":
        return Schedule([(None, InForce(interp))])

    @property
    def constant(self) -> bool:
        return len(self.segments) == 1

    @property
    def initial(self) -> InForce:
        return self.segments[0][1]

    def changes(self) -> list[tuple[Instant, InForce]]:
        return [(s, st) for s, st in self.segments[1:]]

    def at(self, t: Instant | None) -> InForce:
        """The state at an instant, in the linear order of instants; ``None`` is the end of
        the history (the latest state)."""
        if t is None:
            return self.segments[-1][1]
        found = self.segments[0][1]
        kt = _k(t)
        for s, st in self.segments[1:]:
            if _k(s) <= kt:
                found = st
            else:
                break
        return found

    def at_cutoff(self, c: Instant | None) -> InForce:
        """The state at a cutoff (4.6.1), with the relations of 4.2.5: a segment whose start
        is unordered with the cutoff makes the state ambiguous where it changes it (4.5.3)."""
        if c is None:
            return self.segments[-1][1]
        settled = self.segments[0][1]
        maybe: list[InForce] = []
        for s, st in self.segments[1:]:
            r = T.at_or_before(s, c)
            if r is True:
                settled = st
                maybe = []
            elif r is None:
                maybe.append(st)
        states = [settled] + maybe
        if all(x.key == settled.key for x in states):
            return settled
        return merge_states(states)

    @property
    def ambiguous(self) -> bool:
        return any(st.ambiguous for _s, st in self.segments)

    def resolutions(self, cap: int = 8) -> list["Schedule"]:
        """The definite schedules this one stands for: each ambiguous segment resolved to one
        of its candidates (7.6.6: a read evaluates the unit under each combination of
        candidates). At most ``cap`` combinations are formed."""
        if not self.ambiguous:
            return [self]
        options = []
        for s, st in self.segments:
            if st.ambiguous:
                options.append([(s, InForce(i, tuple(ns))) for i, ns in st.candidates])
            else:
                options.append([(s, st)])
        out = []
        for combo in itertools.product(*options):
            out.append(Schedule(_compress(list(combo))))
            if len(out) >= cap:
                break
        return out

    def unavailable(self) -> str | None:
        """The name of an interpretation in the schedule that the reference does not have
        (5.5.4, 7.6.14), if any."""
        for _s, st in self.segments:
            for i in ([st.interp] if st.interp is not None else [c[0] for c in st.candidates]):
                if not available(i):
                    return i.name
        return None

    def unavailable_at(self, c: Instant | None) -> str | None:
        st = self.at_cutoff(c)
        for i in ([st.interp] if st.interp is not None else [x[0] for x in st.candidates]):
            if not available(i):
                return i.name
        return None

    def ambiguous_records(self) -> list[Rec]:
        out: dict = {}
        for _s, st in self.segments:
            for r in st.records:
                out[r.triple] = r
        return [out[t] for t in sorted(out)]


def merge_states(states: list[InForce]) -> InForce:
    """One ambiguous state standing for several (4.5.3), or the common one."""
    cands: dict = {}
    records: dict = {}
    for st in states:
        if st.interp is None:
            for i, ns in st.candidates:
                cands.setdefault(ikey(i), (i, {}))[1].update({r.triple: r for r in ns})
            for r in st.records:
                records[r.triple] = r
        else:
            cands.setdefault(ikey(st.interp), (st.interp, {}))[1].update({r.triple: r for r in st.norms})
            for r in st.norms:
                records[r.triple] = r
    if len(cands) == 1:
        (i, ns), = cands.values()
        return InForce(i, tuple(ns[t] for t in sorted(ns)))
    candidates = tuple((i, tuple(ns[t] for t in sorted(ns)))
                       for i, ns in sorted(cands.values(), key=lambda x: repr(ikey(x[0]))))
    return InForce(None, (), candidates, tuple(records[t] for t in sorted(records)))


def _compress(segments: list) -> list:
    out = [segments[0]]
    for s, st in segments[1:]:
        if st.key == out[-1][1].key:
            continue
        out.append((s, st))
    return out


# ---------------------------------------------------------------------------------------
# the normalizations of an account


def scope_of(r: Rec) -> str | None:
    ts = act_targets(r.values)
    if len(ts) == 1 and is_item_ref(ts[0]):
        return ts[0]["id"]
    return None


def interp_of(r: Rec) -> Interpretation:
    """The interpretation a normalization names (7.3.8): literal comparison for ``null``."""
    v = r.values.get("@interpretation")
    if isinstance(v, dict) and isinstance(v.get("name"), str):
        return Interpretation(v["name"], v.get("version"))
    return LITERAL


class NormIndex:
    """The normalizations of one account and the interpretation in force for its Items."""

    def __init__(self, acc) -> None:
        from .view import connection_state  # noqa: PLC0415  (view imports this module's users)
        self._connection_state = connection_state
        self.acc = acc
        self.norms = sorted((r for r in acc.records.values() if r.action == "reinterpret" and scope_of(r)),
                            key=lambda r: r.triple)
        self.by_scope: dict[str, list[Rec]] = defaultdict(list)
        for r in self.norms:
            self.by_scope[scope_of(r)].append(r)
        self._into: dict[str, list[str]] | None = None
        self._cs: dict = {}
        self._members: dict = {}
        self._sched: dict = {}
        self._up: dict = {}

    @property
    def empty(self) -> bool:
        return not self.norms

    def _graph(self) -> dict[str, list[str]]:
        if self._into is None:
            into: dict[str, list[str]] = defaultdict(list)
            for a, b in self.acc.rs.connections:
                into[b].append(a)
            self._into = into
        return self._into

    def ancestors(self, x: str) -> set[str]:
        """The Items from which ``x`` is reached forward over Connections in any state."""
        if x in self._up:
            return self._up[x]
        into = self._graph()
        seen: set[str] = set()
        stack = [x]
        while stack:
            n = stack.pop()
            for m in into.get(n, ()):
                if m not in seen:
                    seen.add(m)
                    stack.append(m)
        self._up[x] = seen
        return seen

    def _state(self, pair):
        cs = self._cs.get(pair)
        if cs is None:
            cs = self._cs[pair] = self._connection_state(self.acc, pair)
        return cs

    def membership(self, scope: str, x: str) -> list[tuple[Instant | None, bool]]:
        """Whether ``x`` is a member of the scope Item over event time (2.1.5), as segments
        (start, member); the first starts before every instant."""
        key = (scope, x)
        if key in self._members:
            return self._members[key]
        if scope == x:
            out = [(None, True)]
        elif scope not in self.ancestors(x):
            out = [(None, False)]
        else:
            from .view import connection_active_at  # noqa: PLC0415
            up = self.ancestors(x) | {x}
            into = self._graph()
            # the Connections on paths from the scope Item to x: within x's ancestors, the
            # edges whose source is reached from the scope Item
            out_of: dict[str, list[str]] = defaultdict(list)
            for b in up:
                for a in into.get(b, ()):
                    if a in up:
                        out_of[a].append(b)
            reach = {scope}
            stack = [scope]
            while stack:
                n = stack.pop()
                for m in out_of.get(n, ()):
                    if m not in reach:
                        reach.add(m)
                        stack.append(m)
            edges = [(a, b) for a in reach for b in out_of.get(a, ()) if b in reach]
            points: dict = {}
            for pair in edges:
                cs = self._state(pair)
                if cs.connected_at is not None:
                    points[cs.connected_at.text] = cs.connected_at
                for t, _kind, _r, eff in cs.events:
                    if eff:
                        points[t.text] = t
            out = [(None, False)]
            for t in sorted(points.values(), key=_k):
                active: dict[str, list[str]] = defaultdict(list)
                for a, b in edges:
                    if connection_active_at(self._state((a, b)), t) is True:
                        active[a].append(b)
                seen = {scope}
                stack = [scope]
                while stack:
                    n = stack.pop()
                    for m in active.get(n, ()):
                        if m not in seen:
                            seen.add(m)
                            stack.append(m)
                member = x in seen
                if member != out[-1][1]:
                    out.append((t, member))
        self._members[key] = out
        return out

    @staticmethod
    def _member_at(segs: list, t: Instant) -> bool:
        found = segs[0][1]
        for s, m in segs[1:]:
            if _k(s) <= _k(t):
                found = m
        return found

    def scopes_of(self, x: str) -> list[str]:
        """The normalized scope Items that ``x`` belongs to at some instant (in any state)."""
        if self.empty:
            return []
        up = self.ancestors(x)
        return sorted(s for s in self.by_scope if s == x or s in up)

    def schedule(self, x: str, visible: Callable[[Rec], bool] | None = None, vkey=None) -> Schedule:
        """The interpretation in force for ``x`` over event time (7.3.8). ``visible`` keeps
        only the normalizations that count in a participant perspective (4.6.1); ``vkey``
        identifies that filter for caching."""
        key = (x, vkey)
        if key in self._sched:
            return self._sched[key]
        scopes = self.scopes_of(x)
        if not scopes:
            out = Schedule()
            self._sched[key] = out
            return out
        acc = self.acc
        norms = {s: [n for n in self.by_scope[s] if (visible is None or visible(n)) and acc.effective(n) is not None]
                 for s in scopes}
        memb = {s: self.membership(s, x) for s in scopes}
        points: dict = {}
        for s in scopes:
            if not norms[s]:
                continue
            for t, _m in memb[s][1:]:
                points[t.text] = t
            for n in norms[s]:
                e = acc.effective(n)
                points[e.text] = e
        segs = [(None, LITERAL_STATE)]
        for t in sorted(points.values(), key=_k):
            st = self._evaluate(t, scopes, norms, memb)
            if st.key != segs[-1][1].key:
                segs.append((t, st))
        out = Schedule(segs)
        self._sched[key] = out
        return out

    def _evaluate(self, t: Instant, scopes, norms, memb) -> InForce:
        acc = self.acc
        states = []
        for s in scopes:
            if not norms[s] or not self._member_at(memb[s], t):
                continue
            eff = [n for n in norms[s] if _k(acc.effective(n)) <= _k(t)]
            if not eff:
                continue
            latest = acc.latest_of(eff)
            kinds = {ikey(interp_of(n)) for n in latest}
            if len(kinds) == 1:
                states.append(InForce(interp_of(latest[0]), tuple(latest)))
            else:
                by: dict = {}
                for n in latest:
                    by.setdefault(ikey(interp_of(n)), (interp_of(n), []))[1].append(n)
                states.append(InForce(None, (), tuple((i, tuple(ns)) for i, ns in by.values()), tuple(latest)))
        if not states:
            return LITERAL_STATE
        return merge_states(states)


def norm_index(acc) -> NormIndex:
    idx = acc.__dict__.get("_norm_index")
    if idx is None:
        idx = acc.__dict__["_norm_index"] = NormIndex(acc)
    return idx


def subject_schedule(acc, x: str | None, view=None) -> Schedule:
    """The interpretation in force for an Item (7.3.8), in the record perspective or, with a
    participant ``view``, from the normalizations that count in it: one recorded from a
    communication counts once that communication's issuance has been distributed to the
    participant by the cutoff, and then applies from its effective time (4.6.1)."""
    if x is None:
        return Schedule()
    idx = norm_index(acc)
    if idx.empty:
        return Schedule()
    if view is None or view.frame.perspective is None:
        return idx.schedule(x)
    vk = (view.frame.perspective, view.cutoff.text if view.cutoff else None)
    return idx.schedule(x, lambda n: view.visible(n, view.cutoff) is True, vk)


def read_schedule(view, x: str | None) -> Schedule:
    """How a read compares values about ``x``: under the interpretation its frame names, at
    every instant, or else under the interpretation in force at each instant (4.6.1)."""
    if view.frame.named:
        return Schedule.fixed(view.interp)
    return subject_schedule(view.acc, x, view)


# ---------------------------------------------------------------------------------------
# citing records (7.6.6)


def sorted_recs(recs) -> list[Rec]:
    seen: dict = {}
    for r in recs:
        if r is not None:
            seen[r.triple] = r
    return [seen[t] for t in sorted(seen)]


def ref_or_list(recs) -> dict | list | None:
    """7.6.6: one record's exact reference, or, where several records at one instant cause a
    transition, the list of their references ordered by item, context and source id. The
    order is for determinism only."""
    rs = sorted_recs(recs)
    if not rs:
        return None
    if len(rs) == 1:
        return assertion_ref(rs[0].triple)
    return [assertion_ref(r.triple) for r in rs]


def compact_or_list(recs) -> str | list | None:
    rs = sorted_recs(recs)
    if not rs:
        return None
    if len(rs) == 1:
        return compact(rs[0].triple)
    return [compact(r.triple) for r in rs]


def frame_inforce(state: InForce) -> dict:
    """The members a resolved frame carries for the interpretation in force (4.6.1, README §5
    *Resolved frame*): its name and version, and the normalizations that put it in force, or
    `null` when none applies; ``{"ambiguous": [refs]}`` when it is ambiguous."""
    if state.ambiguous:
        return {"interpretation": None, "interpretation_version": None,
                "normalization": {"ambiguous": [compact(r.triple) for r in sorted_recs(state.records)]}}
    return {"interpretation": state.interp.name, "interpretation_version": state.interp.version,
            "normalization": compact_or_list(state.norms)}
