"""Recorded beginnings and endings (spec 7.6) and ending policies (7.7).

Units of work (7.6.1)
    A conflict story and a change story, each identified by its story Item, and one property
    of an expectation, identified by the expectation's triple and the property name.

Periods (7.6.2)
    The derivation stays the definition. ``derive_unit`` derives a unit's periods from the
    existing derivation of §6 and §7: a conflict story's interval (stories.conflict_periods),
    a change story's periods between reviews (stories.change_periods), and an expectation
    property's in-force periods ended by fulfillment or withdrawal (``expectation_periods``).
    Each period is the content (7.6.6) its begin act and its end acts carry.

Recorded transitions (7.6.4-7.6.10)
    Begin acts target the unit; end acts target their begin act; a ``revise`` reconciliation
    targets one begin or end act, and the latest revision by occurrence time gives the act's
    applicable content. ``recorded_periods`` reads them back.

Maintenance and the transition check (7.6.9, 9.5.8)
    Both are one comparison (``compare``): the unit's begin acts whose applicable content is
    not null are matched in the order of their beginnings with the derived periods in order,
    and each matched begin act's end acts with the period's derived endings. Maintenance
    records what differs (``plan_transitions``); the check reports it. A unit whose own
    interpretation the reference does not have (7.6.14) is not compared: its transitions are
    read as recorded, never revised on that account, and listed by the check as unverified;
    maintenance records only a limitation begin act (7.6.6) for such a unit that has none.

Where the acts are recorded (7.6.7)
    A story's acts are Assertions on its Item. An expectation property whose first period has
    exactly one parent story (7.6.15) is part of that story: its acts and their revisions are
    Assertions on that story Item, named ``<story>/exp:<path>/...`` (README §7); any other
    property keeps act Items of its own. The location is fixed by the property's first act.

Ending policies (7.7)
    A unit's policy is named in its first detection's @frame or its expectation context, and
    each ``adopt_policy`` changes it from its effective time (7.7.2, 7.7.3): the policy
    governing a unit is held as segments over event time. A period is governed from its
    beginning by the policy governing then; it ends under a governing policy at the later of
    that policy's own ending and the start of its uninterrupted governance, or, where the next
    policy takes over first, is governed by that one (``walk_governance``). Each end act gives
    its own policy's ending, whenever that policy governs; reads take the end act of the
    policy governing the period's ending, at that adjusted instant (``governed_end``). The
    reference implements one fixture policy, ``fixture-change-closes-with-directive`` version
    "1" (conformance README §5), and records its end acts as maintenance for every period it
    governs at some instant; end acts of any other policy are read as recorded.

Several records (7.6.6)
    Where several records at one instant cause a transition and every order of them gives it
    the same time and cause, its ``record`` is the list of them in identifier order. Where the
    derivation depends on what is unspecified (an ambiguous interpretation in force, or tied
    statements of one source asserting different values), each resolution is derived and the
    contents are ambiguous where they differ.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from . import instants as T
from .account import Account, parse_target
from .errors import WriteError
from .expectations import Expectation, expectation_context_interp, own_schedule
from .instants import Instant
from .interpretations import LITERAL, Interpretation
from .model import Rec, Triple, act_targets, ref_list
from .normalization import Schedule, sorted_recs
from .stories import (AmbiguousPolicy, DPeriod, Story, _k, _instant_text, all_stories, begin_content,
                      change_periods, conflict_periods, content_records, content_variants, end_content, families,
                      load_story, no_period_state, period_begin_records, period_end_records, periods_state,
                      policy_at, policy_candidates, policy_key_of, policy_out, policy_segments,
                      segment_resolutions, segment_tied_records, story_acts, whole_view)
from .values import assertion_ref, canonical, compact, is_assertion_ref, is_item_ref, properties_of, ref_triple
from .view import View

FIXTURE_POLICY = {"name": "fixture-change-closes-with-directive", "version": "1"}
_IMPLEMENTED = {("fixture-change-closes-with-directive", "1")}

# 7.6.4, 7.6.5: the baseline causes each kind of unit allows
BEGIN_CAUSES = {"conflict": {"disagreement"}, "change": {"revision", "review_withdrawn"},
                "expectation": {"in_force"}}
END_CAUSES = {"conflict": {"alignment", "withdrawal", "fulfillment", "correction", "normalization", "interpretation"},
              "change": {"review", "correction", "reconstructed", "normalization"},
              "expectation": {"fulfillment", "withdrawal"}}
# 7.6.6, 7.6.12: the baseline end causes whose ending has no time, for a story with no period
NO_TIME_CAUSES = {"correction", "reconstructed", "normalization", "interpretation"}
LIMITATION_REASONS = {"relocated_reference", "no_occurrence_time", "interpretation_unavailable"}
TIMELINESS = {"on_time", "late", "ambiguous"}


def policy_key(p: Any) -> tuple | None:
    return policy_key_of(p)


def implemented(policy: dict | None) -> bool:
    return policy_key(policy) in _IMPLEMENTED


# ---------------------------------------------------------------------------------------
# units


@dataclass(frozen=True)
class Unit:
    """A unit of work (7.6.1)."""

    story: str | None = None
    exp: Triple | None = None
    prop: str | None = None

    @property
    def id(self) -> str:
        """README §5 `unit`: the story id, or the expectation's compact reference with the
        property selector."""
        return self.story if self.story is not None else compact(self.exp, self.prop)

    @property
    def order(self) -> tuple:
        """README §7: stories by id, then expectation properties by the expectation's compact
        reference and the property name."""
        if self.story is not None:
            return (0, self.story, "")
        return (1, compact(self.exp), self.prop)

    @property
    def record_id(self) -> str:
        """The unit's record, as a removal plan lists it (8.5.2(c), README §2)."""
        return self.story if self.story is not None else compact(self.exp)


def _escape(part: str) -> str:
    """README §7: `%`, `/`, `|`, `#`, `^` and `>` are percent-escaped in each part."""
    for a, b in (("%", "%25"), ("/", "%2F"), ("|", "%7C"), ("#", "%23"), ("^", "%5E"), (">", "%3E")):
        part = part.replace(a, b)
    return part


def expectation_path(exp: Triple, prop: str) -> str:
    return "exp:" + "/".join(_escape(x) for x in (*exp, prop))


def unit_of_begin(acc: Account, b: Rec) -> Unit | None:
    """The unit a begin act targets (7.6.4): a story through its Item or any of its
    detections, or an expectation property through a reference with a property selector."""
    ts = act_targets(b.values)
    if len(ts) != 1:
        return None
    tg = parse_target(ts[0])
    if tg.kind == "item":
        return Unit(story=tg.item)
    if tg.kind == "assertion" and tg.support is None:
        if tg.prop is not None:
            return Unit(exp=tg.triple, prop=tg.prop)
        d = acc.get(tg.triple)
        raw = acc.rs.assertions.get(tg.triple)
        vals = d.values if d is not None else (raw.values if raw is not None else {})
        if vals.get("@action") == "detect":
            return Unit(story=tg.triple[0])
    return None


def begin_index(acc: Account) -> dict[Unit, list[Rec]]:
    """Every begin act in the account, by its unit (7.6.7: reads find acts by their target)."""
    idx = acc.__dict__.get("_begin_index")
    if idx is None:
        idx = {}
        for b in acc.begin_acts:
            u = unit_of_begin(acc, b)
            if u is not None:
                idx.setdefault(u, []).append(b)
        acc.__dict__["_begin_index"] = idx
    return idx


# ---------------------------------------------------------------------------------------
# an expectation's interpretation and policy (7.6.13, 7.7.2)


def _expectation_reconciliations(acc: Account, exp: Triple, outcome: str) -> list[Rec]:
    return [r for r, tg in acc.acts_targeting(("A", exp))
            if r.action == "reconcile" and r.values.get("@outcome") == outcome and tg.support is None]


def expectation_policy_segments(acc: Account, rec: Rec) -> list:
    """7.7.2, 7.7.3: the policy governing an expectation over event time: the one its
    context's `@context` names, changed by each `adopt_policy` from its effective time."""
    p = acc.ctx(rec.context).get("policy")
    initial = {"name": p["name"], "version": p.get("version")} if isinstance(p, dict) and p.get("name") is not None \
        else None
    return policy_segments(acc, initial, _expectation_reconciliations(acc, rec.triple, "adopt_policy"))


def expectation_policy(acc: Account, rec: Rec, at: Instant | None = None) -> dict | None:
    """The policy governing the expectation at an instant (7.7.2), None for the baseline; the
    end of the history when ``at`` is None."""
    return policy_at(expectation_policy_segments(acc, rec), at)


def expectation_interp_named(acc: Account, rec: Rec) -> tuple[str | None, str | None]:
    """The interpretation the expectation's context names (7.6.13); (None, None) when it names
    none, its interpretation then being the one in force for its subject."""
    return expectation_context_interp(acc, rec)


def expectation_unavailable(acc: Account, rec: Rec) -> str | None:
    """7.6.14: the name of the expectation's own interpretation, at some instant, when it is
    one the reference does not have; None otherwise."""
    return own_schedule(acc, rec).unavailable()


def unavailable_content(name: str | None) -> dict:
    """7.6.6: the limitation content of a unit whose interpretation the reference does not
    have (5.5.4)."""
    return {"limitation": "interpretation_unavailable", "records": [], "interpretation": name}


def unit_interpretation_unavailable(acc: Account, unit: Unit) -> str | None:
    """7.6.14: the name of the unit's own interpretation, a story's (7.2.4, 7.3.8) or an
    expectation's (7.6.13), at some instant, when it is one the reference does not have; None
    otherwise. Every transition of such a unit is read as recorded: it is never derived,
    compared or revised."""
    if unit.story is not None:
        st = load_story(acc, unit.story)
        return st.interp_unavailable if st is not None and not st.malformed else None
    rec = acc.get(unit.exp)
    if rec is None or rec.kind != "expectation":
        return None
    return expectation_unavailable(acc, rec)


def is_own_interpretation(acc: Account, rec: Rec, frame) -> bool:
    """7.6.14: whether a read evaluates the expectation under its own interpretation (7.6.13):
    when its frame names no interpretation, whether the expectation's context names one or not,
    or when its frame names the interpretation that the context names. A frame that names
    another interpretation, or requests literal comparison (4.6.1), evaluates it under that one
    at every instant."""
    if not frame.named:
        return True
    name, version = expectation_interp_named(acc, rec)
    if getattr(frame, "literal", False) or name is None or frame.interp.name != name:
        return False
    return version is None or frame.interp.version is None or version == frame.interp.version


