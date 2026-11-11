"""Writes (spec §8) and their validation (10.2), story maintenance (7.2.8) and permanent
removal (8.5).

Every operation runs in one transaction; a rejected write raises ``WriteError`` and leaves
the store unchanged.

* ``assert_`` parses the values with duplicate-key detection and exact numbers (5.1),
  normalizes ``""`` to ``null`` (5.3.2), and then: an unoccupied triple is inserted after
  validation (8.1.1); an occupied triple with identical content is a no-op (8.1.2); changed
  content at an occupied triple fails ``occupied`` (8.1.3). Acts are dispatched on
  ``@action``: disconnect and reconnect also update the Connection's materialized
  properties (8.6), and story maintenance runs in the same transaction (7.2.8). Begin and
  end acts, ``revise`` and ``adopt_policy`` are validated under 10.2.9 before the act rules
  of 10.2.5-10.2.8 (README §6). After story maintenance, the begin and end acts of every
  affected unit of work are recorded or revised in the same transaction (7.6.9,
  transitions.py), and the result lists them in ``transition_acts`` (README §2).
* A normalization (7.3.8) affects the units whose subjects are members of its scope at some
  instant from its effective time: its write maintains every unit reached from the scope Item,
  bounded by that scope. A normalization naming an interpretation the reference does not have
  is rejected (10.2.9). The units are evaluated together: the account holds each story and
  family once, the account before the write is consulted only for the families maintenance
  may join, split or reconcile, and the new records' names are checked, and the records
  inserted, in one batch. A Connection created, disconnected, reconnected or corrected where a
  normalized scope reaches it changes which normalizations apply to the Items reached through
  it, and is maintained the same way; ``connect`` then lists what it records (README §2).
* Removal is planned, then confirmed or cancelled (8.5.3-8.5.4). The plan identifier is a
  hash of the target's content and of the records the impact test examined, so no extra
  table is needed; confirmation recomputes it at serializable isolation. A plan
  is valid only in the session that issued it, and confirming or cancelling it ends it
  (8.5.4); a record carrying the declared extension is refused (8.5.2(e), 10.4.4), and so is
  any Item while some record in the store carries it (10.4.4, 10.3).
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from contextlib import contextmanager
from typing import Any

from . import instants as T
from .account import Account
from .errors import WriteError
from .expectations import Expectation, own_schedule
from .model import DECLARED_REFERENCE_EXTENSION, Item, Triple, act_targets, carries_member
from .normalization import norm_index
from .store import RawAssertion, RecordSet, Store, dependency_refs
from .model import is_transition_record
from .stories import (Namer, StoryIntervals, all_stories, evaluate_story_in_view, load_story,
                      plan_maintenance)
from .transitions import (Unit, directing_stories, expectation_unavailable, plan_transitions, unit_of_begin,
                          units_about, validate_transition_write)
from .validate import validate_act, validate_definition, validate_values
from .values import (compact, iter_refs, literal_equal, normalize, parse_compact,
                     parse_json_text, ref_item_ids, ref_triple, to_json_text)
from .view import Frame, View, connection_active_at, connection_state, materialized_properties


class StoreResolver:
    """Validation's view of the store: the corrected account of the loaded records, with
    direct lookups for anything outside them."""

    def __init__(self, store: Store, acc: Account) -> None:
        self.store = store
        self.acc = acc

    def item(self, item_id: str) -> Item | None:
        it = self.acc.item(item_id)
        return it if it is not None else self.store.get_item(item_id)

    def item_exists(self, item_id: str) -> bool:
        return item_id in self.acc.rs.items or self.store.item_exists(item_id)

    def assertion_exists(self, triple: Triple) -> bool:
        return triple in self.acc.rs.assertions or self.store.assertion_exists(triple)

    def assertion_values(self, triple: Triple) -> dict | None:
        r = self.acc.get(triple)
        if r is not None:
            return r.values
        raw = self.acc.rs.assertions.get(triple) or self.store.get_assertion(triple)
        return raw.values if raw else None

    def connection_exists(self, pair: tuple[str, str]) -> bool:
        return pair in self.acc.rs.connections or self.store.get_connection(*pair) is not None

    def connection_active_at(self, pair: tuple[str, str], at: T.Instant) -> bool | None:
        return connection_active_at(connection_state(self.acc, pair), at)

    def context_instant(self, ctx_id: str) -> T.Instant | None:
        return self.acc.context_instant(ctx_id)[0]

    def story_kind(self, story_id: str) -> str | None:
        st = load_story(self.acc, story_id)
        return st.kind if st else None

    def schedule_ordinals(self, schedule_id: str, exclude: str | None) -> dict[str, Any]:
        """The ordinals of a schedule's other milestones, using corrected definitions where
        they are loaded (4.3.2, 8.3.8)."""
        ids = {r[0] for r in self.store._q(
            "SELECT id FROM items WHERE definition @> %s::jsonb",
            (to_json_text({"@context": {"role": "milestone", "schedule": {"@ref": "item", "id": schedule_id}}}),))}
        # 8.3.8: distinctness is evaluated against the corrected definitions of the schedule's
        # other milestones, so their Item corrections are loaded with them. A milestone whose
        # recorded definition names another schedule may be corrected into this one, so the
        # loaded account's Items are candidates too.
        others = Account(self.store.load_closure(ids - {exclude}, self.acc.rs.copy(), issuance=False))
        candidates = {i: others.item(i) for i in ids}
        candidates.update({it.id: it for it in others.items.values() if it.id not in candidates})
        out = {}
        for it in candidates.values():
            c = it.context if it else None
            if it is None or it.id == exclude or not c or c.get("role") != "milestone":
                continue
            s = c.get("schedule")
            if isinstance(s, dict) and s.get("id") == schedule_id:
                out[it.id] = c.get("ordinal")
        return out


class Writer:
    def __init__(self, store: Store) -> None:
        self.store = store
        # 8.5.4: the plans this session issued and has not yet confirmed or cancelled. A plan
        # identifier is valid only here, so no record of it is stored (I-1).
        self.live_plans: set[str] = set()

    @property
    def conn(self):
        return self.store.conn

    @contextmanager
    def _tx(self, serializable: bool = False):
        """One transaction per operation; confirmation of a removal runs at
        serializable isolation (8.5.4)."""
        conn = self.conn
        if conn.info.transaction_status != 0:  # not idle: close a read's implicit transaction
            conn.rollback()
        with conn.transaction():
            if serializable:
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            self.store.no_jit()
            yield

    # -- loading for writes -----------------------------------------------------------------

    def _milestones_of(self, schedule_id: str) -> set[str]:
        rows = self.store._q("SELECT id FROM items WHERE definition @> %s::jsonb",
                             (to_json_text({"@context": {"role": "milestone", "schedule": {"@ref": "item", "id": schedule_id}}}),))
        return {r[0] for r in rows}

    def _load_for(self, seeds: set[str], connections: set[str] = frozenset(), rs: RecordSet | None = None) -> RecordSet:
        """The records validation and maintenance read: the closure of ``seeds``, without the
        communications that acts name in ``@issuance``, which only a participant perspective
        reads (``Store.load_closure``)."""
        return self.store.load_closure(seeds, rs, with_connections=set(connections), issuance=False)

    # -- create Item (8.1.5) --------------------------------------------------------------

    def create_item(self, item_id: str, kind: str, label: str | None, definition: dict | None,
                    definition_json: str | None = None) -> dict:
        if definition_json is not None:
            # README §2: raw JSON text, parsed like values_json, so that a duplicate key is
            # rejected (5.1.1); text that is not a JSON object fails 10.2.4
            definition = parse_json_text(definition_json)
            if not isinstance(definition, dict):
                raise WriteError("10.2.4", "a definition must be a JSON object (2.1.2)")
        definition = {} if definition is None else definition
        if not isinstance(item_id, str) or not item_id or not isinstance(kind, str) or not kind:
            raise WriteError("10.2.4", "an Item needs a string id and kind (2.1.2)")
        if label is not None and not isinstance(label, str):
            raise WriteError("10.2.4", "an Item's label is text (2.1.2)")
        with self._tx():
            existing = self.store.get_item(item_id)
            if existing is not None:
                if existing.kind == kind and existing.label == label and literal_equal(existing.definition, definition):
                    return {"status": "exists", "id": item_id}
                raise WriteError("occupied", f"Item {item_id!r} exists with different content; definitions never change (8.1.5)")
            seeds = {i for r in iter_refs(definition) for i in ref_item_ids(r)}
            ctx = definition.get("@context") if isinstance(definition, dict) else None
            if isinstance(ctx, dict) and isinstance(ctx.get("schedule"), dict) and isinstance(ctx["schedule"].get("id"), str):
                seeds |= self._milestones_of(ctx["schedule"]["id"])
            acc = Account(self._load_for(seeds))
            validate_definition(item_id, definition, StoreResolver(self.store, acc))
            self.store.insert_item(Item(item_id, kind, label, definition))
        return {"status": "created", "id": item_id}

    # -- connections (8.6.1) --------------------------------------------------------------

    def connect(self, a: str, b: str, at: str) -> dict:
        when = T.parse_instant(at)
        if when is None:
            raise WriteError("10.2.4", f"{at!r} is not an instant in a 4.2.1 form")
        with self._tx():
            for x in (a, b):
                if not self.store.item_exists(x):
                    raise WriteError("10.2.2", f"Item {x!r} does not resolve")
            if self.store.get_connection(a, b) is not None:
                return {"status": "exists"}  # 2.2.1: a no-op, which never reconnects
            self.store.insert_connection(a, b, {"connected_at": at, "disconnected": False})
            out: dict = {"status": "created"}
            subjects = self._newly_normalized(a, b)
            if subjects:
                # 7.3.8, 7.2.8, 7.6.9: a Connection that changes which normalizations apply to
                # a subject is maintained like any write, bounded by the scope (README §2, §7)
                pair = (a, b)
                rs = self._load_for(subjects, {a, b})
                self.store.load_normalizations(rs, subjects)
                rs_before = rs.copy()
                rs_before.connections.pop(pair, None)
                before = StoryIntervals(Account(rs_before), subjects)
                basis = {"@ref": "connection", "from": a, "to": b}
                out["generated"], acc = self._maintain(rs, subjects, None, before, when)
                out["transition_acts"] = self._maintain_transitions(rs, subjects, None, when, basis, acc=acc)
        return out

    def _newly_normalized(self, a: str, b: str) -> set[str]:
        """7.3.8: the subjects whose normalized scopes a Connection from ``a`` to ``b`` can
        change: ``b`` and the Items reached from it, when a normalized scope Item is ``a`` or
        reaches it. Empty when the store holds no normalization, so that a store without one
        does nothing more on a Connection write."""
        rs = RecordSet()
        if not self.store.load_normalizations(rs, {a}):
            return set()
        idx = norm_index(Account(rs))
        if not (set(idx.by_scope) & (idx.ancestors(a) | {a})):
            return set()
        return {b} | self.store.reach(b)

    # -- insert, replay and acts (8.1, 10.2) --------------------------------------------------

    def _affected_subjects(self, acc: Account, triple: Triple, values: dict) -> set[str]:
        """The subjects whose stories a write can change (7.2.8): the written record's
        subject and those of everything it references, of the records at a milestone it
        publishes or an issuance it describes, of the expectations an eligibility Item
        governs, and the subjects of any stories it touches."""
        subjects = {triple[0]}
        frontier = [values]
        depth = 0
        while frontier and depth < 4:
            nxt = []
            for v in frontier:
                # a participant, a frame, a communication or a distribution list names an Item
                # without the write changing that Item's stories (store.IDENTIFYING_MEMBERS)
                for ref in dependency_refs(v):
                    if ref.get("@ref") == "assertion":
                        subjects.add(ref["item"])
                        t = ref_triple(ref)
                        rec = acc.get(t) or acc.rs.assertions.get(t)
                        if rec is not None and "@action" in rec.values:
                            nxt.append(rec.values)
                    elif ref.get("@ref") == "item":
                        subjects.add(ref["id"])
            frontier = nxt
            depth += 1
        if "@published" in values and triple[0] == triple[1]:
            # a publication dates every Assertion at its milestone (4.2.4), and fixes the
            # deadlines and timing scopes that refer to it (6.2.4, 7.6.9)
            subjects |= {a.triple[0] for a in self.store.assertions_at_context(triple[1])}
            subjects |= self._timing_subjects(triple[1])
        for ref in iter_refs(values):
            # a correction of a publication changes the same (4.2.4, 8.3.3)
            if ref.get("@ref") == "assertion" and ref.get("item") == ref.get("context") and values.get("@action") == "correct":
                subjects |= {a.triple[0] for a in self.store.assertions_at_context(ref["item"])}
                subjects |= self._timing_subjects(ref["item"])
        if triple[0] == triple[2] and "@action" not in values:
            # a self-description attributes the statements its issuance carries (3.1.2, 3.3.2)
            subjects |= {a.triple[0] for a in self.store.assertions_at_context(triple[1]) if a.triple[2] == triple[2]}
        if values.get("@action") == "correct":
            for t in act_targets(values):
                if t.get("@ref") == "item":
                    at_ctx = self.store.assertions_at_context(t["id"])
                    subjects |= {a.triple[0] for a in at_ctx}
                    subjects |= self._timing_subjects(t["id"])
                    # acts at a corrected context take effect at its corrected instant (8.4.1):
                    # the units their targets belong to change with it (7.6.9)
                    for a in at_ctx:
                        if "@action" in a.values:
                            for r in iter_refs(a.values):
                                if r.get("@ref") == "assertion" and isinstance(r.get("item"), str):
                                    subjects.add(r["item"])
                                elif r.get("@ref") == "item" and isinstance(r.get("id"), str):
                                    subjects.add(r["id"])
        it = acc.item(triple[0])
        if it is not None and it.is_eligibility:
            subjects |= {a.triple[0] for a in self.store.assertions_by_source(triple[0])}
        subjects |= self._normalization_subjects(acc, values)
        for s in list(subjects):
            st = load_story(acc, s)
            if st and st.subject:
                subjects.add(st.subject)
        return subjects

    def _normalization_subjects(self, acc: Account, values: dict) -> set[str]:
        """7.3.8, 7.6.9: the subjects a write changes the interpretation in force for. A
        normalization, or a correction of one, affects the members of its scope at some
        instant from its effective time; a disconnect or reconnect act, or a correction of a
        Connection or of such an act, affects the Items reached through the Connection when a
        normalized scope reaches it. Bounded by the scope (9.10.1), never the whole store."""
        out: set[str] = set()
        scopes: set[str] = set()
        a = values.get("@action")
        if a == "reinterpret":
            for t in act_targets(values):
                if t.get("@ref") == "item" and isinstance(t.get("id"), str):
                    scopes.add(t["id"])
        if a == "correct":
            corr = values.get("@corrected")
            if isinstance(corr, dict) and corr.get("@action") == "reinterpret":
                scopes |= {t["id"] for t in act_targets(corr) if t.get("@ref") == "item" and isinstance(t.get("id"), str)}
            for t in act_targets(values):
                if t.get("@ref") == "assertion":
                    r = acc.get(ref_triple(t)) or acc.rs.assertions.get(ref_triple(t))
                    v = r.values if r is not None else {}
                    if v.get("@action") == "reinterpret":
                        scopes |= {x["id"] for x in act_targets(v) if x.get("@ref") == "item" and isinstance(x.get("id"), str)}
        for sc in scopes:
            out |= {sc} | self.store.reach(sc)
        pairs = self._connection_pairs(acc, values)
        for x, y in pairs:
            out |= self._newly_normalized(x, y)
        return out

    @staticmethod
    def _connection_pairs(acc: Account, values: dict) -> set[tuple[str, str]]:
        """The Connections a lifecycle act, or a correction of one or of a Connection, concerns."""
        pairs: set = set()
        frontier = [values]
        for _ in range(3):
            nxt = []
            for v in frontier:
                if v.get("@action") not in ("disconnect", "reconnect", "correct"):
                    continue
                for t in act_targets(v):
                    if t.get("@ref") == "connection" and isinstance(t.get("from"), str) and isinstance(t.get("to"), str):
                        pairs.add((t["from"], t["to"]))
                    elif t.get("@ref") == "assertion":
                        r = acc.rs.assertions.get(ref_triple(t))
                        if r is not None and "@action" in r.values:
                            nxt.append(r.values)
            frontier = nxt
        return pairs

    def _timing_subjects(self, item_id: str) -> set[str]:
        """The subjects of the expectations whose timing refers to a milestone or phase, directly
        or through a phase (6.2.1, 6.2.4): their deadlines, scopes and lateness change with it."""
        out: set[str] = set()
        _a, items = self.store.referencing_item(item_id)
        for it in items:
            c = it.context or {}
            if c.get("role") == "expectation":
                out |= {a.triple[0] for a in self.store.assertions_at_context(it.id)}
            elif c.get("role") == "phase":
                for e in self.store.referencing_item(it.id)[1]:
                    if (e.context or {}).get("role") == "expectation":
                        out |= {a.triple[0] for a in self.store.assertions_at_context(e.id)}
        return out

    def assert_(self, item: str, context: str, source: str, values_json: str,
                recorded_at: str | None = None, recorded_by: str | None = None) -> dict:
        values = parse_json_text(values_json)
        if not isinstance(values, dict):
            raise WriteError("10.2.4", "values must be a JSON object (2.3.1)")
        values = normalize(values)
        rec_at = None
        if recorded_at is not None:
            i = T.parse_instant(recorded_at)
            if i is None:
                raise WriteError("10.2.4", f"recorded_at {recorded_at!r} is not an instant")
            rec_at = T.to_datetime(i)
        triple = (item, context, source)
        with self._tx():
            for x in triple:
                if not self.store.item_exists(x):
                    raise WriteError("10.2.2", f"Item {x!r} does not resolve (2.3.1)")
            existing = self.store.get_assertion(triple)
            if existing is not None:
                if literal_equal(existing.values, values):
                    return {"status": "replayed", "ref": compact(triple), "generated": [], "transition_acts": []}
                raise WriteError("occupied", f"{compact(triple)} is occupied by a record with different content (8.1.3)")
            # the Items the write depends on: its coordinates and what its references name,
            # except where a member only identifies (store.IDENTIFYING_MEMBERS); validation
            # looks up any other Item it names directly (StoreResolver)
            refs = dependency_refs(values)
            seeds = set(triple) | {i for r in refs for i in ref_item_ids(r)}
            conns = {i for r in refs if r.get("@ref") == "connection" for i in ref_item_ids(r)}
            rs = self._load_for(seeds, conns)
            acc = Account(rs)
            ctx = acc.item(context) or self.store.get_item(context)
            if ctx is not None and ctx.role == "phase":
                raise WriteError("10.2.3", "a phase is never an Assertion's context (4.1.1)")
            if ctx is None or ctx.context is None:
                raise WriteError("10.2.3", f"{context!r} has no @context and is not a context (4.1.1, 10.2.3)")
            resolver = StoreResolver(self.store, acc)
            shape = validate_values(values, triple, resolver)
            subjects = self._affected_subjects(acc, triple, values)
            rs = self._load_for(subjects, conns, rs)
            # 7.3.8: the normalizations that apply to the affected subjects
            self.store.load_normalizations(rs, subjects)
            acc = Account(rs)
            if shape.is_act and not shape.extension:
                if values.get("@action") in ("begin", "end") or \
                        (values.get("@action") == "reconcile" and values.get("@outcome") in ("revise", "adopt_policy")):
                    # README §6, precedence 6: 10.2.9 before the act rules of 10.2.5-10.2.8
                    validate_transition_write(acc, triple, values, StoreResolver(self.store, acc).assertion_values)
                validate_act(values, triple, StoreResolver(self.store, acc), acc.context_instant(context)[0])
            before = StoryIntervals(acc, subjects)
            self.store.insert_assertion(triple, values, rec_at, recorded_by)
            rs.assertions[triple] = RawAssertion(triple, values, rec_at, recorded_by)
            if values.get("@action") == "reinterpret" or (
                    isinstance(values.get("@corrected"), dict) and values["@corrected"].get("@action") == "reinterpret"):
                # a first normalization: the Connections that decide its scope's members
                rs.no_normalization.clear()
                self.store.load_normalizations(rs, subjects)
            acc = Account(rs)
            if self._refresh_connections(acc, values):
                acc = Account(rs)
            generated, acc = self._maintain(rs, subjects, triple, before, acc=acc)
            transition_acts = self._maintain_transitions(rs, subjects, triple, acc=acc)
        return {"status": "inserted", "ref": compact(triple), "generated": generated,
                "transition_acts": transition_acts}

    def _refresh_connections(self, acc: Account, values: dict) -> bool:
        """8.6.2-8.6.3, 8.6.6: the materialized properties equal the derivation; they are
        recomputed after a lifecycle act (including a backfilled one) or a correction. Returns
        whether the record set's Connections changed."""
        changed = False
        pairs = set()
        frontier = [values]
        for _ in range(4):
            nxt = []
            for v in frontier:
                for t in act_targets(v):
                    if t.get("@ref") == "connection":
                        pairs.add((t["from"], t["to"]))
                    elif t.get("@ref") == "assertion":
                        r = acc.rs.assertions.get(ref_triple(t))
                        if r is not None and "@action" in r.values:
                            nxt.append(r.values)
                corr = v.get("@corrected")
                if isinstance(corr, dict):
                    nxt.append(corr)
            frontier = nxt
        for pair in pairs:
            if pair not in acc.rs.connections:
                # a correction of a lifecycle act names the act, not the Connection, so the
                # Connection row is fetched here; its acts were loaded with the act's closure
                stored = self.store.get_connection(*pair)
                if stored is not None:
                    acc.rs.connections[pair] = stored
                    changed = True
            if pair in acc.rs.connections:
                props = materialized_properties(acc, pair)
                if props != acc.rs.connections[pair]:
                    self.store.update_connection(*pair, props)
                    acc.rs.connections[pair] = props
                    changed = True
        return changed

    def _maintain(self, rs: RecordSet, subjects: set[str], trigger: Triple | None, before,
                  trigger_at: T.Instant | None = None, acc: Account | None = None) -> tuple[list[str], Account]:
        """Record what the write requires for recorded stories (7.2.8), in the same
        transaction, with the deterministic names of README §7. A write that is not an
        Assertion (a Connection) has no trigger record and gives its time in ``trigger_at``.
        ``acc``, when given, is the account of ``rs`` as it stands. Returns the generated
        records and the account of ``rs`` after them."""
        namer = Namer(lambda i: i in rs.items or self.store.item_exists(i), trigger_at)
        generated: list[str] = []
        boundary_done: set[str] = set()
        for _ in range(60):
            acc = acc if acc is not None else Account(rs)
            g = plan_maintenance(acc, subjects, namer, acc.get(trigger) if trigger is not None else None, before,
                                 boundary_done)
            if g is None:
                break
            acc = None
            for rec in (g, g.follow):
                if rec is None:
                    continue
                for iid, kind, definition in rec.items:
                    if iid not in rs.items and not self.store.item_exists(iid):
                        it = Item(iid, kind, None, definition)
                        self.store.insert_item(it)
                        rs.items[iid] = it
                if rec.triple in rs.assertions:
                    continue
                self.store.insert_assertion(rec.triple, rec.values)
                rs.assertions[rec.triple] = RawAssertion(rec.triple, rec.values)
                generated.append(compact(rec.triple))
        return generated, (acc if acc is not None else Account(rs))

    def _maintain_transitions(self, rs: RecordSet, subjects: set[str], trigger: Triple | None,
                              trigger_at: T.Instant | None = None, basis: dict | None = None,
                              acc: Account | None = None) -> list[str]:
        """Record the begin and end acts of every unit the write affects, and revise those whose
        applicable content the write changed (7.6.9, 7.6.10), in the same transaction, with the
        names and order of README §7 *Recorded transitions*. ``acc``, when given, is the account
        of ``rs`` as it stands. The new records are inserted in one batch."""
        acc = acc if acc is not None else Account(rs)
        stories = directing_stories(acc, subjects) - subjects
        # a directing story about one of the subjects is already loaded with them
        outside = {sid for sid in stories if (load_story(acc, sid) is None or load_story(acc, sid).subject not in subjects)}
        if outside:
            more = {st.subject for st in (load_story(acc, s) for s in outside) if st is not None and st.subject}
            rs = self._load_for(outside | more, rs=rs)
            self.store.load_normalizations(rs, outside | more)
            acc = Account(rs)
        units = units_about(acc, subjects | stories)
        recs = plan_transitions(acc, units, trigger, lambda i: i in rs.items or self.store.item_exists(i),
                                trigger_at, basis,
                                lambda ids: (set(ids) & set(rs.items)) | {it.id for it in self.store.items(set(ids) - set(rs.items))})
        out: list[str] = []
        wanted = {iid for rec in recs for iid, _k, _d in rec.items if iid not in rs.items}
        existing = {it.id for it in self.store.items(wanted)} if wanted else set()
        new_items: list[Item] = []
        for rec in recs:
            for iid, kind, definition in rec.items:
                if iid not in rs.items and iid not in existing:
                    it = Item(iid, kind, None, definition)
                    new_items.append(it)
                    rs.items[iid] = it
            rs.assertions[rec.triple] = RawAssertion(rec.triple, rec.values)
            out.append(compact(rec.triple))
        self.store.insert_many(new_items, [(rec.triple, rec.values) for rec in recs])
        return out

    # -- removal (8.5) -----------------------------------------------------------------------

    def _plan(self, target: str) -> dict:
        """The plan step: the complete set of dependents under 8.5.2, computed within the
        managed store, and the hash of everything examined."""
        ref = parse_compact(target)
        if ref["@ref"] == "assertion":
            triple = ref_triple(ref)
            raw = self.store.get_assertion(triple)
            if raw is None:
                return {"status": "refused", "reason": "not_found", "dependents": []}
            deps = {compact(a.triple) for a in self.store.referencing_assertion(triple) if a.triple != triple}
            if is_transition_record(raw.values):
                # 8.5.2: a begin act, an end act or a revise is a recorded interpretation; the
                # reads of its unit's standing read it, so its unit is a dependent under (c)
                unit = self._unit_of_transition(triple)
                if unit is not None:
                    deps.add(unit.record_id)
                return {"status": "refused", "dependents": sorted(deps)}
            rs, impact, missing = self._impact(triple, raw)
            deps |= impact
            digest = _digest(("A", triple, to_json_text(raw.values)), rs)
            extended = carries_member(raw.values, DECLARED_REFERENCE_EXTENSION)
            if missing is not None and not extended:
                # 8.5.2(c), 10.3, README §2: the impact test examines a unit evaluated under an
                # interpretation the reference does not have, so its dependency knowledge is
                # incomplete and the plan is refused
                return {"status": "refused", "reason": "interpretation_unavailable", "interpretation": missing,
                        "dependents": sorted(deps)}
        elif ref["@ref"] == "item":
            iid = ref["id"]
            it = self.store.get_item(iid)
            if it is None:
                return {"status": "refused", "reason": "not_found", "dependents": []}
            deps = {compact(a.triple) for a in self.store.assertions_using_item(iid)}
            refs_a, refs_i = self.store.referencing_item(iid)
            deps |= {compact(a.triple) for a in refs_a}
            deps |= {i.id for i in refs_i if i.id != iid}
            deps |= {f"{a}->{b}" for (a, b) in self.store.connections_touching({iid})}
            digest = _digest(("I", iid, it.kind, it.label, to_json_text(it.definition)), RecordSet())
            # 10.4.4, 10.3: while any record in the store carries the declared extension, it may
            # reference this Item in a form discovery (2.4.5) does not find, so dependency
            # knowledge is incomplete and the plan is refused
            extended = carries_member(it.definition, DECLARED_REFERENCE_EXTENSION) \
                or self.store.declared_extension_in_store()
        else:
            return {"status": "refused", "reason": "unsupported_target", "dependents": []}
        if extended:
            # 8.5.2(e), 10.4.4: a record carrying a declared non-standard-reference extension has
            # downstream impact by definition; any other dependents are listed with it
            return {"status": "refused", "dependents": sorted(deps), "extension": DECLARED_REFERENCE_EXTENSION}
        if deps:
            return {"status": "refused", "dependents": sorted(deps)}
        return {"status": "planned", "plan": _plan_id(target, digest)}

    def _unit_of_transition(self, triple: Triple) -> Unit | None:
        """The unit of work whose begin act, end act or revise a record is (7.6.4-7.6.10)."""
        acc = Account(self.store.load_closure(set(triple)))
        rec = acc.get(triple)
        for _ in range(3):
            if rec is None:
                return None
            if rec.action == "begin":
                return unit_of_begin(acc, rec)
            targets = act_targets(rec.values)
            if not targets or targets[0].get("@ref") != "assertion":
                return None
            t = ref_triple(targets[0])
            if t not in acc.records:
                acc = Account(self.store.load_closure(set(t), acc.rs))
            rec = acc.get(t)
        return None

    def _impact(self, triple: Triple, raw: RawAssertion) -> tuple[RecordSet, set[str], str | None]:
        """8.5.2(c): derived results that removing the record would change at any cutoff:
        occurrence times, distribution coverage, expectation standing and story intervals,
        standing and endings. The perspectives tested are the record perspective, that of
        every Item named as ``@producer`` or in a ``@distribution`` of the examined records,
        and that of one participant named in none of them; each story is evaluated under its
        recorded interpretation. A story that ceases to exist, because the removed record is
        its only detection, is a change to its standing. The removed entry's own contribution
        to its source's position is not impact."""
        st = self.store
        v = raw.values
        subjects = {triple[0]}
        for r in iter_refs(v):
            if r.get("@ref") == "assertion":
                subjects.add(r["item"])
            elif r.get("@ref") == "item":
                subjects.add(r["id"])
        subjects |= {a.triple[0] for a in st.assertions_at_context(triple[0])}
        if triple[0] == triple[2]:
            subjects |= {a.triple[0] for a in st.assertions_by_source(triple[2]) if a.triple[1] == triple[1]}
        iss = v.get("@issuance")
        if isinstance(iss, dict) and iss.get("id"):
            subjects |= {a.triple[0] for a in st.assertions_by_source(triple[0]) if a.triple[1] == iss["id"]}
        subj_item = st.get_item(triple[0])
        if subj_item is not None and subj_item.is_eligibility:
            subjects |= {a.triple[0] for a in st.assertions_by_source(triple[0])}
        if v.get("@action") == "reinterpret":
            # 8.5.2(c): for a normalization, the units whose subjects are members of its scope
            # at some instant from its effective time (7.3.8)
            for t in act_targets(v):
                if t.get("@ref") == "item" and isinstance(t.get("id"), str):
                    subjects |= {t["id"]} | st.reach(t["id"])
        rs = st.load_closure(subjects | set(triple))
        acc1 = Account(rs)
        for s in list(subjects):
            story = load_story(acc1, s)
            if story and story.subject:
                subjects.add(story.subject)
        rs = st.load_closure(subjects, rs)
        st.load_normalizations(rs, subjects, issuance=True)
        acc1 = Account(rs)
        acc0 = Account(rs.without(triple))
        missing: str | None = None
        deps: set[str] = set()
        # occurrence times of other Assertions (4.2.4)
        for t in acc1.records:
            if t == triple or t not in acc0.records:
                continue
            o1, o0 = acc1.context_instant(t[1]), acc0.context_instant(t[1])
            if (o1[0].text if o1[0] else o1[1]) != (o0[0].text if o0[0] else o0[1]):
                deps.add(compact(t))
        cutoffs = _cutoffs(acc1)
        participants = sorted({x["id"] for r in acc1.records.values()
                               for k in ("@distribution", "@producer")
                               for x in (r.values.get(k) if isinstance(r.values.get(k), list) else [r.values.get(k)])
                               if isinstance(x, dict) and isinstance(x.get("id"), str)})
        unnamed = _unnamed_participant(acc1)
        perspectives = [None] + participants + [unnamed]
        # distribution coverage (4.4.2)
        for p in participants:
            for c in cutoffs:
                v1, v0 = View(acc1, Frame(c, p)), View(acc0, Frame(c, p))
                for t, r in acc1.records.items():
                    if t == triple or t not in acc0.records or r.kind == "expectation":
                        continue
                    if r.is_act and not v1.is_communication_act(r):
                        continue
                    if v1.visible(r) != v0.visible(acc0.records[t]):
                        deps.add(compact(t))
        # expectation standing (§6)
        for t, r in acc1.records.items():
            if r.kind != "expectation" or t == triple or t not in acc0.records:
                continue
            if r.item not in subjects and r.source not in subjects:
                continue
            missing = missing or expectation_unavailable(acc1, r) or expectation_unavailable(acc0, acc0.records[t])
            for p in perspectives:
                for c in cutoffs:
                    v1, v0 = View(acc1, Frame(c, p)), View(acc0, Frame(c, p))
                    # each unit under its own interpretation (8.5.2(c))
                    e1 = Expectation(v1, r, schedule=own_schedule(acc1, r, v1))
                    e0 = Expectation(v0, acc0.records[t], schedule=own_schedule(acc0, acc0.records[t], v0))
                    for prop in e1.props:
                        if _standing_sig(e1.standing(prop, c, with_current=False)) != \
                                _standing_sig(e0.standing(prop, c, with_current=False)):
                            deps.add(compact(t))
        # stories (7.2), in every tested perspective
        s1 = {s.id: s for s in all_stories(acc1, subjects)}
        s0 = {s.id: s for s in all_stories(acc0, subjects)}
        cache1: dict = {}
        cache0: dict = {}
        for sid, story in s1.items():
            if sid not in s0:
                deps.add(sid)
                continue
            missing = missing or story.interp_unavailable or s0[sid].interp_unavailable
            changed = False
            for p in perspectives:
                for c in cutoffs:
                    e1 = evaluate_story_in_view(View(acc1, Frame(c, p)), sid, cache=cache1)
                    e0 = evaluate_story_in_view(View(acc0, Frame(c, p)), sid, cache=cache0)
                    if e1 is None or e0 is None or _story_sig(e1.result) != _story_sig(e0.result):
                        changed = True
                        break
                if changed:
                    break
            if changed:
                deps.add(sid)
        return rs, deps, missing

    def plan_removal(self, target: str) -> dict:
        with self._tx():
            res = self._plan(target)
        if res.get("status") == "planned":
            self.live_plans.add(res["plan"])
        return res

    def confirm_removal(self, plan: str) -> dict:
        decoded = _decode_plan(plan)
        if decoded is None or plan not in self.live_plans:
            # 8.5.4, README §6: a plan this session did not issue, or has already confirmed or
            # cancelled
            raise WriteError("plan_unknown", "no matching removal plan in this session (8.5.4)")
        target, digest = decoded
        with self._tx(serializable=True):
            again = self._plan(target)
            if again.get("status") != "planned" or _decode_plan(again["plan"])[1] != digest:
                raise WriteError("plan_stale", "the target or its dependents changed since the plan; plan again (8.5.4)")
            ref = parse_compact(target)
            if ref["@ref"] == "assertion":
                triple = ref_triple(ref)
                raw = self.store.get_assertion(triple)
                self.store.delete_assertion(triple)
                if raw is not None and raw.values.get("@action") in ("disconnect", "reconnect", "correct"):
                    pairs = {(t["from"], t["to"]) for t in act_targets(raw.values) if t.get("@ref") == "connection"}
                    if pairs:
                        acc = Account(self.store.load_closure({x for p in pairs for x in p}, with_connections={x for p in pairs for x in p}))
                        for pair in pairs:
                            if pair in acc.rs.connections:
                                self.store.update_connection(*pair, materialized_properties(acc, pair))
            else:
                self.store.delete_item(ref["id"])
        self.live_plans.discard(plan)  # confirming a plan ends it (8.5.4)
        return {"status": "removed"}

    def cancel_removal(self, plan: str) -> dict:
        if _decode_plan(plan) is None or plan not in self.live_plans:
            raise WriteError("plan_unknown", "no matching removal plan in this session (8.5.4)")
        self.live_plans.discard(plan)  # cancelling a plan ends it (8.5.4)
        return {"status": "cancelled"}


