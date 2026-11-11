"""Mail ingestion (SPEC §6, §7): frontier-model extraction, deterministic audit, entropy-based
resolution confidence, holds. No decision model sits between the extractor and the store; the
audit and the confidence rule are code."""
from __future__ import annotations

import random
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from . import confidence, deadlines, ids, instants, pack, schema
from .config import Config
from .ledger import Claim, Ledger, normalise
from .llm import Extractor, Resolver

EXTRACTOR = "mail-v1"
HOLD_HOURS = 72
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
        raises before anything is stored, so the same message can simply be ingested again."""
        msg = self.record(mail)
        out = Outcome(msg["id"])
        if self.ledger.message(msg["id"]):
            out.replay = True
            return out
        body = new_text(mail["body"])
        the_pack = pack.build(self.ledger, msg, body, self.cfg.owner_id)
        decided: list[tuple[Claim, dict, Resolution]] = []
        for i, p in enumerate(self.extractor.extract(body, msg, the_pack)):
            try:
                claim, mention = self.audit(p, i, msg, body, the_pack)
            except Refused as r:
                self.ledger.log("audit", "audit_refused", r.code, message=msg["id"], ordinal=i, **r.detail)
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
                self._write(claim, mention, msg, res)
                (out.written if res.write else out.held).append(claim.id)
        self.projector.append(msg["id"])
        out.released = self.rehold(msg)
        return out

    # -- audit (SPEC §6.3) ---------------------------------------------------------------------------
    def audit(self, p: dict, ordinal: int, msg: dict, body: str, the_pack: dict) -> tuple[Claim, dict]:
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
            self.ledger.log("audit", "vocabulary_gap", None, kind=subject_kind, property=prop, value=value)
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
                self.ledger.log("audit", "deadline_refused", str(e), message=msg["id"], ordinal=ordinal)
        mention["kind"] = subject_kind
        claim = Claim(id=ids.claim(msg["id"], ordinal, EXTRACTOR), message_id=msg["id"], ordinal=ordinal,
                      kind=kind, subject_id="", property=prop, value=None if form == "ask" else value,
                      form=form, obligated_id=obligated, party_id=party, deadline=deadline, quote=quote,
                      flags=flags, extractor=EXTRACTOR)
        return claim, mention

    # -- resolution (SPEC §7) ---------------------------------------------------------------------------
    def collisions(self, text: str, label: str, kind: str) -> set[str]:
        out = set(pack.keyed_items(self.ledger, text))
        for n in {normalise(text), normalise(label or "")} - {""}:
            out |= set(self.ledger.items_named(n, kind))
        return {self.ledger.root(i) for i in out}

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

    def resolve(self, mention: dict, excerpt: str, msg: dict, the_pack: dict) -> Resolution:
        """Always returns a resolution: a request is never dropped for lack of a subject. When
        the rule of §7.2 is not met the resolution is written as a best reading (`write` False)."""
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
            votes, new_names, collided = [], [], set()
            for seed in range(confidence.K):
                order = candidates[:]
                random.Random(seed).shuffle(order)
                v = self.resolver.resolve(mention, excerpt, order, seed)
                choice = v.get("choice")
                if choice == "new":
                    label = v.get("label") or mention.get("label") or mention["text"]
                    hit = self.collisions(mention["text"], label, kind)
                    if hit and attempt == 0:
                        collided |= hit
                        continue
                    # second round: the resolver has seen the colliding Items and still says new
                    votes.append(confidence.NEW)
                    new_names.append((kind, label))
                elif choice in cand_ids:
                    votes.append(choice)
                else:
                    self.ledger.log("audit", "invented_id", None, message=msg["id"], choice=choice)
            missing = collided - cand_ids
            if attempt == 0 and (missing or (collided and not votes)):
                candidates += [pack.entry(self.ledger, i, self.cfg.owner_id) for i in sorted(missing)]
                continue
            break
        if not votes:                     # every vote invalid: a new Item, as a best reading
            label = mention.get("label") or mention["text"]
            new = {"kind": kind, "label": label, "id": ids.resolved_item(kind, label, msg["id"])}
            return Resolution(False, new["id"], {new["id"]: 0.0}, 1.0, new)
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
            self.ledger.log("audit", "name_check_failed", None, message=msg["id"], item=chosen, text=mention["text"])
            write = False
        if not write and chosen != confidence.NEW and confidence.NEW in d.q \
                and (support.get(chosen, 0.0) == 0 or not self._name_ok(chosen, mention["text"], msg["thread_id"])):
            chosen = confidence.NEW      # unsure between an unsupported existing Item and a new one:
            #                             a duplicate is repaired by a merge, a wrong pick contaminates
        q = {(new["id"] if k == confidence.NEW else k): v for k, v in d.q.items()}
        winner = new["id"] if chosen == confidence.NEW else chosen
        return Resolution(write, winner, q, d.entropy, new)

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

    def reresolve(self, claim_id: str, agent: str, mention: dict | None = None) -> str | None:
        """Re-run resolution for one claim with a fresh pack (SPEC §8.4). A confident answer that
        names another subject supersedes the claim (D1); a confident answer that confirms it clears
        the flag. Returns the claim id now in force, or None when nothing changed."""
        c = self.ledger.claim(claim_id)
        if c is None or c.status != "active":
            return None
        msg = self.ledger.message(c.message_id)
        m = mention or self._mention_of(c)
        fresh = pack.build(self.ledger, msg, c.quote or m["text"], self.cfg.owner_id)
        res = self.resolve(m, c.quote or "", msg, fresh)
        if not res.write:
            self.ledger.add_hold(c.id, {**m, "excerpt": c.quote, "message_id": msg["id"],
                                        "thread_id": msg["thread_id"]}, res.q,
                                 self._hold_until(c.id, msg))
            return None
        with self.ledger.conn.transaction():
            self.ledger.drop_hold(c.id)
            flags = sorted(set(c.flags) - {"low_confidence"})
            if self.ledger.root(res.winner) == self.ledger.root(c.subject_id):
                self.ledger.update_claim(c.id, flags=flags, confidence=res.q.get(res.winner, 1.0))
                self.ledger.log(agent, "resolution_confirmed", None, claim=c.id, q=res.q)
                return c.id
            subject = self._materialise(res.winner, res.new, msg["id"], msg["stream_id"])
            new_id = self.ledger.supersede_claim(c.id, agent, f"re-resolved to {subject}", subject_id=subject,
                                                 flags=flags, confidence=res.q.get(res.winner, 1.0))
            self.ledger.add_name(subject, m["text"], msg["id"], msg["stream_id"])
            self.ledger.link(msg["thread_id"], subject, msg["sent_at"])
        return new_id

    def _hold_until(self, claim_id: str, msg: dict) -> str:
        r = self.ledger._q("SELECT hold_until FROM ledger.holds WHERE claim_id=%s", (claim_id,))
        return r[0][0] if r else instants.add_hours(msg["sent_at"], HOLD_HOURS)

    def rehold(self, msg: dict) -> list[str]:
        """SPEC §7.3: a new message in a thread re-runs resolution for that thread's open holds."""
        done = []
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

    def review_queue(self, limit: int = 20) -> list[str]:
        """The self-correction queue (SPEC §8.4), lowest confidence first. A claim enters when it is a best reading (`low_confidence`),
        or when the name it was resolved by is now recorded on more than one Item of its kind,
        which is how a confident pick later becomes doubtful."""
        ambiguous = {r[0] for r in self.ledger._q(
            "SELECT n.name_norm FROM ledger.names n JOIN ledger.items i ON i.id=n.item_id "
            "WHERE i.merged_into IS NULL GROUP BY n.name_norm, i.kind HAVING count(DISTINCT n.item_id) > 1")}
        out = []
        for c in self.ledger.active_claims():
            if c.extractor != EXTRACTOR:
                continue
            names = {r[0] for r in self.ledger._q(
                "SELECT name_norm FROM ledger.names WHERE message_id=%s AND item_id=%s", (c.message_id, c.subject_id))}
            if "low_confidence" in c.flags or names & ambiguous:
                out.append((c.confidence, c.id))
        return [cid for _, cid in sorted(out)[:limit]]

    def review(self, limit: int = 20) -> list[str]:
        """Re-resolve the head of the review queue; the store is repaired at the next rebuild."""
        changed = []
        for cid in self.review_queue(limit):
            r = self.reresolve(cid, "reviewer")
            if r:
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
