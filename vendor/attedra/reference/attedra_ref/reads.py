"""The required reads (spec §9), with the result shapes of conformance README §5.

Every read loads only the records its question needs (9.10.1), builds the
corrected account (8.3.3), resolves its frame (4.6.1), and evaluates in this order:
corrected account, occurrence times, perspective, carry-forward, expectations, comparisons,
stories, distribution, adjacency and the by-party read. Every result carries the resolved
frame (I-15) and reports ``ambiguous`` and ``limitation`` where the specification requires
them (9.6), and the extension records it encountered as ``unsupported`` (10.4.2).

A frame that names no interpretation compares each value under the interpretation that
applies to it: the one in force for its subject at the comparison's time, except that an
expectation is evaluated under its own (7.6.13) and two expectations are compared under theirs
(7.2.4). It resolves to the interpretation in force for the read's scope at the cutoff, with the
normalizations that put it in force (4.6.1, 7.3.8). A frame that names an interpretation, or
requests literal comparison (``"literal"``), computes every comparison under it at every
instant. A comparison that matches only because of an interpretation a normalization put in
force cites that normalization (``matched_by``, 5.5.4). A result that would have to be computed
under an interpretation the reference does not have is the ``interpretation_unavailable``
limitation; a unit's own transitions under such an interpretation are read as recorded (7.6.14).

In the record perspective, the listing reads that report open standing (open_work,
open_stories, pending_review, what_remains) read each unit's recorded beginnings and
endings under its ending policy (7.6.14); they derive no unit's periods. They load the units
in scope and the acts that target them (``Store.load_listing``), not the scope's whole
closure, with a bounded number of indexed queries. Review, disagreement, attention and the
records a standing carries stay derived (9.5.2, 6.6.1), and so does a standing whose reading
depends on an unspecified order; what needs a unit's evidence (a conflict story's
disagreement, an expectation the recorded transitions do not settle) is evaluated on a
second account holding only that evidence (``_Derivation``). Every expectation is read under
its own interpretation by a frame naming none (7.6.14). Participant perspectives, and
expectations read under an interpretation other than their own, compute as before and apply
the baseline; where tied `adopt_policy` acts leave a unit's governing policy ambiguous, the
recorded reading is made under each candidate (7.7.2). The ``derive`` switch answers the
record-perspective listing reads by derivation instead, for comparison. A unit whose own
interpretation the reference does not have cannot be derived: on both paths, and in the story
read, its transitions are read as recorded (7.6.14).
"""
from __future__ import annotations

import itertools
import os
from typing import Any, Callable

from . import instants as T
from .account import Account, parse_target
from .expectations import Expectation, expectation_conflicts, own_schedule, pair_unavailable, read_schedule_of
from .interpretations import LITERAL
from .model import Rec, act_targets
from .normalization import InForce, compact_or_list, frame_inforce, merge_states, subject_schedule
from .positions import (Classification, asserted_properties, classify, position_up_to, relocation_limit,
                        source_position, sources_about, transition, transition_entry, untimed_limitation,
                        untimed_statements)
from .store import RecordSet, Store
from .stories import (Family, StoryEval, _review_dimension, act_event_time, all_stories, comparison_schedule,
                      disagreement_with, ending_of, evaluate_story, evaluate_story_in_view, families,
                      ignore_in_effect, limitation_members, load_story, no_period_ending, no_period_state,
                      participant_story_views, periods_state, policy_out, read_story_periods,
                      segment_resolutions, segment_tied_records, story_attention, story_interpretation_members,
                      story_unavailable_at, unavailable_object, whole_view)
from .transitions import (Unit, check_units, computed_periods_out, continued_in, current_period, derive_unit,
                          diff_out, expectation_periods, expectation_policy, expectation_policy_segments,
                          expectation_standing_recorded, expectation_unavailable, implemented,
                          is_own_interpretation, parents_of, periods_out, policy_open_recorded, recorded_periods,
                          story_state_recorded, transition_out, units_about)
from .values import compact, is_assertion_ref, is_item_ref, literal_equal, parse_compact, ref_triple, to_result
from .view import (Frame, Limitation, View, connection_active_at, connection_state, history,
                   materialized_properties, resolve_frame, scope_members)

class _EveryItem:
    """The subjects of a scoped read that names no scope: every Item in the store (README
    §5, allowed only in fixtures)."""


EVERY_ITEM = _EveryItem()


# The listing reads that, in the record perspective, read recorded transitions (7.6.14).
LISTING_READS = ("open_work", "open_stories", "pending_review", "what_remains")
_KIND_ORDER = {"conflict": 0, "change": 1, "expectation": 2}


class _Derivation:
    """What a recorded listing read derives (7.6.14), on an account of its own.

    A listing read's account holds the units in scope and their recorded transitions, not
    their evidence (``Reader._listing_load``). Three things still need the evidence: a
    conflict story's disagreement (9.5.2), which reads both sides' positions; and an
    expectation that the frame reads under an interpretation other than its own, or whose
    standing its recorded transitions leave to the derivation (an ambiguous or limitation
    content, a tie, or a transition unordered with the cutoff), which is then evaluated as a
    whole. For those, this loads in one go the statements of each side's source about the
    story's subject (``Store.load_statements_of``) and the closure of each expectation
    (``Store.load_closure``, as the expectation read loads it), and evaluates them on that
    account, with the frame unchanged. It shares the read's list of discrepancies (4.3.4).
    On an account that holds the scope's whole closure it changes nothing."""

    def __init__(self, reader: "Reader", view: View) -> None:
        self.reader = reader
        self.view = view
        self.active = getattr(view.acc, "units_only", False)
        self.acc: Account | None = None
        self.exps: set = set()

    def prepare(self, exps=(), stories=()) -> None:
        """Build the account for these expectation records and conflict stories (once)."""
        if not self.active or self.acc is not None:
            return
        acc = self.view.acc
        seeds: set[str] = set()
        pairs: set[tuple[str, str]] = set()
        for rec in exps:
            self.exps.add(rec.triple)
            seeds |= set(rec.triple)
        for st in stories:
            for s in st.sides or ():
                if s.kind == "statement":
                    pairs.add((st.subject, s.source))
                elif acc.get(s.exp) is not None:
                    seeds |= set(s.exp)
        if not seeds and not pairs:
            return
        store = self.reader.store
        rs = store.load_closure(seeds) if seeds else RecordSet()
        store.load_statements_of(rs, pairs)
        # the units are in the read's scope: where its lookup found that no normalization applies
        # to them, none does here (7.3.8)
        rs.no_normalization |= acc.rs.no_normalization
        store.load_normalizations(rs, {s for s, _src in pairs} | {r.item for r in exps})
        side = Account(rs)
        for d in side.discrepancies:
            if d not in acc.discrepancies:
                acc.discrepancies.append(d)
        side.discrepancies = acc.discrepancies
        self.acc = side

    def needs(self, rec: Rec) -> bool:
        """Whether an expectation's entry needs its evidence (see the class docstring)."""
        if not self.active:
            return False
        view, acc = self.view, self.view.acc
        if acc.limits.get(rec.triple):
            return False
        if not is_own_interpretation(acc, rec, view.frame):
            return True
        e = Expectation(view, rec)
        return any(expectation_standing_recorded(acc, e, recorded_periods(acc, Unit(exp=rec.triple, prop=p)),
                                                 view.cutoff) is None for p in e.props)

    def of(self, view: View, rec: Rec) -> tuple[View, Rec]:
        """The view and record an expectation's entry is evaluated on."""
        if self.acc is None or rec.triple not in self.exps:
            return view, rec
        return View(self.acc, view.frame), self.acc.get(rec.triple)

    def disagreement(self, view: View, st, cutoff) -> tuple[str, tuple]:
        """A conflict story's disagreement dimension at the cutoff, under the story's
        interpretation then (9.5.2, 7.2.4), and what it is matched by; the story stands for its
        family (its subject, property and sides)."""
        v = View(self.acc, view.frame) if self.acc is not None else view
        return disagreement_with(v, st, comparison_schedule(v.acc, st), cutoff)


