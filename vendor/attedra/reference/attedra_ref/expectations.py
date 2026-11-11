"""Expectations: support, in-force periods, qualification, fulfillment and standing
(spec §6, 3.3, 7.1.5, 9.3).

An expectation is an Assertion at an expectation context (6.1.1). It is in force while at
least one support covers it (6.3.1). A property is fulfilled at its qualifying moment: the
earliest instant, at or before the cutoff, at which the expectation is in force for it and a
qualifying, unwithdrawn (and, for ``by``/``any`` timing, unsuperseded) Assertion from the
obligated or an eligible source meets the value requirement (6.5.1). Fulfillment, once it
occurs, is not reversed by later events (6.5.2).

The value requirement is met under the expectation's interpretation at each instant (7.6.13):
the one its context names, at every instant, or else the interpretation in force for its
subject (7.3.8). Every read whose frame names no interpretation evaluates it so; a frame that
names another interpretation, or requests literal comparison, evaluates it under that one at
every instant (7.6.14). Evidence that meets it only under an interpretation a normalization put
in force meets it only from the instant that interpretation is in force, and the fulfillment
cites the normalization (6.5.1, 5.5.4).

Where a condition depends on instants whose order is unspecified, the standing is computed
twice, counting the unspecified conditions as met and as unmet; if the two disagree the
standing is ``ambiguous`` with both candidates (4.5.3, 6.6.1).
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from . import instants as T
from .instants import Instant
from .interpretations import LITERAL, Interpretation
from .model import Rec, Triple, ref_list
from .normalization import InForce, Schedule, compact_or_list, subject_schedule
from .positions import classify
from .values import compact, is_assertion_ref, is_item_ref, literal_equal, properties_of, ref_triple, to_result
from .view import Limitation, View, tri_and, tri_or


@dataclass
class Coverage:
    """One support's coverage of one property (6.3.3)."""

    support: Rec
    start: Instant
    end: Instant | None = None
    end_records: list[Rec] = field(default_factory=list)
    voided_by: list[Rec] = field(default_factory=list)


@dataclass
class Period:
    """An in-force period: a continuous period in which at least one support covers the
    property; its establishment time is its start (6.3.3)."""

    start: Instant
    supports: list[Rec]
    end: Instant | None
    end_records: list[Rec]


@dataclass
class Candidate:
    evidence: Rec
    t: Instant
    period: Period
    status: bool | None  # True: all conditions hold; None: some depend on unspecified order
    # the interpretation in force at t under which the evidence meets the requirement (7.6.13),
    # and the normalizations that are the reason it does when it does not meet it literally
    # (5.5.4, 6.5.1)
    state: InForce | None = None
    matched_by: tuple = ()
    tied: list = field(default_factory=list)  # 6.5.1, 7.6.6: other evidence qualifying with it


def expectation_context_interp(acc, rec: Rec) -> tuple[str | None, str | None]:
    """The interpretation an expectation's context names (7.6.13, 4.1.1), as (name, version);
    (None, None) when it names none."""
    i = acc.ctx(rec.context).get("interpretation")
    if isinstance(i, dict) and i.get("name") is not None:
        return i["name"], i.get("version")
    return None, None


def own_schedule(acc, rec: Rec, view: View | None = None) -> Schedule:
    """An expectation's own interpretation over event time (7.6.13): the one its context
    names, at every instant; otherwise the interpretation in force for its subject at each
    instant (7.3.8), literal comparison until a normalization applies. With a participant
    ``view``, the interpretation in force is the one the normalizations that count in that
    perspective give (7.3.8, 7.6.14)."""
    name, version = expectation_context_interp(acc, rec)
    if name is not None:
        return Schedule.fixed(Interpretation(name, version))
    return subject_schedule(acc, rec.item, view)


def read_schedule_of(view: View, rec: Rec) -> Schedule:
    """How a read evaluates an expectation (7.6.14): under the interpretation its frame names,
    or that literal comparison its frame requests, at every instant; under the expectation's own
    interpretation when its frame names none (7.6.13), in the read's perspective."""
    if view.frame.named:
        return Schedule.fixed(view.interp)
    return own_schedule(view.acc, rec, view if view.frame.perspective is not None else None)


def _key(i: Instant | None):
    return (1,) if i is None else (0, i.end, i.start)


def _le(a: Instant, b: Instant | None) -> bool:
    """Linear 'at or before' for building periods (ends of intervals, 4.2.5)."""
    return b is None or a.end <= b.end


