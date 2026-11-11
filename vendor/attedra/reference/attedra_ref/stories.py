"""Stories: conflict and change stories, their intervals, endings and standing, and the
maintenance of their families (spec §7, 9.5).

A story is an Item opened by a detection (7.2.1). Its standing is derived from evidence and
acts (9.5.2); nothing about it is stored as mutable state (I-9).

Conflict stories
    A conflict story concerns one subject, one property and an unordered pair of sides: two
    sources, or two expectation Assertions (7.2.2). The pair identifies the story's *family*.
    The family's event-time account is a timeline of the two sides' applicable values, in
    the corrected account, under the story's interpretation (7.2.4). A maximal run in which
    both sides are present and unequal is an *episode*; it ends by alignment, by withdrawal
    of a side, or by fulfillment of an expectation side (7.2.6).

    Each recorded story is placed on the episode that contains the earliest of its
    detections' basis evidence (its *anchor*). A story begins at its episode's start, except
    a story related to a reviewed predecessor in the same episode, which begins where the
    current comparison evidence first differs from the evidence the review cited, and no
    earlier than the review's effective time (7.3.1, 7.3.5). A story whose anchors fall in no
    episode never disagreed in the corrected account: it reads ended at every cutoff, with
    an empty interval (7.2.6).

Change stories
    A change story concerns one source's revision of one subject at one issuance (7.2.3).
    Its transitions are recomputed in the corrected account, under the interpretation in
    force at the revised Assertion's occurrence time; it ends at the effective time of a
    review that targets it and has not been withdrawn, and is open again only from a
    withdrawal that leaves no review of it in effect (7.2.7, 7.6.2), unless the interpretation
    in force then leaves its revision changing nothing: that period then has no length and ends
    by the normalization. It also ends, for good, at an instant from which the interpretation
    in force leaves its revision changing no property (7.3.8). A revision that a correction,
    backfilled evidence or the interpretation in force at its time leaves changing no property
    has no period (7.6.12); through a normalization, it reads not_started before its revision.
    When a later change of the interpretation in force makes the revision of a change story a
    normalization closed a change again, a related change story of 7.3.8 concerns the same
    revision and begins then (``reversal_start``).

Maintenance (7.2.8, README §7)
    After a write, ``plan_maintenance`` compares each affected family's recorded stories with
    its event-time account and returns the next record the specification requires: a
    continuation detection (7.2.5), a related story (7.3.1, 7.3.2), a reconciliation
    (7.3.3 split, 7.3.4 continuous, 7.3.5 boundary, 7.3.7 reconstructed, one for each change
    story of the revision, with the one related change story of the backfilled revision), or a
    related change story of 7.3.8 (``plan_reversal``). The write path records it and asks
    again until nothing is required. Stories and families are formed once per account, so a
    write that affects every unit of a project, such as a normalization, costs no pass over
    the account per unit.

Interpretation (7.2.4, 7.3.8)
    A story's interpretation at an instant is the interpretation in force for its subject
    then (``normalization.subject_schedule``); a detection's ``@frame`` records the one a
    detection was made under and never sets it. A family's timeline compares the sides at each
    instant under the interpretation in force then, and an instant at which that
    interpretation changes is an event of the timeline: sides that become equal under it end
    their story by normalization (7.2.6(d)), and sides that become unequal begin to disagree,
    the beginning citing the normalization (7.6.4). A comparison that matches only because of
    an interpretation a normalization put in force cites that normalization (``matched_by``,
    5.5.4). A story whose sides, at the instant its interval would begin under literal
    comparison, are equal under the interpretation in force then has no period (7.2.6, 7.6.12),
    and reads ``not_started`` before that instant (its end act's ``since``).
    A conflict story whose sides are two expectations compares each side under that
    expectation's own interpretation (7.2.4, 7.6.13): where the two are the same, under it;
    otherwise under the pair, equal when equal under both, unequal when unequal under both, and
    ambiguous otherwise (``normalization.pair_schedule``, ``Story.cmp``). Such a story that never
    disagreed only because its contexts' interpretations make its sides equal has no period, with
    the cause ``interpretation`` (7.6.12).
    Where the interpretation in force is ambiguous, the derivation runs under each
    resolution and an ambiguous content stands for the differences (transitions.py).

Periods (7.6.2)
    ``conflict_periods`` and ``change_periods`` give a story's periods as the contents (7.6.6)
    its begin and end acts carry, from the derivation above: a conflict story's interval, and
    a change story's periods between reviews. ``periods_state`` reads a unit's open dimension
    at a cutoff from such contents, derived or recorded (7.6.3, 7.6.14). Where several records
    at one instant cause a transition, the transition cites all of them, in identifier order
    (7.6.6). Recording and comparing the acts is in transitions.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cmp_to_key
from typing import Any

from . import instants as T
from .account import Account, parse_target
from .expectations import Expectation, expectation_context_interp, own_schedule
from .instants import Instant
from .interpretations import LITERAL, Interpretation
from .model import Rec, Triple, act_targets, ref_list
from .normalization import (InForce, Schedule, compact_or_list, ikey, pair_schedule, ref_or_list, sorted_recs,
                            subject_schedule)
from .positions import Classification, classify, transition
from .values import (assertion_ref, compact, is_assertion_ref, is_item_ref, item_ref, literal_equal, properties_of,
                     ref_triple)
from .view import Frame, View, tri_and, tri_or


# ---------------------------------------------------------------------------------------
# helpers


def _k(i: Instant | None) -> tuple:
    return (float("inf"), float("inf")) if i is None else (i.start, i.end)


def _max_inst(insts: list[Instant]) -> Instant | None:
    insts = [i for i in insts if i is not None]
    return max(insts, key=lambda i: (i.end, i.start)) if insts else None


def whole_view(acc: Account, interp: Interpretation | None = None) -> View:
    """The record perspective with no cutoff: the whole event-time account, compared under
    ``interp`` at every instant, or, with none, under the interpretation in force (7.3.8)."""
    if interp is None:
        return View(acc, Frame(None, None, LITERAL))
    return View(acc, Frame(None, None, interp, named=True))


def _precedence_sorted(acc: Account, recs: list[Rec]) -> list[Rec]:
    def cmp(a, b):
        p = acc.precedes(a, b)
        if p is True:
            return -1
        if p is False:
            return 1
        ka, kb = acc.sort_key(a), acc.sort_key(b)
        return -1 if ka < kb else (1 if ka > kb else 0)
    return sorted(recs, key=cmp_to_key(cmp))


# ---------------------------------------------------------------------------------------
# sides and timelines


@dataclass(frozen=True)
class Side:
    kind: str  # "statement" | "expectation"
    source: str | None = None
    exp: Triple | None = None

    @property
    def key(self) -> str:
        return self.source if self.kind == "statement" else compact(self.exp)


@dataclass
class SideState:
    present: bool = False
    value: Any = None
    record: Rec | None = None


@dataclass
class SideStep:
    at: Instant
    state: SideState
    cause: Rec | None
    cause_kind: str  # assert | withdraw | support | end | fulfill
    # 7.6.6: every record that caused the step at its instant (``cause`` is the first)
    records: list = field(default_factory=list)
    matched_by: tuple = ()  # 5.5.4: a fulfillment that matches only under a normalization's interpretation

    def __post_init__(self) -> None:
        if not self.records and self.cause is not None:
            self.records = [self.cause]


def _tie_groups(acc: Account, stmts: list[Rec]) -> list[list[Rec]]:
    """The runs of records, in precedence order, that no sequence evidence orders (4.5.2)."""
    groups: list[list[Rec]] = []
    for r in stmts:
        if groups and all(acc.precedes(x, r) is None for x in groups[-1]):
            groups[-1].append(r)
        else:
            groups.append([r])
    return groups


def value_ties(acc: Account, subject: str, source: str, prop: str) -> list[Rec]:
    """7.6.6, 4.5.3: a source's statements of a property that are tied or unordered with one
    another and assert different values, so that which supplies the applicable value is
    unspecified."""
    stmts = _precedence_sorted(acc, [r for r in acc.statements_about(subject, source)
                                     if prop in r.values and acc.occurrence(r) is not None])
    out = []
    for g in _tie_groups(acc, stmts):
        if len(g) > 1 and len({repr(canonical_value(r.values[prop])) for r in g}) > 1:
            out += g
    return out


def canonical_value(v: Any) -> Any:
    from .values import canonical  # noqa: PLC0415
    return canonical(v)


def statement_side_steps(acc: Account, subject: str, source: str, prop: str,
                         reverse_ties: bool = False) -> list[SideStep]:
    """One source's applicable value of a property over event time (5.2.1, 6.7.4). Records
    that no sequence evidence orders are taken in identifier order, or, with
    ``reverse_ties``, in the opposite order, so that a derivation that depends on their order
    can be made both ways (4.5.3, 7.6.6)."""
    stmts = [r for r in acc.statements_about(subject, source) if prop in r.values and acc.occurrence(r) is not None]
    stmts = _precedence_sorted(acc, stmts)
    if reverse_ties:
        stmts = [r for g in _tie_groups(acc, stmts) for r in reversed(g)]
    order = {r.triple: i for i, r in enumerate(stmts)}
    events = [(acc.occurrence(r), 0, order[r.triple], r, None) for r in stmts]
    for r in stmts:
        for w, tg in acc.acts_targeting_triple(r.triple):
            if w.action == "withdraw" and tg.support is None and tg.prop in (None, prop):
                e = acc.effective(w)
                if e is not None:
                    events.append((e, 1, order[r.triple], w, r))
    events.sort(key=lambda e: (_k(e[0]), e[1], e[2]))
    steps: list[SideStep] = []
    latest: Rec | None = None
    withdrawn: dict[Triple, Rec] = {}
    state = SideState()
    i = 0
    while i < len(events):
        j = i
        group = []
        while j < len(events) and _k(events[j][0]) == _k(events[i][0]):
            group.append(events[j])
            j += 1
        cause, kind = None, "assert"
        wds: dict[Triple, list[Rec]] = {}
        for _t, k, _o, rec, target in group:
            if k == 0:
                if latest is None or order[rec.triple] > order[latest.triple]:
                    latest = rec
                cause, kind = rec, "assert"
            else:
                withdrawn.setdefault(target.triple, rec)
                wds.setdefault(target.triple, []).append(rec)
                if latest is not None and target.triple == latest.triple:
                    cause, kind = rec, "withdraw"
        records = None
        if latest is None:
            new = SideState()
        elif latest.triple in withdrawn:
            new = SideState(False, None, latest)
            if kind != "withdraw":
                cause, kind = withdrawn[latest.triple], "withdraw"
            else:
                # 7.6.6: withdrawals of the applicable value taking effect at one instant
                records = sorted_recs(wds.get(latest.triple, [cause]))
        else:
            new = SideState(True, latest.values[prop], latest)
            if kind == "assert":
                # 7.6.6: statements at this instant, unordered with the applicable one, that
                # assert its value: every order of them gives the same step
                records = sorted_recs([rec for _t, k, _o, rec, _tg in group if k == 0 and (
                    rec is latest or (acc.precedes(rec, latest) is None
                                      and literal_equal(rec.values[prop], latest.values[prop])))])
                cause = latest
        if _changed(state, new):
            steps.append(SideStep(group[0][0], new, cause, kind, records or []))
            state = new
        i = j
    return steps


def _changed(a: SideState, b: SideState) -> bool:
    if a.present != b.present:
        return True
    if not a.present:
        return False
    return not literal_equal(a.value, b.value) or (a.record and b.record and a.record.triple != b.record.triple)


def expectation_side_steps(acc: Account, exp: Rec, prop: str) -> list[SideStep]:
    """An expectation side is present while it is in force for the property and not yet
    fulfilled for it (7.1.5); fulfillment ends it for good (6.5.2). Fulfillment is evaluated
    as for the expectation's own unit, under its own interpretation (7.2.6(c), 7.6.13)."""
    e = Expectation(whole_view(acc), exp, schedule=own_schedule(acc, exp))
    if e.requirement(prop)[0] != "value" or prop not in exp.values:
        return []
    periods, _ = e.periods(prop, None)
    q = e.qualifying_moment(prop, None)
    events = []
    for p in periods:
        events.append((p.start, 0, "support", period_begin_records(acc, p), ()))
        if p.end is not None:
            events.append((p.end, 1, "end", period_end_records(acc, p), ()))
    if q is not None:
        events.append((q.t, 2, "fulfill", sorted_recs([q.evidence] + [c.evidence for c in q.tied]), q.matched_by))
    events.sort(key=lambda x: (_k(x[0]), x[1]))
    steps, in_force, fulfilled = [], 0, False
    state = SideState()
    i = 0
    while i < len(events):
        j, recs, kind, mb = i, [], None, ()
        while j < len(events) and _k(events[j][0]) == _k(events[i][0]):
            _t, _o, k, rr, m = events[j]
            if k == "support":
                in_force += 1
            elif k == "end":
                in_force -= 1
            else:
                fulfilled = True
            recs, kind, mb = rr, k, m
            j += 1
        present = in_force > 0 and not fulfilled
        new = SideState(present, exp.values[prop] if present else None, exp if present else None)
        if new.present != state.present:
            steps.append(SideStep(events[i][0], new, recs[0] if recs else None, kind, list(recs), mb))
            state = new
        i = j
    return steps


def first_by_identifier(recs) -> Rec | None:
    """7.6.6: when several records qualify as the record of one transition, being at one
    instant with no sequence evidence ordering them, the record is the first of them in
    identifier order (item, context, source, by Unicode code point). It ranks nothing."""
    recs = [r for r in recs if r is not None]
    return min(recs, key=lambda r: r.triple) if recs else None


def period_end_records(acc: Account, p) -> list[Rec]:
    """The withdrawals whose taking effect ended an in-force period (6.6.1, 6.7.2, 7.6.5): all
    those that take effect at the period's end (7.6.6), in identifier order."""
    at = [w for w in p.end_records if (e := acc.effective(w)) is not None and _k(e) == _k(p.end)]
    return sorted_recs(at or p.end_records[:1])


def period_begin_records(acc: Account, p) -> list[Rec]:
    """The supports whose effective time begins an in-force period (6.3.3, 7.6.4): all those
    that take effect at the period's start (7.6.6), in identifier order."""
    at = [d for d in p.supports if (e := acc.effective(d)) is not None and _k(e) == _k(p.start)]
    return sorted_recs(at or p.supports[:1])


@dataclass
class EvidenceState:
    at: Instant
    records: tuple  # applicable side records (Rec or None)
    values: tuple
    cause: Rec | None
    # 7.6.6: the records of the change at this instant: the side Assertions that changed, or,
    # where only the interpretation in force changed, the normalizations concerned (7.6.4)
    changed: list = field(default_factory=list)

    @property
    def record(self) -> Rec | None:
        return self.changed[0] if self.changed else None


@dataclass
class Episode:
    """A maximal period in which the two sides disagree (7.2.4, 7.2.6)."""

    start: Instant
    start_cause: Rec | None
    states: list[EvidenceState] = field(default_factory=list)
    end: Instant | None = None
    end_kind: str | None = None
    end_records: list = field(default_factory=list)
    start_records: list = field(default_factory=list)  # 7.6.4, 7.6.6: the records of the beginning
    end_matched: tuple = ()  # 5.5.4: an alignment that matches only under a normalization's interpretation
    start_by_interp: bool = False  # the interval begins because the interpretation in force changed

    @property
    def end_record(self) -> Rec | None:
        return self.end_records[0] if self.end_records else None

    @property
    def start_record(self) -> Rec | None:
        return self.start_records[0] if self.start_records else None

    def contains(self, i: Instant) -> bool:
        return _k(self.start) <= _k(i) and (self.end is None or _k(i) < _k(self.end))


@dataclass
class Timeline:
    sides: tuple
    groups: list  # [(at, (SideState, SideState), status)]
    episodes: list[Episode]


def _state_interp(st: InForce) -> Interpretation:
    """The interpretation of a definite state; a derivation under an ambiguous state runs per
    resolution (``Schedule.resolutions``), so the first candidate stands only as a fallback."""
    if st.interp is not None:
        return st.interp
    return st.candidates[0][0] if st.candidates else LITERAL


