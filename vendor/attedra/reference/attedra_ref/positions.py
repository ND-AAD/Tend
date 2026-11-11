"""Source positions: per-property carry-forward with withdrawals (spec 5.2, 5.6, 6.7.4, 9.2).

For one source, one subject and one property at a frame, exactly one classification holds
(5.6.1): ``never_asserted``, ``asserted`` (with value and origin), ``withdrawn`` (with the
withdrawing record) or ``ambiguous`` (with the candidates).

Only statements contribute values: Assertions at ``event`` and ``milestone`` contexts whose
occurrence time is at or before the cutoff (9.2.2). Expectations, acts and reserved members
never contribute (2.4.7, I-6). Each property carries forward from the Assertion that last
asserted it, by occurrence order and, within one schedule, by ordinal (5.2.1). When the most
recent Assertion carrying a property is withdrawn, the property has no current value and no
older value is revived (6.7.4).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .instants import Instant
from .interpretations import LITERAL, Interpretation
from .model import Rec
from .values import compact, is_reserved_key, literal_equal, normalize, properties_of, to_result
from .view import Limitation, View


@dataclass
class Classification:
    kind: str  # never_asserted | asserted | withdrawn | ambiguous
    value: Any = None
    origin: Rec | None = None
    withdrawn_by: Rec | None = None
    withdrawn: Rec | None = None  # the withdrawn Assertion
    candidates: list = field(default_factory=list)  # [(kind, value, origin, withdrawn_by)]

    def to_result(self) -> dict:
        out: dict[str, Any] = {"classification": self.kind}
        if self.kind == "asserted":
            out["value"] = to_result(self.value)
            out["origin"] = compact(self.origin.triple)
        elif self.kind == "withdrawn":
            out["withdrawn_by"] = compact(self.withdrawn_by.triple)
            out["withdrawn_assertion"] = compact(self.withdrawn.triple)
        elif self.kind == "ambiguous":
            cands = []
            for kind, value, origin, wby in self.candidates:
                if kind == "never_asserted":
                    cands.append({"classification": "never_asserted"})
                    continue
                c: dict[str, Any] = {"classification": "asserted", "value": to_result(value),
                                     "origin": compact(origin.triple)}
                if kind == "withdrawn":
                    c = {"classification": "withdrawn", "origin": compact(origin.triple),
                         "withdrawn_by": compact(wby.triple)}
                cands.append(c)
            out["candidates"] = cands
        return out

    def same(self, other: "Classification", interp: Interpretation = LITERAL, prop: str | None = None) -> bool:
        if self.kind != other.kind:
            return False
        if self.kind == "asserted":
            return interp.equal(self.value, other.value, prop)
        return True

    @property
    def present(self) -> bool:
        return self.kind == "asserted"


def withdrawals_of(view: View, r: Rec, prop: str | None, cutoff: Instant | None = None) -> tuple[list[Rec], list[Rec]]:
    """Withdrawals targeting a statement, or the named property of it (6.7.2), whose effect
    is at or before the cutoff: (definite, unspecified)."""
    definite, maybe = [], []
    for act, tg in view.acc.acts_targeting_triple(r.triple):
        if act.action != "withdraw" or tg.support is not None:
            continue
        if tg.prop is not None and tg.prop != prop:
            continue
        w = view.effective_within(act, cutoff)
        if w is True:
            definite.append(act)
        elif w is None:
            maybe.append(act)
    key = lambda a: view.acc.sort_key(a)
    return sorted(definite, key=key), sorted(maybe, key=key)


def classify(view: View, subject: str, source: str, prop: str, cutoff: Instant | None = None,
             include: Callable[[Rec], bool | None] | None = None) -> Classification:
    """The classification of one property of one source's position at the frame (5.6.1).
    ``include`` replaces the frame's inclusion test, for a position assembled up to a named
    Assertion (7.1.1); withdrawals still apply by their effect at ``cutoff``."""
    acc = view.acc
    included, maybe = [], []
    for r in acc.statements_about(subject, source):
        if prop not in r.values or is_reserved_key(prop):
            continue
        w = include(r) if include is not None else view.statement_in(r, cutoff)
        if w is True:
            included.append(r)
        elif w is None:
            maybe.append(r)
    outcomes = _outcomes(view, included, prop, cutoff)
    if maybe:
        alt = _outcomes(view, included + maybe, prop, cutoff)
        merged = list(outcomes)
        for o in alt:
            if not any(_same_outcome(o, m) for m in merged):
                merged.append(o)
        outcomes = merged
    if len(outcomes) == 1:
        kind, value, origin, wby = outcomes[0]
        if kind == "asserted":
            return Classification("asserted", value, origin)
        if kind == "withdrawn":
            return Classification("withdrawn", withdrawn_by=wby, withdrawn=origin)
        return Classification("never_asserted")
    return Classification("ambiguous", candidates=outcomes)


def _same_outcome(a, b) -> bool:
    if a[0] != b[0]:
        return False
    if a[0] == "asserted":
        return literal_equal(a[1], b[1])
    return True


def _outcomes(view: View, recs: list[Rec], prop: str, cutoff) -> list[tuple]:
    """The possible current outcomes given a set of contributing Assertions: one per
    maximal Assertion (the latest by 5.2.1), deduplicated by value (4.5.3). Where tied
    corrections leave a record's corrected content unspecified (8.3.4), each candidate
    correction's content is an outcome."""
    if not recs:
        return [("never_asserted", None, None, None)]
    latest = view.acc.latest_of(recs)
    outs: list[tuple] = []
    for l in latest:
        tied = view.acc.ambiguous_corrections.get(("A", l.triple))
        if tied:
            for c in tied:
                cv = view.acc.records[c].values if c in view.acc.records else {}
                if cv.get("@outcome") == "replace" and isinstance(cv.get("@corrected"), dict) and prop in cv["@corrected"]:
                    o = ("asserted", normalize(cv["@corrected"])[prop], l, None)
                else:
                    o = _outcomes(view, [r for r in recs if r is not l], prop, cutoff)[0] if len(recs) > 1 \
                        else ("never_asserted", None, None, None)
                if not any(_same_outcome(o, x) for x in outs):
                    outs.append(o)
            continue
        definite, maybe = withdrawals_of(view, l, prop, cutoff)
        cands = []
        if definite:
            cands.append(("withdrawn", None, l, _earliest_withdrawal(view, definite)))
        else:
            cands.append(("asserted", l.values[prop], l, None))
            if maybe:
                cands.append(("withdrawn", None, l, maybe[0]))
        for c in cands:
            if not any(_same_outcome(c, o) for o in outs):
                outs.append(c)
    return outs