class Expectation:
    """The evaluation of one expectation at a view (§6)."""

    def __init__(self, view: View, rec: Rec, interp: Interpretation | None = None,
                 schedule: Schedule | None = None) -> None:
        """``interp`` evaluates under one interpretation at every instant (a frame's, or the
        context's); ``schedule`` under the given interpretation over time. With neither, the
        expectation is evaluated as the read's frame evaluates it: under the interpretation the
        frame names, or literally where it requests literal comparison, and else under the
        expectation's own interpretation (``read_schedule_of``, 4.6.1, 7.6.13, 7.6.14)."""
        self.view = view
        self.acc = view.acc
        self.rec = rec
        if interp is not None:
            self.sched = Schedule.fixed(interp)
        elif schedule is not None:
            self.sched = schedule
        else:
            self.sched = read_schedule_of(view, rec)
        st = self.sched.at_cutoff(view.cutoff)
        self.interp = st.interp if st.interp is not None else LITERAL
        self.ctx = self.acc.ctx(rec.context)
        t = self.ctx.get("timing")
        self.timing = t if isinstance(t, dict) else {}
        self.ttype = self.timing.get("type")
        self.fresh = self.ctx.get("fresh") is True
        self.props = sorted(properties_of(rec.values))
        src = self.acc.item(rec.source)
        self.eligibility = bool(src and src.is_eligibility)
        self._periods: dict = {}
        # 3.3.2, 9.6.1: evidence whose qualification is ambiguous because criteria of
        # different sources disagree -> each source's @eligible Assertion in force then
        self._disagreeing_criteria: dict[Triple, list[Rec]] = {}

    # -- supports and withdrawals (6.3, 6.7.2) -------------------------------------------

    def _in_frame(self, r: Rec, cutoff, lenient: bool) -> bool:
        """An act is counted when it is in the frame; with ``lenient``, also when its relation
        to the cutoff (or its distribution to the participant) is unspecified (4.5.3)."""
        inc = self.view.act_in(r, cutoff)
        return inc is True or (lenient and inc is None)

    def supports(self, cutoff: Instant | None = None, lenient: bool = False) -> list[tuple[Rec, set | None]]:
        """Supports in the frame: establish and reaffirm acts targeting the expectation, and
        reviews whose ``@establishes`` or ``@reaffirms`` list it (6.3.1). A property
        selector narrows a support to that property."""
        acc, E = self.acc, self.rec.triple
        found: dict[Triple, set | None] = {}
        order: list[Rec] = []

        def add(r: Rec, prop):
            if r.triple not in found:
                found[r.triple] = set() if prop is not None else None
                order.append(r)
            if found[r.triple] is not None:
                if prop is None:
                    found[r.triple] = None
                else:
                    found[r.triple].add(prop)

        for r, tg in acc.acts_targeting(("A", E)):
            if r.action in ("establish", "reaffirm") and tg.support is None and self._in_frame(r, cutoff, lenient):
                add(r, tg.prop)
        for r, _member in acc.establishes_of.get(E, []):
            if self._in_frame(r, cutoff, lenient):
                for ref in ref_list(r.values, "@establishes") + ref_list(r.values, "@reaffirms"):
                    if is_assertion_ref(ref) and ref_triple(ref) == E:
                        add(r, ref.get("property"))
        order.sort(key=lambda r: acc.sort_key(r))
        return [(r, found[r.triple]) for r in order]

    def _withdrawals(self, cutoff, lenient: bool = False):
        acc, E = self.acc, self.rec.triple
        exp_level: list[tuple[Rec, str | None]] = []
        for r, tg in acc.acts_targeting(("A", E)):
            if r.action == "withdraw" and tg.support is None and self._in_frame(r, cutoff, lenient):
                exp_level.append((r, tg.prop))
        return exp_level

    def _support_withdrawals(self, d: Rec, cutoff, lenient: bool = False) -> list[tuple[Rec, str | None]]:
        acc, E = self.acc, self.rec.triple
        out = []
        for r, tg in acc.acts_targeting(("S", d.triple, E)):
            if r.action == "withdraw" and self._in_frame(r, cutoff, lenient):
                out.append((r, tg.prop))
        for r, tg in acc.acts_targeting(("A", d.triple)):
            if r.action == "withdraw" and tg.support is None and self._in_frame(r, cutoff, lenient):
                out.append((r, tg.prop))
        return out

    def coverages(self, prop: str | None, cutoff: Instant | None = None, lenient: bool = False) -> list[Coverage]:
        """Each support's coverage of a property (None: of the whole expectation), ended by
        withdrawals of the support or of the expectation (6.7.2):

        * withdrawing the expectation (or the property) ends every support covering it at
          the withdrawal's effective time, and also every support that occurred at or before
          the withdrawal and takes effect later;
        * only a support that occurs after the withdrawal and takes effect after its
          effective time is unaffected, and begins a new in-force period.
        """
        acc = self.acc
        out = []
        exp_w = [(w, p) for w, p in self._withdrawals(cutoff, lenient) if p is None or p == prop]
        for d, props in self.supports(cutoff, lenient):
            if prop is not None and props is not None and prop not in props:
                continue
            if prop is None and props is not None:
                continue
            start = acc.effective(d)
            if start is None:
                continue
            cov = Coverage(d, start)
            ends: list[tuple[Instant, Rec]] = []
            for w, p in self._support_withdrawals(d, cutoff, lenient):
                if p is None or p == prop:
                    we = acc.effective(w)
                    if we is not None:
                        ends.append((we, w))
            d_occ = acc.occurrence(d)
            for w, _p in exp_w:
                we, wo = acc.effective(w), acc.occurrence(w)
                if we is None:
                    continue
                if _le(start, we):
                    ends.append((we, w))
                elif d_occ is not None and wo is not None and _le(d_occ, wo):
                    cov.voided_by.append(w)
            if cov.voided_by:
                out.append(cov)
                continue
            if ends:
                ends.sort(key=lambda x: (_key(x[0]), x[1].triple))
                first = ends[0][0]
                if _le(first, start):  # withdrawn before (or as) it took effect
                    cov.voided_by = [w for e, w in ends if _le(e, start)]
                    out.append(cov)
                    continue
                cov.end = first
                cov.end_records = [w for e, w in ends if e.end == first.end and e.start == first.start]
            out.append(cov)
        return out

    def periods(self, prop: str | None, cutoff: Instant | None = None,
                lenient: bool = False) -> tuple[list[Period], list[Rec]]:
        """In-force periods for a property, and the withdrawals that voided supports before
        they took effect (6.3.3, 6.6.1)."""
        key = (prop, cutoff.text if cutoff else None, lenient)
        if key in self._periods:
            return self._periods[key]
        covs = self.coverages(prop, cutoff, lenient)
        voiding = sorted({w.triple: w for c in covs for w in c.voided_by}.values(), key=self.acc.sort_key)
        live = sorted([c for c in covs if not c.voided_by], key=lambda c: (_key(c.start), c.support.triple))
        periods: list[Period] = []
        for c in live:
            if periods and (periods[-1].end is None or _le(c.start, periods[-1].end)):
                p = periods[-1]
                p.supports.append(c.support)
                if p.end is not None and (c.end is None or not _le(c.end, p.end)):
                    p.end = c.end
                p.end_records += c.end_records
            else:
                periods.append(Period(c.start, [c.support], c.end, list(c.end_records)))
        for p in periods:
            p.end_records = sorted({w.triple: w for w in p.end_records}.values(), key=self.acc.sort_key)
        self._periods[key] = (periods, voiding)
        return periods, voiding

    def covered_at(self, prop: str | None, at: Instant | None, lenient: bool = False) -> bool | None:
        periods, _ = self.periods(prop, self.view.cutoff, lenient)
        votes = []
        for p in periods:
            started = True if at is None else T.at_or_before(p.start, at)
            if started is False:
                continue
            ongoing = True if p.end is None else (False if at is None else T.after(p.end, at))
            votes.append(tri_and(started, ongoing))
        return tri_or(*votes) if votes else False

    # -- timing (6.2) ---------------------------------------------------------------------

    def _milestone_instant(self, ref) -> Instant | None:
        if is_item_ref(ref):
            return self.acc.publication_instant(ref["id"])[0]
        return None

    def _bound(self, v) -> Instant | None:
        if isinstance(v, str):
            return T.parse_instant(v)
        return self._milestone_instant(v)

    def phase_bounds(self) -> tuple[Instant | None, Instant | None]:
        ph = self.timing.get("phase")
        c = self.acc.ctx(ph["id"]) if is_item_ref(ph) else {}
        return self._bound(c.get("starts")), self._bound(c.get("ends"))

    def deadline(self) -> Instant | None:
        if self.ttype != "by":
            return None
        if "instant" in self.timing:
            return T.parse_instant(self.timing["instant"])
        return self._milestone_instant(self.timing.get("milestone"))

    def in_timing_scope(self, a: Rec, occ: Instant) -> bool | None:
        """Does the evidence fall within the timing scope (6.2.1)?"""
        if self.ttype == "at":
            m = self.timing.get("milestone")
            return is_item_ref(m) and a.context == m["id"]
        if self.ttype == "during":
            start, end = self.phase_bounds()
            if start is None:
                return False
            return tri_and(T.at_or_after(occ, start), True if end is None else T.before(occ, end))
        return True

    def scope_reached(self, at: Instant | None) -> bool | None:
        """Is the timing scope reached at the cutoff (6.2.1)?"""
        if self.ttype == "at":
            pub = self._milestone_instant(self.timing.get("milestone"))
            return False if pub is None else (True if at is None else T.at_or_before(pub, at))
        if self.ttype == "during":
            start, _ = self.phase_bounds()
            return False if start is None else (True if at is None else T.at_or_before(start, at))
        return True

    def overdue(self, at: Instant | None) -> bool | None:
        """The overdue condition (6.2.1)."""
        if at is None:
            return False
        if self.ttype == "at":
            return self.scope_reached(at)
        if self.ttype == "during":
            _, end = self.phase_bounds()
            return False if end is None else T.at_or_before(end, at)
        if self.ttype == "by":
            d = self.deadline()
            return False if d is None else T.after(at, d)
        return False

    # -- value requirement (6.4) ----------------------------------------------------------

    def requirement(self, prop: str) -> tuple[str, Any]:
        v = self.rec.values.get(prop)
        if isinstance(v, dict) and v.get("@ask") is True and "@ref" not in v:
            return ("ask", v.get("@suggested"))
        return ("value", v)

    def meets(self, prop: str, value: Any, interp: Interpretation | None = None) -> bool:
        interp = interp or self.interp
        kind, req = self.requirement(prop)
        if kind == "ask":
            return value is not None or interp.accepts_empty_answer(prop)
        return interp.equal(value, req, prop)

    def windows(self, prop: str, value: Any) -> list[tuple[Instant | None, Instant | None, InForce, bool | None]]:
        """The spans of event time in which the value meets the requirement under the
        expectation's interpretation then (6.5.1(b), 7.6.13): (start, end, state, status), with
        status None where it does under some candidates of an ambiguous interpretation only."""
        segs = self.sched.segments
        out = []
        for i, (start, st) in enumerate(segs):
            end = segs[i + 1][0] if i + 1 < len(segs) else None
            if st.interp is not None:
                ok: bool | None = self.meets(prop, value, st.interp)
            else:
                votes = {self.meets(prop, value, c[0]) for c in st.candidates}
                ok = votes.pop() if len(votes) == 1 else None
            if ok is not False:
                out.append((start, end, st, ok))
        return out

    def matched_by(self, prop: str, value: Any, state: InForce | None) -> tuple:
        """5.5.4, 6.5.1: the normalizations that are the reason evidence meets the requirement:
        those that put the interpretation in force when the evidence meets it only under that
        interpretation."""
        if state is None or state.interp is None or not state.norms or state.interp.name is None:
            return ()
        if self.meets(prop, value, LITERAL):
            return ()
        return state.norms if self.meets(prop, value, state.interp) else ()

    # -- eligibility (3.3.2) --------------------------------------------------------------

    def criteria_in_force(self, at: Instant) -> list[tuple[str, dict, Rec]] | None:
        """For each source that has asserted ``@eligible`` on the eligibility Item, its most
        recent criteria at or before the instant that have not been withdrawn with effect
        at or before it, with the ``@eligible`` Assertion (3.3.2). None when that depends on
        an unspecified order."""
        acc, view = self.acc, self.view
        by_src: dict[str, list[Rec]] = {}
        for r in acc.statements_about(self.rec.source):
            if isinstance(r.values.get("@eligible"), dict):
                by_src.setdefault(r.source, []).append(r)
        out = []
        for src, recs in sorted(by_src.items()):
            usable = []
            for r in recs:
                w = tri_and(view.statement_in(r), view.within(acc.occurrence(r), at))
                if w is None:
                    return None
                if w:
                    usable.append(r)
            if not usable:
                continue
            latest = acc.latest_of(usable)
            if len(latest) > 1:
                return None
            l = latest[0]
            withdrawn = False
            for w_, tg in acc.acts_targeting_triple(l.triple):
                if w_.action == "withdraw" and tg.support is None and view.act_in(w_) is True:
                    e = acc.effective(w_)
                    if e is not None and T.at_or_before(e, at) is True:
                        withdrawn = True
            if not withdrawn:
                out.append((src, l.values["@eligible"], l))
        return out

    def qualifies(self, a: Rec, occ: Instant) -> tuple[bool | None, str | None]:
        """Source qualification of evidence (3.3.1-3.3.2, 6.1.2-6.1.3)."""
        if not self.eligibility:
            return (a.source == self.rec.source, None if a.source == self.rec.source else "not_obligated_source")
        criteria = self.criteria_in_force(occ)
        if criteria is None:
            return None, "criteria_order_unspecified"
        if not criteria:
            return False, "no_criteria_in_force"
        sd = self.acc.self_description(a.source, a.context)
        prod = sd.values.get("@producer") if sd else None
        producer = prod["id"] if is_item_ref(prod) else None
        agents = [x["id"] for x in (sd.values.get("@agent") or []) if is_item_ref(x)] if sd else []
        results = []
        for _src, crit, _rec in criteria:
            party = crit.get("party", {}).get("id")
            req_agents = [x["id"] for x in crit["agents"] if is_item_ref(x)] if isinstance(crit.get("agents"), list) else None
            if producer is None:
                results.append((False, "missing_producer"))
            elif producer != party:
                results.append((False, "producer"))
            elif req_agents is not None and not agents:
                results.append((False, "missing_agent"))
            elif req_agents is not None and not set(agents) & set(req_agents):
                results.append((False, "agents"))
            else:
                results.append((True, None))
        oks = {r[0] for r in results}
        if oks == {True}:
            return True, None
        if oks == {False}:
            return False, results[0][1]
        self._disagreeing_criteria[a.triple] = [rec for _src, _crit, rec in criteria]
        return None, "criteria_disagree"

    # -- fulfillment (6.5) -----------------------------------------------------------------

    def candidates(self, prop: str, cutoff: Instant | None = None,
                   lenient: bool = False) -> tuple[list[Candidate], list[dict]]:
        """Every (evidence, in-force period) pair and the earliest instant at which 6.5.1's
        conditions hold for it, with the evidence that does not qualify and why. Under the
        interpretation in force, evidence that meets the requirement only under an
        interpretation a normalization put in force meets it only from the instant that
        interpretation is in force for the subject, so its qualifying moment is never earlier
        (6.5.1, 7.3.8)."""
        acc, view = self.acc, self.view
        periods, _ = self.periods(prop, cutoff, lenient)
        out: list[Candidate] = []
        unqualified: list[dict] = []  # 3.3.2: listed whether or not the expectation is in force
        if not periods and not self.eligibility:
            return out, unqualified
        for a in acc.statements_about(self.rec.item):
            if prop not in a.values:
                continue
            inc = view.statement_in(a, cutoff)
            if inc is False:
                continue
            occ = acc.occurrence(a)
            if occ is None:
                continue
            qual, why = self.qualifies(a, occ)
            if qual is False:
                if self.eligibility:
                    unqualified.append({"evidence": compact(a.triple), "unmet": why})
                continue
            windows = self.windows(prop, a.values[prop])
            if not windows:
                continue
            scope = self.in_timing_scope(a, occ)
            if scope is False:
                continue
            w_ends = []
            for w, tg in acc.acts_targeting_triple(a.triple):
                if w.action == "withdraw" and tg.support is None and (tg.prop is None or tg.prop == prop) \
                        and view.act_in(w, cutoff) is True:
                    e = acc.effective(w)
                    if e is not None:
                        w_ends.append(e)
            s_ends = []
            if self.ttype in ("by", "any"):
                for b in acc.statements_about(a.item, a.source):
                    if b is a or prop not in b.values or view.statement_in(b, cutoff) is not True:
                        continue
                    if acc.precedes(a, b) is True:
                        s_ends.append(acc.occurrence(b))
            done = False
            for p in periods:
                s = p.start
                # The qualifying moment is the latest of the evidence's occurrence time, the
                # establishment time of the in-force period, and the instant from which the
                # interpretation under which the evidence meets the requirement is in force
                # (6.5.1). "At or before" compares interval ends (4.2.5), so the instant with
                # the later end is the earliest at which all of them have occurred.
                base = occ if T.at_or_before(s, occ) is True else s
                for ws, we, st, ok in windows:
                    t = base if ws is None or T.at_or_before(ws, base) is True else ws
                    if we is not None and not ((t.start, t.end) < (we.start, we.end)):
                        continue
                    conds = [
                        inc,                                                     # in the frame (4.6.1)
                        qual,                                                    # (b) obligated or eligible source
                        scope,                                                   # (b) within the timing scope
                        ok,                                                      # (b) meets the requirement at t
                        True if p.end is None else T.after(p.end, t),            # (a) in force at t
                        T.at_or_after(occ, s) if self.fresh else True,           # (c) fresh evidence
                        True if cutoff is None else T.at_or_before(t, cutoff),   # at or before the cutoff
                    ]
                    conds += [T.after(e, t) for e in w_ends]                     # (d) not withdrawn by t
                    conds += [T.after(e, t) for e in s_ends if e is not None]    # (d) not superseded by t
                    status = tri_and(*conds)
                    if status is False:
                        continue
                    out.append(Candidate(a, t, p, status, st, self.matched_by(prop, a.values[prop], st)))
                    if status is True:
                        done = True
                        break
                if done:
                    break
        return out, unqualified

    def _first(self, cands: list[Candidate]) -> Candidate | None:
        """The fulfilling candidate: the earliest qualifying moment and, of the evidence
        qualifying then, the earliest by occurrence time. Where several earliest share one
        occurrence time with no sequence evidence ordering them, the result references all of
        them (6.5.1, 7.6.6): they are listed in ``tied``."""
        if not cands:
            return None
        order = sorted(cands, key=lambda c: (c.t.end, c.t.start, _key(self.acc.occurrence(c.evidence)),
                                             c.evidence.triple))
        first = order[0]
        occ = self.acc.occurrence(first.evidence)
        tied = []
        for c in order[1:]:
            if c.evidence.triple == first.evidence.triple or c.status != first.status:
                continue
            if (c.t.start, c.t.end) != (first.t.start, first.t.end):
                continue
            o = self.acc.occurrence(c.evidence)
            if o is None or occ is None or (o.start, o.end) != (occ.start, occ.end):
                continue
            if self.acc.precedes(first.evidence, c.evidence) is not None:
                continue
            if all(x.evidence.triple != c.evidence.triple for x in tied):
                tied.append(c)
        first.tied = tied
        return first

    def timeliness(self, c: Candidate) -> tuple[str | None, str | None]:
        """``on_time`` or ``late`` and the derived lateness (6.5.4); (None, None) when the
        evidence's relation to the deadline is unspecified, which the caller reports as
        timeliness ``ambiguous`` (6.6.1)."""
        if self.ttype != "by":
            return "on_time", None
        d = self.deadline()
        occ = self.acc.occurrence(c.evidence)
        if d is None or occ is None:
            return "on_time", None
        late = T.after(occ, d)
        if late is True:
            return "late", T.late_by(occ, d)
        if late is False:
            return "on_time", None
        return None, None

    # -- standing (6.6) --------------------------------------------------------------------

    def standing(self, prop: str, cutoff: Instant | None = None, with_current: bool = True) -> dict:
        """The standing of one property at the cutoff (6.6.1, 9.3.1)."""
        if self.acc.limits.get(self.rec.triple):
            corr, act = self.acc.limits[self.rec.triple][0]
            return {"standing": "limitation", "limitation": "relocated_reference",
                    "correction": compact(corr), "record": compact(act)}
        cutoff = cutoff if cutoff is not None else self.view.cutoff
        cands, unqualified = self.candidates(prop, cutoff)
        definite = [c for c in cands if c.status is True]
        maybe = [c for c in cands if c.status is None]
        pess = self._standing_from(prop, cutoff, self._first(definite))
        if maybe:
            opt = self._standing_from(prop, cutoff, self._first(definite + maybe))
            if _signature(opt) != _signature(pess):
                res = {"standing": "ambiguous", "candidates": [pess, opt],
                       "records": sorted({compact(c.evidence.triple) for c in maybe})}
                criteria = {r.triple: r for c in maybe for r in self._disagreeing_criteria.get(c.evidence.triple, [])}
                if criteria:
                    res["criteria"] = sorted(compact(t) for t in criteria)
                return self._decorate(res, prop, cutoff, unqualified, with_current)
        return self._decorate(pess, prop, cutoff, unqualified, with_current)

    def _decorate(self, res: dict, prop: str, cutoff, unqualified, with_current) -> dict:
        """The members every standing carries where they apply (README §5 <standing>); the
        candidates of an ambiguous standing carry only the members of their own value."""
        res["timing"] = to_result(self.timing)
        # README §5 <standing>: for a fulfilled property, the interpretation it was fulfilled
        # under; otherwise the one applied at the cutoff
        res["interpretation"] = res.pop("_interpretation") if "_interpretation" in res else self.interp.name
        for c in res.get("candidates") or []:
            if isinstance(c, dict):
                c.pop("_interpretation", None)
        d = self.deadline()
        if d is not None and d.precision != "competing":
            res["deadline"] = d.text  # 6.5.4, 9.3.1: with `by` timing, once the deadline is known
        kind, sug = self.requirement(prop)
        if kind == "ask" and "@suggested" in (self.rec.values.get(prop) or {}):
            res["suggested"] = to_result(sug)
        if unqualified:
            res["unqualified"] = unqualified
        if with_current and not self.eligibility:
            try:
                res["source_current"] = classify(self.view, self.rec.item, self.rec.source, prop, cutoff).to_result()
            except Limitation:
                pass
        return res

    def _standing_from(self, prop: str, cutoff, q: Candidate | None) -> dict:
        periods, voiding = self.periods(prop, cutoff)
        started = [p for p in periods if cutoff is None or T.at_or_before(p.start, cutoff) is True]
        if not started:
            return {"standing": "not_in_force", "withdrawn_by": [compact(w.triple) for w in voiding]}
        if q is not None:
            res: dict[str, Any] = {"standing": "fulfilled"}
            timely, lateness = self.timeliness(q)
            # 6.5.4/6.6.1: late evidence still qualifies under `by`, so the property is
            # fulfilled whichever way an unspecified order falls; only its timeliness is ambiguous.
            res["timeliness"] = timely if timely is not None else "ambiguous"
            res["fulfilled_by"] = compact_or_list([q.evidence] + [c.evidence for c in q.tied])
            res["qualifying_moment"] = q.t.text
            if lateness:
                res["late_by"] = lateness
            if q.matched_by:
                res["matched_by"] = compact_or_list(q.matched_by)
            if q.state is not None and q.state.interp is not None:
                res["_interpretation"] = q.state.interp.name
            # 6.6.1: a later ending of the requirement, after the qualifying moment and at or
            # before the cutoff, is reported alongside. Only an in-force period that has ended
            # is an ending: a withdrawal that leaves another support covering the property is
            # not (6.3.2). Its records are those `withdrawn_by` would carry for that ending.
            later = []
            for p in periods:
                if p.end is None or T.after(p.end, q.t) is False:
                    continue
                if cutoff is not None and T.at_or_before(p.end, cutoff) is not True:
                    continue
                for w in p.end_records:
                    if not any(x["record"] == compact(w.triple) for x in later):
                        later.append({"kind": "withdrawal", "record": compact(w.triple)})
            if later:
                res["later"] = later
            return res
        votes = []
        for p in started:
            votes.append(True if p.end is None else (False if cutoff is None else T.after(p.end, cutoff)))
        covered = tri_or(*votes)
        if covered is False:
            last = started[-1]
            return {"standing": "withdrawn", "withdrawn_by": [compact(w.triple) for w in last.end_records]}
        open_ = self._open_standing(cutoff)
        if covered is None:
            # 4.5.3, 6.6.1: whether coverage ended at or before the cutoff is unspecified. The
            # candidates are complete standings, and the records are the withdrawals whose
            # effective time is unordered with the cutoff.
            unsettled = [p for p in started if p.end is not None and cutoff is not None and T.after(p.end, cutoff) is None]
            ending = unsettled[-1] if unsettled else started[-1]
            withdrawn = {"standing": "withdrawn", "withdrawn_by": [compact(w.triple) for w in ending.end_records]}
            others = open_["candidates"] if open_["standing"] == "ambiguous" else [open_]
            records = {compact(w.triple) for p in unsettled for w in p.end_records} | set(open_.get("records", []))
            return {"standing": "ambiguous", "candidates": [withdrawn, *others], "records": sorted(records)}
        return open_

    def _open_standing(self, cutoff) -> dict:
        """``outstanding`` or ``not_yet_due`` for a covered, unfulfilled property (6.6.1), or
        ``ambiguous`` with both when whether the timing scope is reached is unspecified."""
        reached = self.scope_reached(cutoff)
        outstanding = {"standing": "outstanding", "overdue": self.overdue(cutoff) is True}
        if reached is True:
            return outstanding
        not_yet_due = {"standing": "not_yet_due", "overdue": False}  # 6.2.1: never overdue before the scope
        if reached is False:
            return not_yet_due
        return {"standing": "ambiguous", "candidates": [outstanding, not_yet_due], "records": self._scope_records()}

    def _scope_records(self) -> list[str]:
        """The records whose order with the cutoff decides whether the timing scope is
        reached: the publication of the milestone that starts it (6.2.1, 4.4.1)."""
        m = None
        if self.ttype == "at":
            m = self.timing.get("milestone")
        elif self.ttype == "during":
            ph = self.timing.get("phase")
            m = self.acc.ctx(ph["id"]).get("starts") if is_item_ref(ph) else None
        if not is_item_ref(m):
            return []
        return sorted(compact(p.triple) for p in self.acc.publications.get(m["id"], []))

    def qualifying_moment(self, prop: str, cutoff: Instant | None = None, lenient: bool = False) -> Candidate | None:
        cands, _ = self.candidates(prop, cutoff, lenient)
        return self._first([c for c in cands if c.status is True])

    def in_force(self, cutoff: Instant | None = None) -> bool:
        cutoff = cutoff if cutoff is not None else self.view.cutoff
        props = self.props or [None]
        for p in props:
            periods, _ = self.periods(p, cutoff)
            for per in periods:
                if (cutoff is None or T.at_or_before(per.start, cutoff) is True) and \
                        (per.end is None or (cutoff is not None and T.after(per.end, cutoff) is True)):
                    return True
        return False

    def support_entries(self, cutoff: Instant | None = None) -> list[dict]:
        """9.3.1: every support whose occurrence time is at or before the cutoff, in
        presentation order, with the properties it covers at the cutoff (a property selector
        limits it to that property, 6.3.1) and the withdrawals that ended its coverage, or
        voided it before it began, at or before the cutoff (6.3.3, 6.7.2)."""
        cutoff = cutoff if cutoff is not None else self.view.cutoff
        per_prop = {p: {c.support.triple: c for c in self.coverages(p, cutoff)} for p in self.props}
        out = []
        for d, _props in self.supports(cutoff):
            covers, ended = [], {}
            for p in self.props:
                c = per_prop[p].get(d.triple)
                if c is None:
                    continue
                for w in c.voided_by:
                    ended[w.triple] = w
                if c.voided_by:
                    continue
                if c.end is not None and (cutoff is None or T.at_or_before(c.end, cutoff) is True):
                    for w in c.end_records:
                        ended[w.triple] = w
                    continue
                if cutoff is None or T.at_or_before(c.start, cutoff) is True:
                    covers.append(p)
            out.append({"support": compact(d.triple), "covers": sorted(covers),
                        "withdrawn_by": [compact(w.triple) for w in sorted(ended.values(), key=self.acc.sort_key)]})
        return out

    def evaluate(self, cutoff: Instant | None = None) -> dict:
        """The expectation read (9.3.1)."""
        cutoff = cutoff if cutoff is not None else self.view.cutoff
        props = {p: self.standing(p, cutoff) for p in self.props}
        return {"in_force": self.in_force(cutoff), "supports": self.support_entries(cutoff),
                "properties": props, "overall": overall_of(list(props.values()))}

    # -- as a side of a comparison (7.1.5) ----------------------------------------------

    def present_for(self, prop: str, at: Instant | None) -> bool | None:
        """In force for the property and not yet fulfilled for it, at an instant (7.1.5).
        None when that depends on an unspecified order (4.5.3, 9.4.2): evaluated without and
        with the acts whose relation to the frame is unspecified, the two disagree."""
        kind, _ = self.requirement(prop)
        if kind != "value" or prop not in self.rec.values:
            return False
        strict = self._present(prop, at, lenient=False)
        lenient = self._present(prop, at, lenient=True)
        return strict if strict == lenient else None

    def _present(self, prop: str, at: Instant | None, lenient: bool) -> bool | None:
        cov = self.covered_at(prop, at, lenient)
        if cov is not True:
            return cov
        q = self.qualifying_moment(prop, at if at is not None else self.view.cutoff, lenient)
        return q is None