def build_timeline(acc: Account, subject: str, prop: str, sides: tuple[Side, Side], sched: Schedule,
                   reverse_ties: bool = False) -> Timeline:
    """The family's event-time account: both sides' applicable values over time and the
    episodes in which they disagree, compared at each instant under the interpretation in
    force then (7.2.4, 7.3.8). An instant at which that interpretation changes is an event: it
    can end an episode (7.2.6(d)) or begin one (7.6.4). An expectation side's fulfillment is
    evaluated under the expectation's own interpretation (7.2.6(c))."""
    per_side = []
    for s in sides:
        if s.kind == "statement":
            per_side.append(statement_side_steps(acc, subject, s.source, prop, reverse_ties))
        else:
            rec = acc.get(s.exp)
            per_side.append(expectation_side_steps(acc, rec, prop) if rec else [])
    events = [(st.at, i, st) for i, steps in enumerate(per_side) for st in steps]
    events += [(t, 2, st) for t, st in sched.changes()]
    events.sort(key=lambda x: (_k(x[0]), x[1]))
    states = [SideState(), SideState()]
    cur = sched.initial
    groups, episodes = [], []
    status = "absent"
    current: Episode | None = None
    i = 0
    while i < len(events):
        j = i
        causes = {}
        prev = list(states)
        prev_state = cur
        while j < len(events) and _k(events[j][0]) == _k(events[i][0]):
            _at, side, st = events[j]
            if side == 2:
                cur = st
            else:
                states[side] = st.state
                causes[side] = st
            j += 1
        at = events[i][0]
        a, b = states
        icur = _state_interp(cur)
        if a.present and b.present:
            new_status = "aligned" if icur.equal(a.value, b.value, prop) else "disagreeing"
        else:
            new_status = "absent"
        interp_changed = cur.interp_key != prev_state.interp_key
        # 7.2.4, 7.6.6: the side steps that changed the comparison at this instant: a side's
        # presence, or its value under the interpretation in force now
        changed_steps = [stp for sd, stp in sorted(causes.items())
                         if prev[sd].present != stp.state.present
                         or (stp.state.present and not icur.equal(prev[sd].value, stp.state.value, prop))]
        side_recs = sorted_recs([r for stp in changed_steps for r in stp.records])
        # 7.2.6(d), 7.6.4: the normalization whose interpretation is in force from now, or,
        # where none is because the subject left the normalized scope, the one in force until now
        norm_recs = list(cur.norms) or list(prev_state.norms)
        main = causes.get(0) or causes.get(1)
        if new_status == "disagreeing":
            by_interp = not side_recs and interp_changed
            recs = side_recs if side_recs else (norm_recs if interp_changed else
                                                sorted_recs([r for stp in causes.values() for r in stp.records]))
            cause = main.cause if main else (recs[0] if recs else None)
            ev = EvidenceState(at, (a.record, b.record), (a.value, b.value), cause, recs)
            if status != "disagreeing":
                current = Episode(at, ev.cause, [ev], start_records=recs, start_by_interp=by_interp)
                episodes.append(current)
            else:
                last = current.states[-1]
                if not (icur.equal(last.values[0], ev.values[0], prop) and icur.equal(last.values[1], ev.values[1], prop)):
                    current.states.append(ev)
        elif status == "disagreeing":
            current.end = at
            if new_status == "aligned":
                if side_recs:
                    current.end_kind = "alignment"
                    current.end_records = side_recs
                    current.end_matched = cur.matched_by(a.value, b.value, prop, literal_equal)
                else:
                    current.end_kind = "normalization"
                    current.end_records = norm_recs
            else:
                gone_sides = [s for s in (0, 1) if s in causes and not states[s].present]
                gone_steps = [causes[s] for s in gone_sides]
                kinds = {g.cause_kind for g in gone_steps}
                if gone_steps and len(kinds) == 1:
                    gone = gone_steps[0]
                    recs = sorted_recs([r for g in gone_steps for r in g.records])
                else:
                    first = first_by_identifier([g.cause for g in gone_steps])
                    gone = next((g for g in gone_steps if g.cause is first), gone_steps[0] if gone_steps else main)
                    recs = list(gone.records) if gone else []
                current.end_kind = "fulfillment" if gone and gone.cause_kind == "fulfill" else "withdrawal"
                current.end_records = recs
                if current.end_kind == "fulfillment":
                    current.end_matched = gone.matched_by
                gone_side = next((s for s in gone_sides if causes[s] is gone), None)
                if current.end_kind == "withdrawal" and gone_side is not None:
                    # 7.2.6(b): a side whose applicable value comes to be withdrawn only because
                    # a correction changed the account ends the story with the correction as
                    # its ending record, of kind `correction`
                    corr = _correction_causing_absence(acc, subject, prop, sides[gone_side], at, sched,
                                                       gone.cause if gone else None)
                    if corr is not None:
                        current.end_kind = "correction"
                        current.end_records = [corr]
            current = None
        groups.append((at, (SideState(a.present, a.value, a.record), SideState(b.present, b.value, b.record)), new_status))
        status = new_status
        i = j
    return Timeline(tuple(sides), groups, episodes)


def _side_present_at(acc: Account, subject: str, prop: str, side: Side, at: Instant, sched: Schedule) -> bool:
    if side.kind == "statement":
        steps = statement_side_steps(acc, subject, side.source, prop)
    else:
        rec = acc.get(side.exp)
        steps = expectation_side_steps(acc, rec, prop) if rec else []
    present = False
    for st in steps:
        if _k(st.at) <= _k(at):
            present = st.state.present
    return present


def _correction_causing_absence(acc: Account, subject: str, prop: str, side: Side, at: Instant,
                                sched: Schedule, cause: Rec | None) -> Rec | None:
    """The correction without which the side would still have an applicable value at the
    instant it lost it (7.2.6, 8.3.3), if any: a correction of a record about the subject, of
    an act that targets one, of the record that ended the side, or of a context those records
    are at. The latest such correction by occurrence time is the ending record."""
    keys: set = set()
    for r in acc.by_item.get(subject, []):
        keys.add(("A", r.triple))
        keys.add(("I", r.context))
        for act, _tg in acc.acts_targeting_triple(r.triple):
            keys.add(("A", act.triple))
    if cause is not None:
        keys.add(("A", cause.triple))
    # corrected-away records are absent from the account but their corrections still apply
    for t in acc.absent:
        if t[0] == subject:
            keys.add(("A", t))
    cands = {c for key in keys for c in acc.corrections_of.get(key, []) if c in acc.records}
    for c in sorted((acc.records[t] for t in cands), key=acc.sort_key, reverse=True):
        alt = Account(acc.rs.without(c.triple))
        if _side_present_at(alt, subject, prop, side, at, sched):
            return c
    return None


# ---------------------------------------------------------------------------------------
# recorded stories


@dataclass
class Story:
    id: str
    detections: list[Rec]
    kind: str | None
    subject: str | None
    prop: str | None
    sides: tuple | None
    relates_to: str | None
    sched: Schedule  # 7.2.4: the story's interpretation over event time, the one in force for its subject
    frame_scope: Any
    malformed: str | None = None
    # 7.7.2, 7.7.3: the policy governing the story over event time, as segments (start,
    # policy): the one its first detection's @frame names, then each `adopt_policy` from its
    # effective time. None is the baseline.
    policy_segments: list = field(default_factory=lambda: [(None, None)])
    # 7.6.14: the name of the story's interpretation, at some instant, when it is one the
    # reference does not have; its transitions are then read as recorded, never derived
    interp_unavailable: str | None = None
    # 7.2.4: for a conflict story between two expectations, how its sides are compared over
    # event time (``normalization.pair_schedule``): each under the expectation's own
    # interpretation; ``side_scheds`` are those, in side order, and ``side_named`` says which
    # contexts name an interpretation (the others are compared under the one in force)
    cmp_sched: Schedule | None = None
    side_scheds: tuple | None = None
    side_named: tuple = ()

    @property
    def cmp(self) -> Schedule:
        """How the story's comparisons are made over event time (7.2.4): under the
        interpretation in force for its subject, or, between two expectations, under their own."""
        return self.cmp_sched if self.cmp_sched is not None else self.sched

    @property
    def first(self) -> Rec:
        return self.detections[0]

    @property
    def family(self) -> tuple | None:
        if self.kind != "conflict" or not self.sides:
            return None
        return (self.subject, self.prop, tuple(sorted(s.key for s in self.sides)))

    @property
    def interp(self) -> Interpretation:
        """The story's interpretation at the end of the history (internal use)."""
        return _state_interp(self.sched.at(None))

    @property
    def policy(self) -> dict | None:
        """The policy governing the story at the end of the history (7.7.2)."""
        return self.policy_segments[-1][1]

    def policy_at(self, t: Instant | None) -> dict | None:
        return policy_at(self.policy_segments, t)

    @property
    def ever_policies(self) -> list:
        """Every policy that governs the story at some instant, or is a candidate to govern it
        (7.7.2, 7.7.3)."""
        out = []
        for _s, p in self.policy_segments:
            for c in policy_candidates(p):
                if c not in out:
                    out.append(c)
        return out


@dataclass(frozen=True)
class AmbiguousPolicy:
    """7.7.2: the policy governing a unit from an instant at which several of its `adopt_policy`
    acts are tied or unordered, with no `@after` evidence ordering them, and name different
    policies. ``candidates`` are the policies they name (``None`` for the baseline), once each,
    in the order of the tied acts' compact references; ``records`` are the tied acts."""

    candidates: tuple
    records: tuple

    def out(self) -> dict:
        """README §5 *Ending policies*: {"ambiguous": [candidates], "records": [refs, sorted]}."""
        return {"ambiguous": [dict(c) if c is not None else None for c in self.candidates],
                "records": sorted(compact(r.triple) for r in self.records)}


def policy_candidates(p: Any) -> list:
    """The policies a segment's value stands for: one policy, or the candidates of an
    ambiguous one (7.7.2)."""
    return list(p.candidates) if isinstance(p, AmbiguousPolicy) else [p]


def policy_out(p: Any) -> Any:
    """A unit's policy as reads report it (README §5): `null`, {name, version}, or the ambiguous
    form."""
    return p.out() if isinstance(p, AmbiguousPolicy) else p


def segment_resolutions(segments: list, cap: int = 8) -> list[list]:
    """The definite policy histories an ambiguous one stands for (7.7.2: a result that depends on
    an ambiguous governing policy is evaluated under each candidate); consecutive segments
    naming one policy are one uninterrupted governance."""
    if not any(isinstance(p, AmbiguousPolicy) for _s, p in segments):
        return [segments]
    import itertools  # noqa: PLC0415
    options = [[(s, c) for c in policy_candidates(p)] for s, p in segments]
    out = []
    for combo in itertools.product(*options):
        segs = [combo[0]]
        for seg in combo[1:]:
            if policy_key_of(seg[1]) != policy_key_of(segs[-1][1]):
                segs.append(seg)
        out.append(segs)
        if len(out) >= cap:
            break
    return out


def segment_tied_records(segments: list) -> list[Rec]:
    """The tied `adopt_policy` acts of a unit's ambiguous policy segments (7.7.2)."""
    out: dict = {}
    for _s, p in segments:
        if isinstance(p, AmbiguousPolicy):
            for r in p.records:
                out[r.triple] = r
    return [out[t] for t in sorted(out)]


def policy_at(segments: list, t: Instant | None) -> dict | None:
    """The policy governing a unit at an instant (7.7.2): the one named by its latest
    `adopt_policy` effective at or before the instant, or else the one named for it at the
    start. ``t`` None is the end of the history."""
    found = segments[0][1]
    for s, p in segments[1:]:
        if t is None or (T.at_or_before(s, t) is True):
            found = p
    return found


def policy_segments(acc: Account, initial: dict | None, adopts: list[Rec]) -> list:
    """7.7.2, 7.7.3: a unit's policy over event time. An `adopt_policy` takes effect when it is
    made, at its effective time (8.4.1). Where several take effect at one instant with no
    `@after` evidence ordering them, the latest of them is unspecified: when they name the same
    policy, that one governs from then; when they name different policies, the governing policy
    is ambiguous among them (``AmbiguousPolicy``). Consecutive segments naming one policy are
    one uninterrupted governance."""
    segs: list = [(None, initial)]
    timed = [(acc.effective(r), r) for r in adopts]
    timed = [(e, r) for e, r in timed if e is not None]
    timed.sort(key=lambda x: (_k(x[0]), x[1].triple))
    i = 0
    while i < len(timed):
        e = timed[i][0]
        group = [r for t, r in timed[i:] if _k(t) == _k(e)]
        i += len(group)
        latest = acc.latest_of(group) if len(group) > 1 else group
        cands: list = []
        for r in sorted(latest, key=lambda r: compact(r.triple)):
            p = frame_policy(r.values.get("@frame"))
            if all(policy_key_of(p) != policy_key_of(c) for c in cands):
                cands.append(p)
        value = cands[0] if len(cands) == 1 else AmbiguousPolicy(tuple(cands), tuple(sorted(latest, key=lambda r: r.triple)))
        segs.append((e, value))
    out = [segs[0]]
    for seg in segs[1:]:
        if policy_key_of(seg[1]) != policy_key_of(out[-1][1]):
            out.append(seg)
    return out


def policy_key_of(p: Any) -> tuple | None:
    if isinstance(p, AmbiguousPolicy):
        return ("ambiguous",) + tuple(policy_key_of(c) for c in p.candidates)
    return (p.get("name"), p.get("version")) if isinstance(p, dict) else None


def _det_time(acc: Account, d: Rec) -> tuple:
    return acc.sort_key(d)


def load_story(acc: Account, story_id: str) -> Story | None:
    """A recorded story as the account shows it (7.2.1), read once per account: an account
    never changes once built, and nothing changes a Story once loaded."""
    cache = acc.__dict__.setdefault("_story_cache", {})
    if story_id not in cache:
        cache[story_id] = _load_story(acc, story_id)
    return cache[story_id]


def _load_story(acc: Account, story_id: str) -> Story | None:
    dets = [d for d in acc.detections_of.get(story_id, []) if d.item == story_id]
    if not dets:
        return None
    dets.sort(key=lambda d: _det_time(acc, d))
    first = _first_detection(acc, dets)
    sv = first.values.get("@story") if isinstance(first.values.get("@story"), dict) else {}
    kind = sv.get("kind")
    subj = sv.get("subject", {}).get("id") if is_item_ref(sv.get("subject")) else None
    prop = sv.get("property")
    frame = first.values.get("@frame") if isinstance(first.values.get("@frame"), dict) else {}
    rel = first.values.get("@relates_to")
    relates = ref_triple(rel)[0] if is_assertion_ref(rel) else None
    # 7.2.4: a story's interpretation is the interpretation in force for its subject at each
    # instant (7.3.8); a detection's @frame records the one it was made under and never sets it
    sched = subject_schedule(acc, subj)
    st = Story(story_id, dets, kind, subj, prop, None, relates, sched, frame.get("scope"))
    if kind == "conflict":
        sides = _sides_from_basis(acc, first, subj)
        if sides is None:
            st.malformed = "conflict_story_sides_not_two"
        elif sides[0].kind != sides[1].kind:
            # 7.1.5: comparing an expectation with submitted evidence is fulfillment, never a
            # conflict; a story that pairs them cannot be evaluated as a conflict story
            st.malformed = "conflict_story_mixes_statement_and_expectation"
        elif sides[0].kind == "expectation":
            # 7.2.4: two expectations are compared under their own interpretations
            recs = (acc.get(sides[0].exp), acc.get(sides[1].exp))
            if recs[0] is not None and recs[1] is not None:
                st.side_scheds = (own_schedule(acc, recs[0]), own_schedule(acc, recs[1]))
                st.side_named = tuple(expectation_context_interp(acc, r)[0] is not None for r in recs)
                st.cmp_sched = pair_schedule(st.side_scheds[0], st.side_scheds[1], recs)
        st.sides = sides
    if st.side_scheds is not None:
        st.interp_unavailable = st.side_scheds[0].unavailable() or st.side_scheds[1].unavailable()
    else:
        st.interp_unavailable = sched.unavailable()
    # 7.7.2, 7.7.3: the policy its first detection names, changed by each adopt_policy from its
    # effective time
    recs = story_acts(acc, st, ("reconcile",))
    adopts = [r for r in recs if r.values.get("@outcome") == "adopt_policy"]
    st.policy_segments = policy_segments(acc, frame_policy(frame), adopts)
    return st


def frame_policy(frame: Any) -> dict | None:
    """The ending policy a @frame names by `policy` and `policy_version` (7.7.2), None for the
    baseline."""
    if not isinstance(frame, dict) or frame.get("policy") is None:
        return None
    return {"name": frame["policy"], "version": frame.get("policy_version")}


def _first_detection(acc: Account, dets: list[Rec]) -> Rec:
    """The detection that opened the story: the one without a predecessor among the
    story's detections; generated continuations carry the story's own context names."""
    own = [d for d in dets if d.context.startswith(d.item + "/d")]
    others = [d for d in dets if d not in own]
    if others:
        return others[0]
    return sorted(own, key=lambda d: _det_num(d))[0]


def _det_num(d: Rec) -> int:
    try:
        return int(d.context.rsplit("/d", 1)[1])
    except (ValueError, IndexError):
        return 0


def _sides_from_basis(acc: Account, det: Rec, subject: str | None) -> tuple | None:
    sides = []
    for ref in ref_list(det.values, "@basis"):
        if not is_assertion_ref(ref):
            continue
        t = ref_triple(ref)
        if acc.role(t[1]) == "expectation":
            s = Side("expectation", exp=t)
        else:
            s = Side("statement", source=t[2])
        if s not in sides:
            sides.append(s)
    if len(sides) != 2:
        return None
    return tuple(sorted(sides, key=lambda s: s.key))


