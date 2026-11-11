"""Deterministic GitHub ingestion (SPEC §5.5). Input: GitHub webhook payloads with their event
name, as delivered to a webhook or replayed from the events API. No model is involved."""
from __future__ import annotations

from datetime import datetime

from . import ids, instants
from .config import Config
from .ledger import Claim, Ledger
from .projector import holding

EXTRACTOR = "github-v1"


def _instant(ts: str) -> str:
    return instants.from_datetime(datetime.fromisoformat(ts.replace("Z", "+00:00")))


def _person(cfg: Config, login: str) -> str:
    return cfg.owner_for(ids.person_gh(login))


def map_event(event_name: str, payload: dict, cfg: Config, ledger: Ledger) -> tuple[dict, list[Claim]] | None:
    """Return the ledger message and its claims, or None when the event carries nothing we map.
    Unmapped events still return a message with no claims, so the log is complete."""
    repo = payload["repository"]["full_name"]
    action = payload.get("action", "")
    sender = payload["sender"]["login"]
    obj = payload.get("pull_request") or payload.get("issue")
    if obj is None:
        return None
    # a comment on a pull request arrives as an issue carrying a `pull_request` link: same Item
    is_pr = "pull_request" in payload or "pull_request" in obj
    n = obj["number"]
    subject = ids.pr(repo, n) if is_pr else ids.issue(repo, n)
    kind = "pr" if is_pr else "issue"
    url = obj.get("html_url", "")
    if event_name == "pull_request_review":
        when, eid = payload["review"]["submitted_at"], f"{repo}:review:{payload['review']['id']}"
    else:
        when = obj.get("updated_at") or obj.get("created_at")
        eid = f"{repo}:{event_name}:{n}:{action}:{when}"
        if action in ("review_requested", "review_request_removed", "assigned", "unassigned"):
            target = payload.get("requested_reviewer") or payload.get("assignee") or {}
            eid += ":" + target.get("login", "")
    msg = {
        "id": ids.event("gh", eid), "provider": "gh", "provider_id": eid,
        "thread_id": ids.thread("gh", f"{repo.lower()}/{n}"), "stream_id": ids.gh_log(repo),
        "producer_id": _person(cfg, sender), "recipients": [], "sent_at": _instant(when),
        "artifact": {"@ref": "artifact", "id": url or eid, "edition": when},
    }
    ledger.ensure_item(subject, kind, f"{obj.get('title')} ({repo.split('/')[-1]}#{n})", keys=[subject, url.lower()] if url else [subject])
    owner = cfg.owner_id
    claims: list[Claim] = []

    def add(kind_: str, prop: str, value, **kw) -> Claim:
        c = Claim(id=ids.claim(msg["id"], len(claims), EXTRACTOR), message_id=msg["id"], ordinal=len(claims),
                  kind=kind_, subject_id=subject, property=prop, value=value, extractor=EXTRACTOR, **kw)
        claims.append(c)
        return c

    def open_commitments(prop: str | None = None) -> list[Claim]:
        """Active commitments of the owner on this subject not yet met by a later owner statement."""
        pairs = ledger.message_claims()
        out = []
        for c, m in pairs:
            if c.kind != "commitment" or c.subject_id != subject or cfg.owner_for(c.obligated_id) != owner \
                    or (prop and c.property != prop):
                continue
            if any(s.kind == "statement" and s.subject_id == subject and s.property == c.property
                   and s.value == c.value and sm["producer_id"] == owner
                   and instants.sort_key(sm["sent_at"]) >= instants.sort_key(m["sent_at"]) for s, sm in pairs):
                continue
            if any(w.kind == "withdrawal" and ledger.successor(w.value["claim"]) == c.id for w, _ in pairs):
                continue
            out.append(c)
        return out

    def withdraw_all(prop: str | None = None, keep: str | None = None) -> None:
        for target in open_commitments(prop):
            if target.property != keep:
                add("withdrawal", target.property, {"claim": target.id}, party_id=_person(cfg, sender))

    def here(prop: str) -> bool:
        return any(c.kind == "commitment" and c.property == prop for c in claims)

    def standing(prop: str) -> bool:
        """Whether GitHub still has the owner assigned (prop `resolved`) or as a requested reviewer
        (prop `review_by_owner`). Read from the payload when it says, else from the ledger: the last
        assignment or request was not removed, and for a review, not yet answered by one."""
        people = [x.get("login", "") for x in obj.get("assignees" if prop == "resolved" else "requested_reviewers") or []]
        if prop == "resolved" and obj.get("assignees") is not None or prop == "review_by_owner" and \
                obj.get("requested_reviewers") is not None:
            return any(_person(cfg, x) == owner for x in people)
        state = False
        for c, m in sorted(ledger.message_claims(), key=lambda cm: instants.sort_key(cm[1]["sent_at"])):
            if c.subject_id != subject or c.property != prop:
                continue
            act = m["provider_id"].split(":")[3] if m["provider_id"].count(":") >= 3 else ""
            if c.kind == "commitment":
                state = True
            elif c.kind == "withdrawal" and act in ("unassigned", "review_request_removed"):
                state = False
            elif c.kind == "statement" and prop == "review_by_owner" and m["producer_id"] == owner:
                state = False
        return state

    def await_owner() -> None:
        """A pull request you opened or were assigned waits on you to merge or close it."""
        if not open_commitments("resolved") and not here("resolved"):
            add("commitment", "resolved", True, obligated_id=owner, party_id=_person(cfg, sender))

    if action in ("opened", "reopened"):
        vals = {"state": "open", "title": obj["title"], "author": obj["user"]["login"]}
        if not is_pr and action == "reopened":
            vals["resolved"] = False
        if is_pr:
            vals["resolved"] = False
        for p, v in vals.items():
            add("statement", p, v)
        if is_pr and _person(cfg, obj["user"]["login"]) == owner:
            await_owner()
        if action == "reopened":
            # GitHub sends no new assigned or review_requested on reopen: what still stands returns
            if standing("resolved") and not open_commitments("resolved") and not here("resolved"):
                add("commitment", "resolved", True, obligated_id=owner, party_id=_person(cfg, sender))
            if is_pr and standing("review_by_owner") and not open_commitments("review_by_owner"):
                add("commitment", "review_by_owner", "submitted", obligated_id=owner, party_id=_person(cfg, sender))
    elif action == "closed":
        if is_pr:
            add("statement", "state", "merged" if obj.get("merged") else "closed")
            add("statement", "resolved", True)
            # nothing remains to review; your own close is the evidence for "merge or close"
            withdraw_all(keep="resolved" if _person(cfg, sender) == owner else None)
        else:
            add("statement", "state", "closed")
            if _person(cfg, sender) == owner:
                add("statement", "resolved", True)
            else:
                # closed by someone else: the task assigned to you ended without your evidence
                add("statement", "resolved", True)
                withdraw_all()
    elif action == "review_requested" and _person(cfg, payload["requested_reviewer"]["login"]) == owner:
        add("commitment", "review_by_owner", "submitted", obligated_id=owner, party_id=_person(cfg, sender))
    elif action == "review_request_removed" and _person(cfg, payload["requested_reviewer"]["login"]) == owner:
        withdraw_all("review_by_owner")
    elif event_name == "pull_request_review" and action == "submitted" and _person(cfg, sender) == owner:
        add("statement", "review_by_owner", "submitted")
    elif event_name == "pull_request" and action == "assigned" and _person(cfg, payload["assignee"]["login"]) == owner:
        await_owner()
    elif event_name == "pull_request" and action == "unassigned" and _person(cfg, payload["assignee"]["login"]) == owner \
            and _person(cfg, obj["user"]["login"]) != owner:
        withdraw_all("resolved")
    elif event_name == "issues" and action == "assigned" and _person(cfg, payload["assignee"]["login"]) == owner:
        add("commitment", "resolved", True, obligated_id=owner, party_id=_person(cfg, sender))
    elif event_name == "issues" and action == "unassigned" and _person(cfg, payload["assignee"]["login"]) == owner:
        withdraw_all("resolved")
    return msg, claims