class Reader:
    """Runs one read against a store.

    ``derive`` is the internal switch of the reference: with it, the listing reads
    of the record perspective answer by deriving every unit's transitions (§6, §7) instead of
    reading the recorded ones. It exists for comparison, by the scale benchmark and the audit;
    by I-17 the two answers are equal.

    ``full_closure`` is a second internal switch, for the development audit only: the listing
    reads of the record perspective then read the recorded transitions from the scope's whole
    closure, instead of the records of the units in scope. The two
    answers are identical."""

    def __init__(self, store: Store, derive: bool = False, full_closure: bool = False) -> None:
        self.store = store
        self.derive = derive
        self.full_closure = full_closure

    # -- loading ------------------------------------------------------------------------

    def _load(self, frame_spec: dict | None, seeds: set[str], scoped: bool = False,
              connections: set[str] | None = None) -> tuple[Account, set[str] | None]:
        """Load a scope (when the read lists across subjects) or the closure of the read's
        subjects (2.1.5, 9.10.1). A read that names no scope uses the whole store, which the
        conformance contract allows only in fixtures (README §5)."""
        spec = frame_spec or {}
        scope = spec.get("scope")
        candidates = None
        seeds = set(seeds) | getattr(self, "_cutoff_seeds", set())
        if scoped and scope is None:
            rs = self.store.load_all()
            subjects = None
        elif scoped and isinstance(scope, list):
            ids = {x["id"] if is_item_ref(x) else x for x in scope}
            rs = self.store.load_closure(ids | seeds, with_connections=ids)
            subjects = ids | seeds
        elif scoped:
            sid = scope["id"] if is_item_ref(scope) else scope
            rs, candidates = self.store.load_scope(sid)
            rs = self.store.load_closure(seeds, rs) if seeds else rs
            subjects = candidates | {sid} | seeds
        else:
            rs = self.store.load_closure(seeds, with_connections=connections or set())
            subjects = set(seeds) | ({scope["id"] if is_item_ref(scope) else scope} if isinstance(scope, (str, dict))
                                     else set(x["id"] if is_item_ref(x) else x for x in scope)
                                     if isinstance(scope, list) else set())
        # 7.3.8: the normalizations that apply to the read's subjects and to its scope
        persp = spec.get("perspective", "record")
        self.store.load_normalizations(rs, subjects, issuance=not (persp is None or persp == "record"))
        return Account(rs), candidates

    def _listing_load(self, frame_spec: dict | None) -> Account:
        """The account of a listing read (open_work, open_stories, pending_review,
        what_remains). In the record perspective it holds the units of work in scope and what
        reading their recorded transitions needs (7.6.14, ``Store.load_listing``), not the
        scope's whole closure; the few units whose reading needs their evidence are evaluated
        on a second account of their own closures (``_Derivation``). With the ``derive``
        switch, or in a participant perspective, it is the scope's closure, as before."""
        spec = frame_spec or {}
        persp = spec.get("perspective", "record")
        if self.derive or self.full_closure or not (persp is None or persp == "record"):
            acc, _ = self._load(frame_spec, set(), scoped=True)
            return acc
        scope = spec.get("scope")
        seeds = getattr(self, "_cutoff_seeds", set())
        if scope is None:
            rs, _ = self.store.load_listing(None, None, seeds)
            subjects = None
        elif isinstance(scope, list):
            ids = {x["id"] if is_item_ref(x) else x for x in scope}
            rs, _ = self.store.load_listing(None, ids, seeds)
            subjects = ids
        else:
            sid = scope["id"] if is_item_ref(scope) else scope
            rs, candidates = self.store.load_listing(sid, None, seeds)
            subjects = (candidates or set()) | {sid}
        # 7.3.8, 9.10.1: the normalizations, found from the records that are normalizations and
        # the scopes they target; with none in the store this reads no other record
        self.store.load_normalizations(rs, subjects)
        acc = Account(rs)
        acc.units_only = True
        return acc

    # -- dispatch -----------------------------------------------------------------------

    def read(self, name: str, args: dict) -> dict:
        fn: Callable | None = getattr(self, "r_" + name, None)
        if fn is None:
            return {"limitation": "unknown_read", "read": name}
        self._cutoff_seeds = _cutoff_ids(args or {})
        res = fn(args or {})
        if _SELFCHECK and name in LISTING_READS and not self.derive and not self.full_closure:
            # development audit: the recorded and the derived answers must agree (I-17), and
            # reading the units in scope must give exactly the answer read from the scope's
            # whole closure
            self.derive = True
            try:
                alt = fn(args or {})
            finally:
                self.derive = False
            if _strip(res) != _strip(alt):
                raise AssertionError(f"selfcheck {name}: recorded {_strip(res)!r} != derived {_strip(alt)!r}")
            self.full_closure = True
            try:
                whole = fn(args or {})
            finally:
                self.full_closure = False
            # a "now" cutoff resolves anew for each answer (4.6.1), so the echoed frames may
            # differ by its second; everything else must be equal
            if {k: v for k, v in res.items() if k != "frame"} != {k: v for k, v in whole.items() if k != "frame"}:
                raise AssertionError(f"selfcheck {name}: units {res!r} != whole closure {whole!r}")
        if "frame" not in res:
            # README §5: every result carries the resolved frame, including the exact reads,
            # which do not evaluate at a cutoff
            res["frame"] = resolve_frame(Account(RecordSet()), (args or {}).get("frame")).echo()
        return res

    def _frame(self, acc: Account, args: dict, key: str = "frame", inforce: bool = True) -> tuple[View, dict | None]:
        frame = resolve_frame(acc, args.get(key))
        view = View(acc, frame)
        if inforce and not frame.named and frame.cutoff is not None:
            frame.inforce = self._inforce(view, (args.get(key) or {}).get("scope"))
        if frame.limitation and frame.limitation.get("limitation") != "interpretation_unavailable":
            return view, dict(frame.limitation, frame=frame.echo())
        return view, None

    def _inforce(self, view: View, scope: Any) -> dict:
        """4.6.1, README §5 *Resolved frame*: a frame that names no interpretation resolves to
        the interpretation in force for the read's scope at the cutoff, with the normalizations
        that put it in force: for a scope Item, the one in force for that Item; for a list, or
        an omitted scope (every Item in the store, fixtures only), the one in force for every
        listed Item, ambiguous when they differ (7.3.8)."""
        acc = view.acc
        if not norm_present(acc):
            return frame_inforce(InForce(LITERAL))
        if scope is None:
            # fixtures only (README §5): every Item in the store
            full = acc if acc.rs.complete else Account(self.store.load_all())
            items = sorted(full.items)
            v = View(full, view.frame)
            states = [subject_schedule(full, x, v).at_cutoff(view.cutoff) for x in items]
        else:
            items = [x["id"] if is_item_ref(x) else x for x in scope] if isinstance(scope, list) else \
                [scope["id"] if is_item_ref(scope) else scope]
            states = [subject_schedule(acc, x, view).at_cutoff(view.cutoff) for x in items]
        if not states:
            return frame_inforce(InForce(LITERAL))
        first = states[0]
        st = first if all(x.key == first.key for x in states) else merge_states(states)
        return frame_inforce(st)

    def _finish(self, view: View, res: dict, name: str, compute_literal: Callable | None = None,
                subjects: Any = None, unavailable: str | None = None) -> dict:
        """Echo the frame (I-15) and attach what the read excluded (4.6.1), the extension
        records it encountered (10.4.2) and declared-order discrepancies (4.3.4). A result that
        would have to be computed under an interpretation the reference does not have
        (``unavailable``) is that limitation, with the literal comparison as a separate,
        labelled result (5.5.4, 7.6.14)."""
        if unavailable is not None:
            out = {"limitation": "interpretation_unavailable", "interpretation": unavailable,
                   "frame": view.frame.echo()}
            if compute_literal is not None:
                out["literal"] = compute_literal()
            return out
        res["frame"] = view.frame.echo()
        if view.frame.perspective is not None:
            res["excluded"] = sorted(compact(t) for t in view.excluded)
        if view.acc.discrepancies:
            res["discrepancies"] = view.acc.discrepancies
        if subjects is not None and "unsupported" not in res:
            uns = self._unsupported(view.acc, subjects)
            if uns:
                res["unsupported"] = uns
        return res

    @staticmethod
    def _unsupported(acc: Account, subjects: Any) -> list[str]:
        """10.4.2, README §5 Side reports: the extension records (an undefined ``@action``, or
        an undefined ``@`` member) about the read's subjects or that target records about
        them, sorted."""
        out = []
        for r in acc.unsupported:
            hit = subjects is EVERY_ITEM or r.item in subjects
            if not hit:
                for ref in act_targets(r.values):
                    tg = parse_target(ref)
                    if (tg.triple and tg.triple[0] in subjects) or (tg.support and tg.support[0] in subjects) \
                            or tg.item in subjects or (tg.pair and (tg.pair[0] in subjects or tg.pair[1] in subjects)):
                        hit = True
                        break
            if hit:
                out.append(compact(r.triple))
        return sorted(out)

    @staticmethod
    def _scope_subjects(members: set[str] | None, *extra: str) -> Any:
        return EVERY_ITEM if members is None else set(members) | set(extra)

    # -- 9.2 submitted values -----------------------------------------------------------

    def r_exact(self, args: dict) -> dict:
        """9.2.1: the record as recorded, every correction in the corrected account that
        targets it with the applicable one (8.3.4), the withdrawals that target it and the
        records that reference it; ``not_found`` for a triple that is not recorded, whether
        never written or permanently removed (8.5.5)."""
        ref = parse_compact(args["ref"])
        if ref["@ref"] == "item":
            return self.r_item({"id": ref["id"]})
        if ref["@ref"] == "connection":
            props = self.store.get_connection(ref["from"], ref["to"])
            if props is None:
                return {"status": "not_found"}
            acc = Account(self.store.load_closure({ref["from"], ref["to"]}, with_connections={ref["from"]}))
            out = {"status": "found", "properties": to_result(props),
                   "derived": materialized_properties(acc, (ref["from"], ref["to"])),
                   "corrections": [compact(t) for t in acc.corrections_applying(("C", (ref["from"], ref["to"])))]}
            uns = self._unsupported(acc, {ref["from"], ref["to"]})
            if uns:
                out["unsupported"] = uns
            return out
        if ref["@ref"] != "assertion":
            return {"status": "not_found"}
        triple = ref_triple(ref)
        raw = self.store.get_assertion(triple)
        if raw is None:
            return {"status": "not_found"}
        acc = Account(self.store.load_closure({triple[0], triple[1], triple[2]}))
        withdrawals = sorted({w.triple for w, tg in acc.acts_targeting_triple(triple) if w.action == "withdraw"},
                             key=lambda t: acc.sort_key(acc.records[t]))
        # README §2: dependents are a set, listed sorted by compact form
        dependents = sorted({a.triple for a in self.store.referencing_assertion(triple) if a.triple != triple}, key=compact)
        rec = acc.get(triple)
        out = {"status": "found", "values": to_result(raw.values),
               "corrections": [compact(t) for t in acc.corrections_applying(("A", triple))],
               "withdrawals": [compact(t) for t in withdrawals],
               "dependents": [compact(t) for t in dependents],
               "kind": rec.kind if rec else acc.absent.get(triple, ("excluded",))[0]}
        if ("A", triple) in acc.ambiguous_corrections:
            # 8.3.4: tied corrections without @after evidence; none is applicable
            out["corrections_ambiguous"] = [compact(t) for t in acc.ambiguous_corrections[("A", triple)]]
        elif ("A", triple) in acc.applicable:
            out["applicable_correction"] = compact(acc.applicable[("A", triple)])
        if rec is not None and rec.corrected_by:
            out["corrected_values"] = to_result(rec.values)
        if triple in acc.absent:
            out["in_corrected_account"] = False
        # 8.3.6, 9.8.1: an act keeps its recorded basis; the read says where a correction
        # now applies to a record it cited
        basis_corr = []
        for b in raw.values.get("@basis", []) if isinstance(raw.values.get("@basis"), list) else []:
            if isinstance(b, dict) and b.get("@ref") == "assertion":
                cs = acc.corrections_applying(("A", ref_triple(b)))
                if cs:
                    basis_corr.append({"record": compact(ref_triple(b)), "corrections": [compact(c) for c in cs]})
        if basis_corr:
            out["basis_corrections"] = basis_corr
        # 9.8.1: whether later evidence or corrections affect the event-time account of the
        # question the act recorded
        act = rec if rec is not None else None
        if act is not None and act.action in ("detect", "review", "reconcile"):
            et = act_event_time(acc, act)
            if et is not None:
                out["event_time"] = et
        if raw.recorded_at is not None:
            out["recorded_at"] = str(raw.recorded_at)
        if raw.recorded_by is not None:
            out["recorded_by"] = raw.recorded_by
        uns = self._unsupported(acc, set(triple))
        if uns:
            out["unsupported"] = uns
        return out

    def r_item(self, args: dict) -> dict:
        """The exact read of an Item: as recorded, with the corrections that apply (8.3.8)."""
        it = self.store.get_item(args["id"])
        if it is None:
            return {"status": "not_found"}
        acc = Account(self.store.load_closure({it.id}))
        out = {"status": "found", "kind": it.kind, "label": it.label, "definition": to_result(it.definition),
               "corrections": [compact(t) for t in acc.corrections_applying(("I", it.id))]}
        cur = acc.item(it.id)
        if cur is not None and (cur.kind, cur.label, cur.definition) != (it.kind, it.label, it.definition):
            out["corrected"] = {"kind": cur.kind, "label": cur.label, "definition": to_result(cur.definition)}
        uns = self._unsupported(acc, {it.id})
        if uns:
            out["unsupported"] = uns
        return out

    def r_source_position(self, args: dict) -> dict:
        """9.2.2: a source's effective position, property by property, with origins. A
        property carried by a statement with no occurrence time reads as a limitation naming
        it; the source's other properties are classified as usual."""
        subject, source = args["subject"], args["source"]
        acc, _ = self._load(args.get("frame"), {subject, source})
        view, lim = self._frame(acc, args)
        if lim:
            return lim
        subjects = {subject, source}
        try:
            pos = source_position(view, subject, source, args.get("properties"))
        except Limitation as e:
            return self._finish(view, {"limitation": e.reason, **e.detail}, "source_position", subjects=subjects)
        props: dict[str, Any] = {p: c.to_result() for p, c in pos.items()}
        for p, recs in untimed_statements(view, subject, source).items():
            props[p] = untimed_limitation(recs)
        res = {"subject": subject, "source": source, "properties": dict(sorted(props.items()))}
        for r in sorted(acc.statements_about(subject, source), key=lambda x: x.triple):
            if acc.occurrence_issue(r) == "competing_publication_instants":
                # 4.4.1: the position is ambiguous, not absent, and reads list the competing
                # Assertions; the record still contributes wherever its order is settled.
                res.setdefault("competing_publications", []).append(
                    {"record": compact(r.triple),
                     "competing": sorted(compact(p.triple) for p in acc.publications.get(r.context, []))})
        return self._finish(view, res, "source_position", subjects=subjects)

    def r_resolved_view(self, args: dict) -> dict:
        """9.2.3: every source's classification and value for each property, side by side;
        no winner is selected. A source whose classification is a limitation has the
        limitation in its place (README §5)."""
        subject = args["subject"]
        acc, _ = self._load(args.get("frame"), {subject})
        view, lim = self._frame(acc, args)
        if lim:
            return lim
        sources = sources_about(view, subject)
        props = sorted({p for s in sources for p in asserted_properties(view, subject, s)})
        untimed = {s: untimed_statements(view, subject, s) for s in sources}
        relocated = {s: relocation_limit(view, subject, s) for s in sources}
        out: dict[str, dict] = {}
        for p in props:
            row = {}
            for s in sources:
                if relocated[s]:
                    row[s] = {k: v for k, v in relocated[s].items() if k != "original"}
                elif p in untimed[s]:
                    row[s] = untimed_limitation(untimed[s][p])
                else:
                    row[s] = classify(view, subject, s, p).to_result()
            out[p] = row
        return self._finish(view, {"subject": subject, "properties": out}, "resolved_view", subjects={subject})

    def r_by_party(self, args: dict) -> dict:
        """9.2.4: what a source or a party said, with occurrence and effective times. For a
        party, its statements are those whose issuance names it as ``@producer``, and its acts
        are those sourced from such a communication or naming it as ``@party``."""
        party, source = args.get("party"), args.get("source")
        st = self.store
        seeds: set[str] = set()
        if source:
            seeds |= {source} | {a.triple[0] for a in st.assertions_by_source(source)}
        if party:
            seeds.add(party)
            seeds |= {a.triple[0] for a in st.assertions_by_source(party)}
            sds = st.assertions_containing({"@producer": {"@ref": "item", "id": party}})
            for sd in sds:
                seeds |= {sd.triple[0]} | {a.triple[0] for a in st.assertions_by_source(sd.triple[2])}
            seeds |= {a.triple[0] for a in st.assertions_containing({"@party": {"@ref": "item", "id": party}})}
        acc, _ = self._load(args.get("frame"), seeds)
        view, lim = self._frame(acc, args)
        if lim:
            return lim
        statements, acts = [], []
        for r in acc.records.values():
            if r.kind == "expectation":
                continue
            if r.is_act:
                if view.act_in(r) is not True:
                    continue
                ok = bool(source and r.source == source)
                if party:
                    p = r.values.get("@party")
                    ok = ok or r.source == party or (is_item_ref(p) and p["id"] == party)
                    iss = r.values.get("@issuance")
                    if is_item_ref(iss):
                        sd = acc.self_description(r.source, iss["id"])
                        prod = sd.values.get("@producer") if sd else None
                        ok = ok or (is_item_ref(prod) and prod["id"] == party)
                if ok:
                    acts.append(r)
            else:
                if view.statement_in(r) is not True:
                    continue
                ok = bool(source and r.source == source)
                if party:
                    ok = ok or r.source == party
                    sd = acc.self_description(r.source, r.context)
                    prod = sd.values.get("@producer") if sd else None
                    ok = ok or (is_item_ref(prod) and prod["id"] == party)
                if ok:
                    statements.append(r)
        # README §5 presentation order: never sequence evidence (4.5.2)
        statements.sort(key=acc.sort_key)
        acts.sort(key=acc.sort_key)

        def timed(r: Rec) -> dict:
            o, e = acc.occurrence(r), acc.effective(r) if r.is_act else None
            d = {"record": compact(r.triple), "occurrence": o.text if o else None}
            if r.is_act:
                d["effective"] = e.text if e else None
                d["action"] = r.action
            return d

        res = {"statements": [compact(r.triple) for r in statements], "acts": [compact(r.triple) for r in acts],
               "details": [timed(r) for r in statements + acts]}
        return self._finish(view, res, "by_party", subjects={x for x in (party, source) if x})

    # -- 9.3 expectations -----------------------------------------------------------------

    def _expectation_rec(self, acc: Account, ref: str) -> Rec | None:
        r = parse_compact(ref)
        if r.get("@ref") != "assertion":
            return None
        rec = acc.get(ref_triple(r))
        if rec is None or rec.kind != "expectation":
            return None
        return rec

    def r_expectation(self, args: dict) -> dict:
        """9.3.1: whether the expectation is in force, its supports with their coverage and,
        per property, its standing with the fulfilling or withdrawing records, the timing
        scope, lateness, the interpretation and the obligated source's current
        classification. In the record perspective under its own interpretation (7.6.14) the
        standing and periods are read from the recorded transitions, also where the reference
        does not have that interpretation; otherwise they are computed, and a computation that
        needs an interpretation the reference does not have is that limitation (7.6.14)."""
        ref = parse_compact(args["ref"])
        triple = ref_triple(ref)
        acc, _ = self._load(args.get("frame"), set(triple))
        view, lim = self._frame(acc, args)
        if lim:
            return lim
        rec = self._expectation_rec(acc, args["ref"])
        if rec is None:
            if triple in acc.relocated:
                corr, repl = acc.relocated[triple]
                return self._finish(view, {"limitation": "relocated", "correction": compact(corr),
                                           "replacement": compact(repl)}, "expectation", subjects={triple[0]})
            return self._finish(view, {"status": "not_found"}, "expectation")
        if acc.limits.get(triple):
            corr, act = acc.limits[triple][0]
            return self._finish(view, {"limitation": "relocated_reference", "correction": compact(corr),
                                       "record": compact(act)}, "expectation", subjects={rec.item})
        lim = self._recorded_limitation(view, rec)
        if lim is not None:
            # 7.6.14, 7.6.6: read as recorded, and recorded as a limitation (README §5)
            return self._finish(view, lim, "expectation", subjects={rec.item})

        def compute(v: View):
            e = Expectation(v, rec)
            out = e.evaluate()
            out["policy"] = policy_out(expectation_policy(acc, rec, v.cutoff))
            self._read_recorded_standings(v, rec, e, out["properties"])
            self._add_periods(v, rec, out["properties"])
            return out

        res = compute(view)
        res["expectation"] = compact(rec.triple)
        return self._finish(view, res, "expectation", lambda: compute(literal_view(acc, view)),
                            subjects={rec.item}, unavailable=self._computed_unavailable(view, rec))

    @staticmethod
    def _computed_unavailable(view: View, rec: Rec) -> str | None:
        """7.6.14: the interpretation the reference does not have under which a read would
        have to compute the expectation: one the frame names other than its own, or, in a
        participant perspective with a frame naming none, its own as it is in that perspective.
        An expectation read under its own interpretation in the record perspective is read as
        recorded."""
        own = view.frame.perspective is None and is_own_interpretation(view.acc, rec, view.frame)
        if own:
            return None
        if view.frame.named:
            return frame_unavailable(view)
        return read_schedule_of(view, rec).unavailable()

    @staticmethod
    def _recorded_limitation(view: View, rec: Rec) -> dict | None:
        """7.6.14: an expectation read under its own interpretation, which the reference does
        not have, whose recorded transitions are a limitation content (a unit first recorded in
        that state, 7.6.6): the limitation, as reads list the unit (README §5)."""
        acc = view.acc
        if view.frame.perspective is not None or not is_own_interpretation(acc, rec, view.frame):
            return None
        if expectation_unavailable(acc, rec) is None:
            return None
        for p in sorted(properties_of_rec(rec)):
            for rp in recorded_periods(acc, Unit(exp=rec.triple, prop=p)):
                for c in (rp.begin.content, rp.end_content(None)):
                    if isinstance(c, dict) and "limitation" in c:
                        return limitation_members(c)
        return None

    @staticmethod
    def _read_recorded_standings(view: View, rec: Rec, e: Expectation, standings: dict) -> None:
        """7.6.14: under its own interpretation in the record perspective, a property whose
        interpretation the reference does not have is read from its recorded transitions (the
        derivation cannot be made); the records each standing carries stay as derived."""
        acc = view.acc
        if view.frame.perspective is not None or not is_own_interpretation(acc, rec, view.frame):
            return
        if expectation_unavailable(acc, rec) is None:
            return
        for p in list(standings):
            rps = recorded_periods(acc, Unit(exp=rec.triple, prop=p))
            st = expectation_standing_recorded(acc, e, rps, view.cutoff)
            if st is None:
                continue
            common = {k: standings[p][k] for k in ("timing", "interpretation", "deadline", "suggested", "unqualified",
                                                   "source_current") if k in standings[p]}
            new = {"standing": st, **common}
            if st in ("outstanding", "not_yet_due"):
                new["overdue"] = e.overdue(view.cutoff) is True if st == "outstanding" else False
            if st == "fulfilled":
                end = next((rp.end_content(None) for rp in rps if isinstance(rp.end_content(None), dict)
                            and rp.end_content(None).get("cause") == "fulfillment"), None)
                if end is not None:
                    new["fulfilled_by"] = _compact_ref(end.get("record"))
                    new["qualifying_moment"] = end.get("at")
                    new["timeliness"] = end.get("timeliness")
                    if end.get("matched_by") is not None:
                        new["matched_by"] = _compact_ref(end["matched_by"])
                    i = end.get("interpretation")
                    new["interpretation"] = i.get("name") if isinstance(i, dict) else None
            standings[p] = new

    @staticmethod
    def _add_periods(view: View, rec: Rec, standings: dict) -> None:
        """9.3.1, README §5 *Periods*: each standing carries the property's periods, read from
        the recorded acts in the record perspective under the expectation's own
        interpretation, and computed otherwise (7.6.14)."""
        acc = view.acc
        segments = expectation_policy_segments(acc, rec)
        own = view.frame.perspective is None and is_own_interpretation(acc, rec, view.frame)
        for p, standing in standings.items():
            if not isinstance(standing, dict) or standing.get("standing") == "limitation":
                continue
            if own:
                standing["periods"] = periods_out(recorded_periods(acc, Unit(exp=rec.triple, prop=p)), segments)
            else:
                standing["periods"] = computed_periods_out(_computed_expectation_periods(view, rec, p), segments)

    def _property_standings(self, view: View, rec: Rec, e: Expectation) -> tuple[dict, dict | None]:
        """Each property's standing, and, under a non-baseline ending policy, whether it is open
        work (9.3.2, 7.7.4). In the record perspective under the expectation's own
        interpretation they are read from the recorded transitions (7.6.14); a standing whose
        reading depends on an unspecified order, and the records it carries, are derived. With
        the ``derive`` switch, or in another perspective or interpretation, they are computed,
        and a computed result applies the baseline (7.6.14)."""
        acc, cutoff = view.acc, view.cutoff
        own = view.frame.perspective is None and is_own_interpretation(acc, rec, view.frame)
        segments = expectation_policy_segments(acc, rec) if own else [(None, None)]
        governed = any(p is not None for _s, p in segments)
        # 7.6.14: under an own interpretation the reference does not have, the transitions are
        # read as recorded on either path, since they cannot be derived
        unavailable = own and expectation_unavailable(acc, rec) is not None
        derived_policy = any(implemented(p) for _s, p in segments)
        props: dict = {}
        policy_open: dict | None = {} if governed else None
        for p in e.props:
            unit = Unit(exp=rec.triple, prop=p)
            rps = recorded_periods(acc, unit) if own and (not self.derive or not derived_policy or unavailable) \
                else None
            st = None
            if own and (not self.derive or unavailable):
                st = expectation_standing_recorded(acc, e, rps, cutoff)
                if st is not None:
                    st = {"standing": st}
                    if st["standing"] == "outstanding":
                        st["overdue"] = e.overdue(cutoff) is True
            props[p] = st if st is not None else e.standing(p, with_current=False)
            if policy_open is not None:
                if self.derive and derived_policy and not unavailable:
                    d = derive_unit(acc, unit)
                    pairs = [(x.begin, x.policy_end) for x in d.periods if x.begin is not None]
                    state = periods_state(pairs, cutoff)[0] if pairs else "not_started"
                    policy_open[p] = True if state == "open" else (None if state == "ambiguous" else False)
                else:
                    policy_open[p] = policy_open_recorded(rps if rps is not None else recorded_periods(acc, unit),
                                                          segments, cutoff)
        return props, policy_open

    def _work(self, view: View, rec: Rec) -> tuple[str, dict]:
        acc = view.acc
        if acc.limits.get(rec.triple):
            corr, act = acc.limits[rec.triple][0]
            return "limitations", {"expectation": compact(rec.triple), "limitation": "relocated_reference",
                                   "correction": compact(corr), "record": compact(act)}
        missing = self._computed_unavailable(view, rec)
        if missing is not None:
            # README §5 *Limitations*: an expectation that would have to be computed under an
            # interpretation the reference does not have is listed among the limitations
            return "limitations", {"expectation": compact(rec.triple), "limitation": "interpretation_unavailable",
                                   "interpretation": missing}
        lim = self._recorded_limitation(view, rec)
        if lim is not None:
            return "limitations", {"expectation": compact(rec.triple), **lim}
        e = Expectation(view, rec)
        props, policy_open = self._property_standings(view, rec, e)
        work = {"expectation": compact(rec.triple),
                "outstanding": sorted(p for p, s in props.items() if s["standing"] == "outstanding"),
                "not_yet_due": sorted(p for p, s in props.items() if s["standing"] == "not_yet_due"),
                "withdrawn": sorted(p for p, s in props.items() if s["standing"] == "withdrawn"),
                "fulfilled": sorted(p for p, s in props.items() if s["standing"] == "fulfilled")}
        amb = {p: s for p, s in props.items() if s["standing"] == "ambiguous"}
        overdue = sorted(p for p, s in props.items() if s["standing"] == "outstanding" and s.get("overdue"))
        if overdue:
            work["overdue"] = overdue

        def placement(standings) -> str:
            if "outstanding" in standings:
                return "open"
            if "not_yet_due" in standings:
                return "upcoming"
            return "excluded"

        if policy_open is not None:
            # 9.3.2, 7.7.4: under a non-baseline policy the lists follow open work: a property is
            # open work while its period is open under the policy, whatever its standing
            if any(v is None for v in policy_open.values()):
                return "ambiguous", work
            options = []
            for p, s in props.items():
                if policy_open.get(p):
                    cands = [c.get("standing") for c in s.get("candidates") or [{}]] if s["standing"] == "ambiguous" \
                        else [s["standing"]]
                    options.append(cands)
            places = {("upcoming" if all(x == "not_yet_due" for x in combo) else "open") if combo else "excluded"
                      for combo in itertools.product(*options)} if options else {"excluded"}
            if amb:
                work["ambiguous"] = sorted(amb)
                work["candidates"] = {p: s.get("candidates", []) for p, s in sorted(amb.items())}
                work["records"] = {p: s.get("records", []) for p, s in sorted(amb.items())}
            return (places.pop() if len(places) == 1 else "ambiguous"), work

        if amb:
            work["ambiguous"] = sorted(amb)
            work["candidates"] = {p: s.get("candidates", []) for p, s in sorted(amb.items())}
            work["records"] = {p: s.get("records", []) for p, s in sorted(amb.items())}
            # 9.3.2: only an entry whose inclusion depends on an ambiguous standing is listed
            # as ambiguous. When every combination of candidate standings places the
            # expectation in the same list, it is placed there.
            settled = [s["standing"] for s in props.values() if s["standing"] != "ambiguous"]
            options = [[c.get("standing") for c in s.get("candidates") or [{}]] for s in amb.values()]
            places = {placement(settled + list(combo)) for combo in itertools.product(*options)}
            if len(places) != 1 or any(None in o or "ambiguous" in o for o in options):
                return "ambiguous", work
            return places.pop(), work
        return placement([s["standing"] for s in props.values()]), work

    def r_open_work(self, args: dict) -> dict:
        """9.3.2: every expectation in scope with an outstanding property; those whose only
        open properties are not yet due as upcoming work; ambiguous and limited entries in
        separate lists. With an attention filter, expectations that an ignore in effect at
        the cutoff targets are omitted from every list (9.5.5); one whose attention depends
        on an unspecified order is listed among the ambiguous entries in its place."""
        acc = self._listing_load(args.get("frame"))
        view, lim = self._frame(acc, args)
        if lim:
            return lim
        filt = args.get("attention_filter")

        def compute(v: View):
            members = scope_members(acc, v.frame.scope, v.cutoff)
            out = {"open": [], "upcoming": [], "ambiguous": [], "limitations": []}
            recs = [r for r in sorted((r for r in acc.records.values() if r.kind == "expectation"), key=lambda r: r.triple)
                    if members is None or r.item in members]
            deriv = _Derivation(self, v)
            deriv.prepare([r for r in recs if deriv.needs(r)])
            for rec in recs:
                attention = _ignored(v, rec) if filt == "ignore" else False
                if attention is True:
                    continue
                where, work = self._work(*deriv.of(v, rec))
                if where not in out:
                    continue
                if attention is None and where != "limitations":
                    where = "ambiguous"
                out[where].append(work)
            out["filter"] = filt
            return out

        res = compute(view)
        members = scope_members(acc, view.frame.scope, view.cutoff)
        return self._finish(view, res, "open_work", subjects=self._scope_subjects(members))

    def r_expectations_about(self, args: dict) -> dict:
        """9.3.3: every expectation about a subject, in force or not, with its standing. A read
        that must compute an expectation under an interpretation the reference does not have
        is that limitation (7.6.14, README §5 *Limitations*)."""
        subject = args["subject"]
        acc, _ = self._load(args.get("frame"), {subject})
        view, lim = self._frame(acc, args)
        if lim:
            return lim

        def compute(v: View):
            out = []
            for rec in sorted(acc.expectations_about(subject), key=lambda r: r.triple):
                if acc.limits.get(rec.triple):
                    corr, act = acc.limits[rec.triple][0]
                    out.append({"expectation": compact(rec.triple), "limitation": "relocated_reference",
                                "correction": compact(corr), "record": compact(act)})
                    continue
                lim = self._recorded_limitation(v, rec)
                if lim is not None:
                    out.append({"expectation": compact(rec.triple), **lim})
                    continue
                e = Expectation(v, rec)
                ev = e.evaluate()
                self._read_recorded_standings(v, rec, e, ev["properties"])
                self._add_periods(v, rec, ev["properties"])
                out.append({"expectation": compact(rec.triple), "in_force": ev["in_force"],
                            "properties": ev["properties"], "supports": ev["supports"], "overall": ev["overall"],
                            "policy": policy_out(expectation_policy(acc, rec, v.cutoff))})
            return {"expectations": out}

        missing = next((m for m in (self._computed_unavailable(view, r) for r in acc.expectations_about(subject))
                        if m is not None), None)
        return self._finish(view, compute(view), "expectations_about", lambda: compute(literal_view(acc, view)),
                            subjects={subject}, unavailable=missing)

    # -- 9.4 comparisons ----------------------------------------------------------------

    @staticmethod
    def _transitions(a: dict[str, Classification], b: dict[str, Classification], state: InForce) -> list[dict]:
        """5.6.2: one entry per property whose transition is reported, `unchanged` included,
        in property-name order, compared under the state's interpretation. An `unchanged`
        entry whose values are unequal literally and equal only under an interpretation that a
        normalization put in force names that normalization (5.5.4, 9.4.1); where the
        interpretation is ambiguous, a property whose transition differs between its
        candidates is `ambiguous` (4.5.3)."""
        out = []
        cands = [state.interp] if state.interp is not None else [c[0] for c in state.candidates]
        for p in sorted(set(a) | set(b)):
            ca, cb = a.get(p, Classification("never_asserted")), b.get(p, Classification("never_asserted"))
            kinds = {transition(ca, cb, i, p) for i in cands}
            kind = kinds.pop() if len(kinds) == 1 else "ambiguous"
            if kind is None:
                continue
            if kind == "ambiguous":
                out.append({"property": p, "transition": "ambiguous", "prior": None, "new": None, "members": [],
                            "candidates": [ca.to_result(), cb.to_result()]})
                continue
            entry = transition_entry(p, ca, cb, kind)
            if kind == "unchanged" and ca.kind == "asserted" and cb.kind == "asserted":
                mb = state.matched_by(ca.value, cb.value, p, literal_equal)
                if mb:
                    entry["matched_by"] = compact_or_list(mb)
            out.append(entry)
        return out

    @staticmethod
    def _comparison_state(view: View, subject: str, at) -> tuple[InForce, str | None]:
        """The interpretation a comparison read applies: the frame's, or, where it names none,
        the interpretation in force for the subject at the comparison's time (4.6.1, 7.3.8),
        and the name of an interpretation it would need that the reference does not have."""
        if view.frame.named:
            return InForce(view.interp), frame_unavailable(view)
        sched = subject_schedule(view.acc, subject, view)
        return sched.at_cutoff(at), sched.unavailable_at(at)

    def r_changes(self, args: dict) -> dict:
        """9.4.1: one source's property transitions between two frames, or between two of its
        statements about the subject, with prior and new origins, in the corrected account
        (5.6.2, 7.1.1). A first side after the second, or two cutoffs whose order is
        unspecified, is a limitation. Equality is under the `to` frame's interpretation or,
        where it names none, under the one in force for the subject at the second side's time."""
        if "from_assertion" in args or "to_assertion" in args:
            return self._changes_by_assertion(args)
        subject, source = args["subject"], args["source"]
        acc, _ = self._load(args.get("to") or args.get("frame"), {subject, source})
        v_from, lim = self._frame(acc, args, "from")
        if lim:
            return lim
        v_to, lim = self._frame(acc, args, "to")
        if lim:
            return lim
        if v_from.cutoff is not None and v_to.cutoff is not None:
            # 5.6.2: the first cutoff is at or before the second (4.2.5)
            order = T.at_or_before(v_from.cutoff, v_to.cutoff)
            if order is False:
                return {"limitation": "reversed_comparison", "frame": v_to.frame.echo()}
            if order is None:
                return {"limitation": "unordered_comparison", "frame": v_to.frame.echo()}
        state, missing = self._comparison_state(v_to, subject, v_to.cutoff)

        def compute(st: InForce):
            try:
                a = source_position(v_from, subject, source)
                b = source_position(v_to, subject, source)
            except Limitation as e:
                return {"limitation": e.reason, **e.detail}
            return {"transitions": self._transitions(a, b, st), "interpretation": st.interp.name if st.interp else None}

        res = compute(state)
        res["from"] = v_from.frame.echo()
        return self._finish(v_to, res, "changes", lambda: compute(InForce(LITERAL)), subjects={subject, source},
                            unavailable=missing)

    def _changes_by_assertion(self, args: dict) -> dict:
        """9.4.1, 7.1.1: each side is the source's position assembled from its statements
        that precede or are the named Assertion in 5.2.1 order, so two issues published at
        the same instant are separated by their ordinals (4.3.2). The optional frame supplies
        perspective and interpretation; where it names none, equality is under the one in
        force for the subject at the later Assertion's occurrence time."""
        subject, source = args["subject"], args["source"]
        fa, ta = parse_compact(args["from_assertion"]), parse_compact(args["to_assertion"])
        seeds = {subject, source} | set(ref_triple(fa)) | set(ref_triple(ta))
        acc, _ = self._load(args.get("frame"), seeds)
        view, lim = self._frame(acc, args)
        if lim:
            return lim
        ra, rb = acc.get(ref_triple(fa)), acc.get(ref_triple(ta))

        def statement_of(r: Rec | None) -> bool:
            return r is not None and r.kind == "statement" and r.item == subject and r.source == source

        if not (statement_of(ra) and statement_of(rb)):
            return self._finish(view, {"status": "not_found"}, "changes")
        if acc.precedes(rb, ra) is True:
            return {"limitation": "reversed_comparison", "frame": view.frame.echo()}
        state, missing = self._comparison_state(view, subject, acc.occurrence(rb))

        def compute(st: InForce):
            try:
                a = position_up_to(view, subject, source, ra)
                b = position_up_to(view, subject, source, rb)
            except Limitation as e:
                return {"limitation": e.reason, **e.detail}
            return {"transitions": self._transitions(a, b, st), "interpretation": st.interp.name if st.interp else None}

        return self._finish(view, compute(state), "changes", lambda: compute(InForce(LITERAL)), subjects={subject, source},
                            unavailable=missing)

    def r_conflicts(self, args: dict) -> dict:
        """9.4.2: each property and pair of sources whose applicable values differ under the
        frame's interpretation or, where it names none, the one in force for the subject at
        the cutoff, and each pair of expectations both in force and not yet fulfilled for the
        property at the cutoff that require unequal values (7.1.5). Pairs unequal literally and
        equal only under an interpretation a normalization put in force are not conflicts: they
        are listed in `matched`, with that normalization (5.5.4). A ``never_asserted`` or
        ``withdrawn`` side is absence, not conflict (7.1.4); a pair whose comparison depends on
        an unspecified order is listed as ambiguous (4.5.3)."""
        subject = args["subject"]
        acc, _ = self._load(args.get("frame"), {subject})
        view, lim = self._frame(acc, args)
        if lim:
            return lim
        state, missing = self._comparison_state(view, subject, view.cutoff)
        if missing is None:
            # README §5 *Limitations*: a pair of expectations compared under a context-named
            # interpretation the reference does not have (7.2.4)
            missing = pair_unavailable(view, subject)

        def compute(v: View, st: InForce):
            sources = sources_about(v, subject)
            positions = {}
            for s in sources:
                try:
                    positions[s] = source_position(v, subject, s)
                except Limitation:
                    positions[s] = {}
            props = sorted({p for pos in positions.values() for p in pos})
            cands = [st.interp] if st.interp is not None else [c[0] for c in st.candidates]
            conflicts, ambiguous, matched = [], [], []
            for p in props:
                for i, a in enumerate(sources):
                    for b in sources[i + 1:]:
                        ca, cb = positions[a].get(p), positions[b].get(p)
                        if ca is None or cb is None:
                            continue
                        if ca.kind == "ambiguous" and cb.kind in ("asserted", "ambiguous") or \
                                cb.kind == "ambiguous" and ca.kind == "asserted":
                            ambiguous.append({"property": p, "sources": [a, b]})
                            continue
                        if ca.kind != "asserted" or cb.kind != "asserted":
                            continue
                        votes = {i_.equal(ca.value, cb.value, p) for i_ in cands}
                        if len(votes) != 1:
                            ambiguous.append({"property": p, "sources": [a, b]})
                        elif not votes.pop():
                            conflicts.append({"property": p, "sides": [
                                {"source": a, "value": to_result(ca.value), "origin": compact(ca.origin.triple)},
                                {"source": b, "value": to_result(cb.value), "origin": compact(cb.origin.triple)}]})
                        else:
                            mb = st.matched_by(ca.value, cb.value, p, literal_equal)
                            if mb:
                                matched.append({"property": p, "sources": [a, b], "matched_by": compact_or_list(mb)})
            exp_conflicts, exp_ambiguous, exp_matched = expectation_conflicts(v, subject)
            out = {"conflicts": conflicts, "expectation_conflicts": exp_conflicts,
                   "interpretation": st.interp.name if st.interp is not None else None}
            ambiguous = sorted(ambiguous + exp_ambiguous, key=lambda e: e["property"])
            if ambiguous:
                out["ambiguous"] = ambiguous
            matched = sorted(matched + exp_matched, key=lambda e: (e["property"], e.get("sources") or e.get("expectations")))
            if matched:
                out["matched"] = matched
            return out

        return self._finish(view, compute(view, state), "conflicts",
                            lambda: compute(literal_view(acc, view), InForce(LITERAL)), subjects={subject},
                            unavailable=missing)

    # -- 9.5 stories ----------------------------------------------------------------------

    def _story_account(self, story_id: str, frame_spec) -> Account:
        rs = self.store.load_closure({story_id} | getattr(self, "_cutoff_seeds", set()))
        acc = Account(rs)
        st = load_story(acc, story_id)
        subjects = {story_id}
        if st and st.subject:
            rs = self.store.load_closure({st.subject}, rs)
            subjects.add(st.subject)
        # 7.2.4, 7.3.8: the story's interpretation is the one in force for its subject; a
        # resolved frame names the one in force for the read's scope (4.6.1)
        spec = frame_spec or {}
        scope = spec.get("scope")
        if isinstance(scope, list):
            subjects |= {x["id"] if is_item_ref(x) else x for x in scope}
        elif scope is not None:
            subjects.add(scope["id"] if is_item_ref(scope) else scope)
        persp = spec.get("perspective", "record")
        self.store.load_normalizations(rs, subjects, issuance=not (persp is None or persp == "record"))
        return Account(rs)

    def r_story(self, args: dict) -> dict:
        """9.5.1: a story's detections, acts, related stories, interval, ending and standing,
        in the frame's perspective (9.7.2)."""
        sid = args["story"]
        acc = self._story_account(sid, args.get("frame"))
        view, lim = self._frame(acc, args)
        if lim:
            return lim
        st = load_story(acc, sid)
        if st is None:
            return self._finish(view, {"status": "not_found"}, "story")
        if view.frame.perspective is not None and st.interp_unavailable is not None and not st.malformed:
            # README §5 *Unavailable interpretations*: a computed read of the unit in a
            # participant perspective is the limitation, in place of its result (7.6.14)
            return self._finish(view, unavailable_object(st.interp_unavailable), "story")
        cache: dict = {}
        ev = evaluate_story_in_view(view, sid, args.get("attention_filter"), cache=cache)
        if view.frame.perspective is None and (st.interp_unavailable is not None or st.cmp.ambiguous or ev.varies) \
                and ev.open != "limitation":
            ev = self._story_as_recorded(view, st, ev)
        if ev.open != "limitation":
            self._story_recorded(view, st, ev, cache)
        return self._finish(view, ev.result, "story")

    @staticmethod
    def _story_as_recorded(view: View, st, ev: StoryEval) -> StoryEval:
        """7.6.14: a story whose interpretation the reference does not have cannot be derived,
        so its open dimension, baseline ending and interval are read from its recorded
        transitions, in the record perspective; so is a story whose interpretation in force is
        ambiguous, whose recorded contents carry the candidates (7.6.6). A recorded limitation
        content makes the read a limitation. Its other dimensions are derived as before (9.5.2)."""
        acc, res = view.acc, dict(ev.result)
        rps = recorded_periods(acc, Unit(story=st.id))
        lim = next((c for rp in rps for c in (rp.begin.content, rp.end_content(None))
                    if isinstance(c, dict) and "limitation" in c), None)
        if lim is not None:
            keep = ("kind", "detections", "acts", "related", "interpretation", "interpretation_version",
                    "normalization", "subject", "unsupported")
            out = {**limitation_members(lim), **{k: res[k] for k in keep if k in res}}
            return StoryEval(st, out, "limitation", ev.review)
        standing = dict(res.get("standing") or {})
        nonnull = [rp for rp in rps if rp.begin.content is not None]
        state, _end, _start = story_state_recorded(acc, st, view.cutoff, None, rps)
        if state == "continued_in" or continued_in(acc, st) is not None:
            standing["open"] = state
        elif not nonnull:
            end = next((rp.end_content(None) for rp in rps if rp.end_content(None) is not None), None)
            standing["open"] = state
            # 7.6.12: before a normalization ending's `since` the story reads not_started
            res["ending"] = no_period_ending(acc, end) if end is not None and state == "ended" else None
            res["interval"] = {"start": None, "end": None, "empty": True} if end is not None else \
                {"start": None, "end": None}
        else:
            state, ending, interval = read_story_periods(
                acc, [(rp.begin.content, rp.end_content(None)) for rp in nonnull], view.cutoff)
            standing["open"] = state
            res["ending"] = ending
            res["interval"] = interval
        if standing.get("open") != "continued_in":
            standing.pop("continued_in", None)
        res["standing"] = standing
        return StoryEval(st, res, standing["open"], ev.review)

    def _story_recorded(self, view: View, st, ev: StoryEval, cache: dict) -> None:
        """9.5.1, README §5 `story`: the ending policy, the periods, and the ending under the
        policy with the baseline ending beside it (7.7.4). In the record perspective the
        periods and, under a non-baseline policy, the ending and the open dimension are read
        from the recorded transitions (7.6.14); in a participant perspective they are computed
        and the baseline applies."""
        acc, res = view.acc, ev.result
        res["policy"] = policy_out(st.policy_at(view.cutoff))
        res["baseline_ending"] = res.get("ending")
        standing = res.get("standing") or {}
        governed = any(p is not None for _s, p in st.policy_segments)
        if view.frame.perspective is None:
            rps = recorded_periods(acc, Unit(story=st.id))
            res["periods"] = periods_out(rps, st.policy_segments)
            empty = (res.get("interval") or {}).get("empty")
            if governed and not empty and standing.get("open") != "continued_in":
                # 7.7.3, 7.6.14: the ending under the policy governing the period's ending, at
                # the later of its end act's `at` and the start of that policy's governance;
                # where tied adopt_policy acts leave that policy ambiguous, under each candidate
                # (7.7.2, README §5 *Ending policies*)
                cands = [story_state_recorded(acc, st, view.cutoff, segs, rps)
                         for segs in segment_resolutions(st.policy_segments)]
                states = {c[0] for c in cands}
                if not states & {"limitation", "continued_in"}:
                    endings = [ending_of(acc, c[1]) if c[0] == "ended" else None for c in cands]
                    state = states.pop() if len(states) == 1 else "ambiguous"
                    standing["open"] = state
                    if all(e == endings[0] for e in endings):
                        res["ending"] = endings[0]
                    else:
                        res["ending"] = {"ambiguous": endings,
                                         "records": [compact(r.triple) for r in segment_tied_records(st.policy_segments)]}
                    ev.open = state
        else:
            strict, _lenient = participant_story_views(view, cache.setdefault(("accounts", id(acc)), {}))
            d = derive_unit(strict.acc, Unit(story=st.id))
            res["periods"] = computed_periods_out(d.periods, st.policy_segments)

    def _recorded_story_eval(self, view: View, st, attention_filter: str | None) -> StoryEval:
        """A story's open dimension in a listing read of the record perspective, read from its
        recorded transitions under its ending policy (7.6.14, 9.5.3); review and attention are
        derived (9.5.2)."""
        acc, cutoff = view.acc, view.cutoff
        review, _r = _review_dimension(view, st, cutoff)
        if st.malformed or st.kind not in ("conflict", "change"):
            return StoryEval(st, {"limitation": st.malformed or "story_unresolvable"}, "limitation", review)
        state, _end, start = story_state_recorded(acc, st, cutoff)
        if state == "limitation":
            # 7.6.6: a beginning that cannot be placed is recorded as a limitation content
            content = next((rp.begin.content for rp in recorded_periods(acc, Unit(story=st.id))
                            if isinstance(rp.begin.content, dict) and "limitation" in rp.begin.content), {})
            return StoryEval(st, limitation_members(content), "limitation", review)
        standing = {"open": state, "review": review}
        if attention_filter:
            standing["attention"] = story_attention(view, st, cutoff)
        return StoryEval(st, {"interval": {"start": start}, "standing": standing}, state, review)

    @staticmethod
    def _derived_variant_state(view: View, ev: StoryEval) -> None:
        """With the ``derive`` switch, a story whose derivation depends on what is unspecified
        (7.6.6): its open dimension and interval start from its derived periods, whose contents
        are ambiguous where the resolutions differ."""
        d = derive_unit(view.acc, Unit(story=ev.story.id))
        pairs = [(p.begin, p.end) for p in d.periods if p.begin is not None]
        standing = ev.result.setdefault("standing", {})
        if not pairs:
            ends = [p.end for p in d.periods if p.end is not None]
            if ends:
                # 7.6.12: ended, from a normalization ending's `since`
                ev.open = standing["open"] = no_period_state(ends[0], view.cutoff)
            return
        state, _ending, interval = read_story_periods(view.acc, pairs, view.cutoff)
        ev.open = standing["open"] = state
        ev.result["interval"] = interval

    def _derived_policy_state(self, view: View, ev: StoryEval) -> None:
        """With the ``derive`` switch, a story under a non-baseline policy: its open dimension
        follows the policy's endings, derived when the reference implements the policy and
        read from its end acts otherwise (7.7.5)."""
        st = ev.story
        if all(p is None for _s, p in st.policy_segments) or ev.open in ("limitation", "continued_in"):
            return
        if (ev.result.get("interval") or {}).get("empty"):
            return
        acc = view.acc
        if all(p is None or implemented(p) for _s, p in st.policy_segments):
            d = derive_unit(acc, Unit(story=st.id))
            pairs = [(p.begin, p.policy_end) for p in d.periods if p.begin is not None]
            if not pairs:
                return
            state, _idx = periods_state(pairs, view.cutoff)
        else:
            state, _end, _start = story_state_recorded(acc, st, view.cutoff)
        ev.open = state
        ev.result.setdefault("standing", {})["open"] = state

    def _evaluate_scope_stories(self, view: View, attention_filter: str | None):
        members = scope_members(view.acc, view.frame.scope, view.cutoff)
        stories = [s for s in all_stories(view.acc, None) if members is None or s.subject in members]
        if view.frame.perspective is None:
            if not self.derive:
                return [self._recorded_story_eval(view, s, attention_filter) for s in stories]
            fam_of: dict[str, Family] = {}
            for f in families(view.acc, stories):
                for sid in f.by_id:
                    fam_of[sid] = f
            evals = []
            for s in stories:
                if s.interp_unavailable is not None and not s.malformed:
                    # 7.6.14: a story whose interpretation the reference does not have is read
                    # as recorded on either path
                    evals.append(self._recorded_story_eval(view, s, attention_filter))
                    continue
                ev = evaluate_story(view, s, fam_of.get(s.id), attention_filter)
                if (ev.varies or s.cmp.ambiguous) and ev.open != "limitation":
                    self._derived_variant_state(view, ev)
                self._derived_policy_state(view, ev)
                evals.append(ev)
            return evals
        cache: dict = {}
        evals = []
        for s in stories:
            if s.interp_unavailable is not None and not s.malformed:
                # README §5 *Unavailable interpretations*: a computed read in a participant
                # perspective lists the unit among its limitations (7.6.14)
                review, _r = _review_dimension(view, s, view.cutoff)
                evals.append(StoryEval(s, unavailable_object(s.interp_unavailable), "limitation", review))
                continue
            ev = evaluate_story_in_view(view, s.id, attention_filter, cache)
            if ev is not None:
                evals.append(ev)
        return evals

    @staticmethod
    def _supersede(evals) -> tuple[list, list, list, list]:
        """9.5.3: the open stories, a conflict-story family's disagreement counted once."""
        listed, superseded, ambiguous, limitations = [], [], [], []
        by_family: dict[tuple, list] = {}
        for ev in evals:
            if ev.open == "limitation":
                limitations.append(ev)
            elif ev.open == "ambiguous":
                ambiguous.append(ev)
            elif ev.open == "open":
                fam = ev.story.family if ev.story.kind == "conflict" else None
                if fam is None:
                    listed.append(ev)
                else:
                    by_family.setdefault(fam, []).append(ev)
        for evs in by_family.values():
            latest = [e for e in evs if not any(_began_after(o, e) for o in evs if o is not e)]
            if len(latest) == 1:
                listed.append(latest[0])
            else:
                ambiguous += latest  # 9.5.3, 4.5.3: tied for latest, so none is chosen
            superseded += [e for e in evs if not any(e is x for x in latest)]
        return listed, superseded, ambiguous, limitations

    def _story_lists(self, view: View, filt: str | None):
        """9.5.3: the open stories in scope, a conflict-story family's disagreement counted
        once. Of several stories of one family that read `open`, only the one whose interval
        began latest is listed; the others are superseded and keep their own standing in
        story reads. When the latest starts are equal or unordered (4.2.5), none is chosen:
        the stories that no other story of the family began after are listed among the
        ambiguous entries (4.5.3), and the family's other open stories are superseded. A
        story continued in another is not listed. Change stories belong to no family, so
        every open change story is listed and counted (7.2.7, 7.3.7). Stories that read
        `ambiguous`, or whose read is a limitation, are listed apart. With the attention
        filter, superseding is decided first; an ignored story is then omitted, and one whose
        attention reads `ambiguous` is listed among the ambiguous entries in its place."""
        evals = self._evaluate_scope_stories(view, filt)
        listed, superseded, ambiguous, limitations = self._supersede(evals)
        if filt == "ignore":
            kept = []
            for ev in listed:
                attention = (ev.result.get("standing") or {}).get("attention")
                if attention == "ignored":
                    continue
                if attention == "ambiguous":
                    ambiguous.append(ev)
                    continue
                kept.append(ev)
            listed = kept
        return listed, superseded, ambiguous, limitations

    def r_open_stories(self, args: dict) -> dict:
        """9.5.3: every open story in scope, each disagreement counted once; ignored stories
        are included unless an attention filter is named (9.5.5)."""
        acc = self._listing_load(args.get("frame"))
        view, lim = self._frame(acc, args)
        if lim:
            return lim
        filt = args.get("attention_filter")

        def compute(v: View):
            listed, superseded, ambiguous, limitations = self._story_lists(v, filt)
            return {"stories": _ids(listed), "count": len(listed), "superseded": _ids(superseded),
                    "ambiguous": _ids(ambiguous), "limitations": _ids(limitations), "filter": filt}

        members = scope_members(acc, view.frame.scope, view.cutoff)
        return self._finish(view, compute(view), "open_stories",
                            lambda: compute(View(acc, Frame(view.cutoff, view.frame.perspective, LITERAL, view.frame.scope))),
                            subjects=self._scope_subjects(members))

    def r_pending_review(self, args: dict) -> dict:
        """9.5.4: the open stories listed by 9.5.3 that are unreviewed, and the superseded ones
        that are unreviewed; ambiguous and limitation entries in separate lists."""
        acc = self._listing_load(args.get("frame"))
        view, lim = self._frame(acc, args)
        if lim:
            return lim
        filt = args.get("attention_filter")

        def compute(v: View):
            listed, superseded, ambiguous, limitations = self._story_lists(v, filt)
            stories = [ev for ev in listed if ev.review == "unreviewed"]
            return {"stories": _ids(stories), "count": len(stories),
                    "superseded": _ids([ev for ev in superseded if ev.review == "unreviewed"]),
                    "ambiguous": _ids(ambiguous + [ev for ev in listed if ev.review == "ambiguous"]),
                    "limitations": _ids(limitations), "filter": filt}

        members = scope_members(acc, view.frame.scope, view.cutoff)
        return self._finish(view, compute(view), "pending_review",
                            lambda: compute(View(acc, Frame(view.cutoff, view.frame.perspective, LITERAL, view.frame.scope))),
                            subjects=self._scope_subjects(members))

    # -- 9.5.7 what remains, 9.5.8 transition check ------------------------------------

    def r_what_remains(self, args: dict) -> dict:
        """9.5.7: every unit of work in scope that is open at the frame under its ending
        policy, with counts by kind; superseded, upcoming, ambiguous and limitation entries in
        separate lists; ignored entries included unless an attention filter is named (9.5.5).
        In the record perspective it reads the recorded transitions (7.6.14); in a participant
        perspective, and for an expectation whose interpretation differs from the frame's, it
        computes them."""
        acc = self._listing_load(args.get("frame"))
        view, lim = self._frame(acc, args)
        if lim:
            return lim
        filt = args.get("attention_filter")
        members = scope_members(acc, view.frame.scope, view.cutoff)
        res = self._what_remains(view, members, filt)
        return self._finish(view, res, "what_remains", subjects=self._scope_subjects(members))

    def _what_remains(self, view: View, members, filt: str | None) -> dict:
        acc, cutoff = view.acc, view.cutoff
        lists: dict[str, list] = {"open": [], "upcoming": [], "superseded": [], "ambiguous": [], "limitations": []}
        evals = self._evaluate_scope_stories(view, filt)
        story_open = {ev.story.id: ev.open for ev in evals}
        listed, superseded, ambiguous, limitations = self._supersede(evals)
        cache: dict = {}
        exp_recs = [r for r in sorted((r for r in acc.records.values() if r.kind == "expectation"), key=lambda r: r.triple)
                    if members is None or r.item in members]
        deriv = _Derivation(self, view)
        deriv.prepare([r for r in exp_recs if deriv.needs(r)],
                      [ev.story for ev in listed + superseded + ambiguous
                       if ev.story.kind == "conflict" and (ev.result.get("standing") or {}).get("disagreement") is None])

        def open_of(sid: str) -> str:
            if sid not in story_open:
                st = load_story(acc, sid)
                if st is None:
                    story_open[sid] = "not_found"
                elif view.frame.perspective is None and (not self.derive or st.interp_unavailable is not None):
                    story_open[sid] = self._recorded_story_eval(view, st, None).open
                else:
                    ev = evaluate_story_in_view(view, sid, None, cache)
                    if ev is not None and view.frame.perspective is None:
                        self._derived_policy_state(view, ev)
                    story_open[sid] = ev.open if ev is not None else "not_found"
            return story_open[sid]

        story_entries: dict[str, dict] = {}

        def story_entry(ev: StoryEval) -> dict:
            st = ev.story
            standing: dict[str, Any] = {"review": ev.review}
            if st.kind == "conflict":
                d = (ev.result.get("standing") or {}).get("disagreement")
                if d is not None:
                    standing["disagreement"] = d
                    mb = (ev.result.get("standing") or {}).get("matched_by")
                    if mb is not None:
                        standing["matched_by"] = mb
                elif story_unavailable_at(st, cutoff) is not None:
                    standing["disagreement"] = unavailable_object(story_unavailable_at(st, cutoff))
                else:
                    d, mb = deriv.disagreement(view, st, cutoff)
                    standing["disagreement"] = d
                    if mb:
                        standing["matched_by"] = compact_or_list(mb)
            if filt:
                standing["attention"] = (ev.result.get("standing") or {}).get("attention") or \
                    story_attention(view, st, cutoff)
            succeeds = sorted({ref_triple(d.values["@relates_to"])[0] for d in st.detections
                               if is_assertion_ref(d.values.get("@relates_to"))})
            entry = {"kind": st.kind, "unit": st.id, "began": self._story_began(view, st),
                     "policy": policy_out(st.policy_at(cutoff)), "standing": standing, "parents": [], "succeeds": succeeds,
                     "children": [], "interpretation": story_interpretation_members(st, cutoff)["interpretation"]}
            story_entries[st.id] = entry
            return entry

        for ev in listed:
            lists["open"].append(story_entry(ev))
        for ev in superseded:
            lists["superseded"].append(story_entry(ev))
        for ev in ambiguous:
            lists["ambiguous"].append(story_entry(ev))
        for ev in limitations:
            entry = {"kind": ev.story.kind, "unit": ev.story.id, "limitation": ev.result.get("limitation")}
            if "records" in ev.result:
                entry["records"] = ev.result["records"]
            if entry["limitation"] == "interpretation_unavailable" and "interpretation" in ev.result:
                entry["interpretation"] = ev.result["interpretation"]
            lists["limitations"].append(entry)
        children: dict[str, set] = {}
        for rec in exp_recs:
            if acc.limits.get(rec.triple):
                corr, act = acc.limits[rec.triple][0]
                for p in sorted(properties_of_rec(rec)):
                    lists["limitations"].append({"kind": "expectation", "unit": compact(rec.triple, p),
                                                 "limitation": "relocated_reference", "correction": compact(corr),
                                                 "record": compact(act)})
                continue
            for where, entry in self._expectation_remains(*deriv.of(view, rec), filt, open_of):
                lists[where].append(entry)
                if where in ("open", "upcoming"):
                    for parent in entry["parents"]:
                        children.setdefault(parent["story"], set()).add(entry["unit"])
        for sid, units in children.items():
            if sid in story_entries:
                story_entries[sid]["children"] = sorted(units)
        if filt == "ignore":
            for name in ("open", "upcoming"):
                kept = []
                for e in lists[name]:
                    att = e["standing"].get("attention")
                    if att == "ignored":
                        continue
                    if att == "ambiguous":
                        lists["ambiguous"].append(e)
                        continue
                    kept.append(e)
                lists[name] = kept
        for name in lists:
            lists[name].sort(key=lambda e: (_KIND_ORDER.get(e.get("kind"), 3), e["unit"]))
        out: dict[str, Any] = dict(lists)
        out["counts"] = {k: sum(1 for e in lists["open"] if e["kind"] == k) for k in ("conflict", "change", "expectation")}
        out["filter"] = filt
        return out

    def _story_began(self, view: View, st) -> dict | None:
        """9.5.7: the begin act of the story's current period, the latest open period that
        began at or before the cutoff; computed outside the recorded path (act null)."""
        acc = view.acc
        record = view.frame.perspective is None
        unimplemented = any(p is not None and not implemented(p) for _s, p in st.policy_segments)
        if record and (not self.derive or unimplemented or st.interp_unavailable is not None or st.cmp.ambiguous):
            # a policy the reference does not implement is read from its end acts (7.7.5), and a
            # story whose interpretation it does not have from its recorded acts (7.6.14)
            cur = current_period(recorded_periods(acc, Unit(story=st.id)), st.policy_segments, view.cutoff)
            if not self.derive:
                return transition_out(cur.begin) if cur is not None else None
            return transition_out(None, cur.begin.content) if cur is not None else None
        d_acc = acc if record else participant_story_views(view)[0].acc
        d = derive_unit(d_acc, Unit(story=st.id))
        return _current_derived(d.periods, record and any(p is not None for _s, p in st.policy_segments), view.cutoff)

    def _expectation_remains(self, view: View, rec: Rec, filt, open_of) -> list[tuple[str, dict]]:
        """The what-remains entries of one expectation's properties (9.5.7)."""
        acc, cutoff = view.acc, view.cutoff
        own = view.frame.perspective is None and is_own_interpretation(acc, rec, view.frame)
        missing = self._computed_unavailable(view, rec)
        if missing is not None:
            # 7.6.14: computed under an interpretation the reference does not have
            return [("limitations", {"kind": "expectation", "unit": compact(rec.triple, p),
                                     "limitation": "interpretation_unavailable", "interpretation": missing})
                    for p in sorted(properties_of_rec(rec))]
        e = Expectation(view, rec)
        props, policy_open = self._property_standings(view, rec, e)
        segments = expectation_policy_segments(acc, rec)
        policy = policy_out(expectation_policy(acc, rec, cutoff))
        attention = _ignored(view, rec) if filt else False
        unavailable = own and expectation_unavailable(acc, rec) is not None
        interp_state = (own_schedule(acc, rec) if own else read_schedule_of(view, rec)).at_cutoff(cutoff)
        interp_name = interp_state.interp.name if interp_state.interp is not None else None
        unimplemented = any(p is not None and not implemented(p) for _s, p in segments)
        out = []
        for p in e.props:
            s = props[p]
            st = s["standing"]
            unit = Unit(exp=rec.triple, prop=p)
            if unavailable:
                # 7.6.14, 7.6.6: read as recorded; a recorded limitation content puts the unit
                # among the limitations, since its standing cannot be derived
                lim = next((c for rp in recorded_periods(acc, unit) for c in (rp.begin.content, rp.end_content(None))
                            if isinstance(c, dict) and "limitation" in c), None)
                if lim is not None:
                    out.append(("limitations", {"kind": "expectation", "unit": unit.id, **limitation_members(lim)}))
                    continue
            if policy_open is not None:
                po = policy_open.get(p)
                if po is None:
                    where = "ambiguous"
                elif po is False:
                    continue
                else:
                    where = "upcoming" if st == "not_yet_due" else "open"
                    if st == "ambiguous":
                        c = {x.get("standing") for x in s.get("candidates") or []}
                        where = "upcoming" if c == {"not_yet_due"} else ("open" if "not_yet_due" not in c else "ambiguous")
            else:
                def place(x):
                    return "open" if x == "outstanding" else ("upcoming" if x == "not_yet_due" else None)
                if st == "ambiguous":
                    places = {place(c.get("standing")) for c in s.get("candidates") or [{}]}
                    if len(places) != 1:
                        where = "ambiguous"
                    else:
                        where = places.pop()
                else:
                    where = place(st)
                if where is None:
                    continue
            standing: dict[str, Any] = {"standing": st}
            if st in ("outstanding", "not_yet_due"):
                standing["overdue"] = bool(s.get("overdue")) if st == "outstanding" else False
            if st == "ambiguous":
                standing["candidates"] = [c.get("standing") for c in s.get("candidates") or []]
            if filt:
                standing["attention"] = "ignored" if attention is True else ("ambiguous" if attention is None else "attended")
            if own and (not self.derive or unimplemented or unavailable):
                # recorded transitions; with the derive switch only for a policy the reference
                # does not implement, whose endings are read from its end acts (7.7.5), or for an
                # own interpretation it does not have (7.6.14)
                cur = current_period(recorded_periods(acc, unit), segments, cutoff)
                begin_content = cur.begin.content if cur is not None else None
                began = (transition_out(cur.begin) if not self.derive else transition_out(None, begin_content)) \
                    if cur is not None else None
            else:
                if own:
                    d = derive_unit(acc, unit)
                    periods, with_policy = d.periods, any(x is not None for _s, x in segments)
                else:
                    periods, with_policy = _computed_expectation_periods(view, rec, p), False
                cur = _current_derived_period(periods, with_policy, cutoff)
                begin_content = cur.begin if cur is not None else None
                began = transition_out(None, begin_content) if cur is not None else None
            parents = [{"story": sid, "open": open_of(sid)}
                       for sid in parents_of(acc, rec, p, begin_content)] if begin_content is not None else []
            out.append((where, {"kind": "expectation", "unit": unit.id, "began": began,
                                "policy": policy, "standing": standing, "parents": parents,
                                "succeeds": [], "children": [], "interpretation": interp_name}))
        return out

    def r_transition_check(self, args: dict) -> dict:
        """9.5.8: for every unit of work in scope, its applicable recorded baseline
        transitions compared with those derived from the record, in the record perspective;
        the end acts of a governing policy the reference does not implement, and the begin and
        end acts of a unit whose interpretation it does not have (7.6.14), are listed as
        unverified. The check records nothing; the cutoff only decides the scope's members."""
        spec = dict(args.get("frame") or {})
        spec["perspective"] = "record"
        spec["interpretation"] = None
        acc, _ = self._load(spec, set(), scoped=True)
        view, lim = self._frame(acc, {"frame": spec}, inforce=False)
        if lim:
            return lim
        members = scope_members(acc, view.frame.scope, view.cutoff)
        diffs, unverified = check_units(acc, units_about(acc, members))
        diffs.sort(key=lambda d: (d.unit.id, 1 if d.act is None else 0,
                                  compact(d.act.rec.triple) if d.act is not None else "", d.position))
        res = {"differences": [diff_out(d) for d in diffs],
               "unverified": sorted({compact(r.triple) for r in unverified})}
        # README §5 `transition_check`: record perspective and interpretation null, without
        # `normalization`
        view.frame.inforce = {"interpretation": None, "interpretation_version": None}
        res["frame"] = view.frame.echo()
        return res

    # -- 9.7 distribution -----------------------------------------------------------------

    def r_distribution(self, args: dict) -> dict:
        """9.7.1: a milestone's or communication's dated distributions at or before the
        cutoff, the issuance each distributed and their recipients. No cumulative list
        substitutes for the history. A distribution whose relation to the cutoff is
        unspecified is listed as ambiguous (4.5.3); in a participant perspective only the
        distribution records covered for the participant are listed (4.4.2, 9.7.2)."""
        item = args["item"]
        acc, _ = self._load(args.get("frame"), {item})
        view, lim = self._frame(acc, args)
        if lim:
            return lim
        out, ambiguous = [], []
        for r in sorted(acc.statements_about(item), key=acc.sort_key):
            if "@distribution" not in r.values:
                continue
            occ = acc.occurrence(r)
            when = view.within(occ)
            if when is False:
                continue
            if view.frame.perspective is not None:
                covered = view.visible(r)
                if covered is False:
                    continue
                if covered is None:
                    when = None
            # The issuance each record distributed (4.4.1): the one a later distribution names
            # in @issuance; a milestone's publication (and its later distributions) for a
            # milestone; a communication's own issuance context for its self-description.
            iss = r.values.get("@issuance")
            if is_item_ref(iss):
                issuance = iss["id"]
            elif acc.role(item) == "milestone":
                issuance = item
            elif r.item == r.source:
                issuance = r.context
            else:
                issuance = None
            entry = {"record": compact(r.triple), "at": occ.text if occ else None, "issuance": issuance,
                     "recipients": [x["id"] for x in r.values["@distribution"] if is_item_ref(x)]}
            (out if when is True else ambiguous).append(entry)
        res: dict[str, Any] = {"distributions": out}
        if ambiguous:
            res["ambiguous"] = ambiguous
        return self._finish(view, res, "distribution", subjects={item})

    def r_distributed_to(self, args: dict) -> dict:
        """9.7.1: the statements distributed to a participant by the cutoff (4.4.2),
        including the self-descriptions, publications and later distributions that list
        the participant."""
        participant = args["participant"]
        acc, _ = self._load(args.get("frame"), set(), scoped=True)
        view, lim = self._frame(acc, args)
        if lim:
            return lim
        members = scope_members(acc, view.frame.scope, view.cutoff)
        pview = View(acc, Frame(view.cutoff, participant, view.interp, view.frame.scope))
        recs = []
        for r in acc.records.values():
            if r.kind != "statement":
                continue
            if members is not None and r.item not in members:
                continue
            if pview.statement_in(r) is True:
                recs.append(r)
        recs.sort(key=acc.sort_key)
        return self._finish(view, {"participant": participant, "records": [compact(r.triple) for r in recs]},
                            "distributed_to", subjects=self._scope_subjects(members, participant))

    # -- 9.9 adjacency --------------------------------------------------------------------

    def r_adjacency(self, args: dict) -> dict:
        """9.9.1: Connections active at the cutoff in both directions and, on request, the
        state history of every Connection touching the Item that was created at or before
        the cutoff (8.6.4). What this read surfaces is exactly what traversal reaches."""
        item = args["item"]
        acc, _ = self._load(args.get("frame"), {item}, connections={item})
        view, lim = self._frame(acc, args)
        if lim:
            return lim
        outgoing, incoming, hist, ignored = [], [], {}, {}
        for pair in sorted(acc.rs.connections):
            if item not in pair:
                continue
            cs = connection_state(acc, pair)
            if connection_active_at(cs, view.cutoff) is True:
                if pair[0] == item:
                    outgoing.append(pair[1])
                if pair[1] == item:
                    incoming.append(pair[0])
            if args.get("history"):
                if cs.connected_at is None or (view.cutoff is not None
                                               and T.at_or_before(cs.connected_at, view.cutoff) is not True):
                    continue  # created after the cutoff (9.1.1)
                key = f"{pair[0]}->{pair[1]}"
                hist[key] = history(cs, view.cutoff)
                ign = [compact(r.triple) for t, _k, r, eff in cs.events
                       if not eff and (view.cutoff is None or T.at_or_before(t, view.cutoff) is True)]
                if ign:
                    ignored[key] = ign
        res: dict[str, Any] = {"outgoing": sorted(outgoing), "incoming": sorted(incoming)}
        if args.get("history"):
            res["history"] = hist
            if ignored:
                res["history_ignored_acts"] = ignored
        return self._finish(view, res, "adjacency", subjects={item})


