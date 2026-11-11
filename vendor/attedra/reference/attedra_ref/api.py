"""Public interface of the Attedra 0.1.0 reference library.

The conformance runner (conformance/run.py) uses only this module and errors.WriteError.
Semantics: Attedra_Specification.md (0.1.0, preliminary). Result shapes, references and
error codes: conformance/README.md.

Every write is one transaction on the given psycopg connection; a failed write raises
WriteError and leaves the store unchanged.

Module map:

* ``values``, ``instants``: the value space (5.1, 5.3, 5.5.1) and instants (4.2).
* ``model``: the three primitives and the reserved vocabulary (§2).
* ``validate``: validation on write (10.2).
* ``store``: the three tables and scoped loading (9.10.1).
* ``account``: the corrected account and chronology (8.3, 4.2.4, 4.3, 4.5).
* ``view``: frames, perspective, distribution, scope and Connection state (4.6, 4.4, 2.1.5, 8.6).
* ``positions``: carry-forward and source positions (5.2, 5.6, 9.2).
* ``interpretations``: the fixture interpretations, and those a session has retired
  (conformance README §2, ``retire_interpretation``).
* ``normalization``: normalizations and the interpretation in force for an Item over event
  time (7.3.8, 4.6.1), and the comparison of two expectations under their own (7.2.4).
* ``expectations``: support, fulfillment and standing (§6, 9.3).
* ``stories``: stories, their standing and maintenance (§7, 9.5).
* ``transitions``: recorded beginnings and endings, ending policies, the transition check
  and the record-perspective reading of open standing (7.6, 7.7, 9.5.7, 9.5.8).
* ``reads``, ``writes``: the operations of 10.5.2.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from . import interpretations
from .reads import Reader
from .store import Store
from .writes import Writer


class Session:
    """A connection to one Attedra store (the three tables of reference/schema.sql)."""

    def __init__(self, conn, derive_listing: bool = False) -> None:
        """``derive_listing`` is the reference's internal switch (not part of the model): the
        listing reads of the record perspective (open_work, open_stories, pending_review,
        what_remains) then answer by deriving every unit's transitions instead of reading the
        recorded ones (7.6.14). The scale benchmark and the audit use it for comparison."""
        self.conn = conn
        self.store = Store(conn)
        self._writer = Writer(self.store)
        self._reader = Reader(self.store, derive=derive_listing)
        # conformance README §2 `retire_interpretation`: the fixture interpretations this
        # session no longer has (interpretations.retired)
        self.retired: set[str] = set()

    @contextmanager
    def _scope(self):
        token = interpretations.retired.set(frozenset(self.retired))
        try:
            yield
        finally:
            interpretations.retired.reset(token)

    def retire_interpretation(self, name: str) -> dict:
        """From now on in this session the reference does not have the named interpretation
        (conformance README §2): records written before stay as written, and are read as
        recorded (7.3.8, 7.6.14); a normalization naming it is rejected (10.2.9).
        Returns {'status': 'retired'}."""
        self.retired.add(name)
        return {"status": "retired"}

    # -- writes -------------------------------------------------------------------------

    def create_item(self, id: str, kind: str, label: str | None = None,
                    definition: dict | None = None, definition_json: str | None = None) -> dict:
        """Create an Item (spec 8.1.5), validating context definitions (10.2.3). The definition
        may be given as raw JSON text in ``definition_json``, parsed like ``values_json`` with
        duplicate-key detection (5.1.1). Returns {'status': 'created' | 'exists', 'id'};
        ``exists`` is an identical re-creation, and different content fails ``occupied``."""
        with self._scope():
            return self._writer.create_item(id, kind, label, definition, definition_json)

    def assert_(self, item: str, context: str, source: str, values_json: str,
                recorded_at: str | None = None, recorded_by: str | None = None) -> dict:
        """Insert an Assertion, or replay an identical one (8.1). `values_json` is raw JSON text,
        parsed with duplicate-key detection (5.1.1) and normalized (5.3.2). Acts are dispatched
        on values['@action'] and validated (10.2); disconnect/reconnect also update the
        Connection (8.6); story maintenance (7.2.8) and the recording of begin and end acts
        (7.6.9) run in the same transaction.
        Returns {'status': 'inserted' | 'replayed', 'ref': 'item|context|source', 'generated': [refs],
        'transition_acts': [refs]}: the story records maintenance generated, and the begin acts,
        end acts and revisions it recorded (README §2, §7)."""
        with self._scope():
            return self._writer.assert_(item, context, source, values_json, recorded_at, recorded_by)

    def connect(self, from_id: str, to_id: str, at: str) -> dict:
        """Create a Connection (8.6.1); a no-op if the pair already has one (2.2.1).
        Returns {'status': 'created' | 'exists'}."""
        with self._scope():
            return self._writer.connect(from_id, to_id, at)

    def plan_removal(self, target: str) -> dict:
        """Plan permanent removal of an Assertion ('item|context|source') or an Item (id) (8.5.3).
        Returns {'status': 'planned', 'plan': id} or {'status': 'refused', 'dependents': [refs]},
        with 'reason': 'not_found' for a target that is not recorded and 'extension' for a
        record carrying the declared extension (8.5.2(e)), or for an Item while any record in
        the store carries it (10.4.4). The plan is valid only in this Session (8.5.4)."""
        with self._scope():
            return self._writer.plan_removal(target)

    def confirm_removal(self, plan: str) -> dict:
        """Confirm a plan (8.5.4): revalidate the target and every record the impact test
        examined, then remove atomically; confirming ends the plan. Raises WriteError
        ('plan_stale' | 'plan_unknown'). Returns {'status': 'removed'}."""
        with self._scope():
            return self._writer.confirm_removal(plan)

    def cancel_removal(self, plan: str) -> dict:
        """Cancel a plan; the record is untouched and the plan ends (8.5.4). Raises
        WriteError('plan_unknown') for a plan this Session did not issue or has already
        confirmed or cancelled. Returns {'status': 'cancelled'}."""
        with self._scope():
            return self._writer.cancel_removal(plan)

    # -- reads --------------------------------------------------------------------------

    def read(self, name: str, args: dict[str, Any]) -> dict:
        """Run a §9 read by its conformance name (README §5) and return its result shape."""
        conn = self.conn
        if conn.info.transaction_status != 0:
            conn.rollback()
        with conn.transaction(force_rollback=True), self._scope():
            self.store.no_jit()
            return self._reader.read(name, args)