def story_acts(acc: Account, st: Story, actions: tuple[str, ...]) -> list[Rec]:
    """Acts of the given kinds that target the story Item or any of its detections."""
    found: dict[Triple, Rec] = {}
    keys = [("I", st.id)] + [("A", d.triple) for d in st.detections]
    for key in keys:
        for r, _tg in acc.acts_targeting(key):
            if r.action in actions:
                found[r.triple] = r
    return sorted(found.values(), key=acc.sort_key)


def all_stories(acc: Account, subjects: set[str] | None = None) -> list[Story]:
    """The recorded stories of the account, by id, or those about the subjects; every story is
    loaded once per account and indexed by its subject, so that asking for the stories of one
    subject after another costs no pass over the others."""
    idx = acc.__dict__.get("_stories_by_subject")
    if idx is None:
        idx = {}
        ordered = []
        for sid in sorted(acc.detections_of):
            st = load_story(acc, sid)
            if st is None:
                continue
            ordered.append(st)
            idx.setdefault(st.subject, []).append(st)
        acc.__dict__["_stories_by_subject"] = idx
        acc.__dict__["_stories_ordered"] = ordered
    if subjects is None:
        return list(acc.__dict__["_stories_ordered"])
    if len(subjects) == 1:
        return list(idx.get(next(iter(subjects)), []))
    return [st for st in acc.__dict__["_stories_ordered"] if st.subject in subjects]


def detection_anchor(acc: Account, det: Rec, st: Story) -> Instant | None:
    """The time a detection's compared evidence was applicable: the later of its basis
    statements' occurrence times in the corrected account; for expectation sides, the
    detection's frame cutoff."""
    occs = []
    for ref in ref_list(det.values, "@basis"):
        if is_assertion_ref(ref):
            r = acc.get(ref_triple(ref))
            if r is not None and r.kind == "statement":
                occs.append(acc.occurrence(r))
    a = _max_inst(occs)
    if a is not None:
        return a
    if st.sides and all(s.kind == "expectation" for s in st.sides):
        f = det.values.get("@frame") if isinstance(det.values.get("@frame"), dict) else {}
        c = f.get("cutoff")
        if isinstance(c, str):
            i = T.parse_instant(c)
            if i is not None:
                return i
        return acc.occurrence(det)
    return None


# ---------------------------------------------------------------------------------------
# family analysis


@dataclass
class StoryInfo:
    story: Story
    episode: Episode | None = None
    start: Instant | None = None
    end: Instant | None = None
    ending: dict | None = None  # {"kind", "records": [Rec], "at": Instant, "matched_by": (Rec, ...)}
    continued_in: str | None = None
    tie: Instant | None = None
    empty_reason: str | None = None  # correction | normalization | interpretation
    # 7.6.12: the normalizations in force then, or, for `interpretation`, the two expectations
    empty_records: list = field(default_factory=list)
    start_records: list = field(default_factory=list)  # 7.6.4, 7.6.6: the records that began the interval
    tied_with: list = field(default_factory=list)  # 7.6.6 `tied`: records the beginning is tied with
    literal_start: Instant | None = None  # 7.2.6: where its interval would begin under literal comparison

    @property
    def start_record(self) -> Rec | None:
        return self.start_records[0] if self.start_records else None


LITERAL_SCHEDULE = Schedule.fixed(LITERAL)


def _sched_key(sched: Schedule) -> tuple:
    return tuple((s.text if s is not None else None, st.key) for s, st in sched.segments)


class Family:
    """The stories of one conflict family and their event-time account, under the
    interpretation in force for the subject (7.2.4), or under ``sched``, one resolution of it
    (normalization.Schedule.resolutions)."""

    def __init__(self, acc: Account, stories: list[Story], sched: Schedule | None = None,
                 reverse_ties: bool = False) -> None:
        self.acc = acc
        self.stories = stories
        self.by_id = {s.id: s for s in stories}
        root = stories[0]
        self.subject, self.prop, self.sides = root.subject, root.prop, root.sides
        self.sched = sched if sched is not None else root.cmp
        self.reverse_ties = reverse_ties
        # 7.6.6, 4.5.3: a side's tied statements that assert different values; a derivation
        # that depends on their order is made both ways (``reverse_ties``)
        self.tied: list[Rec] = sorted(
            (r for side in (self.sides or ()) if side.kind == "statement"
             for r in value_ties(acc, self.subject, side.source, self.prop)), key=lambda r: r.triple)
        self._timelines: dict = {}
        self.info: dict[str, StoryInfo] = {}
        # 4.2.4, 9.2.2, 7.6.6: a statement side's statements that carry the property but have no
        # occurrence time; the side's value, and with it the story, cannot be placed
        self.untimed: list[Rec] = sorted(
            (r for side in (self.sides or ()) if side.kind == "statement"
             for r in acc.statements_about(self.subject, side.source)
             if self.prop in r.values and acc.occurrence(r) is None), key=lambda r: r.triple)
        self._analyze()

    @property
    def normalized(self) -> bool:
        """Whether the sides are compared at some instant under anything but literal comparison:
        a normalization applies to the subject (7.3.8), or an expectation side's context names an
        interpretation (7.2.4, 7.6.13)."""
        return not (self.sched.constant and not self.sched.initial.norms
                    and self.sched.initial.interp_key == ikey(LITERAL))

    def timeline(self, sched: Schedule | None = None) -> Timeline:
        sched = self.sched if sched is None else sched
        key = _sched_key(sched)
        if key not in self._timelines:
            self._timelines[key] = build_timeline(self.acc, self.subject, self.prop, self.sides, sched,
                                                  self.reverse_ties)
        return self._timelines[key]

    def variants(self) -> list["Family"]:
        """The family under every resolution of what its derivation leaves unspecified: an
        ambiguous interpretation in force (7.3.8) and tied statements of one source that assert
        different values (4.5.3), each resolved both ways (7.6.6)."""
        out = []
        for res in self.sched.resolutions():
            for rev in ((False, True) if self.tied else (False,)):
                if res is self.sched and rev == self.reverse_ties:
                    out.append(self)
                else:
                    out.append(Family(self.acc, self.stories, res, rev))
        return out

    def variant_records(self) -> list[Rec]:
        return sorted({r.triple: r for r in (self.sched.ambiguous_records() + self.tied)}.values(),
                      key=lambda r: r.triple)

    def anchors(self, st: Story) -> list[tuple[Instant, Rec]]:
        out = []
        for d in st.detections:
            a = detection_anchor(self.acc, d, st)
            if a is not None:
                out.append((a, d))
        return sorted(out, key=lambda x: _k(x[0]))

    def episode_of(self, st: Story) -> Episode | None:
        if st.id in self.info:
            return self.info[st.id].episode
        return self._anchor_episode(self.timeline(), st)

    def _anchor_episode(self, tl: Timeline, st: Story) -> Episode | None:
        anchors = self.anchors(st)
        for ep in tl.episodes:
            if any(ep.contains(a) for a, _d in anchors):
                return ep
        return None

    def _analyze(self) -> None:
        acc = self.acc
        tl = self.timeline()
        for st in self.stories:
            self.info[st.id] = StoryInfo(st, self._anchor_episode(tl, st))
        if self.normalized and self.sides:
            self._normalization_mapping(tl)
        # continuous reconciliations (7.3.4)
        for st in self.stories:
            for r in story_acts(acc, st, ("reconcile",)):
                if r.values.get("@outcome") == "continuous" and is_item_ref(r.values.get("@representative")):
                    rep = r.values["@representative"]["id"]
                    if rep != st.id:
                        self.info[st.id].continued_in = rep
        for st in self.stories:
            info = self.info[st.id]
            ep = info.episode
            if ep is None:
                if info.empty_reason is None:
                    info.empty_reason = "correction"
                elif info.empty_reason in ("normalization", "interpretation") and self._correction_governs(st):
                    # 7.6.12: `correction` comes before `normalization` and `interpretation` where,
                    # without the corrections, the story would have a period under its
                    # interpretation
                    info.empty_reason = "correction"
                continue
            info.start = ep.start
            info.start_records = list(ep.start_records)
            pred = self.by_id.get(st.relates_to) if st.relates_to else None
            if pred is not None and self.info[pred.id].episode is ep:
                anchors = self.anchors(st)
                anchor_entry = next(((a, d) for a, d in anchors if ep.contains(a)), None)
                anchor = anchor_entry[0] if anchor_entry else ep.start
                reviews = story_acts(acc, pred, ("review",))
                if reviews:
                    # 7.3.1, 7.3.5: a story related to a reviewed predecessor begins where the
                    # evidence first differs from what the review cited, no earlier than the
                    # review's effective time
                    info.start = anchor
                    state = _state_at(ep, anchor)
                    info.start_records = (list(state.changed) if state is not None and state.changed else None) \
                        or list(ep.start_records)
                    for review in sorted(reviews, key=lambda r: _k(acc.effective(r))):
                        b, tie, recs, tied = review_boundary(acc, self, pred, review, ep)
                        if b is not None:
                            info.start = b
                            info.start_records = recs
                            if tie:
                                info.tie = b
                                info.tied_with = tied
                            break
            info.end = ep.end
            if ep.end is not None:
                info.ending = {"kind": ep.end_kind, "records": list(ep.end_records), "at": ep.end,
                               "matched_by": tuple(ep.end_matched)}

    def _normalization_mapping(self, tl: Timeline) -> None:
        """7.2.6, 7.3.2, 7.3.8: the stories of a family whose subject a normalization applies to.

        * A story that is not a related story of the family is decided at the instant at which
          its interval would begin under literal comparison: where its sides are equal then
          under the interpretation in force, it never disagreed under its interpretation and
          has no period, its ending record the normalization in force then (7.6.12); otherwise
          its interval is the episode, under the interpretation in force, that contains that
          instant. Nothing later changes this.
        * A related story whose predecessor ended by a normalization, or had no period because
          of one, and which cites no evidence later than its predecessor's, stands for a later
          disagreement of the same evidence under a later interpretation in force (7.3.8 *After
          it*): its interval is the first episode that begins after that ending."""
        lit = self.timeline(LITERAL_SCHEDULE)
        done: set[str] = set()
        pending = list(self.stories)
        while pending:
            progressed = False
            for st in list(pending):
                pred = self.by_id.get(st.relates_to) if st.relates_to and st.relates_to != st.id else None
                if pred is not None and pred.id not in done and pred in pending:
                    continue
                pending.remove(st)
                done.add(st.id)
                progressed = True
                info = self.info[st.id]
                anchors = self.anchors(st)
                if pred is not None:
                    if self._renormalized(st, pred, info.episode, anchors):
                        info.episode = self._episode_after(tl, pred)
                    continue
                lit_ep = next((ep for ep in lit.episodes if any(ep.contains(a) for a, _d in anchors)), None)
                if lit_ep is None:
                    continue
                info.literal_start = lit_ep.start
                state = self.sched.at(lit_ep.start)
                vals = lit_ep.states[0].values
                if _state_interp(state).equal(vals[0], vals[1], self.prop):
                    info.episode = None
                    if state.norms or not self.sides or self.sides[0].kind != "expectation":
                        # 7.6.12: the normalizations that put the interpretation in force then,
                        # for the sides compared under it
                        info.empty_reason = "normalization"
                        info.empty_records = list(state.norms)
                    else:
                        # 7.6.12: two expectations whose contexts' interpretations alone make
                        # their sides equal; the record is the two expectations (7.6.6)
                        info.empty_reason = "interpretation"
                        info.empty_records = sorted_recs(self.acc.get(sd.exp) for sd in self.sides)
                else:
                    info.episode = next((ep for ep in tl.episodes if ep.contains(lit_ep.start)), info.episode)
            if not progressed:
                break

    def _renormalized(self, st: Story, pred: Story, ep: Episode | None, anchors) -> bool:
        pinfo = self.info[pred.id]
        pep = pinfo.episode
        by_norm = (pep is not None and pep.end_kind == "normalization") or \
            (pep is None and pinfo.empty_reason == "normalization")
        if not by_norm:
            return False
        p_anchors = self.anchors(pred)
        if not p_anchors or not anchors:
            return False
        last = max((a for a, _d in p_anchors), key=_k)
        if any(_k(a) > _k(last) for a, _d in anchors):
            return False
        return ep is None or ep is pep or (pep is not None and _k(ep.start) <= _k(pep.start))

    def _episode_after(self, tl: Timeline, pred: Story) -> Episode | None:
        pinfo = self.info[pred.id]
        after = pinfo.episode.end if pinfo.episode is not None else pinfo.literal_start
        if after is None:
            return None
        return next((ep for ep in tl.episodes if _k(ep.start) >= _k(after)), None)

    def _correction_governs(self, st: Story) -> bool:
        acc = self.acc
        if not any(k[0] == "A" and k[1][0] == self.subject for k in acc.corrections_of):
            return False
        raw = Account(acc.rs, apply_corrections=False)
        alt = load_story(raw, st.id)
        if alt is None or alt.malformed or alt.kind != "conflict":
            return False
        fam = next((f for f in families(raw, all_stories(raw, {alt.subject})) if alt.id in f.by_id), None)
        return fam is not None and fam.info[alt.id].episode is not None


def review_in_effect_linear(acc: Account, st: Story, at: Instant) -> Rec | None:
    """The latest review of a story effective at or before an instant (a tie counts as
    in effect, 7.3.1) and not withdrawn by then."""
    found = None
    for r in story_acts(acc, st, ("review",)):
        e = acc.effective(r)
        if e is None or _k(e) > _k(at):
            continue
        if _withdrawn_linear(acc, r, at):
            continue
        found = r
    return found


def _withdrawn_linear(acc: Account, r: Rec, at: Instant) -> bool:
    for w, tg in acc.acts_targeting_triple(r.triple):
        if w.action == "withdraw" and tg.support is None:
            e = acc.effective(w)
            if e is not None and _k(e) <= _k(at):
                return True
    return False


def cited_values(acc: Account, fam: Family, st: Story, review: Rec) -> tuple | None:
    """The side values a review cited (7.3.5); a side the review's basis does not cite is
    taken from the story's latest detection at or before the review."""
    out = []
    dets = [d for a, d in fam.anchors(st) if _k(a) <= _k(acc.effective(review) or a)] or st.detections
    for side in fam.sides:
        val, found = None, False
        for source in (review, *reversed(dets)):
            for ref in ref_list(source.values, "@basis"):
                if not is_assertion_ref(ref):
                    continue
                t = ref_triple(ref)
                if (side.kind == "statement" and t[2] == side.source and t[0] == fam.subject) or \
                        (side.kind == "expectation" and t == side.exp):
                    rec = acc.get(t)
                    vals = rec.values if rec else (acc.rs.assertions[t].values if t in acc.rs.assertions else {})
                    val, found = vals.get(fam.prop), True
                    break
            if found:
                break
        if not found:
            return None
        out.append(val)
    return tuple(out)


def review_boundary(acc: Account, fam: Family, st: Story, review: Rec, ep: Episode
                    ) -> tuple[Instant | None, bool, list, list]:
    """Where the current comparison evidence of a reviewed story first differs from what the
    review cited, no earlier than the review's effective time (7.3.1, 7.3.5), judged under the
    story's interpretation at each instant (7.2.4). Returns the boundary, whether it is a
    change tied with the review without ``@after`` evidence, the records that begin the
    related story there (7.6.4: the review, where the interval begins at its effective time;
    the disagreeing side's Assertion where the change is tied with the review) and the records
    that beginning is tied with (7.6.6)."""
    r = acc.effective(review)
    cited = cited_values(acc, fam, st, review)
    if r is None or cited is None:
        return None, False, [], []

    def differs(state: EvidenceState) -> bool:
        interp = _state_interp(fam.sched.at(state.at))
        return not all(interp.equal(state.values[i], cited[i], fam.prop) for i in range(2))

    before = [s for s in ep.states if _k(s.at) <= _k(r)]
    if before and differs(before[-1]):
        last = before[-1]
        tie = _k(last.at) == _k(r) and not _after_orders(acc, last.cause, review)
        if tie:
            # 7.3.6, 7.6.6: a change at the review's own instant with no @after evidence: the
            # change begins the interval, tied with the review
            return r, True, (list(last.changed) or [last.cause or review]), [review]
        return r, False, [review], []
    for s in ep.states:
        if _k(s.at) > _k(r) and differs(s):
            tie = T.before(r, s.at) is not True and not _after_orders(acc, s.cause, review)
            return s.at, tie, (list(s.changed) or [s.cause]), ([review] if tie else [])
    return None, False, [], []