def _signature(s: dict) -> tuple:
    return (s.get("standing"), s.get("timeliness"), s.get("overdue"))


def _overall(standings: set[str]) -> str:
    """6.4.5, 6.6.2 (README §5 <overall>). A property that no support has covered at or
    before the cutoff (``not_in_force``) does not count; an expectation with no covered
    property is not in force (6.3.1). Over the covered properties it is open while any is
    outstanding or not yet due, fulfilled only when every one is fulfilled, and otherwise
    closed, every one being fulfilled or withdrawn."""
    covered = standings - {"not_in_force"}
    if not covered:
        return "not_in_force"
    if covered & {"outstanding", "not_yet_due"}:
        return "open"
    if covered == {"fulfilled"}:
        return "fulfilled"
    if covered <= {"fulfilled", "withdrawn"}:
        return "closed"
    # A standing with no candidates to evaluate (an ambiguous standing that lists none) leaves
    # the overall standing undetermined. A limitation is reported before this is computed.
    return "ambiguous"


def _candidate_standings(s: dict) -> list:
    """The standings an ambiguous standing may take, a candidate that is itself ambiguous
    contributing its own candidates (4.5.3)."""
    if s.get("standing") != "ambiguous":
        return [s.get("standing")]
    out = [x for c in s.get("candidates") or [] for x in _candidate_standings(c)]
    return out or [None]