# ---------------------------------------------------------------------------------------
# governance by ending policies (7.7.3)


def walk_governance(segments: list, begin: Instant, end_at: Callable[[Any], Instant | None]) -> list[tuple]:
    """7.7.3: the policies that govern one period, in order, as (policy, start of its
    uninterrupted governance, the instant the period ends under it or None). The period is
    governed from its beginning by the policy governing then. A policy governing it while it is
    open ends it at the later of that policy's own ending (``end_at``) and the start of its
    governance, when that is at or before the next change of policy; otherwise the next policy
    governs it from that change. The last entry's instant is None while the period is open."""
    k = 0
    for i, (s, _p) in enumerate(segments):
        if s is None or _k(s) <= _k(begin):
            k = i
    out = []
    while k < len(segments):
        start, pol = segments[k]
        nxt = segments[k + 1][0] if k + 1 < len(segments) else None
        e = end_at(pol)
        if e is not None:
            eff = e if start is None or _k(e) >= _k(start) else start
            if nxt is None or _k(eff) <= _k(nxt):
                out.append((pol, start, eff))
                return out
        out.append((pol, start, None))
        k += 1
    return out


# ---------------------------------------------------------------------------------------
# derivation (7.6.2)


@dataclass
class Derived:
    unit: Unit
    kind: str | None  # conflict | change | expectation; None: not a unit (7.6.1)
    periods: list[DPeriod]
    segments: list = field(default_factory=lambda: [(None, None)])  # 7.7.2: policy over event time
    malformed: str | None = None
    # 7.6.14: the unit's interpretation, when the reference does not have it. Its periods are
    # then only the limitation content (7.6.6) and its recorded transitions are not compared
    unavailable: str | None = None

    @property
    def policy(self) -> dict | None:
        return self.segments[-1][1]

    @property
    def ever_policies(self) -> list:
        """The non-baseline policies that govern the unit at some instant, or are candidates to
        govern it (7.7.2)."""
        return segments_policies(self.segments)

    @property
    def policy_derived(self) -> bool:
        """Whether the unit is governed at some instant by a policy the reference implements,
        whose end acts it derives (7.7.5)."""
        return self.unavailable is None and any(implemented(p) for p in self.ever_policies)


def _ambiguous_merge(a: Any, b: Any, records: list[dict], policy: Any = "absent") -> Any:
    if _canon(a) == _canon(b):
        return a
    out: dict[str, Any] = {"ambiguous": [a, b], "records": records}
    if policy != "absent":
        out["policy"] = policy
    return out


def _merge_period_lists(lists: list[list[DPeriod]], records: list[dict]) -> list[DPeriod]:
    """The periods a unit has under several resolutions of an ambiguous derivation (7.6.6):
    the common contents, and an ambiguous content where they differ."""
    out = []
    n = max(len(x) for x in lists)
    for i in range(n):
        begins = [x[i].begin if i < len(x) else None for x in lists]
        ends = [x[i].end if i < len(x) else None for x in lists]
        begin, end = begins[0], ends[0]
        for b in begins[1:]:
            begin = _merge_into(begin, b, records)
        for e in ends[1:]:
            end = _merge_into(end, e, records, None)
        out.append(DPeriod(begin, end))
    return out


def _merge_into(acc_c: Any, c: Any, records: list[dict], policy: Any = "absent") -> Any:
    if _canon(acc_c) == _canon(c):
        return acc_c
    cands = list(acc_c["ambiguous"]) if isinstance(acc_c, dict) and "ambiguous" in acc_c else [acc_c]
    for x in (c["ambiguous"] if isinstance(c, dict) and "ambiguous" in c else [c]):
        if all(_canon(x) != _canon(y) for y in cands):
            cands.append(x)
    if len(cands) == 1:
        return cands[0]
    out: dict[str, Any] = {"ambiguous": cands, "records": records}
    if policy != "absent":
        out["policy"] = policy
    return out


def _iobj(i: Interpretation | None) -> dict | None:
    return None if i is None or i.name is None else {"name": i.name, "version": i.version}


def expectation_periods(acc: Account, rec: Rec, prop: str, view: View | None = None,
                        interp: Interpretation | None = None, sched: Schedule | None = None) -> list[DPeriod]:
    """The periods of one expectation property (7.6.2): one per in-force period (6.3.3),
    beginning at its establishment time and ending at the qualifying moment (6.5.1) or when
    the in-force period ends by withdrawal (6.7.2), whichever governs (6.6.1). Fulfillment
    is terminal (6.5.2). Where evidence's qualification depends on an unspecified order, the
    contents are ambiguous with both candidates (7.6.6). Derived in the record perspective
    under the expectation's own interpretation (7.6.13) unless a view and an interpretation
    (``interp``, at every instant, or ``sched``, over time) are given. The fulfillment end
    names the interpretation the property was fulfilled under and, where the evidence meets
    the requirement only under one a normalization put in force, that normalization."""
    if acc.limits.get(rec.triple):
        corr, act = acc.limits[rec.triple][0]
        return [DPeriod({"limitation": "relocated_reference",
                         "records": [assertion_ref(corr), assertion_ref(act)]})]
    if interp is not None:
        sched = Schedule.fixed(interp)
    if sched is None:
        sched = own_schedule(acc, rec)
        missing = sched.unavailable()
        if missing is not None:
            e = Expectation(whole_view(acc, LITERAL), rec, LITERAL)
            ps, _ = e.periods(prop, None)
            if not ps:
                return []
            return [DPeriod(unavailable_content(missing))]
    if sched.ambiguous:
        records = [assertion_ref(r.triple) for r in sched.ambiguous_records()]
        lists = [_expectation_periods(acc, rec, prop, view, res) for res in sched.resolutions()]
        return _merge_period_lists(lists, records) if any(lists) else []
    return _expectation_periods(acc, rec, prop, view, sched)


def _expectation_periods(acc: Account, rec: Rec, prop: str, view: View | None, sched: Schedule) -> list[DPeriod]:
    view = view or whole_view(acc)
    cutoff = view.cutoff
    e = Expectation(view, rec, schedule=sched)
    ps, _ = e.periods(prop, cutoff)
    if not ps:
        return []
    cands, _ = e.candidates(prop, cutoff)
    definite = [c for c in cands if c.status is True]
    maybe = [c for c in cands if c.status is None]
    q = e._first(definite)
    q_alt = e._first(definite + maybe) if maybe else q

    def build(qq) -> list[DPeriod]:
        out = []
        for p in ps:
            b = begin_content(p.start, period_begin_records(acc, p), "in_force")
            if qq is not None and qq.period is p:
                tl, _ = e.timeliness(qq)
                fulfilled_under = qq.state.interp if qq.state is not None and qq.state.interp is not None else e.interp
                out.append(DPeriod(b, end_content(qq.t, [qq.evidence] + [c.evidence for c in qq.tied], "fulfillment",
                                                  None, {"timeliness": tl or "ambiguous",
                                                         "interpretation": _iobj(fulfilled_under)},
                                                  matched=qq.matched_by)))
                break
            if p.end is not None:
                out.append(DPeriod(b, end_content(p.end, period_end_records(acc, p), "withdrawal")))
            else:
                out.append(DPeriod(b))
        return out

    pess = build(q)
    if q_alt is q:
        return pess
    opt = build(q_alt)
    records = [assertion_ref(c.evidence.triple) for c in sorted(maybe, key=lambda c: c.evidence.triple)]
    records = [r for i, r in enumerate(records) if r not in records[:i]]
    out = []
    for i in range(max(len(pess), len(opt))):
        a = pess[i] if i < len(pess) else None
        b = opt[i] if i < len(opt) else None
        begin = _ambiguous_merge(a.begin if a else None, b.begin if b else None, records)
        end = _ambiguous_merge(a.end if a else None, b.end if b else None, records, None)
        out.append(DPeriod(begin, end))
    return out


def _with_policy(content: Any, policy: dict) -> Any:
    if not isinstance(content, dict):
        return content
    out = dict(content)
    if "ambiguous" in out:
        out["ambiguous"] = [_with_policy(c, policy) for c in out["ambiguous"]]
    if "policy" in out or "cause" in out or "ambiguous" in out or "limitation" in out:
        out["policy"] = policy
    return out


def _earliest_definite(content: Any) -> tuple[Instant | None, Any, Any]:
    for v in sorted((v for v in content_variants(content) if isinstance(v, dict) and isinstance(v.get("at"), str)),
                    key=lambda v: _k(T.parse_instant(v["at"]))):
        return T.parse_instant(v["at"]), v.get("record"), v
    return None, None, None


def _review_withdrawal(acc: Account, r: Rec) -> tuple[Instant, Rec] | None:
    ws = [(acc.effective(w), w) for w, tg in acc.acts_targeting_triple(r.triple)
          if w.action == "withdraw" and tg.support is None]
    ws = [(e, w) for e, w in ws if e is not None]
    return min(ws, key=lambda x: (_k(x[0]), x[1].triple)) if ws else None


def _baseline_periods_of(acc: Account, erec: Rec, prop: str) -> list[tuple[Any, Any]]:
    """The baseline (begin, end) contents of an expectation property: derived where its
    interpretation is available (equal to the recorded ones, I-17), read as recorded where it
    is not (7.6.14; README §5 *Ending policies*: the fixture policy needs no interpretation)."""
    unit = Unit(exp=erec.triple, prop=prop)
    if expectation_unavailable(acc, erec) is not None:
        return [(rp.begin.content, rp.end_content(None)) for rp in recorded_periods(acc, unit)
                if rp.begin.content is not None]
    return [(dp.begin, dp.end) for dp in expectation_periods(acc, erec, prop)]


