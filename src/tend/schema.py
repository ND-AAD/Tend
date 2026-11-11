"""Property vocabulary per Item kind (SPEC §6.3). A property outside this schema is never written;
the audit logs it as a vocabulary gap for the gardener. Types: 'bool', 'str', 'enum:<a|b>'."""
from __future__ import annotations

PROPERTIES: dict[str, dict[str, str]] = {
    "deliverable": {"delivered": "bool", "status": "enum:not_started|in_progress|done|blocked",
                    "owner": "str", "location": "str", "version": "str"},
    "meeting": {"start": "str", "end": "str", "location": "str",
                "status": "enum:proposed|confirmed|cancelled", "agenda": "str"},
    "project": {"status": "enum:active|paused|done", "phase": "str", "next_milestone": "str"},
    "decision": {"decided": "bool", "outcome": "str"},
    "question": {"answer": "str", "answered": "bool"},
    "document": {"reviewed": "bool", "sent": "bool", "signed": "bool", "version": "str"},
    "pr": {"state": "enum:open|closed|merged", "title": "str", "author": "str",
           "review_by_owner": "enum:submitted", "merged": "bool", "resolved": "bool"},
    "issue": {"state": "enum:open|closed", "title": "str", "resolved": "bool"},
    "person": {"availability": "str", "role": "str"},
}

RESOLVABLE_KINDS = ("deliverable", "meeting", "project", "decision", "question", "document")


def check_value(kind: str, prop: str, value) -> bool:
    t = PROPERTIES.get(kind, {}).get(prop)
    if t is None:
        return False
    if t == "bool":
        return isinstance(value, bool)
    if t == "str":
        return isinstance(value, str) and value != ""
    if t.startswith("enum:"):
        return value in t[5:].split("|")
    return False


def words(prop: str) -> str:
    return prop.replace("_", " ")


TASKS: dict[tuple[str, str], str] = {
    ("pr", "resolved"): "merge or close",
    ("pr", "review_by_owner"): "review",
    ("issue", "resolved"): "resolve",
    ("deliverable", "delivered"): "deliver",
    ("document", "reviewed"): "review",
    ("document", "sent"): "send",
    ("document", "signed"): "sign",
    ("decision", "decided"): "decide",
    ("question", "answer"): "answer",
}


def task(kind: str, prop: str, value, form: str = "value") -> str:
    """The words a list line uses for what is expected."""
    if form == "ask":
        return f"answer: {words(prop)}"
    if value is True and (kind, prop) in TASKS:
        return TASKS[(kind, prop)]
    if (kind, prop) in TASKS and prop == "review_by_owner":
        return TASKS[(kind, prop)]
    return f"{words(prop)}: {value}"