def _after_orders(acc: Account, a: Rec | None, b: Rec | None) -> bool:
    if a is None or b is None:
        return False
    return acc.precedes(a, b) is not None and (acc._after_ref(a) == b.triple or acc._after_ref(b) == a.triple)


def families(acc: Account, stories: list[Story]) -> list[Family]:
    """The conflict families of the stories, in family order. A family is formed from all the
    account's stories of its subject, once per account (``subject_families``), so the stories
    given select families but do not change them."""
    subjects = []
    for st in stories:
        if st.family is not None and not st.malformed and st.subject not in subjects:
            subjects.append(st.subject)
    wanted = {st.family for st in stories if st.family is not None and not st.malformed}
    out = [f for subj in subjects for f in subject_families(acc, subj) if f.stories[0].family in wanted]
    return sorted(out, key=lambda f: f.stories[0].family)


def subject_families(acc: Account, subject: str | None) -> list[Family]:
    """Every conflict family of one subject (7.2.2), formed once per account: an account never
    changes once built, and a family's analysis depends only on it."""
    cache = acc.__dict__.setdefault("_family_cache", {})
    if subject not in cache:
        groups: dict[tuple, list[Story]] = {}
        for st in all_stories(acc, {subject}):
            if st.family is not None and not st.malformed:
                groups.setdefault(st.family, []).append(st)
        cache[subject] = [Family(acc, sorted(groups[key], key=lambda s: (_k(_first_anchor(acc, s)), s.id)))
                          for key in sorted(groups)]
    return cache[subject]


def _first_anchor(acc: Account, st: Story) -> Instant | None:
    a = [detection_anchor(acc, d, st) for d in st.detections]
    a = [x for x in a if x is not None]
    return min(a, key=_k) if a else None


# ---------------------------------------------------------------------------------------
# change stories (7.2.3, 7.2.7, 7.3.7)


def revision_priors(acc: Account, new: Rec, interp: Interpretation = LITERAL) -> list[tuple[str, Triple | None, str | None]]:
    """Each property the revised Assertion carries, in property-name order, with the origin
    of its source's position just before it (the prior Assertion, or the withdrawn one; None
    when never asserted) and the transition (5.6.2, 7.2.3) under the interpretation, `unchanged`
    included."""
    out = []
    earlier = [r for r in acc.statements_about(new.item, new.source) if r is not new and acc.precedes(r, new) is True]
    occ = acc.occurrence(new)
    for p in sorted(properties_of(new.values)):
        carriers = [r for r in earlier if p in r.values]
        prior = Classification("never_asserted")
        if carriers:
            latest = acc.latest_of(carriers)
            l = latest[-1]
            wd = None
            for w, tg in acc.acts_targeting_triple(l.triple):
                if w.action == "withdraw" and tg.support is None and tg.prop in (None, p):
                    e = acc.effective(w)
                    if e is not None and occ is not None and _k(e) <= _k(occ):
                        wd = w
            prior = Classification("withdrawn", withdrawn_by=wd, withdrawn=l) if wd else Classification("asserted", l.values[p], l)
        cur = Classification("asserted", new.values[p], new)
        origin = (prior.origin or prior.withdrawn).triple if prior.kind != "never_asserted" else None
        out.append((p, origin, transition(prior, cur, interp, p)))
    return out


def revision_transitions(acc: Account, new: Rec, interp: Interpretation = LITERAL) -> list[dict]:
    """The property transitions of one revision, in the corrected account: each property
    the revised Assertion carries whose value differs from its source's position just
    before it under the interpretation (5.6.2, 7.2.3). Equal-value transitions are omitted."""
    return [{"property": p, "transition": kind, "prior": prior, "new": new.triple}
            for p, prior, kind in revision_priors(acc, new, interp) if kind not in (None, "unchanged")]


def change_interp(acc: Account, st: Story, new: Rec | None, sched: Schedule | None = None) -> InForce:
    """7.2.7: a change story's transitions are compared under the interpretation in force at
    its revised Assertion's occurrence time, or, for a related change story of 7.3.8, at its
    beginning."""
    sched = sched or st.sched
    pred = same_revision_predecessor(acc, st)
    if pred is not None and new is not None:
        rs = reversal_start(acc, pred, new, sched)
        if rs is not None:
            return sched.at(rs[0])
    occ = acc.occurrence(new) if new is not None else None
    return sched.at(occ) if occ is not None else sched.initial


def same_revision_predecessor(acc: Account, st: Story) -> Story | None:
    """7.3.8 *After it*: the change story that a related change story of 7.3.8 relates to, which
    concerns the same revision (unlike the related change story of 7.3.7, which concerns the
    backfilled issuance's own revision); None otherwise."""
    if st.kind != "change" or not st.relates_to or st.relates_to == st.id:
        return None
    pred = load_story(acc, st.relates_to)
    if pred is None or pred.kind != "change":
        return None
    a = change_story_revision(acc, st)[0]
    b = change_story_revision(acc, pred)[0]
    if a is None or b is None or a.triple != b.triple:
        return None
    return pred


def normalization_closure(acc: Account, st: Story, sched: Schedule | None = None) -> Instant | None:
    """7.3.8 *After it*: when a change story's baseline ending is a normalization, as a period
    ending or as its no-period ending (7.2.7, 7.6.2, 7.6.12), the instant from which that ending
    holds: the period's end, or the no-period ending's `since`. None otherwise."""
    periods = change_periods(acc, st, sched)
    if not periods:
        return None
    last = periods[-1]
    end = last.end
    if not (isinstance(end, dict) and end.get("cause") == "normalization"):
        return None
    t = end.get("since") if last.begin is None else end.get("at")
    return T.parse_instant(t) if isinstance(t, str) else None


def reversal_start(acc: Account, pred: Story, new: Rec, sched: Schedule) -> tuple[Instant, list[Rec]] | None:
    """7.3.8 *After it*: for a revision whose latest change story ``pred`` a normalization
    closed, the first later instant at which a change of the interpretation in force makes the
    revision change a property again, with the normalization in force from then, or, where none
    is because the subject left the normalized scope, the one in force until then (7.6.4)."""
    closed = normalization_closure(acc, pred, sched)
    if closed is None:
        return None
    prev = sched.at(closed)
    for t, stt in sched.changes():
        if _k(t) <= _k(closed):
            continue
        if revision_transitions(acc, new, _state_interp(stt)):
            return t, list(stt.norms) or list(prev.norms)
        prev = stt
    return None


def _revised_assertion(acc: Account, trans: list) -> Rec | None:
    for t in trans:
        if isinstance(t, dict) and is_assertion_ref(t.get("new")):
            new = acc.get(ref_triple(t["new"]))
            if new is None and ref_triple(t["new"]) in acc.relocated:
                new = acc.get(acc.relocated[ref_triple(t["new"])][1])
            return new
    return None


def _transitions_of(r: Rec) -> list:
    return r.values.get("@transitions") if isinstance(r.values.get("@transitions"), list) else []


def reconstructed_of(acc: Account, st: Story) -> list[Rec]:
    """The story's `reconstructed` reconciliations (7.3.7), in occurrence order."""
    return sorted((r for r in story_acts(acc, st, ("reconcile",)) if r.values.get("@outcome") == "reconstructed"),
                  key=acc.sort_key)


def change_story_revision(acc: Account, st: Story) -> tuple[Rec | None, Rec, list[dict]]:
    """The revised Assertion of a change story, the record its transitions come from (the
    detection or the latest ``reconstructed`` reconciliation) and the recorded transitions.
    A `reconstructed` reconciliation whose revision changes no property lists no transition
    (7.3.7); the revised Assertion is then the one the story's other records name."""
    src = st.first
    recon = reconstructed_of(acc, st)
    if recon:
        src = recon[-1]
    trans = _transitions_of(src)
    new = _revised_assertion(acc, trans)
    if new is None and not any(isinstance(t, dict) and is_assertion_ref(t.get("new")) for t in trans):
        for r in [st.first] + recon[:-1]:
            new = _revised_assertion(acc, _transitions_of(r))
            if new is not None:
                break
    return new, src, trans


def reconstructed_no_change(acc: Account, st: Story) -> Rec | None:
    """7.2.7, 7.3.7, 7.6.12: the backfilled Assertion that left the change story's revision
    changing no property: the @basis of its latest `reconstructed` reconciliation, when that
    reconciliation lists no transition and the Assertion is in the corrected account."""
    recon = reconstructed_of(acc, st)
    if not recon or _transitions_of(recon[-1]):
        return None
    for ref in ref_list(recon[-1].values, "@basis"):
        if is_assertion_ref(ref):
            b = acc.get(ref_triple(ref))
            if b is not None:
                return b
    return None


# ---------------------------------------------------------------------------------------
# standing at a frame (9.5.1, 9.5.2)


def _review_dimension(view: View, st: Story, cutoff: Instant | None) -> tuple[str, Rec | None]:
    acc = view.acc
    votes = []
    best = None
    for r in story_acts(acc, st, ("review",)):
        eff = view.effective_within(r, cutoff)
        if eff is False:
            continue
        wd = False
        for w, tg in acc.acts_targeting_triple(r.triple):
            if w.action == "withdraw" and tg.support is None:
                x = view.effective_within(w, cutoff)
                if x is True:
                    wd = True
                elif x is None:
                    eff = None
        if wd:
            continue
        votes.append(eff)
        if eff is True and best is None:
            best = r
    if any(v is True for v in votes):
        return "reviewed", best
    if any(v is None for v in votes):
        return "ambiguous", None
    return "unreviewed", None


def ignore_in_effect(view: View, r: Rec, cutoff: Instant | None) -> bool | None:
    """9.5.6: an ignore is in effect from its effective time while the cutoff is at or before
    its ``@until`` (4.2.5), and until a withdrawal of it takes effect (6.7.9). None when that
    depends on an unspecified order (4.5.3)."""
    acc = view.acc
    eff = view.effective_within(r, cutoff)
    if eff is False:
        return False
    until = T.parse_instant(r.values.get("@until")) if r.values.get("@until") else None
    until_ok = True if until is None or cutoff is None else T.at_or_before(cutoff, until)
    withdrawn = tri_or(*[view.effective_within(w, cutoff) for w, tg in acc.acts_targeting_triple(r.triple)
                         if w.action == "withdraw" and tg.support is None])
    return tri_and(eff, until_ok, None if withdrawn is None else not withdrawn)


def story_attention(view: View, st: Story, cutoff: Instant | None) -> str:
    """``ignored`` when an ignore act targeting the story Item or any of its detections is in
    effect, ``ambiguous`` when that depends on an unspecified order (9.5.2, 9.5.5-9.5.6)."""
    votes = [ignore_in_effect(view, r, cutoff) for r in story_acts(view.acc, st, ("ignore",))]
    if any(v is True for v in votes):
        return "ignored"
    if any(v is None for v in votes):
        return "ambiguous"
    return "attended"


def _side_now(view: View, side: Side, subject: str, prop: str, cutoff) -> tuple[str, Any]:
    acc = view.acc
    if side.kind == "statement":
        c = classify(View(acc, Frame(cutoff, None, LITERAL)), subject, side.source, prop, cutoff)
        if c.kind == "asserted":
            return "present", c.value
        if c.kind == "ambiguous":
            return "ambiguous", None
        return "absent", None
    rec = acc.get(side.exp)
    if rec is None:
        return "absent", None
    # 7.2.6(c), 7.6.13: an expectation side is fulfilled under the expectation's own interpretation
    e = Expectation(View(acc, Frame(cutoff, None, LITERAL)), rec, schedule=own_schedule(acc, rec))
    p = e.present_for(prop, cutoff)
    if p is True:
        return "present", rec.values.get(prop)
    if p is None:
        return "ambiguous", None
    return "absent", None


def disagreement_with(view: View, fam: Family, sched: Schedule, cutoff) -> tuple[str, tuple]:
    """9.5.2: the current comparison of a conflict story's sides at the cutoff, under ``sched``
    at the cutoff, and the normalizations that are the reason sides read ``aligned`` when they
    are equal only under an interpretation a normalization put in force (5.5.4)."""
    states = [_side_now(view, s, fam.subject, fam.prop, cutoff) for s in fam.sides]
    if any(s[0] == "ambiguous" for s in states):
        return "ambiguous", ()
    if all(s[0] == "present" for s in states):
        a, b = states[0][1], states[1][1]
        st = sched.at_cutoff(cutoff)
        if st.interp is not None:
            resolved = [st]
        else:
            resolved = [InForce(i, tuple(ns)) for i, ns in st.candidates]
        votes = {x.interp.equal(a, b, fam.prop) for x in resolved}
        if len(votes) != 1:
            return "ambiguous", ()
        if votes.pop():
            # 5.5.4: the normalizations that are the reason the sides match, where every
            # resolution gives the same (two expectations equal under both of their own
            # interpretations, 7.2.4)
            mbs = {tuple(r.triple for r in x.matched_by(a, b, fam.prop, literal_equal)): x for x in resolved}
            if len(mbs) == 1:
                x = next(iter(mbs.values()))
                return "aligned", x.matched_by(a, b, fam.prop, literal_equal)
            return "aligned", ()
        return "disagreeing", ()
    return "absent", ()


def disagreement(view: View, fam: Family, sched: Schedule | Interpretation, cutoff) -> str:
    if isinstance(sched, Interpretation):
        sched = Schedule.fixed(sched)
    return disagreement_with(view, fam, sched, cutoff)[0]


def story_unavailable_at(st: "Story", cutoff) -> str | None:
    """7.6.14: the name of the story's interpretation at the cutoff when the reference does
    not have it: the one in force, or, for two expectations, either side's own (7.2.4)."""
    if st.side_scheds is not None:
        return st.side_scheds[0].unavailable_at(cutoff) or st.side_scheds[1].unavailable_at(cutoff)
    return st.sched.unavailable_at(cutoff)


def comparison_schedule(acc: Account, st: "Story") -> Schedule:
    """How a story's sides are compared over event time in an account (7.2.4): the
    interpretation in force for its subject, or, for two expectations, each under its own."""
    if st.side_scheds is not None and st.sides:
        recs = (acc.get(st.sides[0].exp), acc.get(st.sides[1].exp))
        if recs[0] is not None and recs[1] is not None:
            return pair_schedule(own_schedule(acc, recs[0]), own_schedule(acc, recs[1]), recs)
    return subject_schedule(acc, st.subject)


def unavailable_object(name: str | None) -> dict:
    """README §5 *Unavailable interpretations*: the limitation that takes the place of a result
    that would have to be computed under an interpretation the reference does not have."""
    return {"limitation": "interpretation_unavailable", "interpretation": name}


def story_interpretation_members(st: "Story", cutoff) -> dict:
    """9.5.1, README §5 `story`: the story's interpretation at the cutoff (7.2.4). For a conflict
    story between two expectations whose own interpretations differ at the cutoff, the list of
    the two sides' names (``null`` for literal comparison) in side order, with as
    ``normalization`` that of the sides compared under the interpretation in force; otherwise
    as ``interpretation_members``."""
    if st.side_scheds is not None:
        sa, sb = (x.at_cutoff(cutoff) for x in st.side_scheds)
        if sa.interp_key != sb.interp_key:
            names = [x.interp.name if x.interp is not None else None for x in (sa, sb)]
            versions = [x.interp.version if x.interp is not None else None for x in (sa, sb)]
            in_force = [x for x, named in zip((sa, sb), st.side_named) if not named]
            if any(x.ambiguous for x in in_force):
                norm: Any = {"ambiguous": [compact(r.triple) for r in
                                           sorted_recs([r for x in in_force for r in x.records])]}
            else:
                norm = compact_or_list([r for x in in_force for r in x.norms])
            return {"interpretation": names, "interpretation_version": versions, "normalization": norm}
    return interpretation_members(st.cmp.at_cutoff(cutoff))


def interpretation_members(state: InForce) -> dict:
    """9.5.1, README §5 `story`: the story's interpretation at the cutoff and the
    normalization that put it in force, `null` when none applies, or `{"ambiguous": [refs]}`
    with the interpretation `null` where it is ambiguous (7.3.8)."""
    if state.ambiguous:
        return {"interpretation": None, "interpretation_version": None,
                "normalization": {"ambiguous": [compact(r.triple) for r in sorted_recs(state.records)]}}
    return {"interpretation": state.interp.name, "interpretation_version": state.interp.version,
            "normalization": compact_or_list(state.norms)}


@dataclass
class StoryEval:
    story: Story
    result: dict
    open: str  # open | ended | continued_in | not_started | ambiguous | limitation
    review: str
    varies: bool = False  # the derivation depends on an unspecified order or interpretation (7.6.6)