def directive_end(acc: Account, review: Rec, policy: dict) -> Any:
    """README §5, fixture policy: a period that a directive ends under the baseline ends once
    every expectation property the directive covers through @establishes or @reaffirms has
    ended under the baseline (the ending of its period in force at the directive's effective
    time), at the latest of those endings or at the directive's effective time if later,
    with cause `directive_closed` and as record the ending record of the property that ended
    last, or the list of them where several ended last at one instant (7.6.6). When the
    directive's withdrawal takes effect before that, or at the instant of the last of those
    endings, it ends at the withdrawal's effective time with cause `withdrawal`."""
    eff = acc.effective(review)
    covered: list[tuple[Rec, str]] = []
    for key in ("@establishes", "@reaffirms"):
        for ref in ref_list(review.values, key):
            if not is_assertion_ref(ref):
                continue
            erec = acc.get(ref_triple(ref))
            if erec is None or erec.kind != "expectation":
                continue
            props = [ref["property"]] if ref.get("property") else sorted(properties_of(erec.values))
            covered += [(erec, p) for p in props if (erec, p) not in covered]
    endings: list[tuple[Instant, Any]] = []
    still_open = False
    for erec, p in covered:
        sel = None
        for b, en in _baseline_periods_of(acc, erec, p):
            at, _r, _v = _earliest_definite(b)
            if at is not None and eff is not None and _k(at) <= _k(eff):
                sel = (b, en)
        if sel is None:
            continue
        at, rec, _v = _earliest_definite(sel[1])
        if at is None:
            still_open = True
            continue
        endings.append((at, rec))
    w = _review_withdrawal(acc, review)
    if still_open:
        return end_content(w[0], w[1], "withdrawal", policy) if w else None
    if endings:
        top = max(_k(at) for at, _r in endings)
        last = [(at, r) for at, r in endings if _k(at) == top]
        at_last = last[0][0]
        refs = []
        for _at, r in last:
            refs += [r] if is_assertion_ref(r) else ([x for x in r if is_assertion_ref(x)] if isinstance(r, list) else [])
        recs_last = sorted_recs([acc.get(ref_triple(x)) for x in refs])
        unordered = [at for at, _r in endings if _k(at) != top and T.before(at, at_last) is not True]
    else:
        at_last, recs_last, unordered = eff, [review], []
    at = at_last if eff is None or _k(at_last) >= _k(eff) else eff
    if w is not None and at is not None and _k(w[0]) <= _k(at):
        return end_content(w[0], w[1], "withdrawal", policy)
    out = end_content(at, recs_last, "directive_closed", policy)
    if unordered:
        cands = [out] + [end_content(u if eff is None or _k(u) >= _k(eff) else eff, recs_last, "directive_closed",
                                     policy) for u in unordered]
        out = {"ambiguous": cands, "records": [assertion_ref(r.triple) for r in recs_last], "policy": policy}
    return out


def _policy_ending(acc: Account, kind: str, p: DPeriod, policy: dict) -> Any:
    """The fixture policy's own ending of a period (README §5): approvals, conflict stories
    and expectation properties end as under the baseline; a directive closes as
    ``directive_end`` gives."""
    if p.end is None:
        return None
    if kind == "change" and isinstance(p.end, dict) and p.end.get("cause") == "review":
        for r in content_records(acc, p.end):
            if r.values.get("@outcome") == "change_required":
                return directive_end(acc, r, policy)
    return _with_policy(p.end, policy)


def apply_policy(acc: Account, kind: str, periods: list[DPeriod], segments: list,
                 recorded: list | None = None) -> None:
    """7.7.3: for each period, the endings of the implemented policies that govern it at some
    instant, or are candidates to govern it (``policy_ends``), and ``policy_end``, the ending
    under the policy that governs the period's ending. A policy's end act gives its own ending
    of the period whenever it governs. The ending of a policy the reference does not implement
    is read from its end act recorded for the period (``recorded``, the unit's recorded periods
    with a beginning, in order), since only whatever implements that policy can derive it
    (7.7.5). Where tied `adopt_policy` acts leave the governing policy ambiguous (7.7.2), the
    period is evaluated under each candidate, and ``policy_end`` is the common ending or the
    ambiguous content of the candidates' endings, with the tied acts as records."""
    resolutions = segment_resolutions(segments)
    tied = [assertion_ref(r.triple) for r in segment_tied_records(segments)]
    dated = [p for p in periods if p.begin is not None]
    for p in periods:
        if p.begin is None:
            continue
        at, _r, _v = _earliest_definite(p.begin)
        if at is None:
            continue
        own: dict = {}
        i = dated.index(p)
        rp = recorded[i] if recorded is not None and i < len(recorded) else None

        def end_at(pol, p=p, own=own, rp=rp):
            if pol is None:
                c = p.end
            elif implemented(pol):
                key = policy_key(pol)
                if key not in own:
                    own[key] = _policy_ending(acc, kind, p, pol)
                c = own[key]
            else:
                c = rp.end_content(pol) if rp is not None else None
            t, _r, _v = _earliest_definite(c)
            return t

        ends = []
        for segs in resolutions:
            walk = walk_governance(segs, at, end_at)
            for pol, _start, _eff in walk:
                if pol is not None and implemented(pol):
                    key = policy_key(pol)
                    if key not in own:
                        own[key] = _policy_ending(acc, kind, p, pol)
                    p.policy_ends[key] = own[key]
            last, _start, eff = walk[-1]
            if eff is None or (last is not None and not implemented(last)):
                ends.append(None)
            else:
                # the ending a read reports: the governing policy's end act, at the later of its
                # own `at` and the start of that policy's uninterrupted governance (7.7.3, 7.6.14)
                ends.append(adjusted(p.end if last is None else p.policy_ends.get(policy_key(last)), eff))
        p.policy_end = _merge_candidates(ends, tied)
    for p in periods:
        if p.begin is None and p.end is not None:
            # 7.6.12: a story with no period has its ending under every policy
            for pol in segments_policies(segments):
                if implemented(pol):
                    p.policy_ends[policy_key(pol)] = _with_policy(p.end, pol)
            ends = []
            for segs in resolutions:
                last = segs[-1][1]
                ends.append(p.end if last is None else p.policy_ends.get(policy_key(last)))
            p.policy_end = _merge_candidates(ends, tied)


def _merge_candidates(contents: list, records: list[dict]) -> Any:
    """The common content of a result evaluated under each candidate of an ambiguous policy
    (7.7.2), or the ambiguous content of the distinct ones, with the tied acts as records."""
    distinct: list = []
    for c in contents:
        if all(_canon(c) != _canon(x) for x in distinct):
            distinct.append(c)
    if len(distinct) == 1:
        return distinct[0]
    return {"ambiguous": distinct, "records": records}


def segments_policies(segments: list) -> list:
    """The non-baseline policies of a unit's policy history, candidates of an ambiguous one
    included (7.7.2)."""
    out = []
    for _s, seg in segments:
        for p in policy_candidates(seg):
            if p is not None and all(policy_key(p) != policy_key(x) for x in out):
                out.append(p)
    return out


def adjusted(content: Any, eff: Instant | None) -> Any:
    """A definite end content whose `at` is moved to ``eff``, the instant at which the period
    ends under its governing policies (7.7.3); other contents as they are."""
    if eff is None or not isinstance(content, dict) or "ambiguous" in content or "limitation" in content:
        return content
    own = T.parse_instant(content.get("at")) if isinstance(content.get("at"), str) else None
    if own is not None and _k(own) == _k(eff):
        return content
    return dict(content, at=eff.text)


class DeriveCache:
    """Families per subject, shared by the units of one comparison: each subject's families are
    formed once, from the account's stories indexed by subject (``stories.all_stories``)."""

    def __init__(self, acc: Account) -> None:
        self.acc = acc
        self.fams: dict[str, dict] = {}

    def family(self, st: Story):
        if st.subject not in self.fams:
            m = {}
            for f in families(self.acc, all_stories(self.acc, {st.subject})):
                for sid in f.by_id:
                    m[sid] = f
            self.fams[st.subject] = m
        return self.fams[st.subject].get(st.id)


def _story_periods(acc: Account, st: Story, cache: DeriveCache) -> list[DPeriod] | None:
    """A story's derived periods. Where the derivation depends on what is unspecified (an
    ambiguous interpretation in force, 7.3.8, or tied statements of one source asserting
    different values, 4.5.3), the periods under each resolution, merged into ambiguous
    contents where they differ (7.6.6)."""
    fam = cache.family(st) if st.kind == "conflict" else None
    if st.kind == "conflict":
        if fam is None:
            return conflict_periods(acc, st, None)
        if not (fam.sched.ambiguous or fam.tied):
            return conflict_periods(acc, st, fam)
        records = [assertion_ref(r.triple) for r in fam.variant_records()]
        lists = [conflict_periods(acc, st, f) for f in fam.variants()]
    else:
        if not st.sched.ambiguous:
            return change_periods(acc, st)
        records = [assertion_ref(r.triple) for r in st.sched.ambiguous_records()]
        lists = [change_periods(acc, st, res) for res in st.sched.resolutions()]
    if any(ps is None for ps in lists):
        return None
    if all(len(x) == len(lists[0]) and all(_canon(a.begin) == _canon(b.begin) and _canon(a.end) == _canon(b.end)
                                           for a, b in zip(x, lists[0])) for x in lists):
        return lists[0]
    return _merge_period_lists(lists, records)


def derive_unit(acc: Account, unit: Unit, cache: DeriveCache | None = None) -> Derived:
    """A unit's derived periods under the baseline, with the endings of the policies the
    reference implements, for the periods they govern at some instant (7.7.3)."""
    cache = cache or DeriveCache(acc)
    if unit.story is not None:
        st = load_story(acc, unit.story)
        if st is None:
            return Derived(unit, None, [])
        if st.malformed:
            return Derived(unit, None, [], malformed=st.malformed)
        if st.kind not in ("conflict", "change"):
            return Derived(unit, None, [], malformed="story_unresolvable")
        if st.interp_unavailable is not None:
            # 7.6.14: the story's transitions cannot be derived without its interpretation
            return Derived(unit, st.kind, [DPeriod(unavailable_content(st.interp_unavailable))], st.policy_segments,
                           unavailable=st.interp_unavailable)
        periods = _story_periods(acc, st, cache)
        if periods is None:
            return Derived(unit, None, [], malformed="story_unresolvable")
        d = Derived(unit, st.kind, periods, st.policy_segments)
        if d.policy_derived:
            apply_policy(acc, st.kind, periods, st.policy_segments, _dated_recorded(acc, unit))
        return d
    rec = acc.get(unit.exp)
    if rec is None or rec.kind != "expectation":
        return Derived(unit, "expectation", [])
    segments = expectation_policy_segments(acc, rec)
    periods = expectation_periods(acc, rec, unit.prop) if unit.prop in properties_of(rec.values) else []
    unavailable = unit_interpretation_unavailable(acc, unit)
    d = Derived(unit, "expectation", periods, segments, unavailable=unavailable)
    if d.policy_derived:
        apply_policy(acc, "expectation", periods, segments, _dated_recorded(acc, unit))
    return d


