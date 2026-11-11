"""The corrected account (spec 8.3) and the chronology it supports (4.2.4, 4.3, 4.5).

Building an ``Account`` from a loaded record set is the first step of every read:

1. Corrections are applied at every cutoff, before anything else (8.3.3). A ``replace``
   gives the record its corrected content, ``erroneous`` removes it from the account and
   ``relocated`` removes it in favour of an existing replacement (8.3.1). Items (8.3.8) and
   Connections' ``connected_at`` (8.3.9) are corrected the same way. Where several
   corrections target one record, the latest by occurrence time applies; a tie without
   ``@after`` evidence is ambiguous (8.3.4). A correction may itself be corrected, so the
   account is computed to a fixed point.
2. Every Assertion's occurrence time is its context's instant: an event's ``at`` or a
   milestone's publication instant (4.2.4, 4.4.1).
3. Ordering primitives: ``precedes`` orders two records by occurrence time, by the ordinals
   of one schedule's milestones where publication instants are equal or unordered (4.3.2),
   and by ``@after`` (4.5.2); otherwise their order is unspecified (4.5.3).

The account also records the limitations of 8.3.7 (effective references to a relocated
original) and the extension content it does not interpret (10.4.2).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from . import instants as T
from .instants import Instant
from .model import (DEFINED_VALUE_MEMBERS, SUPPORT_ACTIONS, Item, Rec, Triple, act_targets, has_effective,
                    record_kind, ref_list)
from .store import RecordSet
from .values import (compact, is_assertion_ref, is_item_ref, normalize,
                     ref_triple)

# Reasons a record has no usable occurrence time (9.6).
PLANNED = "planned_milestone"
COMPETING = "competing_publication_instants"
NO_ROLE = "context_has_no_time"


@dataclass(frozen=True)
class Target:
    """A parsed exact reference used as a target (2.4.1-2.4.3)."""

    kind: str  # "assertion" | "item" | "connection" | "artifact"
    triple: Triple | None = None
    prop: str | None = None
    support: Triple | None = None  # the expectation whose support is selected
    item: str | None = None
    pair: tuple[str, str] | None = None

    @property
    def key(self):
        if self.kind == "assertion":
            return ("A", self.triple)
        if self.kind == "item":
            return ("I", self.item)
        if self.kind == "connection":
            return ("C", self.pair)
        return ("F", None)


def parse_target(ref: dict) -> Target:
    kind = ref.get("@ref")
    if kind == "assertion":
        sup = ref.get("support")
        return Target("assertion", triple=ref_triple(ref), prop=ref.get("property"),
                      support=ref_triple(sup) if is_assertion_ref(sup) else None)
    if kind == "item":
        return Target("item", item=ref.get("id"))
    if kind == "connection":
        return Target("connection", pair=(ref.get("from"), ref.get("to")))
    return Target("artifact")


def _is_publication(values: dict, triple: Triple) -> bool:
    return triple[0] == triple[1] and "@published" in values


def _carries_extension_member(value) -> bool:
    """An object member beginning with ``@`` that the specification does not define (10.4.1),
    at any depth."""
    t = type(value)
    if t is dict:
        for k, x in value.items():
            if isinstance(k, str) and k.startswith("@") and k not in DEFINED_VALUE_MEMBERS:
                return True
            tx = type(x)
            if (tx is dict or tx is list) and _carries_extension_member(x):
                return True
    elif t is list:
        for x in value:
            tx = type(x)
            if (tx is dict or tx is list) and _carries_extension_member(x):
                return True
    return False


class Account:
    """The corrected account of a record set (8.3.3), with chronology (4.2.4)."""

    def __init__(self, rs: RecordSet, apply_corrections: bool = True, max_rounds: int = 12) -> None:
        self.rs = rs
        self.apply_corrections = apply_corrections
        self.items: dict[str, Item] = dict(rs.items)
        self.records: dict[Triple, Rec] = {}
        self.absent: dict[Triple, tuple[str, Triple]] = {}  # triple -> (outcome, correction)
        self.relocated: dict[Triple, tuple[Triple, Triple]] = {}  # original -> (correction, replacement)
        self.applicable: dict[tuple, Triple] = {}  # target key -> applicable correction
        self.ambiguous_corrections: dict[tuple, list[Triple]] = {}
        self.corrections_of: dict[tuple, list[Triple]] = defaultdict(list)
        self.connected_at: dict[tuple[str, str], str] = {}
        self.discrepancies: list[dict] = []
        self._ctx_time_cache: dict[str, tuple[Instant | None, str | None]] = {}
        self.publications: dict[str, list[Rec]] = defaultdict(list)
        self._build(max_rounds)
        self._index()

    # ---------------------------------------------------------------------------------
    # construction

    def _set_round_state(self, values, present, items) -> None:
        """Make the chronology of one round available: Items and publications as they stand
        in the account being built."""
        self.items = items
        self._ctx_time_cache = {}
        pubs: dict[str, list[Rec]] = defaultdict(list)
        for t in present:
            v = values[t]
            if _is_publication(v, t) and "@action" not in v:
                pubs[t[0]].append(Rec(t, v, v))
        self.publications = pubs

    def _build(self, max_rounds: int) -> None:
        raw = {t: a.values for t, a in self.rs.assertions.items()}
        values, present, items, connected = raw, set(raw), dict(self.rs.items), {}
        previous = None
        for n in range(max_rounds if self.apply_corrections else 0):
            self._set_round_state(values, present, items)
            (values, present, items, connected, applicable, ambiguous,
             corr_of, absent, reloc) = self._apply_once(values, present)
            self.applicable, self.ambiguous_corrections = applicable, ambiguous
            self.corrections_of, self.absent, self.relocated = corr_of, absent, reloc
            if n == 0 and not corr_of:
                break  # no correction among the records: the recorded account is the corrected one
            state = (tuple(sorted(applicable.items())), tuple(sorted(corr_of)),
                     tuple(sorted((k, v.kind, v.label, repr(v.definition)) for k, v in items.items())))
            if state == previous:
                break
            previous = state
        self._set_round_state(values, present, items)
        self.connected_at = connected
        for t in sorted(present):
            raw = self.rs.assertions[t]
            v = values[t]
            ctx = items.get(t[1])
            corr = self.applicable.get(("A", t))
            self.records[t] = Rec(t, v, raw.values, raw.recorded_at, raw.recorded_by,
                                  kind=record_kind(v, ctx.role if ctx else None),
                                  corrected_by=corr if corr and t in present else None)

    def _apply_once(self, values, present):
        """One round: find the corrections in the current account and apply the applicable
        one to each target, starting again from the recorded content."""
        raw_values = {t: a.values for t, a in self.rs.assertions.items()}
        corr_of: dict[tuple, list[Triple]] = defaultdict(list)
        for t in present:
            v = values[t]
            if v.get("@action") != "correct":
                continue
            targets = act_targets(v)
            if len(targets) != 1:
                continue
            tg = parse_target(targets[0])
            if tg.kind == "assertion" and tg.prop is None and tg.support is None:
                corr_of[tg.key].append(t)
            elif tg.kind in ("item", "connection"):
                corr_of[tg.key].append(t)
        applicable, ambiguous = {}, {}
        for key, cands in corr_of.items():
            winners = self.latest_of([self._pseudo(c, values[c]) for c in cands])
            if len(winners) == 1:
                applicable[key] = winners[0].triple
            else:
                ambiguous[key] = sorted(w.triple for w in winners)
                applicable[key] = sorted(w.triple for w in winners)[-1]
        new_values = dict(raw_values)
        new_present = set(raw_values)
        absent, reloc = {}, {}
        new_items = dict(self.rs.items)
        new_conn = {}
        for key, c in applicable.items():
            cv = values[c]
            outcome = cv.get("@outcome")
            if key[0] == "A":
                t = key[1]
                if t not in raw_values:
                    continue
                if outcome == "replace" and isinstance(cv.get("@corrected"), dict):
                    new_values[t] = normalize(cv["@corrected"])
                elif outcome == "erroneous":
                    new_present.discard(t)
                    absent[t] = ("erroneous", c)
                elif outcome == "relocated" and is_assertion_ref(cv.get("@corrected")):
                    new_present.discard(t)
                    absent[t] = ("relocated", c)
                    reloc[t] = (c, ref_triple(cv["@corrected"]))
            elif key[0] == "I":
                iid = key[1]
                orig = self.rs.items.get(iid)
                corr = cv.get("@corrected")
                if orig is not None and outcome == "replace" and isinstance(corr, dict):
                    new_items[iid] = Item(iid, corr.get("kind", orig.kind), corr.get("label"),
                                          corr.get("definition") if isinstance(corr.get("definition"), dict) else {})
            elif key[0] == "C":
                corr = cv.get("@corrected")
                if outcome == "replace" and isinstance(corr, dict) and isinstance(corr.get("connected_at"), str):
                    new_conn[key[1]] = corr["connected_at"]
        return new_values, new_present, new_items, new_conn, applicable, ambiguous, dict(corr_of), absent, reloc

    def _pseudo(self, t: Triple, v: dict) -> Rec:
        ctx = self.items.get(t[1])
        return Rec(t, v, v, kind=record_kind(v, ctx.role if ctx else None))

    def _index(self) -> None:
        self.by_item: dict[str, list[Rec]] = defaultdict(list)
        self.by_source: dict[str, list[Rec]] = defaultdict(list)
        self.by_context: dict[str, list[Rec]] = defaultdict(list)
        self.targets_of: dict[tuple, list[tuple[Rec, Target]]] = defaultdict(list)  # target key -> acts
        self.establishes_of: dict[Triple, list[tuple[Rec, str]]] = defaultdict(list)
        self.detections_of: dict[str, list[Rec]] = defaultdict(list)
        self.begin_acts: list[Rec] = []  # 7.6.4: begin acts, found by their targets (7.6.7)
        self.limits: dict[Triple, list[tuple[Triple, Triple]]] = defaultdict(list)
        self.unsupported: list[Rec] = []
        self.publications = defaultdict(list)
        self._ctx_time_cache = {}
        for r in self.records.values():
            self.by_item[r.item].append(r)
            self.by_source[r.source].append(r)
            self.by_context[r.context].append(r)
            if _is_publication(r.values, r.triple) and r.kind == "statement":
                self.publications[r.item].append(r)
        for r in self.records.values():
            if r.is_act:
                for ref in act_targets(r.values):
                    tg = parse_target(ref)
                    self.targets_of[tg.key].append((r, tg))
                    if tg.kind == "assertion" and tg.support is not None:
                        self.targets_of[("S", tg.triple, tg.support)].append((r, tg))
                if r.action == "review":
                    for key in ("@establishes", "@reaffirms"):
                        for ref in ref_list(r.values, key):
                            if is_assertion_ref(ref):
                                self.establishes_of[ref_triple(ref)].append((r, key))
                if r.action == "detect":
                    self.detections_of[r.item].append(r)
                if r.action == "begin":
                    self.begin_acts.append(r)
            # 10.4.1-10.4.2: an extension act, or any record carrying an undefined @ member at
            # any depth, is extension content that reads report as unsupported
            if r.is_extension_act or _carries_extension_member(r.values):
                self.unsupported.append(r)
        # 8.3.7: effective references to a relocated original
        for r in self.records.values():
            if not r.is_act:
                continue
            refs = []
            if r.action in SUPPORT_ACTIONS | {"withdraw", "ignore", "review"}:
                refs += act_targets(r.values)
            if r.action == "review":
                refs += ref_list(r.values, "@establishes") + ref_list(r.values, "@reaffirms")
            if is_assertion_ref(r.values.get("@after")):
                refs.append(r.values["@after"])
            for ref in refs:
                if not is_assertion_ref(ref):
                    continue
                t = ref_triple(ref)
                if t in self.relocated:
                    corr, repl = self.relocated[t]
                    self.limits[t].append((corr, r.triple))
                    self.limits[repl].append((corr, r.triple))
        for r in self.records.values():
            if not r.is_act and is_assertion_ref(r.values.get("@after")):
                t = ref_triple(r.values["@after"])
                if t in self.relocated:
                    corr, repl = self.relocated[t]
                    self.limits[r.triple].append((corr, r.triple))

    # ---------------------------------------------------------------------------------
    # items and contexts

    def item(self, item_id: str) -> Item | None:
        return self.items.get(item_id)

    def role(self, item_id: str) -> str | None:
        it = self.items.get(item_id)
        return it.role if it else None

    def ctx(self, item_id: str) -> dict:
        it = self.items.get(item_id)
        return (it.context or {}) if it else {}

    def schedule_of(self, milestone_id: str) -> str | None:
        c = self.ctx(milestone_id)
        s = c.get("schedule")
        return s.get("id") if is_item_ref(s) else None

    def ordinal_of(self, milestone_id: str):
        return self.ctx(milestone_id).get("ordinal")

    def publication_instant(self, milestone_id: str) -> tuple[Instant | None, str | None]:
        """A milestone's occurrence instant: its asserted ``@published`` (4.4.1). Instants
        from different sources are consistent when one's interval contains the other's,
        and the milestone's instant is then the finer one; otherwise it is ambiguous. A
        milestone with no publication is planned (4.3.2)."""
        pubs = [p for p in self.publications.get(milestone_id, []) if p.item == p.context == milestone_id]
        insts = [T.parse_instant(p.values.get("@published")) for p in pubs]
        insts = [i for i in insts if i is not None]
        if not insts:
            return None, PLANNED
        finest = min(insts, key=lambda i: i.end - i.start)
        if all(T.contains(i, finest) for i in insts):
            for i in insts:
                if all(T.contains(j, i) for j in insts):
                    finest = i if (i.end - i.start) <= (finest.end - finest.start) else finest
            return finest, None
        # Competing instants: the chronological position is ambiguous (4.4.1, 4.5.3), not
        # absent. It is held as the hull of the competing intervals, so that every relation
        # holds exactly when it holds for each competing instant and is otherwise
        # unspecified (4.2.5). The reason travels with it: a milestone with competing
        # instants is still never a cutoff (4.6.1).
        return T.hull(insts), COMPETING

    def context_instant(self, ctx_id: str) -> tuple[Instant | None, str | None]:
        """The instant of an event or milestone context (4.2.4)."""
        if ctx_id in self._ctx_time_cache:
            return self._ctx_time_cache[ctx_id]
        role = self.role(ctx_id)
        if role == "event":
            out = (T.parse_instant(self.ctx(ctx_id).get("at")), None)
        elif role == "milestone":
            out = self.publication_instant(ctx_id)
        else:
            out = (None, NO_ROLE)
        self._ctx_time_cache[ctx_id] = out
        return out

    def milestones_of_schedule(self, schedule_id: str) -> list[str]:
        return sorted(i.id for i in self.items.values() if i.role == "milestone" and self.schedule_of(i.id) == schedule_id)

    # ---------------------------------------------------------------------------------
    # records and times

    def get(self, triple: Triple) -> Rec | None:
        return self.records.get(triple)

    def occurrence(self, r: Rec) -> Instant | None:
        """An Assertion's occurrence time: its context's instant (4.2.4). Expectations have
        none (their times come from timing and supports)."""
        if r.kind == "expectation":
            return None
        return self.context_instant(r.context)[0]

    def occurrence_issue(self, r: Rec) -> str | None:
        if r.kind == "expectation":
            return None
        return self.context_instant(r.context)[1]

    def effective(self, r: Rec) -> Instant | None:
        """An act's effective time: ``@effective`` where allowed, else its occurrence (8.4.1).
        Normalizations and `adopt_policy` reconciliations take effect when they are made, at
        their effective time (7.3.8, 7.7.3)."""
        if r.is_act and has_effective(r.values):
            e = T.parse_instant(r.values.get("@effective"))
            if e is not None:
                return e
        return self.occurrence(r)

    def statements_about(self, item_id: str, source: str | None = None) -> list[Rec]:
        return [r for r in self.by_item.get(item_id, []) if r.kind == "statement" and (source is None or r.source == source)]

    def expectations_about(self, item_id: str) -> list[Rec]:
        return [r for r in self.by_item.get(item_id, []) if r.kind == "expectation"]

    def acts_targeting(self, key: tuple) -> list[tuple[Rec, Target]]:
        return list(self.targets_of.get(key, []))

    def acts_targeting_triple(self, triple: Triple) -> list[tuple[Rec, Target]]:
        return self.acts_targeting(("A", triple))

    def self_description(self, source: str, context: str) -> Rec | None:
        """The self-description of a communication's issuance (3.1.2)."""
        r = self.records.get((source, context, source))
        return r if r is not None and r.kind == "statement" else None

    def is_story(self, item_id: str) -> bool:
        return bool(self.detections_of.get(item_id))

    # ---------------------------------------------------------------------------------
    # ordering (4.3.2, 4.5.2)

    def _after_ref(self, r: Rec) -> Triple | None:
        a = r.values.get("@after")
        return ref_triple(a) if is_assertion_ref(a) else None

    def precedes(self, a: Rec, b: Rec) -> bool | None:
        """True when ``a`` is ordered before ``b``, False when after, None when the order
        is unspecified. Explicit sequence evidence (``@after``, ordinals of one schedule's
        milestones) orders records whose instants are equal or unordered (4.5.2)."""
        if self._after_ref(b) == a.triple:
            return True
        if self._after_ref(a) == b.triple:
            return False
        ta, tb = self._time_for_order(a), self._time_for_order(b)
        if ta is not None and tb is not None:
            if T.before(ta, tb) is True:
                self._check_ordinals(a, b, True)
                return True
            if T.before(tb, ta) is True:
                self._check_ordinals(a, b, False)
                return False
        oa, ob = self._same_schedule_ordinals(a, b)
        if oa is not None:
            if oa < ob:
                return True
            if oa > ob:
                return False
        return None

    def _time_for_order(self, r: Rec) -> Instant | None:
        if r.is_act:
            return self.effective(r) if has_effective(r.values) else self.occurrence(r)
        return self.occurrence(r)

    def _same_schedule_ordinals(self, a: Rec, b: Rec):
        if self.role(a.context) == "milestone" and self.role(b.context) == "milestone" and a.context != b.context:
            sa, sb = self.schedule_of(a.context), self.schedule_of(b.context)
            oa, ob = self.ordinal_of(a.context), self.ordinal_of(b.context)
            if sa is not None and sa == sb and isinstance(oa, int) and isinstance(ob, int):
                return oa, ob
        return None, None

    def _check_ordinals(self, a: Rec, b: Rec, a_first: bool) -> None:
        """4.3.4: a declared ordinal order that disagrees with publication instants is
        reported; instants are used for chronology."""
        oa, ob = self._same_schedule_ordinals(a, b)
        if oa is not None and ((oa > ob) if a_first else (oa < ob)):
            d = {"discrepancy": "ordinal_order_disagrees_with_publication", "milestones": sorted([a.context, b.context])}
            if d not in self.discrepancies:
                self.discrepancies.append(d)

    def latest_of(self, recs: list[Rec]) -> list[Rec]:
        """The maximal records: those that no other record in the list follows (4.5.3).
        More than one means their relative order is unspecified."""
        out = []
        for r in recs:
            if not any(o is not r and self.precedes(r, o) is True for o in recs):
                out.append(r)
        return sorted(out, key=lambda x: x.triple)

    def earliest_of(self, recs: list[Rec]) -> list[Rec]:
        out = []
        for r in recs:
            if not any(o is not r and self.precedes(o, r) is True for o in recs):
                out.append(r)
        return sorted(out, key=lambda x: x.triple)

    def sort_key(self, r: Rec) -> tuple:
        """A linear presentation order: by occurrence (or effective) instant, then by the
        ordinal of a milestone context, then by triple. Used for listing only."""
        t = self._time_for_order(r)
        o = self.ordinal_of(r.context) if self.role(r.context) == "milestone" else None
        return ((0, t.start, t.end) if t else (1, 0, 0), o if isinstance(o, int) else 0, r.triple)

    # ---------------------------------------------------------------------------------
    # corrections as reported by reads

    def corrections_applying(self, key: tuple) -> list[Triple]:
        """Every correction in the account that targets the record (8.3.2, 9.2.1)."""
        return sorted(self.corrections_of.get(key, []), key=lambda t: self.sort_key(self.records[t]) if t in self.records else (2,))

    def compact_rec(self, r: Rec, prop: str | None = None) -> str:
        return compact(r.triple, prop)