def overall_of(standings: list[dict]) -> str:
    """The expectation-level result. When a property's standing is ambiguous, it is computed
    with each of its candidate standings: the common value when all agree, and ``ambiguous``
    otherwise (README §5 <overall>)."""
    options = [_candidate_standings(s) for s in standings]
    values = {_overall(set(combo)) for combo in itertools.product(*options)} if options else {_overall(set())}
    return values.pop() if len(values) == 1 else "ambiguous"


def _votes(state: InForce, a: Any, b: Any, prop: str) -> bool | None:
    """Whether two values are unequal under a state: None where the candidates of an
    ambiguous interpretation in force disagree (4.5.3)."""
    cands = [state.interp] if state.interp is not None else [c[0] for c in state.candidates]
    votes = {not i.equal(a, b, prop) for i in cands}
    return votes.pop() if len(votes) == 1 else None


def pair_states(view: View, a: Rec, b: Rec, cutoff: Instant | None) -> tuple[InForce, InForce]:
    """The interpretations two expectations are compared under at the cutoff (7.2.4, 9.4.2):
    the frame's, where it names one or requests literal comparison, for both; otherwise each
    expectation's own (7.6.13)."""
    if view.frame.named:
        st = InForce(view.interp)
        return st, st
    sa = read_schedule_of(view, a).at_cutoff(cutoff)
    sb = read_schedule_of(view, b).at_cutoff(cutoff)
    return sa, sb