def _dated_recorded(acc: Account, unit: Unit) -> list:
    return [rp for rp in recorded_periods(acc, unit) if rp.begin.content is not None]


# ---------------------------------------------------------------------------------------
# recorded transitions (7.6.4-7.6.10)


@dataclass
class RAct:
    rec: Rec
    content: Any  # applicable content (7.6.10)
    revised_by: Rec | None = None
    revisions: list[Rec] = field(default_factory=list)

    @property
    def policy(self) -> Any:
        own = self.rec.values.get("@period")
        return own.get("policy") if isinstance(own, dict) else None


def revisions_of(acc: Account, act: Rec) -> list[Rec]:
    return [r for r, tg in acc.acts_targeting(("A", act.triple))
            if r.action == "reconcile" and r.values.get("@outcome") == "revise"]


def applicable(acc: Account, act: Rec) -> RAct:
    """The applicable content of a begin or end act: that of its latest revision by
    occurrence time, or the act's own; a tie without @after evidence is ambiguous (7.6.10)."""
    revs = revisions_of(acc, act)
    if not revs:
        return RAct(act, act.values.get("@period"))
    latest = acc.latest_of(revs)
    if len(latest) == 1:
        return RAct(act, latest[0].values.get("@period"), latest[0], revs)
    contents = []
    for r in latest:
        c = r.values.get("@period")
        if all(_canon(c) != _canon(x) for x in contents):
            contents.append(c)
    if len(contents) == 1:
        return RAct(act, contents[0], latest[-1], revs)
    out: dict[str, Any] = {"ambiguous": contents, "records": [assertion_ref(r.triple) for r in latest]}
    if act.action == "end":
        out["policy"] = RAct(act, None).policy
    return RAct(act, out, None, revs)


@dataclass
class RPeriod:
    begin: RAct
    ends: list[RAct]

    def ends_for(self, policy: Any) -> list[RAct]:
        k = policy_key(policy)
        return [e for e in self.ends if policy_key(e.policy) == k]

    def end_content(self, policy: Any) -> Any:
        """The applicable content of the period's end act under the policy, None while it
        has none whose applicable content is not null (README §5 *Periods*)."""
        for e in self.ends_for(policy):
            if e.content is not None:
                return e.content
        return None

    def end_act(self, policy: Any) -> RAct | None:
        for e in self.ends_for(policy):
            if e.content is not None:
                return e
        return None


def _begin_order(c: Any) -> tuple:
    """Periods are ordered by the beginning's `at`; an ambiguous beginning by the earliest
    of its definite candidates (README §5 *Periods*, 9.5.8)."""
    at, _r, _v = _earliest_definite(c)
    if at is not None:
        return (0, at.start, at.end)
    return (1 if c is not None else 2,)


def recorded_periods(acc: Account, unit: Unit) -> list[RPeriod]:
    """The unit's begin acts with their applicable contents and their end acts, null
    beginnings last, in period order."""
    out = []
    for b in begin_index(acc).get(unit, []):
        ends = [applicable(acc, r) for r, _tg in acc.acts_targeting(("A", b.triple)) if r.action == "end"]
        ends.sort(key=lambda e: (acc.sort_key(e.rec)[:2], e.rec.triple))
        out.append(RPeriod(applicable(acc, b), ends))
    out.sort(key=lambda rp: (_begin_order(rp.begin.content), compact(rp.begin.rec.triple)))
    return out


# ---------------------------------------------------------------------------------------
# comparison (7.6.9, 9.5.8)


def _canon(c: Any) -> Any:
    """Contents compare as recorded values; two ambiguous contents are equal when they have
    the same candidates, in any order, and the same records (9.5.8)."""
    if isinstance(c, dict) and "ambiguous" in c:
        return ("ambiguous", frozenset(repr(_canon(x)) for x in c.get("ambiguous") or []),
                frozenset(repr(canonical(r)) for r in c.get("records") or []), canonical(c.get("policy")))
    return canonical(c)


def same_content(a: Any, b: Any) -> bool:
    return _canon(a) == _canon(b)


@dataclass
class Diff:
    unit: Unit
    transition: str  # begin | end
    difference: str  # missing | extra | different
    act: RAct | None
    policy: Any
    recorded: Any = None
    derived: Any = None
    period: int = 0  # index of the derived period (missing acts) or of the begin act
    begin: RAct | None = None  # for a missing end act: its begin act, if it exists
    position: tuple = ()


def compare(derived: Derived, rps: list[RPeriod]) -> list[Diff]:
    """The differences between a unit's applicable recorded transitions and its derived ones
    (9.5.8), in period order: each period's begin act, then its baseline end act, then its
    end act under each policy the reference implements that governs the period at some
    instant (7.7.3, 7.7.5)."""
    u = derived.unit
    impl = [p for p in derived.ever_policies if implemented(p)] if derived.unavailable is None else []
    diffs: list[Diff] = []
    nonnull = [rp for rp in rps if rp.begin.content is not None]
    nulls = [rp for rp in rps if rp.begin.content is None]
    dper = [p for p in derived.periods if p.begin is not None]
    noper = [p for p in derived.periods if p.begin is None]

    def pols_for(p: DPeriod | None) -> list:
        if p is None:
            return [None]
        return [None] + [pol for pol in impl if policy_key(pol) in p.policy_ends]

    def derived_end(p: DPeriod, pol: Any) -> Any:
        return p.end if pol is None else p.policy_ends.get(policy_key(pol))

    def match_end(i: int, rp: RPeriod | None, p: DPeriod | None, pol: Any) -> None:
        want = derived_end(p, pol) if p is not None else None
        ends = rp.ends_for(pol) if rp is not None else []
        pos = (i, 1 if pol is None else 2)
        if not ends:
            if want is not None:
                diffs.append(Diff(u, "end", "missing", None, pol, derived=want, period=i, begin=rp.begin if rp else None,
                                  position=pos))
            return
        first, rest = ends[0], ends[1:]
        if want is None:
            rest = ends
        elif not same_content(first.content, want):
            diffs.append(Diff(u, "end", "different", first, pol, first.content, want, i, rp.begin, pos))
        for e in rest:
            if e.content is not None:
                diffs.append(Diff(u, "end", "extra", e, pol, e.content, None, i, rp.begin, pos))

    used_extra = None
    for i, rp in enumerate(nonnull):
        if i < len(dper):
            p = dper[i]
            if not same_content(rp.begin.content, p.begin):
                diffs.append(Diff(u, "begin", "different", rp.begin, None, rp.begin.content, p.begin, i, rp.begin,
                                  (i, 0)))
            for pol in pols_for(p):
                match_end(i, rp, p, pol)
        else:
            if noper and used_extra is None and not nulls:
                used_extra = rp  # revised to null, it is the begin act of the story with no period
            diffs.append(Diff(u, "begin", "extra", rp.begin, None, rp.begin.content, None, i, rp.begin, (i, 0)))
            if rp is not used_extra:
                for pol in pols_for(None):
                    match_end(i, rp, None, pol)
    base = len(nonnull)
    if noper:
        p = noper[0]
        holder = None
        for rp in nulls:
            if rp.end_content(None) is not None:
                holder = rp
                break
        holder = holder or (nulls[0] if nulls else used_extra)
        if holder is None:
            if not rps:
                diffs.append(Diff(u, "begin", "missing", None, None, derived=None, period=len(dper), position=(base + 1, 0)))
                for pol in pols_for(p):
                    want = derived_end(p, pol)
                    if want is not None:
                        diffs.append(Diff(u, "end", "missing", None, pol, derived=want, period=len(dper),
                                          position=(base + 1, 1 if pol is None else 2)))
        else:
            for pol in pols_for(p):
                match_end(base, holder, p, pol)
        others = [rp for rp in nulls if rp is not holder]
    else:
        others = nulls
    for rp in others:
        for pol in pols_for(None):
            match_end(base + 2, rp, None, pol)
    for j, p in enumerate(dper[len(nonnull):], start=len(nonnull)):
        diffs.append(Diff(u, "begin", "missing", None, None, derived=p.begin, period=j, position=(j, 0)))
        for pol in pols_for(p):
            want = derived_end(p, pol)
            if want is not None:
                diffs.append(Diff(u, "end", "missing", None, pol, derived=want, period=j,
                                  position=(j, 1 if pol is None else 2)))
    return diffs


def governed_end(rp: RPeriod, segments: list) -> tuple[Any, RAct | None, Any, list]:
    """7.7.3, 7.6.14: a recorded period's ending under the unit's policies: (the policy
    governing its ending, or the one governing it while it is open; that policy's end act; the
    act's content with `at` the instant the period ends under them, the later of the act's own
    `at` and the start of that policy's uninterrupted governance; the policies that govern the
    period at some instant, or are candidates to govern it). The act and content are None while
    the period is open. Where tied `adopt_policy` acts leave the governing policy ambiguous
    (7.7.2) and the candidates give different endings, the policy is the ``AmbiguousPolicy``,
    the act None and the content the ambiguous content of the candidates' endings (``None``
    where the period has not ended under one), with the tied acts as records."""
    results = [_governed_end(rp, segs) for segs in segment_resolutions(segments)]
    governing: list = []
    for r in results:
        for g in r[3]:
            if all(policy_key(g) != policy_key(x) for x in governing):
                governing.append(g)
    first = results[0]
    if all(policy_key(r[0]) == policy_key(first[0]) and _canon(r[2]) == _canon(first[2])
           and (r[1] is None) == (first[1] is None) and (r[1] is None or r[1].rec.triple == first[1].rec.triple)
           for r in results):
        return first[0], first[1], first[2], governing
    amb = next((p for _s, p in segments if isinstance(p, AmbiguousPolicy)), None)
    tied = [assertion_ref(r.triple) for r in segment_tied_records(segments)]
    return amb, None, _merge_candidates([r[2] for r in results], tied), governing