def _correction_for_story(acc: Account, st: Story) -> Rec | None:
    """The correction that removed the story's disagreement from the corrected account:
    the latest correction applying to its basis records or its sides' records."""
    cands = []
    for d in st.detections:
        for ref in ref_list(d.values, "@basis"):
            if is_assertion_ref(ref):
                t = ref_triple(ref)
                for c in acc.corrections_of.get(("A", t), []):
                    if c in acc.records:
                        cands.append(acc.records[c])
    if not cands and st.subject:
        for r in acc.rs.assertions:
            if r[0] == st.subject:
                for c in acc.corrections_of.get(("A", r), []):
                    if c in acc.records:
                        cands.append(acc.records[c])
    return latest_by_time(acc, cands)


def latest_by_time(acc: Account, recs: list[Rec]) -> Rec | None:
    """The latest of several records in presentation time, and, where several are latest at
    one instant, the first of them in identifier order (7.6.6)."""
    recs = [r for r in recs if r is not None]
    if not recs:
        return None
    top = max(acc.sort_key(r)[:2] for r in recs)
    return first_by_identifier([r for r in recs if acc.sort_key(r)[:2] == top])


def evaluate_story(view: View, st: Story, fam: Family | None, attention_filter: str | None = None) -> StoryEval:
    """A story's detections, acts, related stories, interval, ending and standing at the
    frame (9.5.1, 9.5.2). A story is always read under its own interpretation, the one in
    force for its subject (7.2.4); a frame that names another reports only whether the sides
    match under it (``match_under_read_interpretation``)."""
    acc = view.acc
    cutoff = view.cutoff
    acts = story_acts(acc, st, ("review", "reconcile", "correct"))
    state = st.cmp.at_cutoff(cutoff)
    res: dict[str, Any] = {
        "kind": st.kind,
        "detections": [compact(d.triple) for d in sorted(st.detections, key=lambda d: _det_time(acc, d))],
        "acts": [compact(a.triple) for a in acts],
        "related": related_stories(acc, st),
        **story_interpretation_members(st, cutoff),
    }
    if st.subject is not None:
        res["subject"] = st.subject
    own_keys = [("I", st.id)] + [("A", d.triple) for d in st.detections]
    unsupported = [compact(r.triple) for r in acc.unsupported
                   if any(parse_target(x).key in own_keys for x in act_targets(r.values))]
    if unsupported:
        res["unsupported"] = unsupported
    review, review_rec = _review_dimension(view, st, cutoff)
    standing: dict[str, Any] = {}
    if st.kind == "change":
        periods = change_periods(acc, st)
        if periods and isinstance(periods[0].begin, dict) and "limitation" in periods[0].begin:
            return StoryEval(st, {**limitation_members(periods[0].begin), **res}, "limitation", review)
        open_, ending, interval = _change_open(view, st, cutoff, review_rec)
        res["transitions"], res["transitions_from"] = _change_transitions(acc, st)
        # 7.2.7, 9.5.1: the corrections that now apply to the transitions' prior and new
        # Assertions; reads recompute the transitions, so no reconciliation is recorded
        tc, seen = [], set()
        for t in res["transitions"]:
            for ref in (t["prior"], t["new"]):
                if ref is None or ref in seen:
                    continue
                seen.add(ref)
                cs = acc.corrections_applying(("A", tuple(ref.split("|"))))
                if cs:
                    tc.append({"record": ref, "corrections": [compact(c) for c in cs]})
        if tc:
            res["transition_corrections"] = tc
        standing["open"] = open_
        standing["review"] = review
    else:
        if st.malformed or fam is None:
            return StoryEval(st, {"limitation": st.malformed or "story_unresolvable", **res}, "limitation", review)
        if fam.untimed:
            return StoryEval(st, {**limitation_members(untimed_content(fam.untimed)), **res}, "limitation", review)
        info = fam.info[st.id]
        open_, ending, interval = _conflict_open(acc, st, info, cutoff)
        standing["open"] = open_
        if info.continued_in:
            standing["continued_in"] = info.continued_in
        standing["review"] = review
        missing = story_unavailable_at(st, cutoff)
        if missing is not None:
            # 7.6.14: computed under an interpretation the reference does not have
            standing["disagreement"] = unavailable_object(missing)
        else:
            d, mb = disagreement_with(view, fam, st.cmp, cutoff)
            standing["disagreement"] = d
            if mb:
                standing["matched_by"] = compact_or_list(mb)
        if view.frame.named and (state.ambiguous or ikey(view.interp) != ikey(state.interp)):
            if view.frame.limitation is not None:
                # 5.5.4, 7.6.14: an unavailable interpretation is reported, never substituted
                res["match_under_read_interpretation"] = unavailable_object(view.interp.name)
            else:
                res["match_under_read_interpretation"] = disagreement(view, fam, view.interp, cutoff) == "aligned"
    if attention_filter:
        standing["attention"] = story_attention(view, st, cutoff)
    res["interval"] = interval
    res["ending"] = ending
    res["standing"] = standing
    return StoryEval(st, res, standing["open"], review, bool(fam is not None and fam.tied))


def evaluate_story_by_id(view: View, story_id: str, attention_filter: str | None = None,
                         cache: dict | None = None) -> StoryEval | None:
    """Evaluate a story in the view's own account, with its family recomputed there. ``cache``
    (keyed by account) avoids rebuilding a family's timelines for every cutoff."""
    a = view.acc
    entry = None
    if cache is not None:
        entry = cache.setdefault(id(a), (a, {}))[1]
    if entry is not None and story_id in entry:
        s, fam = entry[story_id]
    else:
        s = load_story(a, story_id)
        if s is None:
            return None
        fam = None
        if s.kind == "conflict" and not s.malformed:
            fams = families(a, all_stories(a, {s.subject}))
            fam = next((f for f in fams if s.id in f.by_id), None)
        if entry is not None:
            entry[story_id] = (s, fam)
    return evaluate_story(view, s, fam, attention_filter)


def participant_story_views(view: View, cache: dict | None = None) -> tuple[View, View]:
    """4.6.1, 7.5.3, 9.7.2: in a participant perspective a story's evidence is what had been
    distributed to the participant by the cutoff, interpreted at event time. A later
    distribution changes the participant's account as backfill does. The participant's
    account drops the statements (those carrying properties) and the communication-sourced
    acts not distributed by the cutoff; detections, reconciliations, corrections, acts
    recorded without a communication and expectations stay, as do the self-description,
    publication and distribution records that date and attribute the evidence. Records whose
    coverage at the cutoff is unspecified are dropped from one account (``strict``) and kept
    in the other (``lenient``), so that a result depending on them reads ambiguous (4.5.3).
    ``cache`` maps a set of dropped records to the account already built without them."""
    acc = view.acc
    strict_drop, lenient_drop = set(), set()
    for t, r in acc.records.items():
        if r.kind == "expectation":
            continue
        if r.is_act:
            if r.action in ("correct", "detect", "reconcile") or not view.is_communication_act(r):
                continue
        elif not any(not k.startswith("@") for k in r.values):
            continue
        seen = view.visible(r, view.cutoff)
        if seen is not True:
            strict_drop.add(t)
        if seen is False:
            lenient_drop.add(t)

    def build(drop: set) -> Account:
        key = frozenset(drop)
        if cache is not None and key in cache:
            return cache[key]
        rs = acc.rs.copy()
        for t in drop:
            rs.assertions.pop(t, None)
        a = Account(rs)
        if cache is not None:
            cache[key] = a
        return a

    return View(build(strict_drop), view.frame, view.excluded), View(build(lenient_drop), view.frame, view.excluded)


def merge_story_evals(a: StoryEval, b: StoryEval) -> StoryEval:
    """Combine a story's evaluations with and without the evidence whose distribution to the
    participant by the cutoff is unspecified: a dimension that differs reads ambiguous
    (4.5.3, 9.5.2), and differing intervals or endings are listed as candidates."""
    if a.result == b.result:
        return a
    res = dict(a.result)
    standing = dict(res.get("standing") or {})
    other = b.result.get("standing") or {}
    for k in set(standing) | set(other):
        if standing.get(k) != other.get(k):
            standing[k] = "ambiguous"
    if a.result.get("interval") != b.result.get("interval") or a.result.get("ending") != b.result.get("ending"):
        standing["open"] = "ambiguous"
        res["candidates"] = [{"interval": x.result.get("interval"), "ending": x.result.get("ending")} for x in (a, b)]
    res["standing"] = standing
    return StoryEval(a.story, res, standing.get("open", a.open), standing.get("review", a.review))


def not_yet_shown(participant_eval: StoryEval, record_eval: StoryEval | None) -> StoryEval:
    """4.6.1, 9.5.2: a story that disagrees in the record but whose disagreement a
    participant's account does not yet show reads ``not_started`` in that perspective, never
    ended (its account shows no interval yet)."""
    if record_eval is None:
        return participant_eval
    pi, ri = participant_eval.result.get("interval") or {}, record_eval.result.get("interval") or {}
    if not pi.get("empty") or ri.get("empty") or participant_eval.open == "limitation":
        return participant_eval
    res = dict(participant_eval.result)
    res["interval"] = {"start": None, "end": None}
    res["ending"] = None
    standing = dict(res.get("standing") or {})
    standing["open"] = "not_started"
    standing.pop("continued_in", None)
    res["standing"] = standing
    return StoryEval(participant_eval.story, res, "not_started", participant_eval.review)


def evaluate_story_in_view(view: View, story_id: str, attention_filter: str | None = None,
                           cache: dict | None = None) -> StoryEval | None:
    """A story's evaluation at a frame in any perspective (9.5.1, 9.7.2)."""
    if view.frame.perspective is None:
        return evaluate_story_by_id(view, story_id, attention_filter, cache)
    record_view = View(view.acc, Frame(view.cutoff, None, view.interp, view.frame.scope, view.frame.cutoff_input,
                                       view.frame.limitation, view.frame.named, view.frame.inforce,
                                       view.frame.literal))
    record_eval = evaluate_story_by_id(record_view, story_id, attention_filter, cache)
    acc_cache = None if cache is None else cache.setdefault(("accounts", id(view.acc)), {})
    strict, lenient = participant_story_views(view, acc_cache)
    a = evaluate_story_by_id(strict, story_id, attention_filter, cache)
    b = evaluate_story_by_id(lenient, story_id, attention_filter, cache)
    if a is None or b is None:
        return a or b
    return merge_story_evals(not_yet_shown(a, record_eval), not_yet_shown(b, record_eval))


def _ending_out(kind: str, recs, at: Instant | None, provenance: bool = False, matched=()) -> dict:
    """A story's <ending> (README §5): `record` one compact reference, or the list of them
    where several records at one instant caused the ending (7.6.6)."""
    if isinstance(recs, Rec):
        recs = [recs]
    out = {"kind": kind, "record": compact_or_list(recs or []), "at": at.text if at else None}
    if matched:
        out["matched_by"] = compact_or_list(matched)
    if provenance:
        out["at_is_provenance"] = True
    return out


def _conflict_open(acc: Account, st: Story, info: StoryInfo, cutoff) -> tuple[str, dict | None, dict]:
    empty = {"start": None, "end": None, "empty": True}
    if info.episode is None:
        state = "continued_in" if info.continued_in else "ended"
        if info.empty_reason == "normalization":
            # 7.2.6, 7.6.12: its sides were equal under the interpretation in force at the
            # instant its interval would begin under literal comparison; no ending time. Before
            # that instant (its `since`) nothing had begun
            since = info.literal_start
            r = True if cutoff is None or since is None else T.at_or_before(since, cutoff)
            if r is False or r is None:
                return ("not_started" if r is False else "ambiguous"), None, empty
            return state, _ending_out("normalization", info.empty_records, None), empty
        if info.empty_reason == "interpretation":
            # 7.6.12: the expectations' own interpretations alone make the sides equal; it reads
            # ended at every cutoff, with no ending time
            return state, _ending_out("interpretation", info.empty_records, None), empty
        corr = _correction_for_story(acc, st)
        ending = _ending_out("correction", [corr] if corr else [], acc.occurrence(corr) if corr else None,
                             provenance=True)
        return state, ending, empty
    start, end = info.start, info.end
    started = True if cutoff is None else T.at_or_before(start, cutoff)
    ended = False if end is None else (True if cutoff is None else T.at_or_before(end, cutoff))
    interval = {"start": start.text, "end": end.text if ended is True else None}
    ending = None
    if ended is True:
        ending = _ending_out(info.ending["kind"], info.ending["records"], info.ending["at"],
                             matched=info.ending.get("matched_by") or ())
        open_ = "ended"
    elif started is True:
        open_ = "open"
    elif started is False:
        open_ = "not_started"
    else:
        open_ = "ambiguous"
    if ended is None:
        open_ = "ambiguous"
    if info.tie is not None and cutoff is not None and (T.equal(info.tie, cutoff) or T.before(info.tie, cutoff) is None):
        open_ = "ambiguous"
    if info.continued_in and open_ in ("open", "ended"):
        open_ = "continued_in"
    return open_, ending, interval


def _change_transitions(acc: Account, st: Story) -> tuple[list[dict], str | None]:
    """A change story's transitions in the event-time account, compared under the
    interpretation in force at its revised Assertion's occurrence time (7.2.7)."""
    new, src, _trans = change_story_revision(acc, st)
    if new is None:
        return [], compact(src.triple)
    interp = _state_interp(change_interp(acc, st, new))
    out = []
    for t in revision_transitions(acc, new, interp):
        out.append({"property": t["property"], "transition": t["transition"],
                    "prior": compact(t["prior"]) if t["prior"] else None, "new": compact(t["new"])})
    return out, compact(src.triple)


def _change_open(view: View, st: Story, cutoff, review_rec: Rec | None) -> tuple[str, dict | None, dict]:
    """The open dimension, ending and interval of a change story at the cutoff, read from its
    periods (7.2.7, 7.6.2, 7.6.3)."""
    acc = view.acc
    periods = change_periods(acc, st)
    empty = {"start": None, "end": None, "empty": True}
    if not periods:
        return "ended", _ending_out("correction", [], None, True), empty
    if periods[0].begin is None:
        # 7.6.12: before a normalization ending's `since`, nothing had begun
        state = no_period_state(periods[0].end, cutoff)
        return state, (no_period_ending(acc, periods[0].end) if state == "ended" else None), empty
    return read_story_periods(acc, [(p.begin, p.end) for p in periods], cutoff)


def no_period_state(content: Any, cutoff) -> str:
    """7.6.12, 7.6.14: the open dimension of a story with no period, from its end content: ended
    at every cutoff, except that a `normalization` ending applies from its `since`, before which
    the story reads `not_started`; ambiguous where the cutoff and `since` are unordered."""
    variants = content_variants(content)
    states = set()
    for c in variants:
        since = T.parse_instant(c.get("since")) if isinstance(c, dict) and isinstance(c.get("since"), str) else None
        if since is None or cutoff is None:
            states.add("ended" if c is not None else "not_started")
            continue
        r = T.at_or_before(since, cutoff)
        states.add("ended" if r is True else ("not_started" if r is False else "ambiguous"))
    return states.pop() if len(states) == 1 else "ambiguous"


def no_period_ending(acc: Account, content: Any) -> dict | None:
    """The <ending> of a story with no period, from its end content (7.6.12, README §5): no
    ending time; for a correction, the correction's own time is reported as provenance, not an
    ending time (7.2.6, 7.2.7)."""
    out = ending_of(acc, content)
    if out is None:
        return None
    if content.get("cause") == "correction":
        recs = content_records(acc, content)
        rec = recs[0] if recs else None
        occ = acc.occurrence(rec) if rec is not None else None
        out["at"] = occ.text if occ is not None else None
        out["at_is_provenance"] = True
    return out


# ---------------------------------------------------------------------------------------
# periods (7.6.2) and how they are read at a cutoff (7.6.3, 7.6.14)


@dataclass
class DPeriod:
    """One derived period of a unit of work: the contents (7.6.6) its begin act and end acts
    carry. ``begin`` None is the 7.6.11/7.6.12 case of a story with no period. ``policy_ends``
    holds, for each implemented ending policy that governs the period at some instant (7.7.3),
    that policy's own ending of it; ``policy_end`` is the one of the policy governing the
    period's ending."""

    begin: Any
    end: Any = None
    policy_end: Any = None
    policy_ends: dict = field(default_factory=dict)


def instant_text(at: Instant) -> str:
    return at.text


def _refs(records) -> Any:
    """The `record` of a content: one exact reference, or the list of them where several
    records at one instant cause the transition, in identifier order (7.6.6)."""
    if records is None:
        return None
    if isinstance(records, Rec):
        return assertion_ref(records.triple)
    return ref_or_list(records)


def _rec_list(records) -> list:
    if records is None:
        return []
    if isinstance(records, Rec):
        return [records]
    return [r for r in records if r is not None]


def _at_content(at: Instant | None, body: dict, records: list) -> Any:
    """A definite content at an instant, or, at a milestone whose publication instants compete
    (4.4.1), the ambiguous content with one candidate per competing instant (7.6.6)."""
    if at is not None and at.precision == "competing":
        first, last = at.text.split("/", 1)
        return {"ambiguous": [dict(body, at=first), dict(body, at=last)],
                "records": [assertion_ref(r.triple) for r in records if r is not None]}
    return dict(body, at=at.text if at is not None else None)


