"""The ledger (SPEC §4): the application's mutable source of truth. The Attedra store is a
projection of it (projector.py). Every change that alters what the projection would contain is
logged in `revisions` in the same transaction (deviation D1)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from psycopg.types.json import Jsonb

DDL = """
CREATE SCHEMA IF NOT EXISTS ledger;
CREATE TABLE IF NOT EXISTS ledger.meta (key text PRIMARY KEY, value text NOT NULL);
CREATE TABLE IF NOT EXISTS ledger.items (
    id text PRIMARY KEY, kind text NOT NULL, label text, keys jsonb NOT NULL DEFAULT '[]',
    merged_into text, created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE IF NOT EXISTS ledger.names (
    item_id text NOT NULL, name_norm text NOT NULL, name text NOT NULL, message_id text NOT NULL,
    stream_id text, PRIMARY KEY (item_id, name_norm, message_id));
CREATE TABLE IF NOT EXISTS ledger.links (
    from_id text NOT NULL, to_id text NOT NULL, at text NOT NULL, PRIMARY KEY (from_id, to_id));
CREATE TABLE IF NOT EXISTS ledger.messages (
    id text PRIMARY KEY, provider text NOT NULL, provider_id text NOT NULL, thread_id text,
    stream_id text NOT NULL, producer_id text NOT NULL, recipients jsonb NOT NULL DEFAULT '[]',
    sent_at text NOT NULL, artifact jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS ledger.claims (
    id text PRIMARY KEY, message_id text NOT NULL REFERENCES ledger.messages(id), ordinal int NOT NULL,
    kind text NOT NULL, subject_id text NOT NULL, property text NOT NULL, value jsonb,
    form text NOT NULL DEFAULT 'value', obligated_id text, party_id text, deadline text,
    quote text, confidence real NOT NULL DEFAULT 1, flags jsonb NOT NULL DEFAULT '[]',
    status text NOT NULL, superseded_by text, extractor text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp());
CREATE TABLE IF NOT EXISTS ledger.holds (
    claim_id text PRIMARY KEY, mention jsonb NOT NULL, options jsonb NOT NULL, hold_until text NOT NULL);
CREATE TABLE IF NOT EXISTS ledger.owner_acts (
    id text PRIMARY KEY, kind text NOT NULL, target jsonb NOT NULL, at text NOT NULL,
    until text, note text);
CREATE TABLE IF NOT EXISTS ledger.revisions (
    id bigserial PRIMARY KEY, at timestamptz NOT NULL DEFAULT clock_timestamp(), agent text NOT NULL,
    action text NOT NULL, reason text, detail jsonb NOT NULL DEFAULT '{}');
"""

_ARTICLES = re.compile(r"^(the|a|an|our|my)\s+")


def normalise(name: str) -> str:
    """SPEC §7.5."""
    s = re.sub(r"[^\w\s]", " ", name.lower())
    s = re.sub(r"\s+", " ", s).strip()
    return _ARTICLES.sub("", s)


@dataclass
class Claim:
    id: str
    message_id: str
    ordinal: int
    kind: str                      # statement | commitment
    subject_id: str
    property: str
    value: Any
    form: str = "value"            # value | ask
    obligated_id: str | None = None
    party_id: str | None = None
    deadline: str | None = None
    quote: str | None = None
    confidence: float = 1.0
    flags: list[str] = field(default_factory=list)
    status: str = "active"
    extractor: str = "deterministic"


class Ledger:
    def __init__(self, conn) -> None:
        self.conn = conn

    def install(self) -> None:
        with self.conn.transaction(), self.conn.cursor() as c:
            c.execute(DDL)

    # -- low level ------------------------------------------------------------------------
    def _q(self, sql: str, args: tuple = ()) -> list[tuple]:
        with self.conn.cursor() as c:
            c.execute(sql, args)
            return c.fetchall() if c.description else []

    def log(self, agent: str, action: str, reason: str | None = None, **detail) -> None:
        self._q("INSERT INTO ledger.revisions (agent, action, reason, detail) VALUES (%s,%s,%s,%s)",
                (agent, action, reason, Jsonb(detail)))

    def meta(self, key: str) -> str | None:
        r = self._q("SELECT value FROM ledger.meta WHERE key=%s", (key,))
        return r[0][0] if r else None

    def mark_stale(self, reason: str) -> None:
        self.set_meta("stale", "1")
        self.set_meta("stale_reason", reason)

    def set_meta(self, key: str, value: str) -> None:
        self._q("INSERT INTO ledger.meta VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=excluded.value",
                (key, value))

    # -- items, names, links ----------------------------------------------------------------
    def ensure_item(self, id: str, kind: str, label: str | None = None, keys: list[str] | None = None) -> None:
        self._q("INSERT INTO ledger.items (id, kind, label, keys) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (id) DO NOTHING", (id, kind, label, Jsonb(keys or [])))

    def item(self, id: str) -> dict | None:
        r = self._q("SELECT id, kind, label, keys, merged_into FROM ledger.items WHERE id=%s", (id,))
        return dict(zip(("id", "kind", "label", "keys", "merged_into"), r[0])) if r else None

    def root(self, id: str) -> str:
        """Follow the identity map (deviation D2)."""
        seen = set()
        while True:
            r = self._q("SELECT merged_into FROM ledger.items WHERE id=%s", (id,))
            if not r or r[0][0] is None or id in seen:
                return id
            seen.add(id)
            id = r[0][0]

    def active_items(self, kind: str | None = None) -> list[dict]:
        sql = "SELECT id, kind, label, keys, created_at FROM ledger.items WHERE merged_into IS NULL"
        args: tuple = ()
        if kind:
            sql += " AND kind=%s"
            args = (kind,)
        return [dict(zip(("id", "kind", "label", "keys", "created_at"), r)) for r in self._q(sql + " ORDER BY id", args)]

    def items_by_key(self, key: str) -> list[str]:
        return [r[0] for r in self._q(
            "SELECT id FROM ledger.items WHERE merged_into IS NULL AND keys ? %s ORDER BY id", (key.lower(),))]

    def add_name(self, item_id: str, name: str, message_id: str, stream_id: str | None) -> None:
        n = normalise(name)
        if n:
            self._q("INSERT INTO ledger.names VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (item_id, n, name, message_id, stream_id))

    def names_of(self, item_id: str) -> list[str]:
        return [r[0] for r in self._q(
            "SELECT DISTINCT name_norm FROM ledger.names WHERE item_id=%s ORDER BY name_norm", (item_id,))]

    def items_named(self, name_norm: str, kind: str | None = None) -> list[str]:
        sql = ("SELECT DISTINCT n.item_id FROM ledger.names n JOIN ledger.items i ON i.id=n.item_id "
               "WHERE n.name_norm=%s AND i.merged_into IS NULL")
        args: tuple = (name_norm,)
        if kind:
            sql += " AND i.kind=%s"
            args += (kind,)
        return [r[0] for r in self._q(sql + " ORDER BY 1", args)]

    def all_names(self) -> list[tuple[str, str]]:
        return self._q("SELECT DISTINCT n.item_id, n.name_norm FROM ledger.names n JOIN ledger.items i "
                       "ON i.id=n.item_id WHERE i.merged_into IS NULL")

    def link(self, from_id: str, to_id: str, at: str) -> None:
        self._q("INSERT INTO ledger.links VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (from_id, to_id, at))

    def links_from(self, from_id: str) -> list[str]:
        return [r[0] for r in self._q("SELECT to_id FROM ledger.links WHERE from_id=%s ORDER BY 1", (from_id,))]

    def all_links(self) -> list[tuple[str, str, str]]:
        return self._q("SELECT from_id, to_id, at FROM ledger.links ORDER BY from_id, to_id")

    # -- messages and claims ---------------------------------------------------------------
    def add_message(self, m: dict) -> bool:
        r = self._q("INSERT INTO ledger.messages VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING "
                    "RETURNING id", (m["id"], m["provider"], m["provider_id"], m.get("thread_id"),
                                     m["stream_id"], m["producer_id"], Jsonb(m.get("recipients", [])),
                                     m["sent_at"], Jsonb(m["artifact"])))
        return bool(r)

    def message(self, id: str) -> dict | None:
        r = self._q("SELECT id, provider, provider_id, thread_id, stream_id, producer_id, recipients, sent_at, "
                    "artifact FROM ledger.messages WHERE id=%s", (id,))
        keys = ("id", "provider", "provider_id", "thread_id", "stream_id", "producer_id", "recipients",
                "sent_at", "artifact")
        return dict(zip(keys, r[0])) if r else None

    def messages(self) -> list[dict]:
        return [self.message(r[0]) for r in self._q("SELECT id FROM ledger.messages ORDER BY id")]

    def add_claim(self, c: Claim) -> None:
        self._q("INSERT INTO ledger.claims (id, message_id, ordinal, kind, subject_id, property, value, form, "
                "obligated_id, party_id, deadline, quote, confidence, flags, status, extractor) VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                (c.id, c.message_id, c.ordinal, c.kind, c.subject_id, c.property, Jsonb(c.value), c.form,
                 c.obligated_id, c.party_id, c.deadline, c.quote, c.confidence, Jsonb(c.flags), c.status,
                 c.extractor))

    _CLAIM_COLS = ("id", "message_id", "ordinal", "kind", "subject_id", "property", "value", "form",
                   "obligated_id", "party_id", "deadline", "quote", "confidence", "flags", "status", "extractor")

    def _claims(self, where: str, args: tuple) -> list[Claim]:
        rows = self._q(f"SELECT {', '.join(self._CLAIM_COLS)} FROM ledger.claims WHERE {where} "
                       "ORDER BY message_id, ordinal, id", args)
        return [Claim(**dict(zip(self._CLAIM_COLS, r))) for r in rows]

    def claim(self, id: str) -> Claim | None:
        r = self._claims("id=%s", (id,))
        return r[0] if r else None

    def claims_of(self, message_id: str, status: str = "active") -> list[Claim]:
        return self._claims("message_id=%s AND status=%s", (message_id, status))

    def active_claims(self) -> list[Claim]:
        return self._claims("status='active'", ())

    def successor(self, claim_id: str) -> str | None:
        """The current active successor of a claim, following supersession (SPEC §8.3)."""
        seen = set()
        while claim_id and claim_id not in seen:
            seen.add(claim_id)
            r = self._q("SELECT status, superseded_by FROM ledger.claims WHERE id=%s", (claim_id,))
            if not r:
                return None
            status, nxt = r[0]
            if status == "active":
                return claim_id
            if status != "superseded":
                return None
            claim_id = nxt
        return None

    def set_status(self, claim_id: str, status: str, flags: list[str] | None = None) -> None:
        if flags is None:
            self._q("UPDATE ledger.claims SET status=%s WHERE id=%s", (status, claim_id))
        else:
            self._q("UPDATE ledger.claims SET status=%s, flags=%s WHERE id=%s", (status, Jsonb(flags), claim_id))

    def update_claim(self, claim_id: str, **fields) -> None:
        for k, v in fields.items():
            if k not in self._CLAIM_COLS or k == "id":
                raise ValueError(k)
            self._q(f"UPDATE ledger.claims SET {k}=%s WHERE id=%s",
                    (Jsonb(v) if k in ("value", "flags") else v, claim_id))

    # -- holds -------------------------------------------------------------------------------
    def add_hold(self, claim_id: str, mention: dict, options: dict, hold_until: str) -> None:
        self._q("INSERT INTO ledger.holds VALUES (%s,%s,%s,%s) ON CONFLICT (claim_id) DO UPDATE SET "
                "options=excluded.options", (claim_id, Jsonb(mention), Jsonb(options), hold_until))

    def holds(self) -> list[dict]:
        return [dict(zip(("claim_id", "mention", "options", "hold_until"), r))
                for r in self._q("SELECT claim_id, mention, options, hold_until FROM ledger.holds ORDER BY 1")]

    def drop_hold(self, claim_id: str) -> None:
        self._q("DELETE FROM ledger.holds WHERE claim_id=%s", (claim_id,))

    # -- owner acts --------------------------------------------------------------------------
    def add_owner_act(self, id: str, kind: str, target: dict, at: str, until: str | None = None,
                      note: str | None = None) -> None:
        self._q("INSERT INTO ledger.owner_acts VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (id, kind, Jsonb(target), at, until, note))

    def owner_acts(self) -> list[dict]:
        return [dict(zip(("id", "kind", "target", "at", "until", "note"), r))
                for r in self._q("SELECT id, kind, target, at, until, note FROM ledger.owner_acts ORDER BY id")]

    def owner_acts_by_id(self, id: str) -> dict:
        return next(a for a in self.owner_acts() if a["id"] == id)

    # -- self-correction (SPEC §8.1, deviations D1, D2) --------------------------------------
    def supersede_claim(self, claim_id: str, agent: str, reason: str, **changes) -> str:
        old = self.claim(claim_id)
        if old is None or old.status != "active":
            raise ValueError(f"claim {claim_id} is not active")
        new_id = claim_id + "-r" + str(len(self._q("SELECT 1 FROM ledger.claims WHERE id LIKE %s",
                                                    (claim_id + "-r%",))) + 1)
        data = {k: getattr(old, k) for k in self._CLAIM_COLS}
        data.update(changes, id=new_id, status="active")
        self.add_claim(Claim(**data))
        self._q("UPDATE ledger.claims SET status='superseded', superseded_by=%s WHERE id=%s", (new_id, claim_id))
        self.log(agent, "supersede_claim", reason, claim=claim_id, successor=new_id,
                 changes=json.loads(json.dumps(changes, default=str)))
        self.mark_stale(f"claim {claim_id} superseded")
        return new_id

    def drop_claim(self, claim_id: str, agent: str, reason: str) -> None:
        self.set_status(claim_id, "dropped")
        self.drop_hold(claim_id)
        self.log(agent, "drop_claim", reason, claim=claim_id)
        self.mark_stale(f"claim {claim_id} dropped")

    def merge_items(self, survivor: str, absorbed: str, agent: str, reason: str) -> None:
        survivor, absorbed = self.root(survivor), self.root(absorbed)
        if survivor == absorbed:
            return
        self._q("UPDATE ledger.items SET merged_into=%s WHERE id=%s", (survivor, absorbed))
        a, s = self.item(absorbed), self.item(survivor)
        keys = sorted(set(s["keys"]) | set(a["keys"]))
        self._q("UPDATE ledger.items SET keys=%s WHERE id=%s", (Jsonb(keys), survivor))
        self._q("INSERT INTO ledger.names SELECT %s, name_norm, name, message_id, stream_id FROM ledger.names "
                "WHERE item_id=%s ON CONFLICT DO NOTHING", (survivor, absorbed))
        for f, t, at in self._q("SELECT from_id, to_id, at FROM ledger.links WHERE from_id=%s OR to_id=%s",
                                (absorbed, absorbed)):
            self.link(survivor if f == absorbed else f, survivor if t == absorbed else t, at)
        self.log(agent, "merge_items", reason, survivor=survivor, absorbed=absorbed)
        self.mark_stale(f"{absorbed} merged into {survivor}")

    # -- the graph used for structural support and the gardener (SPEC §7.2, §9) ----------------
    def message_claims(self) -> list[tuple[Claim, dict]]:
        msgs = {m["id"]: m for m in self.messages()}
        return [(c, msgs[c.message_id]) for c in self.active_claims()]

    def graph(self, exclude: set[str] = frozenset()) -> dict[str, set[str]]:
        """Undirected adjacency over Item roots: `links`, plus subject–producer and subject–thread
        pairs from active claims. Nodes in `exclude` (the owner, a hub adjacent to everything) are
        left out so that they do not make every Item a two-hop neighbour of every other."""
        edges: dict[str, set[str]] = {}

        def add(a: str | None, b: str | None) -> None:
            if not a or not b:
                return
            a, b = self.root(a), self.root(b)
            if a == b or a in exclude or b in exclude:
                return
            edges.setdefault(a, set()).add(b)
            edges.setdefault(b, set()).add(a)

        for f, t, _ in self.all_links():
            add(f, t)
        for c, m in self.message_claims():
            add(c.subject_id, m["producer_id"])
            add(c.subject_id, m["thread_id"])
        return edges

    def revisions(self, action: str | None = None) -> list[dict]:
        sql = "SELECT id, agent, action, reason, detail FROM ledger.revisions"
        args: tuple = ()
        if action:
            sql += " WHERE action=%s"
            args = (action,)
        return [dict(zip(("id", "agent", "action", "reason", "detail"), r)) for r in self._q(sql + " ORDER BY id", args)]