def governed_ends(rp: RPeriod, segments: list) -> list[tuple[Any, RAct | None, Any, list]]:
    """``governed_end`` under each candidate history of an ambiguous policy (7.7.2)."""
    return [_governed_end(rp, segs) for segs in segment_resolutions(segments)]


def _governed_end(rp: RPeriod, segments: list) -> tuple[Any, RAct | None, Any, list]:
    at, _r, _v = _earliest_definite(rp.begin.content)
    if at is None:
        pol = segments[-1][1]
        act = rp.end_act(pol)
        return pol, act, act.content if act is not None else None, [pol]

    def end_at(pol):
        t, _r2, _v2 = _earliest_definite(rp.end_content(pol))
        return t

    walk = walk_governance(segments, at, end_at)
    pol, _start, eff = walk[-1]
    governing = [w[0] for w in walk]
    if eff is None:
        return pol, None, None, governing
    act = rp.end_act(pol)
    return pol, act, adjusted(act.content if act is not None else None, eff), governing


def check_units(acc: Account, units: list[Unit], cache: DeriveCache | None = None) -> tuple[list[Diff], list[Rec]]:
    """The transition check (9.5.8) over some units: the differences, and the acts listed as
    unverified: the end acts naming a policy the reference does not implement that governs
    their unit at their period's ending (7.7.3), and the begin and end acts of a unit whose
    interpretation the reference does not have, whose transitions are not compared (7.6.14).
    End acts naming a policy that does not govern their period's ending are neither compared
    nor listed."""
    cache = cache or DeriveCache(acc)
    diffs: list[Diff] = []
    unverified: list[Rec] = []
    for u in units:
        d = derive_unit(acc, u, cache)
        rps = recorded_periods(acc, u)
        if d.unavailable is not None:
            for rp in rps:
                unverified.append(rp.begin.rec)
                unverified += [e.rec for e in rp.ends_for(None)]
                for pol in segments_policies(d.segments):
                    unverified += [e.rec for e in rp.ends_for(pol)]
            continue
        diffs += compare(d, rps)
        for rp in rps:
            for pol, _act, _content, _gov in governed_ends(rp, d.segments):
                if pol is not None and not implemented(pol):
                    unverified += [e.rec for e in rp.ends_for(pol) if e.rec not in unverified]
    return diffs, unverified


def directing_stories(acc: Account, subjects: set[str]) -> set[str]:
    """The stories whose reviews establish or reaffirm an expectation about one of the
    subjects: under the fixture policy a directed change closes when the expectations its
    directive covers end (README §5), so their maintenance is keyed by those subjects too."""
    out: set[str] = set()
    for s in subjects:
        for rec in acc.expectations_about(s):
            for r, _key in acc.establishes_of.get(rec.triple, []):
                for ref in act_targets(r.values):
                    tg = parse_target(ref)
                    if tg.kind == "item" and acc.is_story(tg.item):
                        out.add(tg.item)
                    elif tg.kind == "assertion":
                        d = acc.get(tg.triple)
                        if d is not None and d.action == "detect":
                            out.add(d.item)
    return out


def units_about(acc: Account, subjects: set[str] | None) -> list[Unit]:
    """The units whose subject is among ``subjects`` (None: every unit in the account):
    recorded stories, expectation properties, and every unit a begin act targets."""
    units: set[Unit] = set()
    for st in all_stories(acc, subjects):
        units.add(Unit(story=st.id))
    for sid in subjects or ():
        if acc.is_story(sid):
            units.add(Unit(story=sid))
    for rec in acc.records.values():
        if rec.kind == "expectation" and (subjects is None or rec.item in subjects):
            for p in properties_of(rec.values):
                units.add(Unit(exp=rec.triple, prop=p))
    for u in begin_index(acc):
        if u.story is not None:
            st = load_story(acc, u.story)
            subj = st.subject if st is not None else None
            if subjects is None or u.story in subjects or subj in subjects:
                units.add(u)
        elif subjects is None or u.exp[0] in subjects:
            units.add(u)
    return sorted(units, key=lambda u: u.order)


# ---------------------------------------------------------------------------------------
# maintenance (7.6.9, README §7 *Recorded transitions*)


@dataclass
class NewRecord:
    items: list[tuple[str, str, dict]]  # (id, kind, definition)
    triple: Triple
    values: dict


def _event(ctx_id: str, at: str) -> tuple[str, str, dict]:
    return (ctx_id, "event", {"@context": {"role": "event", "at": at}})


class TransitionWriter:
    """Turns the differences of a unit into the records maintenance writes, with the names of
    README §7."""

    def __init__(self, acc: Account, exists: Callable[[str], bool], trigger: Triple | None,
                 trigger_at: Instant | None = None, basis: dict | None = None,
                 exists_many: Callable[[set], set] | None = None) -> None:
        self.acc = acc
        self._exists = exists
        self._exists_many = exists_many
        self._checked: set = set()
        self._taken: set = set()
        self.trigger = trigger
        rec = acc.get(trigger) if trigger is not None else None
        when = trigger_at if trigger_at is not None else (acc.occurrence(rec) if rec is not None else None)
        self.trigger_at = _instant_text(when) if when is not None else None
        self.basis = basis if basis is not None else (assertion_ref(trigger) if trigger is not None else None)
        self.reserved: set[str] = set()
        self.location: dict[Unit, str | None] = {}

    def exists(self, name: str) -> bool:
        if name in self._checked:
            return name in self._taken
        return self._exists(name)

    def prefetch(self, names: set) -> None:
        """Whether each of these names is an Item already, in one lookup (``exists_many``)."""
        names = set(names) - self._checked
        if not names or self._exists_many is None:
            return
        self._taken |= self._exists_many(names)
        self._checked |= names

    def _free(self, fmt: Callable[[int], str]) -> str:
        n = 1
        while fmt(n) in self.reserved or self.exists(fmt(n)):
            n += 1
        self.reserved.add(fmt(n))
        return fmt(n)

    def candidate_names(self, unit: Unit, diffs: list) -> set:
        """The names ``_free`` may test for a unit's new acts and revisions (README §7)."""
        k = len(diffs) + len(recorded_periods(self.acc, unit)) * 3 + 2
        letters = ("b", "e", "v")
        if unit.story is not None:
            return {f"{unit.story}/{x}{n}" for x in letters for n in range(1, k + 1)}
        path = expectation_path(unit.exp, unit.prop)
        first = next((d.derived for d in diffs if d.transition == "begin" and d.difference == "missing"), None)
        story = self.holder(unit, first)
        if story is not None:
            return {f"{story}/{path}/{x}{n}" for x in letters for n in range(1, k + 1)}
        return {f"{path}/{x}{n}" for x in letters for n in range(1, k + 1)}

    def _at(self, fallback: Any) -> str:
        if self.trigger_at is not None:
            return self.trigger_at
        at, _r, _v = _earliest_definite(fallback)
        return at.text if at is not None else "1970-01-01T00:00:00+00:00"

    def holder(self, unit: Unit, first_begin: Any = None) -> str | None:
        """7.6.7, README §7: the story whose Item holds an expectation property's acts, or None
        for acts of its own. It is fixed when the property's first act is recorded: on the one
        story that is the parent of its first period (7.6.15), unless it is then ambiguous
        whether the first period has exactly one parent, or its beginning is a limitation."""
        if unit.story is not None:
            return unit.story
        if unit in self.location:
            return self.location[unit]
        found = recorded_holder(self.acc, unit)
        if found is None and not _has_acts(self.acc, unit):
            rec = self.acc.get(unit.exp)
            if rec is not None and isinstance(first_begin, dict) and "ambiguous" not in first_begin \
                    and "limitation" not in first_begin:
                parents = parents_of(self.acc, rec, unit.prop, first_begin)
                if len(parents) == 1:
                    found = parents[0]
        self.location[unit] = found
        return found

    def begin(self, unit: Unit, content: Any) -> NewRecord:
        values = {"@action": "begin", "@targets": [self._unit_target(unit)], "@period": content}
        return self._act(unit, "b", "begin", values, content)

    def end(self, unit: Unit, begin: Triple, content: Any) -> NewRecord:
        values = {"@action": "end", "@targets": [assertion_ref(begin)], "@period": content}
        return self._act(unit, "e", "end", values, content)

    def revise(self, unit: Unit, act: RAct, content: Any) -> NewRecord:
        at = self._at(content if content is not None else act.content)
        values: dict[str, Any] = {"@action": "reconcile", "@targets": [assertion_ref(act.rec.triple)],
                                  "@outcome": "revise", "@period": content,
                                  "@basis": [self.basis] if self.basis is not None else []}
        if act.revisions:
            # 7.6.10: a revision of an act that already has one is not before it, and carries
            # @after when the two are equal or unordered
            latest = self.acc.latest_of(act.revisions)[-1]
            lat = self.acc.occurrence(latest)
            mine = T.parse_instant(at)
            if lat is not None and (mine is None or T.after(mine, lat) is not True):
                at = _instant_text(lat)
                values["@after"] = assertion_ref(latest.triple)
        if unit.story is not None:
            vid = self._free(lambda n: f"{unit.story}/v{n}")
            ctx = f"{vid}/at"
            return NewRecord([(vid, "reconciliation", {}), _event(ctx, at)], (vid, ctx, vid), values)
        path = expectation_path(unit.exp, unit.prop)
        story = self.holder(unit)
        if story is not None:
            ctx = self._free(lambda n: f"{story}/{path}/v{n}")
            return NewRecord([_event(ctx, at)], (story, ctx, story), values)
        vid = self._free(lambda n: f"{path}/v{n}")
        ctx = f"{vid}/at"
        return NewRecord([(vid, "reconciliation", {}), _event(ctx, at)], (vid, ctx, vid), values)

    def _unit_target(self, unit: Unit) -> dict:
        if unit.story is not None:
            return {"@ref": "item", "id": unit.story}
        return assertion_ref(unit.exp, unit.prop)

    def _act(self, unit: Unit, letter: str, kind: str, values: dict, content: Any) -> NewRecord:
        at = self._at(content)
        if unit.story is not None:
            ctx = self._free(lambda n: f"{unit.story}/{letter}{n}")
            return NewRecord([_event(ctx, at)], (unit.story, ctx, unit.story), values)
        path = expectation_path(unit.exp, unit.prop)
        story = self.holder(unit, content if kind == "begin" else None)
        if story is not None:
            # 7.6.7: part of the story, its middle: an Assertion on the story Item
            ctx = self._free(lambda n: f"{story}/{path}/{letter}{n}")
            return NewRecord([_event(ctx, at)], (story, ctx, story), values)
        iid = self._free(lambda n: f"{path}/{letter}{n}")
        ctx = f"{iid}/at"
        return NewRecord([(iid, kind, {}), _event(ctx, at)], (iid, ctx, iid), values)


