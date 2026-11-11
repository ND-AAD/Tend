"""Mail ingestion (SPEC §6, §7): frontier-model extraction, deterministic audit, entropy-based
resolution confidence, holds. No decision model sits between the extractor and the store; the
audit and the confidence rule are code."""
from __future__ import annotations

import json
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

import psycopg

from . import confidence, deadlines, gardener, ids, instants, pack, schema
from .config import Config
from .ledger import Claim, Ledger, normalise
from .llm import Extractor, Resolver

EXTRACTOR = "mail-v1"
HOLD_HOURS = 72
EVIDENCE = {"displaced", "conflict", "merged"}     # reasons that may overturn a confident reading
SAMPLE = 2          # confident claims re-checked at random each night, never-checked first
_WROTE = re.compile(r"^\s*On .+wrote:\s*$")
_STOP = {"the", "a", "an", "of", "for", "and", "to", "my", "our", "this", "that", "new", "revised", "final", "draft"}


class Refused(Exception):
    def __init__(self, code: str, **detail) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass
class Resolution:
    write: bool
    winner: str                    # an Item id, or the id a new Item would get
    q: dict[str, float]
    entropy: float
    new: dict | None = None        # {"kind", "label"} when the winner is a new Item
    settled_by_code: bool = False
    notes: list[tuple[str, dict]] = field(default_factory=list)    # audit log entries, written with the claim

    def kind(self, ledger: Ledger) -> str | None:
        if self.new and self.winner == self.new["id"]:
            return self.new["kind"]
        it = ledger.item(ledger.root(self.winner))
        return it["kind"] if it else None


@dataclass
class Outcome:
    message_id: str
    replay: bool = False
    written: list[str] = field(default_factory=list)
    held: list[str] = field(default_factory=list)
    refused: list[tuple[int, str]] = field(default_factory=list)
    released: list[str] = field(default_factory=list)


def new_text(body: str) -> str:
    """The body without quoted-reply lines: `>` lines, and everything from an `On … wrote:` line."""
    out = []
    for line in body.splitlines():
        if _WROTE.match(line):
            break
        if line.lstrip().startswith(">"):
            continue
        out.append(line)
    return "\n".join(out)


