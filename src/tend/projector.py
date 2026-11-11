"""Projection of the ledger into an Attedra store (SPEC §5, §8.2).

Every record goes through attedra_ref.api.Session. Appending a message writes into the live
projection schema; a rebuild replays the whole ledger into a fresh schema, checks it with the
transition check (9.5.8), and swaps it in (deviations D1 to D3 live here, at the boundary)."""
from __future__ import annotations

import json
from pathlib import Path

import attedra_ref.api
from attedra_ref.api import Session
from attedra_ref.errors import WriteError

from . import ids, instants
from .config import Config
from .ledger import Claim, Ledger

SCHEMA_SQL = Path(attedra_ref.api.__file__).resolve().parents[1] / "schema.sql"


def R(id: str) -> dict:
    return {"@ref": "item", "id": id}


def aref(item: str, context: str, source: str, prop: str | None = None) -> dict:
    r = {"@ref": "assertion", "item": item, "context": context, "source": source}
    if prop:
        r["property"] = prop
    return r


class RebuildFailed(Exception):
    def __init__(self, message: str, culprit: str | None = None) -> None:
        super().__init__(message)
        self.culprit = culprit       # the ledger message or owner act being replayed, if any


MAX_QUARANTINE = 5     # records one rebuild may set aside before it gives up