def _has_acts(acc: Account, unit: Unit) -> bool:
    return bool(begin_index(acc).get(unit))


def recorded_holder(acc: Account, unit: Unit) -> str | None:
    """The story whose Item holds an expectation property's recorded acts (7.6.7), from where
    its first begin act was recorded; None when it keeps acts of its own or has none."""
    for b in sorted(begin_index(acc).get(unit, []), key=lambda r: (acc.sort_key(r)[:2], r.triple)):
        i, c, src = b.triple
        if i == src and c.startswith(i + "/exp:"):
            return i
        return None
    return None


def plan_unit(writer: TransitionWriter, unit: Unit, diffs: list[Diff]) -> list[NewRecord]:
    """README §7: within a unit, the revisions first, in the order of the acts they revise,
    and then the new acts in period order: each period's begin act, then its baseline end
    act, then its end act under the fixture policy."""
    out: list[NewRecord] = []
    for d in sorted((d for d in diffs if d.difference != "missing"), key=lambda d: d.position):
        out.append(writer.revise(unit, d.act, d.derived))
    created: dict[int, Triple] = {}
    for d in sorted((d for d in diffs if d.difference == "missing"), key=lambda d: d.position):
        if d.transition == "begin":
            rec = writer.begin(unit, d.derived)
            created[d.period] = rec.triple
            out.append(rec)
        else:
            begin = d.begin.rec.triple if d.begin is not None else created.get(d.period)
            if begin is None:
                continue
            out.append(writer.end(unit, begin, d.derived))
    return out


def plan_transitions(acc: Account, units: list[Unit], trigger: Triple | None,
                     exists: Callable[[str], bool], trigger_at: Instant | None = None,
                     basis: dict | None = None, exists_many: Callable[[set], set] | None = None) -> list[NewRecord]:
    """The begin acts, end acts and revisions that maintenance records for the affected
    units (7.6.9), in README §7 order. A write that is not an Assertion (a Connection
    operation) gives its time in ``trigger_at`` and its reference in ``basis``. Every unit is
    compared first, and the names the new records may take are then checked in one lookup
    (``exists_many``), so that a write affecting many units, such as a normalization of a
    project (7.3.8), costs no query per record."""
    writer = TransitionWriter(acc, exists, trigger, trigger_at, basis, exists_many)
    cache = DeriveCache(acc)
    planned: list[tuple[Unit, list[Diff] | None, Any]] = []
    for u in sorted(units, key=lambda u: u.order):
        d = derive_unit(acc, u, cache)
        rps = recorded_periods(acc, u)
        if d.unavailable is not None:
            # 7.6.9, 7.6.14: a unit whose interpretation the reference does not have is read as
            # recorded, and its acts are never revised on that account. A unit that has no
            # begin act yet gets one whose content is the limitation (7.6.6), so that reads
            # report it among their limitations instead of inventing a standing (10.3)
            if not rps and d.periods and d.periods[0].begin is not None:
                planned.append((u, None, d.periods[0].begin))
            continue
        diffs = compare(d, rps)
        if diffs:
            planned.append((u, diffs, None))
    names: set = set()
    for u, diffs, _b in planned:
        names |= writer.candidate_names(u, diffs or [])
    writer.prefetch(names)
    out: list[NewRecord] = []
    for u, diffs, begin in planned:
        if diffs is None:
            out.append(writer.begin(u, begin))
        else:
            out += plan_unit(writer, u, diffs)
    return out


# ---------------------------------------------------------------------------------------
# read shapes (README §5 *Periods*)


def _ref_out(r: Any) -> Any:
    if is_assertion_ref(r):
        return compact(ref_triple(r))
    if isinstance(r, list):
        return [compact(ref_triple(x)) if is_assertion_ref(x) else x for x in r]
    return r


def content_out(c: Any) -> Any:
    """A content in the form of a <transition> without `act`: references in compact form,
    `policy` not repeated (README §5)."""
    if not isinstance(c, dict):
        return c
    out: dict[str, Any] = {}
    for k, v in c.items():
        if k == "policy":
            continue
        if k in ("record", "matched_by"):
            out[k] = _ref_out(v)
        elif k in ("records", "tied"):
            out[k] = [_ref_out(x) for x in v] if isinstance(v, list) else v
        elif k == "ambiguous":
            out[k] = [content_out(x) for x in v] if isinstance(v, list) else v
        else:
            out[k] = v
    return out


def transition_out(act: RAct | None, content: Any = None, policy: Any = "absent") -> dict | None:
    """A <transition>: an act's applicable content (or ``content`` in its place, such as the
    governed ending of 7.7.3), with the act; ``policy`` is added where given (README §5
    *Periods*, `policy_end`)."""
    if act is None:
        if content is None:
            return None
        out = {"act": None, **content_out(content)}
    else:
        out = {"act": compact(act.rec.triple)}
        if act.revised_by is not None:
            out["revised_by"] = compact(act.revised_by.triple)
        c = act.content if content is None else content
        if isinstance(c, dict):
            out.update(content_out(c))
    if policy != "absent":
        out["policy"] = policy
    return out


def periods_out(rps: list[RPeriod], segments: list) -> list[dict]:
    """README §5 *Periods*: one entry per begin act whose applicable content is not null.
    `policy_end` is present when a non-baseline policy governs the unit at some instant of
    the period: the end act of the policy governing the period's ending, at the instant the
    period ends under the unit's policies, with that policy; null while it has not ended."""
    out = []
    tied = [compact(r.triple) for r in segment_tied_records(segments)]
    for rp in rps:
        if rp.begin.content is None:
            continue
        p = {"begin": transition_out(rp.begin), "end": transition_out(rp.end_act(None))}
        ends = governed_ends(rp, segments)
        if any(g is not None for e in ends for g in e[3]):
            cands = [transition_out(act, content, policy_out(pol)) if act is not None else None
                     for pol, act, content, _g in ends]
            if all(c == cands[0] for c in cands):
                p["policy_end"] = cands[0]
            else:
                # README §5 *Ending policies*: the candidates' results under each policy
                p["policy_end"] = {"ambiguous": cands, "records": tied}
        out.append(p)
    return out


def computed_periods_out(periods: list[DPeriod], segments: list) -> list[dict]:
    """Periods computed in a participant perspective or under another interpretation:
    `act` is null and `policy_end` is null where present, because computed periods apply
    the baseline endings (README §5 *Periods*, 7.6.14)."""
    has_policy = any(p is not None for _s, p in segments)
    out = []
    for p in periods:
        if p.begin is None:
            continue
        e = {"begin": transition_out(None, p.begin), "end": transition_out(None, p.end)}
        if has_policy:
            e["policy_end"] = None
        out.append(e)
    out.sort(key=lambda x: _begin_order(_content_from_out(x["begin"])))
    return out


def _content_from_out(t: dict) -> Any:
    return {k: v for k, v in t.items() if k != "act"}


def diff_out(d: Diff) -> dict:
    out: dict[str, Any] = {"unit": d.unit.id, "transition": d.transition, "difference": d.difference,
                           "act": compact(d.act.rec.triple) if d.act is not None else None, "policy": d.policy}
    if d.difference != "missing":
        out["recorded"] = content_out(d.recorded)
    if d.difference != "extra":
        out["derived"] = content_out(d.derived)
    return out


# ---------------------------------------------------------------------------------------
# reading recorded transitions (7.6.14)


def continued_in(acc: Account, st: Story) -> str | None:
    """7.3.4: the representative a `continuous` reconciliation continues the story in."""
    for r in story_acts(acc, st, ("reconcile",)):
        if r.values.get("@outcome") == "continuous" and is_item_ref(r.values.get("@representative")):
            rep = r.values["@representative"]["id"]
            if rep != st.id:
                return rep
    return None


def _segments(policy: Any, default: list) -> list:
    """``"own"`` is the unit's own governance; a list is a policy history (one candidate history
    of an ambiguous one, 7.7.2); any other value is that one policy throughout."""
    if isinstance(policy, list):
        return policy
    return default if policy == "own" else [(None, policy)]


def story_state_recorded(acc: Account, st: Story, cutoff: Instant | None, policy: Any = "own",
                         rps: list[RPeriod] | None = None) -> tuple[str, Any, str | None]:
    """A story's open dimension read from its recorded transitions under its ending policies
    (7.6.14, 7.7.3): (open, the end content it was read from when ended, the interval's start)."""
    segments = _segments(policy, st.policy_segments)
    rps = recorded_periods(acc, Unit(story=st.id)) if rps is None else rps
    rep = continued_in(acc, st)
    if rep is not None:
        rep_st = load_story(acc, rep)
        rep_rps = [rp for rp in recorded_periods(acc, Unit(story=rep)) if rp.begin.content is not None]
        if not rep_rps or rep_st is None:
            return "continued_in", None, None
        state, _ = periods_state([(rep_rps[0].begin.content, None)], cutoff)
        start = rep_rps[0].begin.content.get("at") if isinstance(rep_rps[0].begin.content, dict) else None
        return ("continued_in" if state == "open" else state), None, start
    nonnull = [rp for rp in rps if rp.begin.content is not None]
    if not nonnull:
        for rp in rps:
            c = rp.end_content(None)
            if c is not None:
                # 7.6.12, 7.6.14: ended, from its `since` where it carries one
                state = no_period_state(c, cutoff)
                return state, (c if state == "ended" else None), None
        return "not_started", None, None
    pairs = [(rp.begin.content, governed_end(rp, segments)[2]) for rp in nonnull]
    state, idx = periods_state(pairs, cutoff)
    first = pairs[0][0]
    start = first.get("at") if isinstance(first, dict) else None
    return state, (pairs[idx][1] if state == "ended" and idx is not None else None), start