def _earliest_withdrawal(view: View, ws: list[Rec]) -> Rec:
    return sorted(ws, key=lambda w: (view.acc.effective(w).key if view.acc.effective(w) else (9,), w.triple))[0]


def relocation_limit(view: View, subject: str, source: str) -> dict | None:
    """8.3.7: a source position where a withdrawal (or an ``@after``) references a relocated
    statement of this source about this subject returns a limitation."""
    acc = view.acc
    for orig, (corr, repl) in acc.relocated.items():
        if (orig[0], orig[2]) == (subject, source) or (repl[0], repl[2]) == (subject, source):
            for _corr, act in acc.limits.get(orig, []):
                a = acc.get(act)
                if a is not None and (a.action == "withdraw" or not a.is_act):
                    return {"limitation": "relocated_reference", "correction": compact(corr),
                            "record": compact(act), "original": compact(orig)}
    return None


def asserted_properties(view: View, subject: str, source: str) -> list[str]:
    """Properties the source has ever asserted about the subject, in the corrected account."""
    props: set[str] = set()
    for r in view.acc.statements_about(subject, source):
        props |= set(properties_of(r.values))
    return sorted(props)


def source_position(view: View, subject: str, source: str, extra: list[str] | None = None,
                    cutoff: Instant | None = None) -> dict[str, Classification]:
    """A source's effective position, property by property (9.2.2). Every property keeps
    the origin of the Assertion that supplied it (5.2.2)."""
    lim = relocation_limit(view, subject, source)
    if lim:
        raise Limitation(lim["limitation"], **{k: v for k, v in lim.items() if k != "limitation"})
    props = sorted(set(asserted_properties(view, subject, source)) | set(extra or []))
    return {p: classify(view, subject, source, p, cutoff) for p in props}