def begin_content(at: Instant, records, cause: str, tied: list | None = None) -> Any:
    body: dict[str, Any] = {"record": _refs(records), "cause": cause}
    if tied:
        body["tied"] = [assertion_ref(r.triple) for r in sorted_recs(tied)]
    out = _at_content(at, body, _rec_list(records))
    return _order_content(out)


def end_content(at: Instant | None, records, cause: str, policy: dict | None = None,
                extra: dict | None = None, matched=()) -> Any:
    body: dict[str, Any] = {"record": _refs(records), "cause": cause}
    body.update(extra or {})
    if matched:
        body["matched_by"] = _refs(list(matched))
    body["policy"] = policy
    out = _at_content(at, body, _rec_list(records))
    if isinstance(out, dict) and "ambiguous" in out:
        out["policy"] = policy
    return _order_content(out)


_KEY_ORDER = ("ambiguous", "limitation", "at", "record", "records", "cause", "timeliness", "interpretation",
              "matched_by", "since", "tied", "policy")


def _order_content(c: Any) -> Any:
    if not isinstance(c, dict):
        return c
    out = {k: c[k] for k in _KEY_ORDER if k in c}
    out.update({k: v for k, v in c.items() if k not in out})
    if "ambiguous" in out:
        out["ambiguous"] = [_order_content(x) for x in out["ambiguous"]]
    return out


def content_records(acc: Account, content: Any) -> list[Rec]:
    """The records a content's `record` names, one or a list (7.6.6), as found in the account."""
    if not isinstance(content, dict):
        return []
    v = content.get("record")
    refs = [v] if is_assertion_ref(v) else ([x for x in v if is_assertion_ref(x)] if isinstance(v, list) else [])
    out = []
    for ref in refs:
        r = acc.get(ref_triple(ref)) or acc.records.get(ref_triple(ref))
        if r is not None:
            out.append(r)
    return out


def content_variants(content: Any) -> list:
    """The definite contents (or None) a content stands for (7.6.6)."""
    if isinstance(content, dict) and "ambiguous" in content:
        return list(content["ambiguous"]) or [None]
    return [content]


def _parse_at(c: dict | None) -> Instant | None:
    if not isinstance(c, dict) or not isinstance(c.get("at"), str):
        return None
    return T.parse_instant(c["at"])


def _definite_state(begin: dict | None, end: dict | None, cutoff) -> str:
    """One period's open dimension at the cutoff (7.6.3), for definite contents. The same
    three-valued reading as the derivation: a transition whose relation to the cutoff is
    unspecified makes the dimension ambiguous, and so does a beginning tied with another
    record at the cutoff's instant (7.3.6, 7.6.6)."""
    start = _parse_at(begin)
    if start is None:
        return "not_started"
    finish = _parse_at(end)
    started = True if cutoff is None else T.at_or_before(start, cutoff)
    ended = False if finish is None else (True if cutoff is None else T.at_or_before(finish, cutoff))
    if ended is True:
        state = "ended"
    elif started is True:
        state = "open"
    elif started is False:
        state = "not_started"
    else:
        state = "ambiguous"
    if ended is None:
        state = "ambiguous"
    if begin.get("tied") and cutoff is not None and (T.equal(start, cutoff) or T.before(start, cutoff) is None):
        state = "ambiguous"
    return state


def _consistent(bv: Any, ev: Any) -> bool:
    timed = isinstance(ev, dict) and isinstance(ev.get("at"), str)
    untimed = isinstance(ev, dict) and "at" in ev and ev.get("at") is None
    return not timed if bv is None else not untimed


def periods_state(periods: list[tuple], cutoff) -> tuple[str, int | None]:
    """The open dimension of a unit read from its periods at the cutoff, and the index of the
    period it was read from: the latest period that began at or before the cutoff (7.6.3,
    7.6.14). A content that is ambiguous is read under each candidate, and the dimension is
    ambiguous unless they agree (7.6.6); a limitation content makes it a limitation."""
    states = []
    for b, e in periods:
        if any(isinstance(c, dict) and "limitation" in c for c in (b, e)):
            states.append("limitation")
            continue
        combos = [(bv, ev) for bv in content_variants(b) for ev in content_variants(e)]
        # 7.6.6, 7.6.12: under a candidate in which the story has no period (a null beginning),
        # its ending is the no-period ending (`at` null) or none; under one in which it has a
        # period, its ending is timed or none. The other combinations describe no derivation
        # and are not evaluated
        consistent = [(bv, ev) for bv, ev in combos if _consistent(bv, ev)]
        found = {(_definite_state(bv, ev, cutoff) if bv is not None or ev is None else no_period_state(ev, cutoff))
                 for bv, ev in (consistent or combos)}
        states.append(found.pop() if len(found) == 1 else "ambiguous")
    idx = None
    for i, st in enumerate(states):
        if st != "not_started":
            idx = i
    if idx is None:
        return "not_started", None
    return states[idx], idx


def _refs_compact(v: Any) -> Any:
    if is_assertion_ref(v):
        return compact(ref_triple(v))
    if isinstance(v, list):
        return [compact(ref_triple(x)) if is_assertion_ref(x) else x for x in v]
    return None


def ending_of(acc: Account, content: Any) -> dict | None:
    """A story's <ending> from a definite end content (README §5). An ambiguous content gives
    the ambiguous form, each candidate an <ending> or `null`, with the records concerned."""
    if isinstance(content, dict) and "ambiguous" in content:
        return {"ambiguous": [ending_of(acc, c) for c in content["ambiguous"]],
                "records": [_refs_compact(r) for r in content.get("records") or []]}
    if not isinstance(content, dict) or "cause" not in content:
        return None
    out = {"kind": content["cause"], "record": _refs_compact(content.get("record")), "at": content.get("at")}
    if content.get("matched_by") is not None:
        out["matched_by"] = _refs_compact(content["matched_by"])
    return out


def read_story_periods(acc: Account, periods: list[tuple], cutoff) -> tuple[str, dict | None, dict]:
    """(open, ending, interval) of a story with at least one period, from its begin and end
    contents (7.6.14). The interval is that of 7.2.4: it starts at the first period's
    beginning and ends at the ending of the period the open dimension is read from."""
    state, idx = periods_state(periods, cutoff)
    first = periods[0][0]
    start = first.get("at") if isinstance(first, dict) else None
    ending = None
    if state == "ended" and idx is not None:
        ending = ending_of(acc, periods[idx][1])
    return state, ending, {"start": start, "end": ending.get("at") if ending else None}


def _change_correction(acc: Account, recorded: list[dict]) -> Rec | None:
    """The correction that leaves a change story's revision changing no property: the latest
    correction of the prior or new Assertions its transitions name (7.2.7, 7.6.6)."""
    cands = []
    for t in recorded:
        for k in ("new", "prior"):
            v = t.get(k)
            if isinstance(v, tuple):
                v = assertion_ref(v)
            if is_assertion_ref(v):
                for c in acc.corrections_of.get(("A", ref_triple(v)), []):
                    if c in acc.records:
                        cands.append(acc.records[c])
    return latest_by_time(acc, cands)


def conflict_periods(acc: Account, st: Story, fam: Family | None) -> list[DPeriod] | None:
    """The period of a conflict story: its interval (7.2.4, 7.2.6, 7.6.2). A story that a
    `continuous` reconciliation continues in another has no period of its own (7.6.11); a
    story whose interval is empty has none either, and its ending is recorded on a begin act
    whose content is null (7.6.12). None when the Item's detections do not form one
    conflict story (7.6.1)."""
    if st.malformed or fam is None or st.id not in fam.info:
        return None
    if fam.untimed:
        return [DPeriod(untimed_content(fam.untimed))]
    info = fam.info[st.id]
    if info.continued_in:
        return [DPeriod(None)]
    if info.episode is None:
        if info.empty_reason == "normalization":
            # 7.6.12: `since` is the instant at which its interval would begin under literal
            # comparison
            since = {"since": info.literal_start.text} if info.literal_start is not None else None
            return [DPeriod(None, end_content(None, info.empty_records, "normalization", extra=since))]
        if info.empty_reason == "interpretation":
            return [DPeriod(None, end_content(None, info.empty_records, "interpretation"))]
        corr = _correction_for_story(acc, st)
        return [DPeriod(None, end_content(None, corr, "correction"))]
    begin = begin_content(info.start, info.start_records, "disagreement", info.tied_with)
    end = None
    if info.ending is not None:
        end = end_content(info.ending["at"], info.ending["records"], info.ending["kind"],
                          matched=info.ending.get("matched_by") or ())
    return [DPeriod(begin, end)]


def untimed_content(recs: list[Rec]) -> dict:
    """7.6.6: the limitation content of a transition that depends on statements with no
    occurrence time (4.2.4)."""
    return {"limitation": "no_occurrence_time", "records": [assertion_ref(r.triple) for r in recs]}


def limitation_members(content: dict) -> dict:
    """A limitation content as a read reports it: the code and its members, references in
    compact form (README §5 *Limitations*)."""
    out = {"limitation": content.get("limitation")}
    if isinstance(content.get("records"), list):
        out["records"] = [compact(ref_triple(r)) if is_assertion_ref(r) else r for r in content["records"]]
    if "interpretation" in content:
        out["interpretation"] = content["interpretation"]
    return out


def _change_correction_governs(acc: Account, st: Story, interp: Interpretation) -> bool:
    """7.6.12: `correction` comes before `normalization` where, without the corrections, the
    change story's revision would change a property under its interpretation."""
    raw = Account(acc.rs, apply_corrections=False)
    alt = load_story(raw, st.id)
    if alt is None:
        return False
    new, _src, _rec = change_story_revision(raw, alt)
    return new is not None and bool(revision_transitions(raw, new, interp))


def change_periods(acc: Account, st: Story, sched: Schedule | None = None) -> list[DPeriod] | None:
    """The periods of a change story (7.6.2). The first begins at the revised Assertion's
    occurrence time. A period ends at the earliest instant, at or after its beginning, at
    which a review that targets the story is in effect and not withdrawn, or, if earlier, at
    the instant from which the interpretation in force leaves the revision changing no
    property, which ends the story for good (7.2.7, 7.3.8). Once a period has ended by
    review, the next begins at the effective time of the first withdrawal of a review that
    leaves no review of the story in effect, unless the interpretation in force then leaves
    the revision changing no property; no period begins while another review remains in
    effect (7.2.7, 6.7.9). A revision that a correction, backfilled evidence (7.3.7) or the
    interpretation in force at its occurrence time leaves changing no property has no period
    (7.6.12), the first of those that applies governing. None when the Item's detections do
    not form one change story (7.6.1). ``sched`` is one resolution of the story's
    interpretation over time (normalization.Schedule.resolutions)."""
    sched = sched or st.sched
    new, _src, recorded = change_story_revision(acc, st)
    if new is None:
        corr = _change_correction(acc, recorded or _transitions_of(st.first))
        return [DPeriod(None, end_content(None, corr, "correction"))] if corr is not None else None
    if not revision_transitions(acc, new):
        backfilled = reconstructed_no_change(acc, st)
        if backfilled is not None:
            # 7.3.7, 7.6.12: the backfilled Assertion is the ending record; the ending has no time
            return [DPeriod(None, end_content(None, backfilled, "reconstructed"))]
        listed = recorded or _transitions_of(st.first)
        if listed:
            corr = _change_correction(acc, listed)
            if corr is not None:
                return [DPeriod(None, end_content(None, corr, "correction"))]
    s0 = acc.occurrence(new)
    if s0 is None:
        return [DPeriod({"limitation": "no_occurrence_time", "records": [assertion_ref(new.triple)]})]
    begin_at, begin_recs, cause = s0, [new], "revision"
    pred = same_revision_predecessor(acc, st)
    if pred is not None:
        # 7.3.8 *After it*, 7.6.2, 7.6.4: a related change story of 7.3.8 begins at the instant
        # from which a change of the interpretation in force makes the revision change a
        # property again, its beginning citing the normalization
        rs = reversal_start(acc, pred, new, sched)
        if rs is None:
            return _premise_gone(acc, st, new)
        begin_at, begin_recs = rs
        s0 = begin_at
    else:
        st0 = sched.at(s0)
        i0 = _state_interp(st0)
        if i0.name is not None and revision_transitions(acc, new) and not revision_transitions(acc, new, i0):
            # 7.2.7, 7.6.12: the revision changes a property literally and none under the
            # interpretation in force at its occurrence time; it reads not_started before then
            corr = _change_correction(acc, revision_transitions(acc, new))
            if corr is not None and _change_correction_governs(acc, st, i0):
                return [DPeriod(None, end_content(None, corr, "correction"))]
            return [DPeriod(None, end_content(None, list(st0.norms), "normalization", extra={"since": s0.text}))]

    def no_change(t: Instant) -> bool:
        return not revision_transitions(acc, new, _state_interp(sched.at(t)))

    norm_points = [(t, stt) for t, stt in sched.changes() if _k(t) > _k(s0)]
    # each review's span in effect: from its effective time until its first withdrawal takes
    # effect (6.7.5, 6.7.9); a review withdrawn by then is never in effect
    reviews = []
    for r in story_acts(acc, st, ("review",)):
        e = acc.effective(r)
        if e is None:
            continue
        ws = [(acc.effective(w), w) for w, tg in acc.acts_targeting_triple(r.triple)
              if w.action == "withdraw" and tg.support is None]
        ws = [(we, w) for we, w in ws if we is not None]
        wend = min(ws, key=lambda x: (_k(x[0]), x[1].triple)) if ws else None
        reviews.append((e, r, wend))
    periods: list[DPeriod] = []
    for _ in range(len(reviews) + 1):
        begin = begin_content(begin_at, begin_recs, cause)
        cands = []
        for e, r, wend in reviews:
            t = e if _k(e) >= _k(begin_at) else begin_at
            if wend is not None and _k(wend[0]) <= _k(t):
                continue
            cands.append((t, r, wend, e))
        review_end = None
        if cands:
            first = min(_k(c[0]) for c in cands)
            at_first = [c for c in cands if _k(c[0]) == first]
            effs = {_k(c[3]) for c in at_first}
            recs = [c[1] for c in at_first] if len(effs) == 1 else [min(at_first, key=lambda c: c[1].triple)[1]]
            review_end = (at_first[0][0], sorted_recs(recs))
        norm_end = None
        prev_norms: tuple = sched.at(s0).norms
        for t, stt in norm_points:
            if _k(t) <= _k(begin_at):
                prev_norms = stt.norms or prev_norms
                continue
            if no_change(t):
                norm_end = (t, list(stt.norms) or list(prev_norms))
                break
            prev_norms = stt.norms or prev_norms
        if norm_end is not None and (review_end is None or _k(norm_end[0]) < _k(review_end[0])):
            # 7.2.7, 7.3.8: a period so ended is the story's last
            periods.append(DPeriod(begin, end_content(norm_end[0], norm_end[1], "normalization")))
            break
        if review_end is None:
            periods.append(DPeriod(begin))
            break
        t, recs = review_end
        periods.append(DPeriod(begin, end_content(t, recs, "review")))
        reopened = _no_review_left(reviews, t)
        if reopened is None:
            break
        if no_change(reopened[0]):
            # 7.6.2: where the interpretation in force at the withdrawal's effective time leaves
            # the revision changing no property, the period that begins then also ends then, with
            # the normalization that put that interpretation in force as its ending record. It
            # has no length, is never open and is the story's last
            w_at, w_recs = reopened
            norms = list(sched.at(w_at).norms) or list(prev_norms)
            periods.append(DPeriod(begin_content(w_at, w_recs, "review_withdrawn"),
                                   end_content(w_at, norms, "normalization")))
            break
        begin_at, begin_recs, cause = reopened[0], reopened[1], "review_withdrawn"
    return periods


def _premise_gone(acc: Account, st: Story, new: Rec) -> list[DPeriod] | None:
    """A related change story of 7.3.8 whose premise a later write removed: no change of the
    interpretation in force makes its revision change again after a normalization closed its
    predecessor. Where a correction removed it, the story has no period, with that correction
    as its ending (7.6.12). The specification gives no ending for the other writes that can
    remove it (a backfilled review of the predecessor, a tied normalization); the story then
    cannot be evaluated (None: reads report it among their limitations)."""
    corrections = sorted((r for r in acc.records.values() if r.action == "correct"), key=acc.sort_key, reverse=True)
    for c in corrections:
        alt_acc = Account(acc.rs.without(c.triple))
        alt = load_story(alt_acc, st.id)
        if alt is None:
            continue
        pred = same_revision_predecessor(alt_acc, alt)
        anew = change_story_revision(alt_acc, alt)[0]
        if pred is not None and anew is not None and reversal_start(alt_acc, pred, anew, alt.sched) is not None:
            return [DPeriod(None, end_content(None, c, "correction"))]
    return None