def _store(ledger: Ledger, msg: dict, claims: list[Claim], event_name: str, payload: dict) -> None:
    ledger.add_payload(msg["id"], event_name, payload)
    for c in claims:
        ledger.add_claim(c)
        ledger.link(msg["thread_id"], c.subject_id, msg["sent_at"])
        ledger.link(msg["thread_id"], msg["producer_id"], msg["sent_at"])


@holding(lambda event_name, payload, cfg, ledger, projector, *a, **k: projector)
def ingest(event_name: str, payload: dict, cfg: Config, ledger: Ledger, projector) -> str | None:
    """Invariant: the claims of a subject's events do not depend on the order they arrive in.
    The mapping reads what stands from the ledger, so an event dated before the subject's latest
    one is mapped against the ledger as it stood at its time: the later events' claims are taken
    out, the early event is mapped, and the later events are mapped again from their stored
    payloads in event-time order (SPEC §5.5). Claim ids are deterministic, so owner acts and
    withdrawals that name them still apply."""
    projector.settle("github")
    first = map_event(event_name, payload, cfg, ledger)
    if first is None:
        return None
    msg = first[0]
    if ledger.message(msg["id"]):                 # replay: already ingested
        if msg["id"] in ledger.unprojected():
            projector.refresh("github")          # a retry completes the projection
        return msg["id"]
    with ledger.conn.transaction():
        later = [m for m in ledger.messages() if m["thread_id"] == msg["thread_id"] and m["provider"] == "gh"
                 and instants.sort_key(m["sent_at"]) > instants.sort_key(msg["sent_at"])]
        later.sort(key=lambda m: (instants.sort_key(m["sent_at"]), m["id"]))
        stored = {m["id"]: ledger.payload(m["id"]) for m in later}
        if later and any(v is None for v in stored.values()):
            # a ledger older than stored payloads: the later claims cannot be regenerated, so they
            # are never deleted; the early event is mapped as it arrives, and the store is rebuilt
            msg, claims = first
            # without the later payloads their effect cannot be recomputed, so the early event may
            # not end what a later event of the subject left standing: once a later event states
            # the subject's state, the early event's withdrawals are left out (its statements are
            # kept; the projection orders them by time)
            later_ids = {m["id"] for m in later}
            restated = any(c.message_id in later_ids and c.kind == "statement" and c.property == "state"
                           for c in ledger.active_claims())
            omitted = [c.id for c in claims if restated and c.kind == "withdrawal"]
            claims = [c for c in claims if c.id not in omitted]
            ledger.log("github", "rederive_impossible", "a later event has no stored payload",
                       message=msg["id"], later=[m["id"] for m in later if stored[m["id"]] is None],
                       omitted=omitted)
            ledger.add_message(msg)
            _store(ledger, msg, claims, event_name, payload)
            ledger.mark_stale(f"github event {msg['id']} arrived before later events")
        elif later:
            for m in later:
                ledger.delete_claims(m["id"])
            msg, claims = map_event(event_name, payload, cfg, ledger)
            ledger.add_message(msg)
            _store(ledger, msg, claims, event_name, payload)
            for m in later:
                name, p = stored[m["id"]]
                _, again = map_event(name, p, cfg, ledger)
                for c in again:
                    ledger.add_claim(c)
            ledger.log("github", "rederived", "event arrived before later events of its subject",
                       message=msg["id"], later=[m["id"] for m in later])
            ledger.mark_stale(f"github event {msg['id']} arrived before later events")
        else:
            msg, claims = first
            ledger.add_message(msg)
            _store(ledger, msg, claims, event_name, payload)
    projector.append(msg["id"])
    return msg["id"]