def untimed_statements(view: View, subject: str, source: str) -> dict[str, list[Rec]]:
    """9.2.2, 4.2.4: the source's statements about the subject that have no occurrence time
    (at a planned milestone, or at a context whose corrected definition has no ``@context``),
    by the properties they carry. Each such property reads as a limitation naming them. A
    milestone with competing publication instants still has a chronological position
    (4.4.1) and is not listed here."""
    acc = view.acc
    out: dict[str, list[Rec]] = {}
    for r in acc.statements_about(subject, source):
        why = acc.occurrence_issue(r)
        if why is None or why == "competing_publication_instants":
            continue
        for p in properties_of(r.values):
            out.setdefault(p, []).append(r)
    return out


def untimed_limitation(recs: list[Rec]) -> dict:
    return {"limitation": "no_occurrence_time", "records": sorted(compact(r.triple) for r in recs)}


def position_up_to(view: View, subject: str, source: str, named: Rec, extra: list[str] | None = None
                   ) -> dict[str, Classification]:
    """7.1.1, 9.4.1: the source's position assembled from its statements that precede or are
    the named Assertion in 5.2.1 order (occurrence time, then the ordinals of one schedule's
    milestones, then ``@after``). A statement unordered with the named Assertion makes the
    affected property ambiguous (4.5.3). Withdrawals apply by their effect at the named
    Assertion's occurrence time; perspective applies as at the frame's cutoff."""
    lim = relocation_limit(view, subject, source)
    if lim:
        raise Limitation(lim["limitation"], **{k: v for k, v in lim.items() if k != "limitation"})
    acc = view.acc
    at = acc.occurrence(named)
    if at is None:
        raise Limitation("no_occurrence_time", records=[compact(named.triple)])

    def include(r: Rec) -> bool | None:
        if acc.occurrence(r) is None:
            return False
        seen = view.statement_in(r) if view.frame.perspective is not None else True
        if seen is False:
            return False
        if r.triple == named.triple:
            order = True
        else:
            p = acc.precedes(r, named)
            order = True if p is True else (False if p is False else None)
        if order is False:
            return False
        return None if (order is None or seen is None) else True

    props = sorted(set(asserted_properties(view, subject, source)) | set(extra or []))
    return {p: classify(view, subject, source, p, at, include) for p in props}


def sources_about(view: View, subject: str) -> list[str]:
    return sorted({r.source for r in view.acc.statements_about(subject) if properties_of(r.values)})


# ---------------------------------------------------------------------------------------
# transitions (5.6.2)


def transition(prior: Classification, new: Classification, interp: Interpretation = LITERAL,
               prop: str | None = None) -> str | None:
    """The transition between two classifications of one property (5.6.2)."""
    if prior.kind == "ambiguous" or new.kind == "ambiguous":
        return "ambiguous"
    if prior.kind == "never_asserted":
        if new.kind == "asserted":
            return "introduced"
        if new.kind == "withdrawn":
            return "withdrawn"
        return None
    if prior.kind == "asserted":
        if new.kind == "asserted":
            if interp.equal(prior.value, new.value, prop):
                return "unchanged"
            if new.value is None and prior.value is not None:
                return "cleared"
            return "changed"
        if new.kind == "withdrawn":
            return "withdrawn"
        return None
    if prior.kind == "withdrawn":
        if new.kind == "asserted":
            return "reasserted"
        if new.kind == "withdrawn":
            return "unchanged"
    return None


def member_differences(prior: Any, new: Any) -> list[dict]:
    """Member-level differences of structured values (5.6.2)."""
    if not (isinstance(prior, dict) and isinstance(new, dict)) or "@ref" in prior or "@ref" in new:
        return []
    out = []
    for k in sorted(set(prior) | set(new)):
        if k not in prior:
            out.append({"member": k, "difference": "member_added"})
        elif k not in new:
            out.append({"member": k, "difference": "member_removed"})
        elif not literal_equal(prior[k], new[k]):
            out.append({"member": k, "difference": "member_changed"})
    return out


def transition_entry(prop: str, prior: Classification, new: Classification, kind: str) -> dict:
    entry = {"property": prop, "transition": kind,
             "prior": compact(prior.origin.triple) if prior.kind == "asserted" else None,
             "new": compact(new.origin.triple) if new.kind == "asserted" else None,
             "members": member_differences(prior.value if prior.kind == "asserted" else None,
                                           new.value if new.kind == "asserted" else None)}
    if new.kind == "withdrawn":
        entry["withdrawn_by"] = compact(new.withdrawn_by.triple)
    if prior.kind == "withdrawn":
        entry["prior_withdrawn_by"] = compact(prior.withdrawn_by.triple)
    return entry
