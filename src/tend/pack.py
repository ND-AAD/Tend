"""The context pack (SPEC §6.2): the Items a message could be about, with their recorded names,
latest claims and open expectations, so that the extractor and resolver choose from what exists."""
from __future__ import annotations

import re

from . import ids, instants, schema
from .ledger import Ledger, normalise

MAX_ITEMS = 40
RECENT_HOURS = 30 * 24
_URL = re.compile(r"https?://[^\s<>\"')\]]+")
_GH_REF = re.compile(r"\b([\w.-]+/[\w.-]+)#(\d+)\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")


def exact_keys(text: str) -> list[str]:
    """Exact keys found in text: URLs, owner/repo#n references and email addresses."""
    keys = [u.rstrip(".,;:").lower() for u in _URL.findall(text)]
    for repo, n in _GH_REF.findall(text):
        keys += [ids.pr(repo, int(n)), ids.issue(repo, int(n))]
    keys += [ids.person_email(e) for e in _EMAIL.findall(text)]
    return keys


def keyed_items(ledger: Ledger, text: str) -> list[str]:
    out: list[str] = []
    for k in exact_keys(text):
        for i in ledger.items_by_key(k):
            if i not in out:
                out.append(i)
    return out


def named_items(ledger: Ledger, text: str) -> list[str]:
    body = " " + normalise(text) + " "
    names = sorted(ledger.all_names(), key=lambda r: (-len(r[1]), r[1], r[0]))
    out: list[str] = []
    for item_id, n in names:
        if f" {n} " in body and item_id not in out:
            out.append(item_id)
    return out


def entry(ledger: Ledger, item_id: str, owner: str) -> dict:
    it = ledger.item(item_id) or {"id": item_id, "kind": "thing", "label": None}
    claims = [c for c, _ in ledger.message_claims() if ledger.root(c.subject_id) == item_id]
    latest = [{"property": c.property, "value": c.value, "kind": c.kind} for c in claims[-3:]]
    open_exp = [{"claim": c.id, "property": c.property, "form": c.form,
                 "obligated": "owner" if c.obligated_id == owner else c.obligated_id}
                for c in claims if c.kind == "commitment"]
    return {"id": item_id, "kind": it["kind"], "label": it["label"], "names": ledger.names_of(item_id)[:5],
            "latest_claims": latest, "expectations": open_exp}


def build(ledger: Ledger, message: dict, body: str, owner: str, extra: list[str] = ()) -> dict:
    order: list[str] = []

    def take(xs) -> None:
        for x in xs:
            r = ledger.root(x)
            it = ledger.item(r)
            if it and it["kind"] in schema.RESOLVABLE_KINDS + ("pr", "issue") and r not in order:
                order.append(r)

    take(extra)
    if message.get("thread_id"):
        take(ledger.links_from(message["thread_id"]))
    take(keyed_items(ledger, body))
    take(named_items(ledger, body))
    people = {message["producer_id"], *message.get("recipients", [])} - {owner}
    since = instants.add_hours(message["sent_at"], -RECENT_HOURS)
    for c, m in ledger.message_claims():
        if instants.after(m["sent_at"], since) and people & {m["producer_id"], *m["recipients"]}:
            take([c.subject_id])
    items = [entry(ledger, i, owner) for i in order[:MAX_ITEMS]]
    kinds = sorted({i["kind"] for i in items} | set(schema.RESOLVABLE_KINDS))
    return {"items": items, "properties": {k: schema.PROPERTIES[k] for k in kinds if k in schema.PROPERTIES},
            "people": {"producer": message["producer_id"], "recipients": message.get("recipients", []),
                       "owner": owner}}