def expectation_standing_recorded(acc: Account, e: Expectation, rps: list[RPeriod],
                                  cutoff: Instant | None) -> str | None:
    """A property's standing (6.6.1) read from its baseline transitions (7.6.14), or None
    when the reading depends on an unspecified order, an ambiguous or limitation content or a
    tie, which the caller then derives (the records each standing carries are derived)."""
    pairs = []
    for rp in rps:
        b = rp.begin.content
        if b is None:
            continue
        en = rp.end_content(None)
        for c in (b, en):
            if isinstance(c, dict) and ("ambiguous" in c or "limitation" in c or c.get("tied")):
                return None
        pairs.append((b, en))
    for b, en in pairs:
        if isinstance(en, dict) and en.get("cause") == "fulfillment":
            at = T.parse_instant(en.get("at"))
            r = True if cutoff is None else (T.at_or_before(at, cutoff) if at else None)
            if r is None:
                return None
            if r is True:
                return "fulfilled"
    started = []
    for b, en in pairs:
        at = T.parse_instant(b.get("at"))
        r = True if cutoff is None else (T.at_or_before(at, cutoff) if at else None)
        if r is None:
            return None
        if r is True:
            started.append((b, en))
    if not started:
        return "not_in_force"
    b, en = started[-1]
    if isinstance(en, dict):
        at = T.parse_instant(en.get("at"))
        r = True if cutoff is None else (T.after(at, cutoff) if at else None)
        if r is None:
            return None
        if r is False:
            return "withdrawn"
    reached = e.scope_reached(cutoff)
    if reached is None:
        return None
    return "outstanding" if reached else "not_yet_due"


def policy_open_recorded(rps: list[RPeriod], segments: list, cutoff: Instant | None) -> bool | None:
    """Whether a unit is open at the cutoff under its policies (7.6.3, 7.7.3, 7.7.4): one of
    its periods began at or before the cutoff and has not ended under them at or before it."""
    pairs = [(rp.begin.content, governed_end(rp, segments)[2]) for rp in rps if rp.begin.content is not None]
    if not pairs:
        return False
    state, _ = periods_state(pairs, cutoff)
    if state == "open":
        return True
    if state in ("ended", "not_started"):
        return False
    return None


def current_period(rps: list[RPeriod], segments: list, cutoff: Instant | None) -> RPeriod | None:
    """The latest open period that began at or before the cutoff (9.5.7)."""
    found = None
    for rp in rps:
        if rp.begin.content is None:
            continue
        state, _ = periods_state([(rp.begin.content, governed_end(rp, segments)[2])], cutoff)
        if state in ("open", "ambiguous"):
            found = rp
    return found


def parents_of(acc: Account, exp: Rec, prop: str, begin: Any) -> list[str]:
    """7.6.15: the stories whose review, establishing or reaffirming the expectation and
    covering the property, took effect at the period's beginning and so began it."""
    at, _r, _v = _earliest_definite(begin)
    if at is None:
        return []
    out: set[str] = set()
    for r, key in acc.establishes_of.get(exp.triple, []):
        e = acc.effective(r)
        if e is None or _k(e) != _k(at):
            continue
        covers = False
        for ref in ref_list(r.values, key):
            if is_assertion_ref(ref) and ref_triple(ref) == exp.triple and ref.get("property") in (None, prop):
                covers = True
        if not covers:
            continue
        for ref in act_targets(r.values):
            tg = parse_target(ref)
            if tg.kind == "item" and acc.is_story(tg.item):
                out.add(tg.item)
            elif tg.kind == "assertion":
                d = acc.get(tg.triple)
                if d is not None and d.action == "detect":
                    out.add(d.item)
    return sorted(out)


# ---------------------------------------------------------------------------------------
# validation (10.2.9)


def _fail(msg: str):
    raise WriteError("10.2.9", msg)


def _is_instant(v: Any) -> bool:
    return isinstance(v, str) and T.parse_instant(v) is not None


def _check_ref(v: Any, what: str) -> None:
    if not (is_assertion_ref(v) and "property" not in v and "support" not in v):
        _fail(f"{what} is an exact Assertion reference without selectors (7.6.6)")


def _check_refs(v: Any, what: str) -> None:
    """7.6.6: one exact Assertion reference without selectors, or, where several records at
    one instant cause the transition, a list of two or more of them, distinct and ordered by
    item, context and source id."""
    if isinstance(v, list):
        if len(v) < 2:
            _fail(f"{what} is one reference, or a list of two or more (7.6.6)")
        for x in v:
            _check_ref(x, what)
        keys = [ref_triple(x) for x in v]
        if keys != sorted(set(keys)):
            _fail(f"{what} lists distinct references ordered by item, context and source id (7.6.6)")
        return
    _check_ref(v, what)


def _check_definite(c: dict, act: str, kind: str | None, baseline: bool, policy: Any, no_period: bool) -> None:
    allowed = {"at", "record", "cause", "tied"}
    if act == "end":
        allowed |= {"policy", "timeliness", "interpretation", "matched_by", "since"}
    extra = set(c) - allowed
    if extra:
        _fail(f"@period carries undefined members {sorted(extra)} (7.6.6)")
    for k in ("at", "record", "cause") + (("policy",) if act == "end" else ()):
        if k not in c:
            _fail(f"a definite @period carries {k!r} (7.6.4, 7.6.5)")
    if c["at"] is None:
        if not (act == "end" and c.get("cause") in NO_TIME_CAUSES and no_period):
            _fail("`at` is null only in the end act of a story with no period (7.6.6, 7.6.12)")
    elif not _is_instant(c["at"]):
        raise WriteError("10.2.4", "@period at is not an instant in a 4.2.1 form")
    # 7.6.5, 7.6.6, 7.6.12: the `normalization` end act of a story with no period carries
    # `since`, an instant; no other content does
    needs_since = act == "end" and c["at"] is None and c.get("cause") == "normalization"
    if needs_since != ("since" in c):
        _fail("`since` belongs to, and is required in, the normalization end act of a story with no period "
              "(7.6.5, 7.6.12)")
    if "since" in c and not _is_instant(c["since"]):
        raise WriteError("10.2.4", "@period since is not an instant in a 4.2.1 form")
    _check_refs(c["record"], "`record`")
    if "matched_by" in c:
        # 7.6.5: an alignment or fulfillment end whose record matches only under an
        # interpretation that a normalization put in force cites that normalization
        _check_refs(c["matched_by"], "`matched_by`")
        if baseline and c.get("cause") not in ("alignment", "fulfillment"):
            _fail("matched_by belongs to an alignment or fulfillment end (7.6.5)")
    if not isinstance(c["cause"], str):
        _fail("`cause` is a string (7.6.4, 7.6.5)")
    if "tied" in c and not (isinstance(c["tied"], list) and c["tied"]):
        _fail("`tied` lists the records the transition is tied with (7.6.6)")
    for t in c.get("tied") or []:
        _check_ref(t, "`tied`")
    if act == "end":
        if policy_key(c["policy"]) != policy_key(policy) or (c["policy"] is not None and not _policy_shape(c["policy"])):
            _fail("an end act's content carries its policy (7.6.5, 7.6.10)")
        if baseline and kind is not None and c["cause"] not in END_CAUSES[kind]:
            _fail(f"{c['cause']!r} is not a baseline end cause of a {kind} (7.6.5)")
        if kind == "expectation" and baseline and c["cause"] == "fulfillment":
            if c.get("timeliness") not in TIMELINESS or "interpretation" not in c:
                _fail("a fulfillment end carries timeliness and interpretation (7.6.5)")
            if c["interpretation"] is not None and not _policy_shape(c["interpretation"]):
                _fail("`interpretation` is null or {name, version} (7.6.5)")
        elif ("timeliness" in c or "interpretation" in c) and baseline:
            _fail("timeliness and interpretation belong to an expectation property's fulfillment end (7.6.5)")
    elif kind is not None and c["cause"] not in BEGIN_CAUSES[kind]:
        _fail(f"{c['cause']!r} is not a begin cause of a {kind} (7.6.4)")


def _policy_shape(p: Any) -> bool:
    return isinstance(p, dict) and set(p) == {"name", "version"} and isinstance(p["name"], str) \
        and isinstance(p["version"], str)


def check_content(c: Any, act: str, kind: str | None, policy: Any, allow_null: bool, no_period: bool = False) -> None:
    """10.2.9: a @period has a form 7.6.6 allows for the act."""
    if c is None:
        if not allow_null:
            _fail("this @period is not null (7.6.6)")
        return
    if not isinstance(c, dict):
        _fail("@period is null or an object (7.6.6)")
    baseline = policy is None
    if "ambiguous" in c:
        allowed = {"ambiguous", "records"} | ({"policy"} if act == "end" else set())
        if set(c) - allowed or not isinstance(c.get("ambiguous"), list) or not isinstance(c.get("records"), list):
            _fail("an ambiguous @period is {ambiguous, records} (7.6.6)")
        cands = c["ambiguous"]
        if len(cands) < 2 or len({repr(_canon(x)) for x in cands}) < len(cands):
            _fail("an ambiguous @period lists at least two distinct candidates (7.6.6)")
        for x in cands:
            if x is not None:
                if not isinstance(x, dict) or "ambiguous" in x or "limitation" in x:
                    _fail("each candidate is a definite content or null (7.6.6)")
                _check_definite(x, act, kind, baseline, policy, no_period)
        for r in c["records"]:
            _check_ref(r, "`records`")
        if act == "end" and policy_key(c.get("policy")) != policy_key(policy):
            _fail("an end act's @period carries its policy beside an ambiguous content (7.6.6)")
        return
    if "limitation" in c:
        allowed = {"limitation", "records", "interpretation"} | ({"policy"} if act == "end" else set())
        if set(c) - allowed or c.get("limitation") not in LIMITATION_REASONS or not isinstance(c.get("records"), list):
            _fail("a limitation @period is {limitation, records} with a 7.6.6 reason")
        if (c["limitation"] == "interpretation_unavailable") != ("interpretation" in c):
            _fail("only interpretation_unavailable carries `interpretation` (7.6.6)")
        for r in c["records"]:
            _check_ref(r, "`records`")
        if act == "end" and policy_key(c.get("policy")) != policy_key(policy):
            _fail("an end act's @period carries its policy beside a limitation (7.6.6)")
        return
    _check_definite(c, act, kind, baseline, policy, no_period)


def _unit_kind(acc: Account, unit: Unit) -> str | None:
    if unit.story is None:
        return "expectation"
    st = load_story(acc, unit.story)
    return st.kind if st is not None and not st.malformed else None