def _compact_ref(v: Any) -> Any:
    if is_assertion_ref(v):
        return compact(ref_triple(v))
    if isinstance(v, list):
        return [compact(ref_triple(x)) for x in v if is_assertion_ref(x)]
    return None


def _computed_expectation_periods(view: View, rec: Rec, prop: str) -> list:
    """7.6.14: an expectation's periods computed under the interpretation the frame names, or
    requests (literal comparison), at every instant, or, in a participant perspective with a
    frame naming none, under its own interpretation as it is in that perspective."""
    acc = view.acc
    pv = whole_view(acc, view.interp if view.frame.named else None) if view.frame.perspective is None else \
        View(acc, Frame(view.cutoff, view.frame.perspective, view.interp, named=view.frame.named))
    return expectation_periods(acc, rec, prop, view=pv, sched=read_schedule_of(view, rec))


def _ids(evals) -> list[str]:
    return sorted(ev.story.id for ev in evals)


def norm_present(acc: Account) -> bool:
    """Whether the account holds any normalization (7.3.8)."""
    from .normalization import norm_index  # noqa: PLC0415
    return not norm_index(acc).empty


def literal_view(acc: Account, view: View, scope: Any = None) -> View:
    """The same frame under literal comparison at every instant, for a result labelled as
    literal (5.5.4)."""
    return View(acc, Frame(view.cutoff, view.frame.perspective, LITERAL, scope, named=True))