def pair_unequal(sa: InForce, sb: InForce, va: Any, vb: Any, prop: str) -> bool | None:
    """7.2.4: two expectations' values are unequal when they are unequal under both sides'
    interpretations, equal when equal under both, and the comparison is ambiguous (None)
    otherwise."""
    ua, ub = _votes(sa, va, vb, prop), _votes(sb, va, vb, prop)
    if ua is None or ub is None or ua != ub:
        return None
    return ua


def pair_matched_by(sa: InForce, sb: InForce, va: Any, vb: Any, prop: str) -> tuple:
    """5.5.4: the normalizations that are the reason two expectations' values match: those
    that put either side's interpretation in force, where the values are unequal literally
    and equal under it."""
    out: dict = {}
    for st in (sa, sb):
        for r in st.matched_by(va, vb, prop, literal_equal):
            out[r.triple] = r
    return tuple(out[t] for t in sorted(out))


def _side_name(st: InForce) -> str | None:
    return st.interp.name if st.interp is not None else None


def expectation_conflicts(view: View, subject: str, cutoff: Instant | None = None
                          ) -> tuple[list[dict], list[dict], list[dict]]:
    """Pairs of expectations about one subject that are both in force and not yet fulfilled
    for a property at the cutoff and require unequal values (7.1.5, 9.4.2): under the frame's
    interpretation where it names one or requests literal comparison, and otherwise under each
    expectation's own interpretation at the cutoff (7.2.4, 7.6.13), unequal when unequal under
    both. Also the pairs whose comparison is ambiguous: their standing at the cutoff depends on
    an unspecified order (4.5.3), or their own interpretations disagree on whether the values
    are equal (7.2.4); and the pairs whose required values are unequal literally and equal under
    an interpretation a normalization put in force, which are not conflicts (``matched``,
    5.5.4). An entry carries ``interpretations``, the two sides' interpretation names in side
    order, when either differs from the read's interpretation (README §5 `conflicts`).
    Information requests and suggestions are not compared. Each expectation is evaluated as the
    read's frame evaluates it (``Expectation``)."""
    from .normalization import read_schedule  # noqa: PLC0415
    cutoff = cutoff if cutoff is not None else view.cutoff
    read_state = read_schedule(view, subject).at_cutoff(cutoff)
    read_name = _side_name(read_state)
    exps = [Expectation(view, r) for r in sorted(view.acc.expectations_about(subject), key=lambda r: r.triple)]
    out, ambiguous, matched = [], [], []
    for i, a in enumerate(exps):
        for b in exps[i + 1:]:
            for p in sorted(set(a.props) & set(b.props)):
                if a.requirement(p)[0] != "value" or b.requirement(p)[0] != "value":
                    continue
                va, vb = a.rec.values[p], b.rec.values[p]
                sa, sb = pair_states(view, a.rec, b.rec, cutoff)
                unequal = pair_unequal(sa, sb, va, vb, p)
                names = [_side_name(sa), _side_name(sb)]
                extra = {} if view.frame.named or names == [read_name, read_name] else {"interpretations": names}
                refs = [compact(a.rec.triple), compact(b.rec.triple)]
                both = tri_and(a.present_for(p, cutoff), b.present_for(p, cutoff))
                if unequal is False:
                    mb = () if view.frame.named else pair_matched_by(sa, sb, va, vb, p)
                    if mb and both is True:
                        matched.append({"property": p, "expectations": refs, "matched_by": compact_or_list(mb),
                                        **extra})
                    continue
                if both is True and unequal is True:
                    out.append({"property": p, "sides": [
                        {"expectation": refs[0], "value": to_result(va)},
                        {"expectation": refs[1], "value": to_result(vb)}], **extra})
                elif both is not False:
                    ambiguous.append({"property": p, "expectations": refs, **extra})
    out.sort(key=lambda e: (e["property"], e["sides"][0]["expectation"], e["sides"][1]["expectation"]))
    ambiguous.sort(key=lambda e: (e["property"], e["expectations"]))
    matched.sort(key=lambda e: (e["property"], e["expectations"]))
    return out, ambiguous, matched


def pair_unavailable(view: View, subject: str, cutoff: Instant | None = None) -> str | None:
    """README §5 *Limitations*: under a frame naming no interpretation, the name of an
    interpretation the reference does not have that comparing a pair of expectations about the
    subject would need: one side's own interpretation at the cutoff (7.2.4, 7.6.14)."""
    if view.frame.named:
        return None
    cutoff = cutoff if cutoff is not None else view.cutoff
    recs = sorted(view.acc.expectations_about(subject), key=lambda r: r.triple)
    props = {r.triple: {p for p in properties_of(r.values)
                        if not (isinstance(r.values.get(p), dict) and r.values[p].get("@ask") is True)} for r in recs}
    for i, a in enumerate(recs):
        for b in recs[i + 1:]:
            if not props[a.triple] & props[b.triple]:
                continue
            for r in (a, b):
                missing = read_schedule_of(view, r).unavailable_at(cutoff)
                if missing is not None:
                    return missing
    return None