def _no_review_left(reviews: list[tuple], t: Instant) -> tuple[Instant, list[Rec]] | None:
    """7.6.2: the first instant after ``t`` at which no review of the story is in effect,
    with the withdrawals whose taking effect left none (all of them at that instant, 7.6.6);
    None when a review stays in effect for good. A review that takes effect at the instant
    another is withdrawn is in effect then, so no period begins."""
    until = t
    while True:
        spans = [wend for e, _r, wend in reviews
                 if _k(e) <= _k(until) and (wend is None or _k(wend[0]) > _k(until))]
        if not spans:
            break
        if any(w is None for w in spans):
            return None
        until = max((w[0] for w in spans), key=_k)
    if _k(until) == _k(t):
        return None
    left = [w for e, _r, w in reviews if w is not None and _k(w[0]) == _k(until) and _k(e) < _k(until)]
    return until, sorted_recs([w[1] for w in left])


def _story_of_act(acc: Account, act: Rec) -> Story | None:
    """The story whose question a detection, review or reconciliation recorded: a detection's
    own story, or the story an act targets through its Item or any of its detections."""
    if act.action == "detect":
        return load_story(acc, act.item)
    for ref in act_targets(act.values):
        tg = parse_target(ref)
        if tg.kind == "item" and acc.is_story(tg.item):
            return load_story(acc, tg.item)
        if tg.kind == "assertion":
            d = acc.get(tg.triple)
            if d is not None and d.action == "detect":
                return load_story(acc, d.item)
    return None


def act_event_time(acc: Account, act: Rec) -> dict | None:
    """9.8.1: for a detection, review or reconciliation, the applicable Assertions of the
    question it recorded, in the current event-time account at its ``@frame`` cutoff (for a
    conflict story, its two sides; for a change story, the revision's prior and new
    Assertions), and whether they differ from the Assertions the act cited (its ``@basis``,
    and the prior and new Assertions of its ``@transitions``) that bear on that question.
    The act's own recorded basis and frame are unchanged (7.5.1, 7.5.2)."""
    if act.action not in ("detect", "review", "reconcile"):
        return None
    if act.action == "reconcile":
        # README §5 `exact`: absent for a `revise` (7.6.10) and for a reconciliation that
        # targets an expectation (7.6.13, 7.7.3); neither records a story's question
        if act.values.get("@outcome") == "revise":
            return None
        for ref in act_targets(act.values):
            if is_assertion_ref(ref):
                t = acc.get(ref_triple(ref))
                if t is not None and t.kind == "expectation":
                    return None
    st = _story_of_act(acc, act)
    frame = act.values.get("@frame") if isinstance(act.values.get("@frame"), dict) else {}
    cut = frame.get("cutoff")
    at = None
    if isinstance(cut, str) and cut != "now":
        at = T.parse_instant(cut)
    elif is_item_ref(cut):
        pub, issue = acc.publication_instant(cut["id"])
        at = pub if issue is None else None
    if at is None:
        at = acc.occurrence(act)  # no resolvable recorded cutoff: the act's own time
    persp = frame.get("perspective")
    persp = persp["id"] if is_item_ref(persp) else None
    cited = set()
    for key in ("@basis", "@transitions"):
        for ref in ref_list(act.values, key) if key == "@basis" else \
                [x.get(k) for x in (act.values.get(key) or []) if isinstance(x, dict) for k in ("prior", "new")]:
            if is_assertion_ref(ref):
                cited.add(ref_triple(ref))
    records: set = set()
    relevant = lambda t: False  # noqa: E731
    if st is not None and st.kind == "conflict" and st.sides and not st.malformed:
        view = View(acc, Frame(at, persp, LITERAL))
        for side in st.sides:
            if side.kind == "statement":
                c = classify(view, st.subject, side.source, st.prop, at)
                if c.kind == "asserted":
                    records.add(c.origin.triple)
            elif acc.get(side.exp) is not None:
                records.add(side.exp)
        sources = {s.source for s in st.sides if s.kind == "statement"}
        exps = {s.exp for s in st.sides if s.kind == "expectation"}
        relevant = lambda t: (t[0] == st.subject and t[2] in sources) or t in exps  # noqa: E731
    elif st is not None and st.kind == "change":
        new, _src, _recorded = change_story_revision(acc, st)
        if new is not None:
            records.add(new.triple)
            interp = _state_interp(change_interp(acc, st, new))
            records |= {t["prior"] for t in revision_transitions(acc, new, interp) if t["prior"]}
            relevant = lambda t: t[0] == new.item and t[2] == new.source  # noqa: E731
    cited = {t for t in cited if relevant(t)}
    return {"cutoff": at.text if at is not None else None,
            "records": sorted(compact(t) for t in records),
            "differs": records != cited}


def related_stories(acc: Account, st: Story) -> list[str]:
    """Stories linked to this one by ``@relates_to`` in either direction, and the stories a
    reconciliation of it names (7.3)."""
    rel: set[str] = set()
    if st.relates_to:
        rel.add(st.relates_to)
    det_triples = {d.triple for d in st.detections}
    for sid, dets in acc.detections_of.items():
        if sid == st.id:
            continue
        for d in dets:
            r = d.values.get("@relates_to")
            if is_assertion_ref(r) and (ref_triple(r) in det_triples or ref_triple(r)[0] == st.id):
                rel.add(sid)
    for r in story_acts(acc, st, ("reconcile",)):
        for key in ("@successor", "@representative"):
            v = r.values.get(key)
            if is_item_ref(v) and v["id"] != st.id:
                rel.add(v["id"])
        for t in act_targets(r.values):
            if is_assertion_ref(t) and t["item"] != st.id and acc.is_story(t["item"]):
                rel.add(t["item"])
    return sorted(rel)


# ---------------------------------------------------------------------------------------
# maintenance (7.2.8)


@dataclass
class Generated:
    """A record that maintenance requires: an Item for a new story or reconciliation (if
    any), an event context, and the act Assertion itself (README §7)."""

    items: list[tuple[str, str, dict]]  # (id, kind, definition)
    triple: Triple
    values: dict
    reason: str
    follow: "Generated | None" = None  # a record that must be written together with this one


class Namer:
    """Deterministic names for generated records (README §7). ``when`` is the time of a
    triggering write that is not an Assertion with an occurrence of its own, such as a
    Connection operation (README §7: its `at`), which the generated contexts then take."""

    def __init__(self, exists, when: Instant | None = None) -> None:
        self.exists = exists
        self.when = when
        self.trigger_time: Instant | None = None  # the occurrence time of the triggering record

    def time_for(self, acc: Account, state: "EvidenceState") -> Instant | None:
        """README §7: a generated record's context is at the occurrence time of the triggering
        record. Where the evidence state was caused by the record that changed it, that record's
        time; where only the interpretation in force changed (7.3.8), the write's own time."""
        if self.when is not None:
            return self.when
        if (state.cause is None or state.cause.action == "reinterpret") and self.trigger_time is not None:
            return self.trigger_time
        return _trigger_time(acc, state.cause, state.at)

    def detection_context(self, st: Story) -> str:
        n = len(st.detections) + 1
        while self.exists(f"{st.id}/d{n}"):
            n += 1
        return f"{st.id}/d{n}"

    def related_story(self, prior: str) -> str:
        n = 1
        while self.exists(f"{prior}+{n}"):
            n += 1
        return f"{prior}+{n}"

    def reconciliation(self, target: str) -> str:
        n = 1
        while self.exists(f"{target}/r{n}"):
            n += 1
        return f"{target}/r{n}"


def _instant_text(at: Instant | None) -> str | None:
    """A generated record's time as a 4.2.1 instant. A trigger at a milestone with competing
    publication instants (4.4.1) has no single occurrence time; a generated record's own time
    is provenance, never a boundary (8.4.1), so it takes the later competing instant, by which
    the trigger had occurred under either."""
    if at is None:
        return None
    return at.text.split("/", 1)[1] if at.precision == "competing" else at.text


def _frame_of(st: Story, at: Instant | None, interp: Interpretation | None = None) -> dict:
    """A generated record's @frame (README §7): the interpretation in force for the story's
    subject at the context's `at` (7.2.4, 7.3.8), `null` and `null` for literal comparison;
    where it is ambiguous, `null` and `null` with `normalization: {"ambiguous": [refs]}` (5.5.5).
    When the policy governing the story then is not the baseline, it also names that policy
    (7.7.2); under the baseline the keys are absent."""
    ambiguous = None
    if interp is None:
        state = st.sched.at(at)
        interp = state.interp if state.interp is not None else LITERAL
        if state.ambiguous:
            # 5.5.5: under an ambiguous interpretation in force, the normalizations concerned, so
            # that the frame is never read as literal comparison
            ambiguous = {"ambiguous": [assertion_ref(r.triple) for r in sorted_recs(state.records)]}
    out = {"scope": st.frame_scope, "cutoff": _instant_text(at), "perspective": "record",
           "interpretation": interp.name, "interpretation_version": interp.version}
    if ambiguous is not None:
        out["normalization"] = ambiguous
    policy = st.policy_at(at)
    if isinstance(policy, dict):
        # an ambiguous governing policy (7.7.2) has no @frame form; the keys are then absent
        out["policy"] = policy["name"]
        out["policy_version"] = policy["version"]
    return out


def _basis_refs(fam: Family, state: EvidenceState) -> list[dict]:
    refs = []
    for rec in state.records:
        if rec is not None:
            refs.append(assertion_ref(rec.triple, fam.prop))
    return refs


def _event_ctx(ctx_id: str, at: Instant | None) -> tuple[str, str, dict]:
    return (ctx_id, "event", {"@context": {"role": "event", "at": _instant_text(at)}})


def _trigger_time(acc: Account, rec: Rec | None, fallback: Instant | None) -> Instant | None:
    if rec is not None:
        t = acc.occurrence(rec)
        if t is not None:
            return t
    return fallback


def gen_continuation(acc: Account, fam: Family, st: Story, state: EvidenceState, namer: Namer) -> Generated:
    at = namer.time_for(acc, state)
    ctx = namer.detection_context(st)
    values = {"@action": "detect", "@story": st.first.values["@story"], "@basis": _basis_refs(fam, state),
              "@frame": _frame_of(st, at)}
    return Generated([_event_ctx(ctx, at)], (st.id, ctx, st.id), values, "continuation (7.2.5)")


def gen_related(acc: Account, fam: Family, prior: Story, state: EvidenceState, namer: Namer,
                kind_of_item: str, reason: str, new_id: str | None = None) -> Generated:
    at = namer.time_for(acc, state)
    sid = new_id or namer.related_story(prior.id)
    ctx = f"{sid}/d1"
    values = {"@action": "detect", "@story": prior.first.values["@story"], "@basis": _basis_refs(fam, state),
              "@frame": _frame_of(prior, at), "@relates_to": assertion_ref(prior.first.triple)}
    return Generated([(sid, kind_of_item, {}), _event_ctx(ctx, at)], (sid, ctx, sid), values, reason)


def gen_reconciliation(acc: Account, target: Story, outcome: str, targets: list[Rec], basis: list[Rec],
                       at: Instant | None, namer: Namer, extra: dict | None = None,
                       interp: Interpretation | None = None) -> Generated:
    rid = namer.reconciliation(target.id)
    ctx = f"{rid}/at"
    values = {"@action": "reconcile", "@targets": [assertion_ref(t.triple) for t in targets], "@outcome": outcome,
              "@basis": [assertion_ref(b.triple) for b in basis if b is not None], "@frame": _frame_of(target, at, interp)}
    values.update(extra or {})
    return Generated([(rid, "reconciliation", {}), _event_ctx(ctx, at)], (rid, ctx, rid), values,
                     f"{outcome} reconciliation")


def plan_conflict_family(acc: Account, fam: Family, namer: Namer, trigger: Rec | None,
                         before: dict[str, tuple] | None) -> Generated | None:
    """The first record the family's event-time account requires (7.2.5, 7.3.1-7.3.4)."""
    tl = fam.timeline()
    by_ep: dict[int, list[Story]] = {}
    for st in fam.stories:
        ep = fam.info[st.id].episode
        if ep is not None:
            by_ep.setdefault(id(ep), []).append(st)
    current: Story | None = None
    begun = False
    anchors = [a for a in (_first_anchor(acc, s) for s in fam.stories) if a is not None]
    earliest = min(anchors, key=_k) if anchors else None
    for ep in tl.episodes:
        mapped = by_ep.get(id(ep), [])
        if not begun:
            if not mapped and (earliest is None or _k(earliest) > _k(ep.start)):
                continue
            begun = True
        if not mapped:
            # 7.3.2 / 7.3.3: a later disagreement with no story is a new related story;
            # when a recorded story had been believed to span it, a split is recorded first.
            splitter = _splitter(acc, fam, ep, before)
            prior = current or fam.stories[-1]
            if splitter is not None:
                sid = namer.related_story(splitter.id)
                at = _trigger_time(acc, trigger, ep.start)
                split = gen_reconciliation(acc, splitter, "split", [splitter.first],
                                           list(fam.info[splitter.id].episode.end_records)
                                           if fam.info[splitter.id].episode else [],
                                           at, namer, {"@successor": item_ref(sid)})
                split.follow = gen_related(acc, fam, splitter, ep.states[0], namer, splitter_kind(acc, splitter),
                                           "split successor (7.3.3)", new_id=sid)
                return split
            return gen_related(acc, fam, prior, ep.states[0], namer, splitter_kind(acc, prior),
                               "related story after an ending (7.3.2)")
        primaries = [s for s in mapped if not _review_related(acc, fam, s, ep)]
        joined = [s for s in primaries if fam.info[s.id].continued_in is None]
        if len(joined) > 1 and _apparent_ending_between(joined, before):
            if all(not story_acts(acc, s, ("review",)) for s in joined):
                rep = sorted(joined, key=lambda s: (_k(_first_anchor(acc, s)), s.id))[0]
                at = _trigger_time(acc, trigger, ep.start)
                return gen_reconciliation(acc, rep, "continuous", [s.first for s in sorted(joined, key=lambda s: s.id)],
                                          [trigger] if trigger else [], at, namer,
                                          {"@representative": item_ref(rep.id)})
        current = _representative(fam, primaries) if primaries else mapped[0]
        g = _walk_episode(acc, fam, ep, current, mapped, namer, trigger)
        if g is not None:
            return g
        current = _chain_end(acc, fam, current, mapped)
    return None


def _apparent_ending_between(stories: list[Story], before: dict[str, tuple] | None) -> bool:
    """7.3.4: stories of one episode are joined only when, before the write, an apparent
    ending separated two of them: one had ended no later than the other began. Stories
    recorded for one disagreement with no ending between them, such as a second story
    citing the same evidence, are not joined; open stories lists them as tied (9.5.3)."""
    if not before:
        return False
    spans = [before[s.id][:2] for s in stories if s.id in before]
    for s1, e1 in spans:
        for s2, _e2 in spans:
            if e1 is not None and s2 is not None and _k(e1) <= _k(s2):
                return True
    return False


def splitter_kind(acc: Account, st: Story) -> str:
    it = acc.item(st.id)
    return it.kind if it else "story"


def _representative(fam: Family, primaries: list[Story]) -> Story:
    for s in primaries:
        if fam.info[s.id].continued_in is None:
            return s
    return primaries[0]


def _review_related(acc: Account, fam: Family, st: Story, ep: Episode) -> bool:
    pred = fam.by_id.get(st.relates_to) if st.relates_to else None
    if pred is None or fam.info[pred.id].episode is not ep:
        return False
    return bool(story_acts(acc, pred, ("review",)))


def _successor_in(acc: Account, fam: Family, st: Story, mapped: list[Story]) -> Story | None:
    for s in mapped:
        if s.relates_to == st.id and s is not st:
            return s
    return None


def _chain_end(acc: Account, fam: Family, st: Story, mapped: list[Story]) -> Story:
    seen = {st.id}
    while True:
        nxt = _successor_in(acc, fam, st, mapped)
        if nxt is None or nxt.id in seen:
            return st
        seen.add(nxt.id)
        st = nxt


def _has_detection_for(fam: Family, st: Story, state: EvidenceState) -> bool:
    want = {r.triple for r in state.records if r is not None}
    for d in st.detections:
        got = {ref_triple(x) for x in ref_list(d.values, "@basis") if is_assertion_ref(x)}
        if want <= got:
            return True
    return False