def frame_unavailable(view: View) -> str | None:
    """The interpretation a frame names, when the reference does not have it (5.5.4)."""
    lim = view.frame.limitation
    if view.frame.named and lim and lim.get("limitation") == "interpretation_unavailable":
        return lim.get("interpretation")
    return None


def properties_of_rec(rec: Rec) -> list[str]:
    return sorted(k for k in rec.values if not k.startswith("@"))


def _current_derived_period(periods, with_policy: bool, cutoff):
    """The latest open period that began at or before the cutoff, from derived periods."""
    found = None
    for p in periods:
        if p.begin is None:
            continue
        state, _ = periods_state([(p.begin, p.policy_end if with_policy else p.end)], cutoff)
        if state in ("open", "ambiguous"):
            found = p
    return found


def _current_derived(periods, with_policy: bool, cutoff) -> dict | None:
    """The begin of that period as a computed <transition> (act null)."""
    found = _current_derived_period(periods, with_policy, cutoff)
    return transition_out(None, found.begin) if found is not None else None


_SELFCHECK = os.environ.get("ATTEDRA_SELFCHECK") == "1"


def _strip(o):
    """A result without the members only one path can give: the recorded acts (`act`,
    `revised_by`) and the resolved frame."""
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k not in ("act", "revised_by", "frame")}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