# ---------------------------------------------------------------------------------------
# plan identifiers and impact signatures


def _digest(head: tuple, rs: RecordSet) -> str:
    h = hashlib.sha256()
    h.update(repr(head).encode())
    for t in sorted(rs.assertions):
        h.update(repr(t).encode())
        h.update(to_json_text(rs.assertions[t].values).encode())
    for i in sorted(rs.items):
        it = rs.items[i]
        h.update(repr((it.id, it.kind, it.label)).encode())
        h.update(to_json_text(it.definition).encode())
    for p in sorted(rs.connections):
        h.update(repr(p).encode())
        h.update(to_json_text(rs.connections[p]).encode())
    return h.hexdigest()[:32]


def _plan_id(target: str, digest: str) -> str:
    """A plan identifier: the target, the digest of what the impact test examined, and a
    per-plan nonce. Each plan step returns a new plan (8.5.3), so cancelling one plan never
    blocks a later plan of the same entry; confirmation revalidates the digest (8.5.4)."""
    return ("plan:" + base64.urlsafe_b64encode(target.encode()).decode().rstrip("=") + ":" + digest
            + ":" + secrets.token_hex(8))


def _decode_plan(plan: str) -> tuple[str, str] | None:
    """(target, digest) of a well-formed plan identifier, else None."""
    if not isinstance(plan, str) or not plan.startswith("plan:"):
        return None
    try:
        _p, enc, digest, nonce = plan.split(":", 3)
        if len(digest) != 32 or any(c not in "0123456789abcdef" for c in digest + nonce) or len(nonce) != 16:
            return None
        return base64.b64decode(enc + "=" * (-len(enc) % 4), altchars=b"-_", validate=True).decode(), digest
    except (ValueError, UnicodeDecodeError):
        return None


def _unnamed_participant(acc: Account) -> str:
    """A participant named in no record (8.5.2(c)): an id that is not an Item of the
    examined records, so that no distribution or production names it."""
    pid = "~participant-named-nowhere"
    while pid in acc.items:
        pid += "~"
    return pid


def _cutoffs(acc: Account) -> list:
    """Every instant at which a derived result can change, and the whole history."""
    insts = {}
    for r in acc.records.values():
        for i in (acc.occurrence(r), acc.effective(r) if r.is_act else None):
            if i is not None:
                insts[i.text] = i
    return sorted(insts.values(), key=lambda i: i.key) + [None]


def _standing_sig(s: dict) -> tuple:
    return tuple((k, repr(s.get(k))) for k in ("standing", "timeliness", "fulfilled_by", "qualifying_moment",
                                                 "withdrawn_by", "overdue", "late_by", "candidates"))


def _story_sig(r: dict) -> tuple:
    return (repr(r.get("interval")), repr(r.get("ending")), repr(r.get("standing")))
