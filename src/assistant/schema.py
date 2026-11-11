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
           "review_by_owner": "enum:submitted", "merged": "bool"},
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