def _interval_start(ev) -> T.Instant | None:
    start = (ev.result.get("interval") or {}).get("start")
    return T.parse_instant(start) if isinstance(start, str) else None


def _began_after(other, ev) -> bool:
    """9.5.3, 4.2.5: whether ``other``'s interval began after ``ev``'s. Equal or unordered
    starts are neither; a story with no start is treated as beginning before every story
    that has one."""
    a, b = _interval_start(ev), _interval_start(other)
    if b is None:
        return False
    if a is None:
        return True
    return T.before(a, b) is True


def _ignored(view: View, rec: Rec) -> bool | None:
    """9.5.6: an ignore applies to an expectation it targets; True when one is in effect at
    the cutoff, None when that depends on an unspecified order."""
    votes = [ignore_in_effect(view, r, view.cutoff) for r, _tg in view.acc.acts_targeting(("A", rec.triple))
             if r.action == "ignore"]
    if any(v is True for v in votes):
        return True
    if any(v is None for v in votes):
        return None
    return False


def _cutoff_ids(args: dict) -> set[str]:
    """Milestones named as cutoffs must be loaded to resolve them (4.6.1)."""
    out = set()
    for key in ("frame", "from", "to"):
        f = args.get(key)
        if not isinstance(f, dict):
            continue
        c = f.get("cutoff")
        if isinstance(c, dict) and is_item_ref(c):
            out.add(c["id"])
        elif isinstance(c, str) and c != "now" and T.parse_instant(c) is None:
            out.add(c)
    return out
