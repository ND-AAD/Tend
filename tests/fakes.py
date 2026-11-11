"""Scripted model fakes (SPEC §12): the code under test sees only the llm Protocols."""
from __future__ import annotations

from typing import Callable


class Extractor:
    def __init__(self, script: dict[str, list[dict]]) -> None:
        self.script = script
        self.seen: list[dict] = []

    def extract(self, body, message, pack):
        self.seen.append({"body": body, "message": message, "pack": pack})
        return self.script.get(message["provider_id"], [])


class Resolver:
    """`rule(mention, candidates, seed)` returns a choice: a candidate id or ("new", kind, label)."""

    def __init__(self, rule: Callable) -> None:
        self.rule = rule
        self.calls = 0

    def resolve(self, mention, excerpt, candidates, seed):
        self.calls += 1
        r = self.rule(mention, candidates, seed)
        if isinstance(r, tuple):
            return {"choice": "new", "kind": r[1], "label": r[2], "why": "scripted"}
        return {"choice": r, "kind": mention.get("kind", "deliverable"), "label": "", "why": "scripted"}


def by_name(mention, candidates, seed):
    """Pick the candidate whose names contain a word of the mention, else new."""
    words = set(mention["text"].lower().split()) - {"the", "a", "revised"}
    for c in candidates:
        if any(w in " ".join(c["names"] + [c["label"] or ""]).lower() for w in words):
            return c["id"]
    return ("new", mention.get("kind", "deliverable"), mention.get("label") or mention["text"])


class Judge:
    def __init__(self, answer: bool = True) -> None:
        self.answer = answer
        self.asked: list[tuple[str, str]] = []

    def same(self, a, b, evidence):
        self.asked.append((a["id"], b["id"]))
        return self.answer, "scripted judgement"


def mention(text, resolution="new", item_id="", kind="deliverable", label=""):
    return {"text": text, "resolution": resolution, "item_id": item_id, "kind": kind,
            "label": label or text, "why": ""}


def proposal(kind, quote, mentions, prop, value, form="value", obligated="", party="", deadline=None, subject=0):
    return {"kind": kind, "mentions": mentions, "subject": subject, "property": prop, "value": value,
            "form": form, "obligated": obligated, "party": party, "deadline": deadline, "quote": quote}


def mail(id, thread, frm, to, sent_at, body):
    return {"id": id, "thread_id": thread, "from": frm, "to": to, "cc": [], "sent_at": sent_at, "body": body}