def _walk_episode(acc: Account, fam: Family, ep: Episode, start_story: Story, mapped: list[Story],
                  namer: Namer, trigger: Rec | None) -> Generated | None:
    """Within one episode:

    * evidence that the write changed continues an unreviewed story with a new detection
      (7.2.5), unless the change occurred before the story was first recorded (7.2.8); a
      correction is not a new issuance and continues nothing (7.2.6);
    * once a story has a review that has not been withdrawn, changed evidence does not
      continue it: where the current comparison evidence differs from what the review cited,
      a related story is opened (7.3.1, 7.3.5), including for evidence backfilled before the
      review's effective time, whose related story begins at that time.
    """
    chain = start_story
    first_anchor = _first_anchor(acc, chain)
    checkpoints = [(s.at, "change", s) for s in ep.states[1:]]
    for st in mapped:
        for r in story_acts(acc, st, ("review",)):
            e = acc.effective(r)
            if e is not None and ep.contains(e):
                checkpoints.append((e, "review", (st.id, r)))
    checkpoints.sort(key=lambda x: (_k(x[0]), 0 if x[1] == "change" else 1))
    for at, kind, obj in checkpoints:
        if kind == "review" and obj[0] != chain.id:
            continue
        if kind == "change" and first_anchor is not None and _k(at) <= _k(first_anchor):
            continue
        state = obj if kind == "change" else _state_at(ep, at)
        if state is None:
            continue
        review = review_in_effect_linear(acc, chain, at)
        if review is not None:
            cited = cited_values(acc, fam, chain, review)
            # 7.2.4: changed evidence is judged under the story's interpretation at that instant
            interp = _state_interp(fam.sched.at(state.at))
            if cited is not None and not all(interp.equal(state.values[i], cited[i], fam.prop) for i in range(2)):
                succ = _successor_in(acc, fam, chain, mapped)
                if succ is None:
                    return gen_related(acc, fam, chain, state, namer, splitter_kind(acc, chain),
                                       "related story after review (7.3.1)")
                chain = succ
                first_anchor = _first_anchor(acc, chain)
                if kind == "change" and _caused_by(state, trigger) and not _has_detection_for(fam, chain, state) \
                        and first_anchor is not None and _k(state.at) > _k(first_anchor) \
                        and not _before_first_recorded(acc, chain, state.at):
                    return gen_continuation(acc, fam, chain, state, namer)
            continue
        if kind != "change" or _later_review(acc, chain, at):
            continue
        if _caused_by(state, trigger) and not _has_detection_for(fam, chain, state) \
                and not _before_first_recorded(acc, chain, state.at):
            return gen_continuation(acc, fam, chain, state, namer)
    return None


def _before_first_recorded(acc: Account, st: Story, at: Instant) -> bool:
    """7.2.8: maintenance records no continuation for an evidence change that occurred before
    the story was first recorded (its first detection's own time); the story's interval
    derives from its evidence, not from its detections (7.2.4)."""
    t = acc.occurrence(st.first)
    return t is not None and _k(at) < _k(t)


def _caused_by(state: EvidenceState, trigger: Rec | None) -> bool:
    return trigger is not None and state.cause is not None and state.cause.triple == trigger.triple


def _later_review(acc: Account, st: Story, at: Instant) -> bool:
    """A review of the story, not withdrawn, that takes effect after the instant: evidence
    backfilled before it does not continue the reviewed story (7.3.1)."""
    for r in story_acts(acc, st, ("review",)):
        e = acc.effective(r)
        if e is None or _k(e) <= _k(at):
            continue
        if any(w.action == "withdraw" and tg.support is None for w, tg in acc.acts_targeting_triple(r.triple)):
            continue
        return True
    return False


def _state_at(ep: Episode, at: Instant) -> EvidenceState | None:
    before = [s for s in ep.states if _k(s.at) <= _k(at)]
    return before[-1] if before else None


def _splitter(acc: Account, fam: Family, ep: Episode, before: dict | None) -> Story | None:
    """A recorded story believed to span this episode: one of its detections' evidence lies
    inside it, or before the write its interval covered the episode's start (7.3.3)."""
    for st in fam.stories:
        info = fam.info[st.id]
        if info.episode is None or info.episode is ep:
            continue
        if _k(info.episode.start) >= _k(ep.start):
            continue
        if story_acts(acc, st, ("review",)):
            continue  # 7.3.5: reviewed stories are not split; the later disagreement is related
        if any(ep.contains(a) for a, _d in fam.anchors(st)):
            return st
        if before and st.id in before:
            b_start, b_end, _latest = before[st.id]
            if b_start is not None and _k(b_start) <= _k(ep.start) and (b_end is None or _k(ep.start) < _k(b_end)):
                return st
    return None


def revision_chains(acc: Account, stories: list[Story]) -> list[list[Story]]:
    """The change stories recorded for each revision, in the order they were recorded: a
    revision's first change story, then each related change story of 7.3.8 that relates to the
    one before (7.2.8, 7.3.8). The last of a chain is the latest change story recorded for the
    revision."""
    groups: dict[Triple, list[Story]] = {}
    for st in stories:
        new = change_story_revision(acc, st)[0]
        if new is not None:
            groups.setdefault(new.triple, []).append(st)
    pos = {st.id: i for i, st in enumerate(stories)}
    out = []
    for key in sorted(groups, key=lambda k: min(pos[x.id] for x in groups[k])):
        sts = groups[key]
        ids = {x.id for x in sts}
        pred = {x.id: (x.relates_to if x.relates_to in ids and same_revision_predecessor(acc, x) is not None else None)
                for x in sts}
        order = sorted(sts, key=lambda x: (acc.sort_key(x.first), x.id))
        chain, seen = [], set()
        roots = [x for x in order if pred[x.id] is None]
        frontier = roots
        while frontier:
            nxt = []
            for x in frontier:
                if x.id in seen:
                    continue
                seen.add(x.id)
                chain.append(x)
                nxt += [y for y in order if pred[y.id] == x.id]
            frontier = nxt
        chain += [x for x in order if x.id not in seen]
        out.append(chain)
    return out


def latest_of_chain(chain: list[Story]) -> Story:
    """The latest change story recorded for a revision: the one no other story of its chain
    relates to (7.2.8)."""
    rel = {x.relates_to for x in chain}
    tips = [x for x in chain if x.id not in rel]
    return tips[-1] if tips else chain[-1]


def plan_reversal(acc: Account, latest: Story, namer: Namer) -> Generated | None:
    """7.3.8 *After it*, 7.2.8: when a normalization closed the latest change story recorded for
    a revision, and a later change of the interpretation in force (a normalization, a return to
    literal comparison, or the subject joining or leaving a normalized scope) makes the revision
    change a property again, a related change story: `<latest>+<n>`, its detection listing the
    revision's transitions under the interpretation in force from then, with their prior
    Assertions and the revised Assertion as `@basis`, and `@relates_to` the closed story's first
    detection (README §7). Its context is at the triggering record's time; its period begins
    when the revision changes again."""
    new = change_story_revision(acc, latest)[0]
    if new is None or latest.subject is None:
        return None
    rs = reversal_start(acc, latest, new, latest.sched)
    if rs is None:
        return None
    t, _norms = rs
    trans = revision_transitions(acc, new, _state_interp(latest.sched.at(t)))
    if not trans:
        return None
    at = namer.when or namer.trigger_time or t
    sid = namer.related_story(latest.id)
    ctx = f"{sid}/d1"
    values = {"@action": "detect", "@story": {"kind": "change", "subject": item_ref(latest.subject)},
              "@transitions": [{"property": x["property"], "transition": x["transition"],
                                "prior": assertion_ref(x["prior"]) if x["prior"] else None,
                                "new": assertion_ref(x["new"])} for x in trans],
              "@basis": [assertion_ref(x["prior"]) for x in trans if x["prior"]] + [assertion_ref(new.triple)],
              "@frame": _frame_of(latest, at), "@relates_to": assertion_ref(latest.first.triple)}
    return Generated([(sid, splitter_kind(acc, latest), {}), _event_ctx(ctx, at)], (sid, ctx, sid), values,
                     "related change story (7.3.8)")


def plan_change_story(acc: Account, st: Story, namer: Namer, latest: Story | None = None) -> Generated | None:
    """7.3.7: a backfilled issuance between a change story's prior and revised Assertions
    is reconciled (``reconstructed``), and its own revision becomes a related change story.
    A backfill that leaves the revision changing no property is reconciled too, with an empty
    ``@transitions`` (7.3.7, 7.6.12). Where several change stories are recorded for the
    revision (7.3.8), each is reconciled, with its own transitions, and the backfilled
    revision's one related change story relates to the latest of them (``latest``)."""
    new, src, recorded = change_story_revision(acc, st)
    if new is None:
        return None
    interp = _state_interp(change_interp(acc, st, new))
    priors = revision_priors(acc, new, interp)
    current = [{"property": p, "transition": kind, "prior": prior, "new": new.triple}
               for p, prior, kind in priors if kind not in (None, "unchanged")]
    listed = recorded
    if not listed:
        # a reconciliation that lists no transition: the priors are those last listed
        for r in reversed([st.first] + reconstructed_of(acc, st)[:-1]):
            if _transitions_of(r):
                listed = _transitions_of(r)
                break
    rec_priors = {t.get("property"): (ref_triple(t["prior"]) if is_assertion_ref(t.get("prior")) else None)
                  for t in listed if isinstance(t, dict)}
    # a backfill already reconciled is not reconciled again
    reconciled = {ref_triple(b) for r in reconstructed_of(acc, st) for b in ref_list(r.values, "@basis")
                  if is_assertion_ref(b)}
    backfilled = None
    for p, prior, _kind in priors:
        old = rec_priors.get(p, "missing")
        if old == "missing" or old == prior or prior is None or prior in reconciled:
            continue
        b = acc.get(prior)
        o = acc.get(old) if old else None
        if b is None:
            continue
        if old is not None and (o is None or acc.precedes(o, b) is not True):
            continue  # not a backfill between the prior and the revision
        backfilled = b
        break
    if backfilled is None:
        return None
    at = acc.occurrence(backfilled)
    trans = [{"property": t["property"], "transition": t["transition"],
              "prior": assertion_ref(t["prior"]) if t["prior"] else None, "new": assertion_ref(t["new"])}
             for t in current]
    g = gen_reconciliation(acc, st, "reconstructed", [st.first], [backfilled], at, namer, {"@transitions": trans})
    # the backfilled issuance's own revision, unless already recorded as a change story; it is
    # one change story, related to the latest change story recorded for the targeted revision
    exists = any(
        s.kind == "change" and change_story_revision(acc, s)[0] is backfilled
        for s in all_stories(acc, {st.subject}))
    if not exists and (latest is None or latest.id == st.id):
        bt = revision_transitions(acc, backfilled, _state_interp(st.sched.at(acc.occurrence(backfilled))))
        if bt:
            sid = namer.related_story(st.id)
            ctx = f"{sid}/d1"
            values = {"@action": "detect", "@story": {"kind": "change", "subject": item_ref(st.subject)},
                      "@transitions": [{"property": t["property"], "transition": t["transition"],
                                        "prior": assertion_ref(t["prior"]) if t["prior"] else None,
                                        "new": assertion_ref(t["new"])} for t in bt],
                      "@basis": [assertion_ref(t["prior"]) for t in bt if t["prior"]] + [assertion_ref(backfilled.triple)],
                      "@frame": _frame_of(st, at), "@relates_to": assertion_ref(st.first.triple)}
            g.follow = Generated([(sid, splitter_kind(acc, st), {}), _event_ctx(ctx, at)], (sid, ctx, sid), values,
                                 "related change story (7.3.7)")
    return g


class StoryIntervals(dict):
    """``story_intervals`` of an account, formed for a story's subject only when a story of it
    is looked up: maintenance consults the account before a write only for the families whose
    stories it may join, split or reconcile (7.3.3-7.3.5), so a write that affects many
    subjects, such as a normalization of a project (7.3.8), forms no family twice."""

    def __init__(self, acc: Account, subjects: set[str] | None) -> None:
        super().__init__()
        self.acc = acc
        self.subjects = subjects
        self.done: set = set()

    def _fill(self, sid) -> None:
        st = load_story(self.acc, sid) if isinstance(sid, str) else None
        if st is None or st.subject in self.done:
            return
        self.done.add(st.subject)
        if self.subjects is None or st.subject in self.subjects:
            self.update(story_intervals(self.acc, {st.subject}))

    def __contains__(self, sid) -> bool:
        self._fill(sid)
        return super().__contains__(sid)

    def __getitem__(self, sid):
        self._fill(sid)
        return super().__getitem__(sid)

    def get(self, sid, default=None):
        self._fill(sid)
        return super().get(sid, default)

    def __bool__(self) -> bool:
        return True


def story_intervals(acc: Account, subjects: set[str] | None) -> dict[str, tuple]:
    """Each conflict story's event-time interval (start, end) and the latest instant of
    its family's timeline, for comparing the account before and after a write."""
    out = {}
    for fam in families(acc, all_stories(acc, subjects)):
        tl = fam.timeline()
        latest = max((g[0] for g in tl.groups), key=_k) if tl.groups else None
        for sid, info in fam.info.items():
            out[sid] = (info.start, info.end, latest)
    return out


def _is_backfill(acc: Account, trigger: Rec | None, latest: Instant | None) -> bool:
    """A write changes the event-time account retroactively when it is a correction (8.3.3)
    or when it occurred before evidence already recorded in the family (7.3.3)."""
    if trigger is None or trigger.action == "reinterpret":
        return False  # a normalization is not evidence (7.3.5, 7.3.8)
    if trigger.action == "correct":
        return True
    t = acc.effective(trigger) if trigger.is_act else acc.occurrence(trigger)
    return t is not None and latest is not None and _k(t) < _k(latest)


def _before_review(acc: Account, trigger: Rec | None, st: Story) -> bool:
    """7.3.5: backfilled evidence is evidence that occurred before a review's effective time
    but was recorded after it. The write being maintained is recorded after every review
    already in the store."""
    if trigger is None or trigger.action == "reinterpret":
        return False
    t = acc.effective(trigger) if trigger.is_act else acc.occurrence(trigger)
    if t is None:
        return False
    for r in story_acts(acc, st, ("review",)):
        e = acc.effective(r)
        if e is not None and _k(t) < _k(e):
            return True
    return False


def _same_generated(a: Generated | None, b: Generated | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return a.triple == b.triple and literal_equal(a.values, b.values) and _same_generated(a.follow, b.follow)


def plan_maintenance(acc: Account, subjects: set[str] | None, namer: Namer, trigger: Rec | None,
                     before: dict[str, tuple] | None, boundary_done: set[str]) -> Generated | None:
    """The next record that maintenance requires for the affected families, or None.

    A family whose subject is, at some instant, under an interpretation the reference does
    not have records nothing (7.6.14: no story record whose need depends on it). Where the
    interpretation in force is ambiguous, a record is required only when every resolution
    requires it (4.5.3)."""
    stories = all_stories(acc, subjects)
    namer.trigger_time = acc.occurrence(trigger) if trigger is not None else None
    for fam in families(acc, stories):
        if fam.sched.unavailable() is not None:
            continue
        if fam.sched.ambiguous or fam.tied:
            gens = [_plan_family(acc, f, namer, trigger, before, set(boundary_done)) for f in fam.variants()]
            if gens and all(_same_generated(g, gens[0]) for g in gens) and gens[0] is not None:
                return gens[0]
            continue
        g = _plan_family(acc, fam, namer, trigger, before, boundary_done)
        if g is not None:
            return g
    change = [st for st in stories if st.kind == "change" and st.sched.unavailable() is None
              and not st.sched.ambiguous]
    for chain in revision_chains(acc, change):
        latest = latest_of_chain(chain)
        if trigger is None or trigger.action != "correct":
            # 7.2.7: a correction that changes a change story's transitions records nothing
            for st in chain:
                g = plan_change_story(acc, st, namer, latest)
                if g is not None:
                    return g
        # 7.3.8 *After it*: a change of the interpretation in force that makes the revision a
        # change again after a normalization closed its latest change story
        g = plan_reversal(acc, latest, namer)
        if g is not None:
            return g
    return None


def _plan_family(acc: Account, fam: Family, namer: Namer, trigger: Rec | None, before: dict[str, tuple] | None,
                 boundary_done: set[str]) -> Generated | None:
    # 7.3.5: a reviewed story whose event-time boundary the write changed. Only backfilled
    # evidence or a correction changes a boundary that way; a normalization, which applies from
    # its effective time, and a Connection operation never do (``_is_backfill``,
    # ``_before_review``)
    if before is not None and trigger is not None and trigger.action != "reinterpret":
        for st in fam.stories:
            if st.id in boundary_done or st.id not in before:
                continue
            if not story_acts(acc, st, ("review",)):
                continue
            info = fam.info[st.id]
            b0, b1, latest = before[st.id]
            if (_k(b0) != _k(info.start) or _k(b1) != _k(info.end)) and \
                    (_is_backfill(acc, trigger, latest) or _before_review(acc, trigger, st)):
                boundary_done.add(st.id)
                at = _trigger_time(acc, trigger, info.start)
                return gen_reconciliation(acc, st, "boundary", [st.first], [trigger] if trigger else [], at, namer)
    return plan_conflict_family(acc, fam, namer, trigger, before)