def unit_policy_segments(acc: Account, unit: Unit) -> list:
    """7.7.2, 7.7.3: the policy governing a unit over event time."""
    if unit.story is not None:
        st = load_story(acc, unit.story)
        return st.policy_segments if st is not None else [(None, None)]
    rec = acc.get(unit.exp)
    return expectation_policy_segments(acc, rec) if rec is not None else [(None, None)]


def governs_period(acc: Account, unit: Unit, begin: Rec, policy: Any) -> bool:
    """7.7.3, 10.2.9: whether the policy governs, at some instant, the period that the begin
    act begins: the policies governing it from its beginning while it is open, its endings
    read from the end acts recorded for it."""
    segments = unit_policy_segments(acc, unit)
    rp = next((x for x in recorded_periods(acc, unit) if x.begin.rec.triple == begin.triple), None)
    if rp is None:
        return False
    if rp.begin.content is None:
        return any(policy_key(p) == policy_key(policy) for _s, seg in segments for p in policy_candidates(seg))
    _pol, _act, _c, governing = governed_end(rp, segments)
    return any(policy_key(p) == policy_key(policy) for p in governing)


def _begin_target_unit(acc: Account, values: dict) -> Unit:
    ts = values.get("@targets")
    if not isinstance(ts, list) or len(ts) != 1:
        _fail("a begin act has exactly one target (7.6.4)")
    tg = parse_target(ts[0])
    if tg.kind == "item":
        if not acc.is_story(tg.item):
            _fail("a begin act's Item target is a story (7.6.4)")
        return Unit(story=tg.item)
    if tg.kind == "assertion" and tg.support is None:
        rec = acc.get(tg.triple)
        if rec is not None and rec.action == "detect" and tg.prop is None:
            return Unit(story=rec.item)
        if rec is not None and rec.kind == "expectation" and tg.prop is not None \
                and tg.prop in properties_of(rec.values):
            return Unit(exp=tg.triple, prop=tg.prop)
    _fail("a begin act targets a story, one of its detections, or an expectation with a property selector (7.6.4)")


def _target_act(acc: Account, values: dict, what: str, actions: tuple) -> Rec:
    ts = values.get("@targets")
    if not isinstance(ts, list) or len(ts) != 1 or not is_assertion_ref(ts[0]):
        _fail(f"{what} has exactly one target, {' or '.join(actions)} (7.6.5, 7.6.10)")
    t = acc.get(ref_triple(ts[0]))
    if t is None or t.action not in actions or "property" in ts[0] or "support" in ts[0]:
        _fail(f"{what} targets {' or '.join(actions)} act (7.6.5, 7.6.10)")
    return t


def _gives_ignore(acc: Account, content: Any, lookup: Callable[[Triple], dict | None] | None) -> bool:
    """Whether a content, or any candidate of an ambiguous one, gives an ignore act (9.5.6) as
    its `record` (7.7.4)."""
    for v in content_variants(content):
        if not isinstance(v, dict):
            continue
        rec = v.get("record")
        refs = [rec] if is_assertion_ref(rec) else ([x for x in rec if is_assertion_ref(x)] if isinstance(rec, list) else [])
        for ref in refs:
            t = ref_triple(ref)
            r = acc.get(t)
            vals = r.values if r is not None else (acc.rs.assertions[t].values if t in acc.rs.assertions
                                                   else (lookup(t) if lookup is not None else None))
            if isinstance(vals, dict) and vals.get("@action") == "ignore":
                return True
    return False


def validate_transition_write(acc: Account, triple: Triple, values: dict,
                              lookup: Callable[[Triple], dict | None] | None = None) -> None:
    """10.2.9 for begin and end acts, `revise` and `adopt_policy` (README §6, precedence 6).
    An explicit baseline act, or a revision of one, must equal the derivation where the
    unit's interpretation is available (7.6.14) and must not repeat a transition another act
    already gives; an identical write of a generated act is a replay and never reaches this
    check (8.1.2). An end act naming a policy, or a revision of one, never gives an ignore as
    its `record` (7.7.4). ``lookup`` gives the values of a record outside the account."""
    a = values.get("@action")
    outcome = values.get("@outcome")
    if a == "reconcile" and outcome == "adopt_policy":
        f = values.get("@frame")
        if not isinstance(f, dict) or "policy" not in f or "policy_version" not in f \
                or (f.get("policy") is None) != (f.get("policy_version") is None):
            _fail("an adopt_policy's @frame carries both policy and policy_version (7.7.3)")
        ts = values.get("@targets")
        if not isinstance(ts, list) or len(ts) != 1 or not is_assertion_ref(ts[0]) \
                or "property" in ts[0] or "support" in ts[0]:
            _fail("an adopt_policy has exactly one target: a detection of a story, or an expectation (7.7.3)")
        t = acc.get(ref_triple(ts[0]))
        if t is None or not (t.action == "detect" or t.kind == "expectation"):
            _fail("an adopt_policy targets a detection of a story or an expectation (7.7.3)")
        return
    if a == "begin":
        unit = _begin_target_unit(acc, values)
        kind = _unit_kind(acc, unit)
        if "@period" not in values:
            _fail("a begin act carries @period (7.6.4)")
        check_content(values["@period"], "begin", kind, None, allow_null=True)
        _check_against_derivation(acc, unit, "begin", None, values["@period"], None)
        return
    if a == "end":
        begin = _target_act(acc, values, "an end act", ("begin",))
        unit = unit_of_begin(acc, begin)
        if unit is None:
            _fail("an end act's begin act targets no unit (7.6.5)")
        kind = _unit_kind(acc, unit)
        p = values.get("@period")
        if not isinstance(p, dict) or "policy" not in p:
            _fail("an end act's @period carries `policy` (7.6.5)")
        policy = p["policy"]
        if policy is not None and not _policy_shape(policy):
            _fail("`policy` is null or {name, version} (7.6.5)")
        b_content = applicable(acc, begin).content
        check_content(p, "end", kind, policy, allow_null=False, no_period=b_content is None)
        if policy is not None:
            if not governs_period(acc, unit, begin, policy):
                _fail("an end act naming a policy targets the begin act of a period that the policy governs "
                      "at some instant (7.7.3, 10.2.9)")
            if any(policy_key(e.policy) == policy_key(policy)
                   for e in (applicable(acc, r) for r, _t in acc.acts_targeting(("A", begin.triple)) if r.action == "end")):
                _fail("the begin act already has an end act naming this policy (7.6.5)")
            if _gives_ignore(acc, p, lookup):
                _fail("an ignore ends nothing under any policy; a policy end act gives no ignore as its record "
                      "(7.7.4, 9.5.6)")
            if not implemented(policy):
                return
        else:
            if any(applicable(acc, r).policy is None for r, _t in acc.acts_targeting(("A", begin.triple))
                   if r.action == "end"):
                _fail("the begin act already has a baseline end act (7.6.5)")
        _check_against_derivation(acc, unit, "end", begin, p, policy)
        return
    if a == "reconcile" and outcome == "revise":
        target = _target_act(acc, values, "a revise", ("begin", "end"))
        if "@period" not in values:
            _fail("a revise carries @period (7.6.10)")
        if target.action == "begin":
            unit = unit_of_begin(acc, target)
            policy = None
            no_period = False
        else:
            b = acc.get(ref_triple(act_targets(target.values)[0]))
            unit = unit_of_begin(acc, b) if b is not None else None
            policy = RAct(target, None).policy
            no_period = b is not None and applicable(acc, b).content is None
        if unit is None:
            _fail("a revise targets an act of a unit of work (7.6.10)")
        check_content(values["@period"], target.action, _unit_kind(acc, unit), policy, allow_null=True,
                      no_period=no_period)
        if policy is not None and _gives_ignore(acc, values["@period"], lookup):
            _fail("an ignore ends nothing under any policy; a revision of a policy end act gives no ignore "
                  "as its record (7.7.4, 9.5.6)")
        if policy is None or implemented(policy):
            _check_revision(acc, unit, target, values["@period"], policy)


def _check_against_derivation(acc: Account, unit: Unit, act: str, begin: Rec | None, content: Any,
                              policy: Any) -> None:
    """10.2.9: an explicit act equals the derivation, where the unit's interpretation is
    available (7.6.14), and repeats no transition another act already gives."""
    d = derive_unit(acc, unit)
    rps = recorded_periods(acc, unit)
    if act == "begin":
        wanted = [p.begin for p in d.periods]
        if d.unavailable is None and not any(same_content(content, w) for w in wanted):
            _fail("an explicit begin act differs from the derivation (I-17, 10.2.9)")
        if any(same_content(content, rp.begin.content) for rp in rps):
            _fail("another begin act already gives this transition (10.2.9)")
        return
    if d.unavailable is not None:
        return  # read as recorded; not compared with the derivation (7.6.14)
    want = _derived_end_for(d, rps, begin, policy)
    if want is None or not same_content(content, want):
        _fail("an explicit end act differs from the derivation (I-17, 10.2.9)")


def _derived_end_for(d: Derived, rps: list[RPeriod], begin: Rec, policy: Any) -> Any:
    nonnull = [rp for rp in rps if rp.begin.content is not None]
    dper = [p for p in d.periods if p.begin is not None]
    for i, rp in enumerate(nonnull):
        if rp.begin.rec.triple == begin.triple:
            if i < len(dper):
                return dper[i].end if policy is None else dper[i].policy_ends.get(policy_key(policy))
            return None
    noper = [p for p in d.periods if p.begin is None]
    if noper:
        return noper[0].end if policy is None else noper[0].policy_ends.get(policy_key(policy))
    return None


def _check_revision(acc: Account, unit: Unit, target: Rec, content: Any, policy: Any) -> None:
    d = derive_unit(acc, unit)
    if d.unavailable is not None:
        # 7.6.14: not compared with the derivation; it still repeats no other act's transition
        if target.action == "begin" and content is not None and any(
                rp.begin.rec.triple != target.triple and same_content(content, rp.begin.content)
                for rp in recorded_periods(acc, unit)):
            _fail("another begin act already gives this transition (10.2.9)")
        return
    diffs = [x for x in compare(d, recorded_periods(acc, unit)) if x.act is not None and x.act.rec.triple == target.triple]
    if not diffs or not same_content(content, diffs[0].derived):
        _fail("an explicit revise of a baseline act differs from the derivation, or repeats its content (I-17, 10.2.9)")