class Projector:
    def __init__(self, conn, ledger: Ledger, config: Config) -> None:
        self.conn = conn
        self.ledger = ledger
        self.config = config
        self.session = Session(conn)
        self._current: str | None = None
        schema = ledger.meta("projection_schema")
        if schema:
            self._use(schema)

    # -- schema management -------------------------------------------------------------------
    def _use(self, schema: str) -> None:
        with self.conn.cursor() as c:
            c.execute(f'SET search_path TO "{schema}"')
        self.schema = schema

    def _create(self, schema: str) -> None:
        with self.conn.transaction(), self.conn.cursor() as c:
            c.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            c.execute(f'CREATE SCHEMA "{schema}"')
            c.execute(f'SET search_path TO "{schema}"')
            c.execute(SCHEMA_SQL.read_text())
        self.schema = schema
        self._fixed()

    def initialise(self) -> None:
        """Create the first projection if none exists."""
        if self.ledger.meta("projection_schema"):
            return
        self._create("proj_1")
        self.ledger.set_meta("projection_schema", "proj_1")

    # -- primitives ------------------------------------------------------------------------------
    def item(self, id: str, kind: str, label: str | None = None, definition: dict | None = None) -> None:
        self.session.create_item(id, kind, label, definition)

    def event(self, id: str, at: str) -> None:
        self.item(id, "event", None, {"@context": {"role": "event", "at": at}})

    def write(self, item: str, context: str, source: str, values: dict, by: str = "tend") -> dict:
        return self.session.assert_(item, context, source, json.dumps(values, sort_keys=True), recorded_by=by)

    def _fixed(self) -> None:
        self.event(ids.SETUP_CONTEXT, self.config.setup_at)
        self.event(ids.ELIGIBILITY_CONTEXT, ids.EPOCH)
        self.item(ids.CONFIG_SOURCE, "config")
        self.item(ids.OWNER_REVIEW, "review_log")
        self.item(ids.SCOPE, "scope")
        self.item(self.config.owner_id, "person")

    def _subject(self, subject_id: str) -> str:
        root = self.ledger.root(subject_id)
        it = self.ledger.item(root)
        self.item(root, it["kind"] if it else "thing", it["label"] if it else None)
        return root

    def _person(self, pid: str) -> str:
        pid = self.config.owner_for(pid)
        self.item(pid, "person")
        return pid

    def _elig(self, person: str) -> str:
        e = ids.elig(person)
        self.item(e, "eligibility", None, {"@eligibility": True})
        self.write(e, ids.ELIGIBILITY_CONTEXT, ids.CONFIG_SOURCE, {"@eligible": {"party": R(person)}})
        return e

    # -- one message (SPEC §5.2 to §5.5) ---------------------------------------------------------
    def project_message(self, message_id: str) -> None:
        m = self.ledger.message(message_id)
        E = ids.event(m["provider"], m["provider_id"])
        S = m["stream_id"]
        producer = self._person(m["producer_id"])
        recipients = [self._person(r) for r in m["recipients"]]
        self.event(E, m["sent_at"])
        self.item(S, "event_log" if S.startswith("ghlog:") else "correspondence")
        self.write(S, E, S, {"@producer": R(producer), "@distribution": [R(r) for r in recipients],
                             "message_id": m["provider_id"], "provider": m["provider"],
                             "artifact": m["artifact"]})
        thread = m["thread_id"]
        if thread:
            self.item(thread, "thread")
        claims = self.ledger.claims_of(message_id)
        statements: dict[str, dict] = {}
        for c in claims:
            subject = self._subject(c.subject_id)
            if thread:
                self.session.connect(thread, subject, m["sent_at"])
            self.session.connect(ids.SCOPE, subject, m["sent_at"])
            if c.kind == "statement":
                vals = statements.setdefault(subject, {})
                if c.property in vals:
                    self.ledger.drop_claim(c.id, "projector", "duplicate property in one message")
                    continue
                vals[c.property] = c.value
        for subject, vals in statements.items():
            self.write(subject, E, S, vals)
        for c in claims:
            if c.kind == "commitment":
                self._commitment(c, m, E, S)
            elif c.kind == "withdrawal":
                self._withdrawal(c, m, E, S)

    def expectation_ref(self, c: Claim) -> dict:
        return aref(self.ledger.root(c.subject_id), ids.expctx(c.id), ids.elig(self.config.owner_for(c.obligated_id)))

    def _commitment(self, c: Claim, m: dict, E: str, S: str) -> None:
        obligated = self._person(c.obligated_id)
        party = self._person(c.party_id or c.obligated_id)
        elig = self._elig(obligated)
        timing = {"type": "by", "instant": c.deadline} if c.deadline else {"type": "any"}
        ctx = ids.expctx(c.id)
        self.item(ctx, "expectation_context", None, {"@context": {"role": "expectation", "timing": timing,
                                                                   "fresh": True}})
        subject = self.ledger.root(c.subject_id)
        value = {"@ask": True} if c.form == "ask" else c.value
        self.write(subject, ctx, elig, {c.property: value})
        self.item(ids.act(c.id), "commitment")
        self.write(ids.act(c.id), E, S, {
            "@action": "establish", "@targets": [aref(subject, ctx, elig)], "@party": R(party),
            "@issuance": R(E), "@basis": [m["artifact"]]})

    def _withdrawal(self, c: Claim, m: dict, E: str, S: str) -> None:
        target = self.ledger.successor(c.value["claim"])
        tc = self.ledger.claim(target) if target else None
        if tc is None or tc.kind != "commitment":
            self.ledger.log("projector", "withdrawal_skipped", "target commitment not active", claim=c.id)
            return
        self.item(ids.act(c.id), "withdrawal")
        self.write(ids.act(c.id), E, S, {
            "@action": "withdraw", "@targets": [self.expectation_ref(tc)],
            "@party": R(self._person(c.party_id)), "@issuance": R(E), "@basis": [m["artifact"]]})

    # -- owner acts (SPEC §8.3, deviation D3) ---------------------------------------------------
    def project_owner_act(self, a: dict) -> bool:
        target = self.ledger.successor(a["target"].get("claim", ""))
        tc = self.ledger.claim(target) if target else None
        if tc is None or tc.kind != "commitment":
            self.ledger.log("projector", "owner_act_dropped", "target no longer exists", act=a["id"])
            return False
        item, ctx = ids.owner_act(a["id"])
        self.event(ctx, a["at"])
        self.item(item, "owner_act")
        values: dict = {"@targets": [self.expectation_ref(tc)], "@party": R(self.config.owner_id)}
        if a["kind"] == "snooze":
            values["@action"] = "ignore"
            if a["until"]:
                values["@until"] = a["until"]
        elif a["kind"] == "withdraw":
            values["@action"] = "withdraw"
        else:
            raise ValueError(a["kind"])
        if a.get("note"):
            values["note"] = a["note"]
        self.write(item, ctx, ids.OWNER_REVIEW, values, by="owner")
        return True

    # -- appending one message (SPEC §8.2, last paragraph) ---------------------------------------
    def append(self, message_id: str) -> None:
        """Project one newly committed message into the live store (SPEC §8.2, last paragraph).

        Reads at "now" are correct after an append in every case. Two cases leave historical reads
        differing from a rebuild, and mark the store stale so that the next batch `rebuild()` repairs
        them: a message older than one already projected (Connections keep their first-seen
        instant), and a failed append, which re-raises after marking; the ledger keeps the message,
        so nothing is lost and a replay of the same input is a no-op."""
        m = self.ledger.message(message_id)
        latest = self.ledger.meta("latest_sent_at")
        try:
            self.project_message(message_id)
        except Exception:
            self.ledger.mark_stale(f"append of {message_id} failed")
            raise
        if latest and instants.sort_key(m["sent_at"]) < instants.sort_key(latest):
            self.ledger.mark_stale(f"message {message_id} arrived out of order")
        else:
            self.ledger.set_meta("latest_sent_at", m["sent_at"])

    def refresh(self, agent: str = "tend") -> str | None:
        """Rebuild if the ledger has changes the store does not show yet."""
        if self.ledger.meta("stale") == "1":
            return self.rebuild(agent, self.ledger.meta("stale_reason") or "stale")
        return None

    # -- quarantine (SPEC §8.2) ----------------------------------------------------------------
    def quarantined(self) -> dict[str, str]:
        """Ledger records a rebuild set aside because they could not be projected, with why."""
        return json.loads(self.ledger.meta("quarantine") or "{}")

    def quarantine(self, record_id: str, why: str, agent: str = "tend") -> None:
        q = self.quarantined()
        q[record_id] = why[:500]
        self.ledger.set_meta("quarantine", json.dumps(q, sort_keys=True))
        self.ledger.log(agent, "quarantined", why[:2000], record=record_id)

    def release_quarantine(self, agent: str = "owner") -> list[str]:
        """Try the set-aside records again at the next rebuild (after a fix)."""
        q = list(self.quarantined())
        if q:
            self.ledger.set_meta("quarantine", "{}")
            self.ledger.mark_stale("quarantine released")
            self.ledger.log(agent, "quarantine_released", None, records=q)
        return q

    # -- rebuild (SPEC §8.2) -------------------------------------------------------------------
    def rebuild(self, agent: str = "tend", reason: str = "") -> str:
        """Invariant: one record that cannot be projected costs that record, never the list. A
        replay that fails on a message or owner act sets it aside (quarantine, shown on the list)
        and tries again; any other failure keeps the previous projection in use."""
        for attempt in range(MAX_QUARANTINE + 1):
            try:
                return self._rebuild_once(agent, reason)
            except RebuildFailed as e:
                if e.culprit is None or attempt == MAX_QUARANTINE:
                    raise
                self.quarantine(e.culprit, str(e), agent)
        raise AssertionError("unreachable")

    # -- what a rewrite changed (SPEC §8.2, the visibility invariant) -----------------------
    def open_now(self) -> dict[str, str]:
        """Open and upcoming expectations at "now": claim id to subject."""
        r = self.session.read("what_remains", {"frame": {"scope": ids.SCOPE, "cutoff": "now"},
                                               "attention_filter": "ignore"})
        out = {}
        for e in r.get("open", []) + r.get("upcoming", []):
            if e.get("kind") != "expectation":
                continue
            subject, ctx, _ = e["unit"].rpartition("#")[0].split("|")
            out[ctx.removeprefix("expctx:")] = subject
        return out

    def _why(self, since: int) -> list[str]:
        """The rewrites recorded since revision `since`, in words."""
        out = []
        for r in self.ledger.revisions():
            if r["id"] <= since:
                continue
            d, a = r["detail"], r["action"]
            if a == "supersede_claim":
                c = self.ledger.claim(d.get("claim", ""))
                subj = (d.get("changes") or {}).get("subject_id")
                if c and subj:
                    it = self.ledger.item(subj) or {}
                    out.append(f'I re-read "{c.quote or c.property}" as about {it.get("label") or subj}')
                else:
                    out.append(r["reason"] or "I corrected a reading")
            elif a == "merge_items":
                lab = lambda i: (self.ledger.item(i) or {}).get("label") or i
                out.append(f"I merged {lab(d['absorbed'])} into {lab(d['survivor'])}")
            elif a == "unmerge_items":
                out.append(f"I separated {(self.ledger.item(d['item']) or {}).get('label') or d['item']} again")
            elif a == "drop_claim":
                out.append(f"I dropped a reading ({r['reason']})")
            elif a == "quarantined":
                out.append("a record could not be stored and was set aside")
            elif a == "rederived":
                out.append("a GitHub event arrived out of order and I re-read its pull request or issue")
        return list(dict.fromkeys(out))

    def _record_changes(self, before: dict[str, str], after: dict[str, str], since: int, agent: str) -> None:
        """Invariant: no automated rewrite ends or moves an open obligation without a visible
        entry. Every live append and owner act is already in the old projection, so what differs
        between the old and the new at "now" is exactly what the rewrites did. Each difference is
        logged `obligation_changed`, and the list shows it (§10)."""
        why = self._why(since) or ["a rebuild"]
        for cid, subject in before.items():
            now = self.ledger.successor(cid)
            if now in after:
                if self.ledger.root(after[now]) != self.ledger.root(subject):
                    self.ledger.log(agent, "obligation_changed", "; ".join(why), claim=cid, now_claim=now,
                                    change="moved", was_subject=subject, now_subject=after[now])
            else:
                self.ledger.log(agent, "obligation_changed", "; ".join(why), claim=cid, now_claim=now,
                                change="closed", was_subject=subject)

    def _rebuild_once(self, agent: str, reason: str) -> str:
        old = self.ledger.meta("projection_schema")
        try:
            before = self.open_now() if old else {}
        except Exception:
            before = {}
        since = max([r["id"] for r in self.ledger.revisions("rebuild")] or [0])
        n = int(old.split("_")[1]) + 1 if old else 1
        new = f"proj_{n}"
        self._current = None
        try:
            self._create(new)
            self._replay()
            check = self.session.read("transition_check", {"frame": {"scope": ids.SCOPE}})
            if check.get("differences"):
                raise RebuildFailed(json.dumps(check["differences"])[:2000])
        except Exception as e:          # any failure: the previous projection stays in use
            culprit = self._current
            with self.conn.cursor() as c:
                c.execute(f'DROP SCHEMA IF EXISTS "{new}" CASCADE')
            if old:
                self._use(old)
            self.ledger.log(agent, "rebuild_failed", f"{type(e).__name__}: {e}"[:2000], schema=new, record=culprit)
            raise RebuildFailed(str(e), culprit) from e
        after = self.open_now()
        self.ledger.set_meta("projection_schema", new)
        self.ledger.set_meta("stale", "0")
        self.ledger.set_meta("stale_reason", "")
        if old:
            with self.conn.cursor() as c:
                c.execute(f'DROP SCHEMA IF EXISTS "{old}" CASCADE')
        self._record_changes(before, after, since, agent)
        self.ledger.log(agent, "rebuild", reason or None, schema=new)
        return new

    def _replay(self) -> None:
        skip = self.quarantined()
        events: list[tuple] = []
        for m in self.ledger.messages():
            events.append((instants.sort_key(m["sent_at"]), 0, m["id"], m))
        for a in self.ledger.owner_acts():
            events.append((instants.sort_key(a["at"]), 1, a["id"], a))
        for _, kind, rid, x in sorted(events, key=lambda e: e[:3]):
            if rid in skip:
                continue
            self._current = rid
            if kind == 0:
                self.project_message(x["id"])
                self.ledger.set_meta("latest_sent_at", x["sent_at"])
            else:
                self.project_owner_act(x)
        self._current = None