def _collapse(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def person(cfg: Config, raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip().lower()
    if not raw.startswith("person:"):
        raw = ids.person_email(raw) if "@" in raw else "person:" + raw
    return cfg.owner_for(raw)


class MailIngest:
    def __init__(self, cfg: Config, ledger: Ledger, projector, extractor: Extractor, resolver: Resolver) -> None:
        self.cfg, self.ledger, self.projector = cfg, ledger, projector
        self.extractor, self.resolver = extractor, resolver

    # -- the message record ---------------------------------------------------------------------
    def record(self, mail: dict) -> dict:
        producer = person(self.cfg, mail["from"])
        recipients = sorted({person(self.cfg, r) for r in mail.get("to", []) + mail.get("cc", [])} - {producer})
        sent = instants.from_datetime(datetime.fromisoformat(mail["sent_at"].replace("Z", "+00:00")))
        mid = ids.event("gmail", mail["id"])
        return {"id": mid, "provider": "gmail", "provider_id": mail["id"],
                "thread_id": ids.thread("gmail", mail["thread_id"]), "stream_id": ids.stream(producer),
                "producer_id": producer, "recipients": recipients, "sent_at": sent,
                "artifact": {"@ref": "artifact", "id": mail.get("url") or f"gmail:{mail['id']}", "edition": sent}}

    # -- ingest -------------------------------------------------------------------------------------
    def ingest(self, mail: dict) -> Outcome:
        """Model work first, then one transaction of writes. A model failure (refusal, outage)
        raises before anything is stored, so the same message can simply be ingested again.
        Every proposal ends written or refused, and every refusal is logged with its quote in the
        same transaction as the message, so the list can show what could not be placed (§10)."""
        msg = self.record(mail)
        out = Outcome(msg["id"])
        if self.ledger.message(msg["id"]):
            out.replay = True
            if msg["id"] in self.ledger.unprojected():
                self.projector.refresh("resolver")      # a retry completes the projection
            return out
        body = new_text(mail["body"])
        the_pack = pack.build(self.ledger, msg, body, self.cfg.owner_id)
        decided: list[tuple[Claim, dict, Resolution]] = []
        notes: list[tuple[str, dict]] = []
        for i, p in enumerate(self.extractor.extract(body, msg, the_pack)):
            try:
                claim, mention = self.audit(p, i, msg, body, the_pack, notes)
            except Refused as r:
                notes.append(self._refusal(msg, i, r.code, p, **r.detail))
                out.refused.append((i, r.code))
                continue
            decided.append((claim, mention, self.resolve(mention, claim.quote or "", msg, the_pack)))
        with self.ledger.conn.transaction():
            if not self.ledger.add_message(msg):
                out.replay = True
                return out
            for p in [msg["producer_id"], *msg["recipients"]]:
                self.ledger.link(msg["thread_id"], p, msg["sent_at"])
            for claim, mention, res in decided:
                notes += res.notes
                kind = res.kind(self.ledger)
                if not self.fits(claim, kind):
                    # the one place the vocabulary is enforced on the subject actually chosen
                    notes.append(self._refusal(msg, claim.ordinal, "property_outside_schema", claim.__dict__,
                                               kind=kind, property=claim.property))
                    out.refused.append((claim.ordinal, "property_outside_schema"))
                    continue
                self._write(claim, mention, msg, res)
                (out.written if res.write else out.held).append(claim.id)
            for action, detail in notes:
                self.ledger.log("audit", action, None, **detail)
        self.projector.append(msg["id"])
        out.released = self.rehold(msg)
        return out

    @staticmethod
    def _refusal(msg: dict, ordinal: int, code: str, p: dict, **detail) -> tuple[str, dict]:
        """An `audit_refused` entry carrying what the list needs to show it (SPEC §10)."""
        return "audit_refused", {"message": msg["id"], "ordinal": ordinal, "code": code, "sent_at": msg["sent_at"],
                                 "stream": msg["stream_id"], "claim_kind": p.get("kind"), "quote": p.get("quote"),
                                 "party": p.get("party") or p.get("party_id"), **detail}

    @staticmethod
    def fits(claim: Claim, kind: str | None) -> bool:
        """The vocabulary invariant (SPEC §6.3): a claim's property belongs to the kind of the Item
        it is written on. Checked against the subject resolution chose, on every path."""
        if claim.kind not in ("statement", "commitment"):
            return True
        if claim.form == "ask":
            return claim.property in schema.PROPERTIES.get(kind or "", {})
        return schema.check_value(kind or "", claim.property, claim.value)

    # -- audit (SPEC §6.3) ---------------------------------------------------------------------------
    def audit(self, p: dict, ordinal: int, msg: dict, body: str, the_pack: dict,
              notes: list | None = None) -> tuple[Claim, dict]:
        notes = [] if notes is None else notes
        quote = p.get("quote") or ""
        if not quote or _collapse(quote) not in _collapse(body):
            raise Refused("quote_not_in_body")
        kind, form = p.get("kind"), p.get("form", "value")
        if kind not in ("statement", "commitment") or form not in ("value", "ask") \
                or (form == "ask" and kind != "commitment"):
            raise Refused("bad_kind")
        mentions = p.get("mentions") or []
        si = p.get("subject")
        if not isinstance(si, int) or not 0 <= si < len(mentions):
            raise Refused("bad_subject")
        mention = dict(mentions[si])
        known = {e["id"]: e for e in the_pack["items"]}
        if mention.get("resolution") == "existing" and mention.get("item_id") not in known:
            mention["resolution"] = "unsure"
        subject_kind = known[mention["item_id"]]["kind"] if mention.get("resolution") == "existing" \
            else mention.get("kind")
        prop, value = p.get("property"), p.get("value")
        ok = prop in schema.PROPERTIES.get(subject_kind, {}) if form == "ask" \
            else schema.check_value(subject_kind, prop, value)
        if not ok:
            notes.append(("vocabulary_gap", {"kind": subject_kind, "property": prop, "value": value}))
            raise Refused("property_outside_schema", kind=subject_kind, property=prop)
        allowed = {msg["producer_id"], *msg["recipients"], self.cfg.owner_id}
        obligated, party = person(self.cfg, p.get("obligated")), person(self.cfg, p.get("party"))
        if kind == "commitment":
            if obligated not in allowed or (party or obligated) not in allowed:
                raise Refused("person_not_in_message", obligated=obligated, party=party)
        else:
            obligated = party = None
        flags: list[str] = []
        deadline = None
        dl = p.get("deadline")
        if dl and kind == "commitment":
            try:
                if _collapse(dl.get("text", "")).lower() not in _collapse(body).lower():
                    raise deadlines.DeadlineRefused("deadline words are not in the message")
                deadline = deadlines.resolve(dl["text"], dl["value"], msg["sent_at"])
            except deadlines.DeadlineRefused as e:
                flags.append("deadline_unchecked")
                notes.append(("deadline_refused", {"message": msg["id"], "ordinal": ordinal, "why": str(e),
                                                   "text": dl.get("text")}))
        mention["kind"] = subject_kind
        claim = Claim(id=ids.claim(msg["id"], ordinal, EXTRACTOR), message_id=msg["id"], ordinal=ordinal,
                      kind=kind, subject_id="", property=prop, value=None if form == "ask" else value,
                      form=form, obligated_id=obligated, party_id=party, deadline=deadline, quote=quote,
                      flags=flags, extractor=EXTRACTOR)
        return claim, mention

    # -- resolution (SPEC §7) ---------------------------------------------------------------------------
    def collisions(self, text: str, label: str, kind: str) -> set[str]:
        """Existing Items of `kind` a vote for a new Item would duplicate: same exact key or name."""
        out = set(pack.keyed_items(self.ledger, text))
        for n in {normalise(text), normalise(label or "")} - {""}:
            out |= set(self.ledger.items_named(n, kind))
        return {r for r in (self.ledger.root(i) for i in out) if (self.ledger.item(r) or {}).get("kind") == kind}

    def _name_ok(self, item_id: str, text: str, thread_id: str) -> bool:
        """The deterministic check of a pick of an existing Item against the nomenclature: the
        mention shares a word with one of the Item's recorded names or its label, or the Item is
        already linked from the message's thread (so a bare "it" or "the draft" can still refer)."""
        if item_id in {self.ledger.root(i) for i in self.ledger.links_from(thread_id)}:
            return True
        it = self.ledger.item(item_id) or {}
        words = set(normalise(text).split()) - _STOP
        names = self.ledger.names_of(item_id) + [normalise(it.get("label") or "")]
        return any(words & (set(n.split()) - _STOP) for n in names)

    def _overlap(self, item_id: str, text: str, except_message: str | None) -> int:
        it = self.ledger.item(item_id) or {}
        words = set(normalise(text).split()) - _STOP
        names = self.ledger.names_of(item_id, except_message) + [normalise(it.get("label") or "")]
        return len(words & {w for n in names for w in n.split()})

    def _fits_name_better(self, c: Claim, text: str, target: str) -> bool:
        """A move must not go against the nomenclature: refused when the mention shares more words
        with the current subject (its names from other messages, and its label) than with the
        target. "Acme deck v1" stays on v1 whatever the votes say."""
        current = self.ledger.root(c.subject_id)
        if self.ledger.root(target) == current or not self.ledger.item(self.ledger.root(target)):
            return False
        return self._overlap(current, text, c.message_id) > self._overlap(self.ledger.root(target), text, c.message_id)

    def resolve(self, mention: dict, excerpt: str, msg: dict, the_pack: dict,
                as_new: dict[str, str] | None = None) -> Resolution:
        """Always returns a resolution: a request is never dropped for lack of a subject. When
        the rule of §7.2 is not met the resolution is written as a best reading (`write` False).

        Invariants, each enforced here once:
        - an exact key identifies its Item whatever kind the extractor guessed (the vocabulary
          check in `fits` then refuses a property that Item cannot carry);
        - every valid vote counts. A vote for a new Item is set aside only when the resolver had
          not been shown the existing Item it would duplicate; that Item is then shown and all
          votes are taken again."""
        notes: list[tuple[str, dict]] = []
        keyed = {self.ledger.root(i) for i in pack.keyed_items(self.ledger, mention["text"])}
        if len(keyed) == 1:
            w = keyed.pop()
            return Resolution(True, w, {w: 1.0}, 0.0, settled_by_code=True)
        kind = mention.get("kind")
        candidates = [c for c in the_pack["items"] if c["kind"] == kind]
        votes: list[str] = []
        new_names: list[tuple[str, str]] = []
        for attempt in range(2):
            cand_ids = {c["id"] for c in candidates}
            votes, new_names, unseen = [], [], set()
            for seed in range(confidence.K):
                order = candidates[:]
                random.Random(seed).shuffle(order)
                v = self.resolver.resolve(mention, excerpt, order, seed)
                choice = v.get("choice")
                if as_new and choice in as_new:
                    choice, v = "new", {**v, "label": as_new[choice]}
                if choice == "new":
                    label = v.get("label") or mention.get("label") or mention["text"]
                    hit = self.collisions(mention["text"], label, kind) - cand_ids
                    if hit and attempt == 0:
                        unseen |= hit
                        continue
                    votes.append(confidence.NEW)
                    new_names.append((kind, label))
                elif choice in cand_ids:
                    votes.append(choice)
                else:
                    notes.append(("invented_id", {"message": msg["id"], "choice": choice}))
            if attempt == 0 and unseen:
                candidates += [pack.entry(self.ledger, i, self.cfg.owner_id) for i in sorted(unseen)]
                continue
            break
        if not votes:                     # every vote invalid: a new Item, as a best reading
            label = mention.get("label") or mention["text"]
            new = {"kind": kind, "label": label, "id": ids.resolved_item(kind, label, msg["id"])}
            return Resolution(False, new["id"], {new["id"]: 0.0}, 1.0, new, notes=notes)
        owner = self.cfg.owner_id
        anchors = {msg["thread_id"], msg["producer_id"], *msg["recipients"],
                   *(self.ledger.root(i) for i in self.ledger.links_from(msg["thread_id"]))} - {owner}
        edges = self.ledger.graph(exclude={owner})
        support = {o: confidence.support(edges, o, anchors) for o in set(votes)}
        d = confidence.decide(votes, support)
        new = None
        if confidence.NEW in d.q:
            nk, nl = Counter(new_names).most_common(1)[0][0]
            new = {"kind": nk, "label": nl, "id": ids.resolved_item(nk, nl, msg["id"])}
        write, chosen = d.write, d.winner
        if chosen != confidence.NEW and not self._name_ok(chosen, mention["text"], msg["thread_id"]):
            notes.append(("name_check_failed", {"message": msg["id"], "item": chosen, "text": mention["text"]}))
            write = False
        if not write and chosen != confidence.NEW and confidence.NEW in d.q \
                and (support.get(chosen, 0.0) == 0 or not self._name_ok(chosen, mention["text"], msg["thread_id"])):
            chosen = confidence.NEW      # unsure between an unsupported existing Item and a new one:
            #                             a duplicate is repaired by a merge, a wrong pick contaminates
        q = {(new["id"] if k == confidence.NEW else k): v for k, v in d.q.items()}
        winner = new["id"] if chosen == confidence.NEW else chosen
        return Resolution(write, winner, q, d.entropy, new, notes=notes)

    # -- writes, holds and corrections ----------------------------------------------------------------
    def _materialise(self, winner: str, new: dict | None, msg_id: str, stream: str) -> str:
        if new and winner == new["id"]:
            self.ledger.ensure_item(new["id"], new["kind"], new["label"])
            self.ledger.add_name(new["id"], new["label"], msg_id, stream)
        return winner

    def _write(self, claim: Claim, mention: dict, msg: dict, res: Resolution) -> None:
        """Every audited claim is written at once. A resolution short of the rule is written as the
        best reading, flagged `low_confidence` (shown as "my best reading"), and watched: a `holds`
        row keeps it open to re-resolution by later messages in the thread for 72 hours, and the
        review queue (`review()`) keeps re-checking it after that."""
        subject = self._materialise(res.winner, res.new, msg["id"], msg["stream_id"])
        claim.subject_id = subject
        claim.confidence = res.q.get(res.winner, 1.0 if res.write else 0.0)
        claim.status = "active"
        if not res.write:
            claim.flags = sorted(set(claim.flags) | {"low_confidence"})
        self.ledger.add_claim(claim)
        self.ledger.add_name(subject, mention["text"], msg["id"], msg["stream_id"])
        self.ledger.link(msg["thread_id"], subject, msg["sent_at"])
        if not res.write:
            m = {**mention, "excerpt": claim.quote, "message_id": msg["id"], "thread_id": msg["thread_id"]}
            self.ledger.add_hold(claim.id, m, res.q, instants.add_hours(msg["sent_at"], HOLD_HOURS))
            self.ledger.log("resolver", "uncertain_write", None, claim=claim.id, winner=subject, q=res.q,
                            entropy=res.entropy)

    def _mention_of(self, c: Claim) -> dict:
        r = self.ledger._q("SELECT name FROM ledger.names WHERE message_id=%s AND item_id=%s ORDER BY name LIMIT 1",
                           (c.message_id, c.subject_id))
        it = self.ledger.item(self.ledger.root(c.subject_id)) or {}
        return {"text": r[0][0] if r else (it.get("label") or ""), "kind": it.get("kind"), "label": it.get("label"),
                "resolution": "unsure", "item_id": "", "why": "re-resolution"}

    def reresolve(self, claim_id: str, agent: str, mention: dict | None = None,
                  evidence: bool = True) -> str | None:
        """Re-run resolution for one claim with a fresh pack (SPEC §8.4). Returns the claim id now
        in force when the answer is confident (the same claim when it confirms the subject), or
        None when it is not.

        Invariant: a re-check sees the store as if the claim had not been placed. Its own name,
        thread link and claim are hidden for the resolution (a transaction rolled back), so a
        guess cannot confirm itself; only other evidence can.

        A confident answer that names an Item the gardener absorbed undoes that merge (§9.3). A
        confident answer whose subject cannot carry the property moves nothing. An unsure answer
        about a claim that was confident makes it a best reading: the evidence that queued it
        stands, and the list should say so.

        Invariant: a confident reading is overturned only on positive contradicting evidence
        (`evidence`, from the queue's `displaced`, `conflict` or `merged`). A re-check without it,
        such as the random sample or a shared name, that disagrees with a confident claim makes it
        a best reading, shown as such, and never moves it. A best reading may be moved by any
        confident answer. Every move or close that results is shown on the list (SPEC §8.2)."""
        c = self.ledger.claim(claim_id)
        if c is None or c.status != "active":
            return None
        msg = self.ledger.message(c.message_id)
        m = mention or self._mention_of(c)
        res = None
        with self.ledger.conn.transaction():
            self.ledger.hide_footprint(c)
            fresh = pack.build(self.ledger, msg, c.quote or m["text"], self.cfg.owner_id)
            current = self.ledger.root(c.subject_id)
            it = self.ledger.item(current)
            if current not in {e["id"] for e in fresh["items"]} and it:
                # the current subject is always a candidate, on its other evidence: a move must
                # be a choice against it, not a failure to see it
                fresh["items"].append(pack.entry(self.ledger, current, self.cfg.owner_id))
            # an Item known only from this claim has no other evidence to support it: a vote for it
            # is a vote for a new Item of its label, which is what it is
            bare = {current: it["label"]} if it and not self.ledger.evidence_of(current) else {}
            res = self.resolve(m, c.quote or "", msg, fresh, as_new=bare)
            raise psycopg.Rollback()
        with self.ledger.conn.transaction():
            for action, detail in res.notes:
                self.ledger.log(agent, action, None, **detail)
            if res.write and not self.fits(c, res.kind(self.ledger)):
                self.ledger.log(agent, "move_refused", "property outside the schema of the subject chosen",
                                claim=c.id, winner=res.winner)
                res.write = False
            if res.write and self._fits_name_better(c, m["text"], res.winner):
                self.ledger.log(agent, "move_refused", "the mention names the current subject more closely",
                                claim=c.id, winner=res.winner)
                res.write = False
            if not res.write:
                if "low_confidence" in c.flags:
                    self.ledger.add_hold(c.id, {**m, "excerpt": c.quote, "message_id": msg["id"],
                                                "thread_id": msg["thread_id"]}, res.q, self._hold_until(c.id, msg))
                else:
                    self.ledger.update_claim(c.id, flags=sorted(set(c.flags) | {"low_confidence"}),
                                             confidence=res.q.get(self.ledger.root(c.subject_id), 0.0))
                    self.ledger.log(agent, "doubted", "re-check could not confirm a confident pick", claim=c.id,
                                    q=res.q)
                return None
            target = res.winner
            moves = self.ledger.root(target) != self.ledger.root(c.subject_id) or \
                bool((self.ledger.item(target) or {}).get("merged_into"))
            if moves and not evidence and "low_confidence" not in c.flags:
                self.ledger.update_claim(c.id, flags=sorted(set(c.flags) | {"low_confidence"}),
                                         confidence=res.q.get(self.ledger.root(c.subject_id), 0.0))
                self.ledger.log(agent, "doubted", "a re-check without contrary evidence disagreed; not moved",
                                claim=c.id, q=res.q, winner=target)
                return None
            self.ledger.drop_hold(c.id)
            flags = sorted(set(c.flags) - {"low_confidence"})
            if (self.ledger.item(target) or {}).get("merged_into"):
                was = self.ledger.root(target)
                self.ledger.unmerge(target, agent, f"re-resolution of {c.id} names it apart from {was}")
                gardener.remember_different(self.ledger, self.cfg, target, was, agent, "undone by re-resolution")
            if self.ledger.root(target) == self.ledger.root(c.subject_id):
                self.ledger.update_claim(c.id, flags=flags, confidence=res.q.get(target, 1.0))
                self.ledger.log(agent, "resolution_confirmed", None, claim=c.id, q=res.q)
                return c.id
            subject = self._materialise(target, res.new, msg["id"], msg["stream_id"])
            new_id = self.ledger.supersede_claim(c.id, agent, f"re-resolved to {subject}", subject_id=subject,
                                                 flags=flags, confidence=res.q.get(target, 1.0))
            self.ledger.add_name(subject, m["text"], msg["id"], msg["stream_id"])
            self.ledger.link(msg["thread_id"], subject, msg["sent_at"])
        return new_id

    def _hold_until(self, claim_id: str, msg: dict) -> str:
        r = self.ledger._q("SELECT hold_until FROM ledger.holds WHERE claim_id=%s", (claim_id,))
        return r[0][0] if r else instants.add_hours(msg["sent_at"], HOLD_HOURS)

    def rehold(self, msg: dict) -> list[str]:
        """SPEC §7.3: a new message in a thread re-runs resolution for that thread's open holds."""
        done = []
        if any(h["mention"]["thread_id"] == msg["thread_id"] and h["mention"]["message_id"] != msg["id"]
               for h in self.ledger.holds()):
            self.projector.settle("resolver")
        for h in self.ledger.holds():
            m = h["mention"]
            if m["thread_id"] != msg["thread_id"] or m["message_id"] == msg["id"]:
                continue
            try:
                r = self.reresolve(h["claim_id"], "resolver", m)
            except Exception as e:      # a model failure leaves the hold for the next message
                self.ledger.log("resolver", "rehold_failed", f"{type(e).__name__}: {e}"[:500], claim=h["claim_id"])
                continue
            if r:
                done.append(r)
        return done

    # -- the review queue (SPEC §8.4) -------------------------------------------------------------
    def reasons(self) -> dict[str, set[str]]:
        """Why each mail claim is open to re-check. Doubt: `best_reading` (written short of the
        rule), `shared_name` (its name is now on two Items of its kind). Evidence, whatever the
        claim's confidence: `merged` (its Item was absorbed by a merge), `displaced` (an open
        request on A while a later statement on another Item of A's kind says what was asked,
        among the same people), `conflict` (Attedra's conflicts read finds sources disagreeing
        on the claim's property of its subject)."""
        pairs = self.ledger.message_claims()
        mine = {c.id for c, _ in pairs if c.extractor == EXTRACTOR}
        out: dict[str, set[str]] = {}

        def add(cid: str, why: str) -> None:
            if cid in mine:
                out.setdefault(cid, set()).add(why)

        ambiguous = {r[0] for r in self.ledger._q(
            "SELECT n.name_norm FROM ledger.names n JOIN ledger.items i ON i.id=n.item_id "
            "WHERE i.merged_into IS NULL GROUP BY n.name_norm, i.kind HAVING count(DISTINCT n.item_id) > 1")}
        root = {c.id: self.ledger.root(c.subject_id) for c, _ in pairs}
        kind = {r: (self.ledger.item(r) or {}).get("kind") for r in set(root.values())}
        withdrawn = {self.ledger.successor(c.value["claim"]) for c, _ in pairs if c.kind == "withdrawal"}
        owner = self.cfg.owner_id

        def people(m: dict) -> set[str]:
            return {m["producer_id"], *m["recipients"]} - {owner}

        def met_before(k: Claim, km: dict, sm: dict) -> bool:
            return any(t.kind == "statement" and root[t.id] == root[k.id] and t.property == k.property
                       and t.value == k.value and t.id != s_id[0]
                       and instants.sort_key(km["sent_at"]) <= instants.sort_key(tm["sent_at"])
                       < instants.sort_key(sm["sent_at"]) for t, tm in pairs)

        s_id = [""]

        def explained(s: Claim, sm: dict) -> bool:
            """A request on the statement's own Item, among the same people, still open when the
            statement arrived, accounts for it."""
            s_id[0] = s.id
            return any(k.kind == "commitment" and k.form == "value" and root[k.id] == root[s.id]
                       and k.property == s.property and k.value == s.value
                       and instants.sort_key(km["sent_at"]) <= instants.sort_key(sm["sent_at"])
                       and (km["thread_id"] == sm["thread_id"] or people(km) & people(sm))
                       and not met_before(k, km, sm)
                       for k, km in pairs)

        for c, m in pairs:
            if c.id not in mine:
                continue
            if "low_confidence" in c.flags:
                add(c.id, "best_reading")
            names = {r[0] for r in self.ledger._q(
                "SELECT name_norm FROM ledger.names WHERE message_id=%s AND item_id=%s", (c.message_id, c.subject_id))}
            if names & ambiguous:
                add(c.id, "shared_name")
            if root[c.id] != c.subject_id:
                add(c.id, "merged")
            if c.kind != "commitment" or c.form != "value" or c.id in withdrawn:
                continue
            after = [(s, sm) for s, sm in pairs if s.kind == "statement" and s.property == c.property
                     and s.value == c.value and instants.sort_key(sm["sent_at"]) >= instants.sort_key(m["sent_at"])]
            if any(root[s.id] == root[c.id] for s, _ in after):
                continue           # met where it was placed
            for s, sm in after:
                if explained(s, sm):
                    continue       # it meets a request on its own Item among the same people: no oddity
                if kind[root[s.id]] == kind[root[c.id]] and \
                        (sm["thread_id"] == m["thread_id"] or people(sm) & people(m)):
                    add(c.id, "displaced")
                    add(s.id, "displaced")
        for subject in sorted({root[c] for c in mine}):
            try:
                r = self.projector.session.read("conflicts", {"subject": subject, "frame": {"scope": ids.SCOPE}})
            except Exception:      # a limitation or a stale projection: no evidence either way
                continue
            for k in r.get("conflicts", []):
                sources = {side["source"] for side in k["sides"]}
                for c, m in pairs:
                    if root[c.id] == subject and c.property == k["property"] and m["stream_id"] in sources:
                        add(c.id, "conflict")
        return out

    def signature(self, claim_id: str, why: set[str]) -> str:
        """What a re-check of the claim would rest on: the reasons, the subject, the pack the
        resolver would be shown, and each candidate's structural support. Unchanged, a second re-check would give the same answer."""
        c = self.ledger.claim(claim_id)
        msg = self.ledger.message(c.message_id)
        p = pack.build(self.ledger, msg, c.quote or "", self.cfg.owner_id)
        owner = self.cfg.owner_id
        anchors = {msg["thread_id"], msg["producer_id"], *msg["recipients"],
                   *(self.ledger.root(i) for i in self.ledger.links_from(msg["thread_id"]))} - {owner}
        edges = self.ledger.graph(exclude={owner})
        data = [sorted(why), self.ledger.root(c.subject_id), sorted(c.flags),
                [[e["id"], e["names"], e["latest_claims"], round(confidence.support(edges, e["id"], anchors), 3)]
                 for e in p["items"]]]
        return ids._h(json.dumps(data, sort_keys=True, default=str))

    def _reviewed(self) -> dict[str, str]:
        return {r["detail"]["claim"]: r["detail"]["signature"] for r in self.ledger.revisions("reviewed")}

    def review_queue(self, limit: int = 20) -> list[str]:
        """Claims open to re-check and not already re-checked on the same evidence. Evidence first
        (it can catch a confident wrong pick), then doubt; within each, lowest confidence first."""
        seen = self._reviewed()
        out = []
        for cid, why in self.reasons().items():
            if seen.get(cid) == self.signature(cid, why):
                continue
            c = self.ledger.claim(cid)
            evidence = bool(why & EVIDENCE)
            out.append((0 if evidence else 1, c.confidence, cid))
        return [cid for *_, cid in sorted(out)[:limit]]

    def _remember(self, claim_id: str, why: str) -> None:
        reasons = self.reasons().get(claim_id, set())
        self.ledger.log("reviewer", "reviewed", why, claim=claim_id, signature=self.signature(claim_id, reasons))

    def review(self, limit: int = 20, sample: int | None = None) -> list[str]:
        """Re-check the head of the queue, one claim at a time; after a change the queue is read
        again, since a correction can settle other entries. Then re-check a small random sample of
        confident claims never re-checked (SAMPLE): the backstop for a wrong pick no evidence has
        reached yet. Every re-check is remembered with its evidence signature."""
        sample = SAMPLE if sample is None else sample
        self.projector.settle("reviewer")
        changed: list[str] = []
        done: set[str] = set()
        queue = self.review_queue(limit)
        reasons = self.reasons()
        while queue and len(done) < limit:
            cid = queue.pop(0)
            if cid in done:
                continue
            done.add(cid)
            r = self.reresolve(cid, "reviewer", evidence=bool(reasons.get(cid, set()) & EVIDENCE))
            self._remember(r or cid, "queue")
            if r:
                changed.append(r)
                if r != cid:
                    queue = [x for x in self.review_queue(limit) if x not in done]
                    reasons = self.reasons()
        seen = self._reviewed()
        pool = sorted(c.id for c in self.ledger.active_claims()
                      if c.extractor == EXTRACTOR and "low_confidence" not in c.flags and c.id not in seen
                      and c.id not in done)
        for cid in random.Random(len(seen)).sample(pool, min(sample, len(pool))):
            r = self.reresolve(cid, "reviewer", evidence=False)
            self._remember(r or cid, "sample")
            if r and r != cid:
                changed.append(r)
        return changed

    def release_holds(self, now: str) -> list[str]:
        """Past `hold_until`, stop watching the thread. The claim stays written, flagged, and in
        the review queue."""
        done = []
        for h in self.ledger.holds():
            if instants.parse(now)[0] < instants.parse(h["hold_until"])[0]:
                continue
            c = self.ledger.claim(h["claim_id"])
            self.ledger.drop_hold(h["claim_id"])
            self.ledger.log("resolver", "hold_released", None, claim=h["claim_id"],
                            winner=c.subject_id if c else None, q=h["options"])
            done.append(h["claim_id"])
        return done
