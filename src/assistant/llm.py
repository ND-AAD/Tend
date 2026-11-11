"""Model interfaces (SPEC §6, §7.2, §9) and their Claude implementations.

Code depends only on the three Protocols; tests use scripted fakes. Every model output is parsed
from structured JSON and then audited by code before anything reaches the ledger, so a model
error can drop or hold a claim but cannot write an unchecked one."""
from __future__ import annotations

import json
import os
from typing import Any, Protocol

from . import schema

# -- interfaces --------------------------------------------------------------------------------


class Extractor(Protocol):
    def extract(self, body: str, message: dict, pack: dict) -> list[dict]:
        """Proposals in the SPEC §6.1 format."""


class Resolver(Protocol):
    def resolve(self, mention: dict, excerpt: str, candidates: list[dict], seed: int) -> dict:
        """One vote: {"choice": <candidate id> | "new", "kind": ..., "label": ...}."""


class Judge(Protocol):
    def same(self, a: dict, b: dict, evidence: dict) -> tuple[bool, str]:
        """Whether two Items are one thing, with a one-sentence reason."""


class ModelRefused(RuntimeError):
    pass


# -- JSON schemas for structured output ------------------------------------------------------------

_MENTION = {
    "type": "object", "additionalProperties": False,
    "required": ["text", "resolution", "item_id", "kind", "label", "why"],
    "properties": {
        "text": {"type": "string"},
        "resolution": {"type": "string", "enum": ["existing", "new", "unsure"]},
        "item_id": {"type": "string"},
        "kind": {"type": "string", "enum": list(schema.RESOLVABLE_KINDS)},
        "label": {"type": "string"},
        "why": {"type": "string"},
    },
}

PROPOSAL_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["proposals"],
    "properties": {"proposals": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["kind", "mentions", "subject", "property", "value", "form", "obligated", "party",
                     "deadline", "quote"],
        "properties": {
            "kind": {"type": "string", "enum": ["statement", "commitment"]},
            "mentions": {"type": "array", "items": _MENTION},
            "subject": {"type": "integer"},
            "property": {"type": "string"},
            "value": {"type": ["string", "boolean"]},
            "form": {"type": "string", "enum": ["value", "ask"]},
            "obligated": {"type": "string"},
            "party": {"type": "string"},
            "deadline": {"anyOf": [{"type": "null"}, {
                "type": "object", "additionalProperties": False, "required": ["text", "value"],
                "properties": {"text": {"type": "string"}, "value": {"type": "string"}}}]},
            "quote": {"type": "string"},
        }}}},
}

VOTE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["choice", "kind", "label", "why"],
    "properties": {"choice": {"type": "string"}, "kind": {"type": "string", "enum": list(schema.RESOLVABLE_KINDS)},
                   "label": {"type": "string"}, "why": {"type": "string"}},
}

JUDGE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["same", "reason"],
    "properties": {"same": {"type": "boolean"}, "reason": {"type": "string"}},
}

EXTRACT_SYSTEM = """You read one email for its owner and propose what it establishes, as JSON.

A statement says something is now the case about a thing (a deliverable was delivered, a meeting is
confirmed). A commitment says someone is now expected to do something: the sender promising, or the
sender asking the owner or another recipient. A question asked of someone is a commitment with
form "ask" on a question item, property "answer".

Rules:
- Only propose what the new text of the email says. Ignore quoted replies.
- `quote` is copied exactly from the email and contains the words that establish the proposal.
- Properties must come from the property schema for the subject's kind. If none fits, propose
  nothing for that point.
- `obligated` and `party` are person ids from the message's producer and recipients. For a
  statement, use the producer for both.
- For each mention, look at the context pack. If the mention is an Item in the pack, use
  resolution "existing" and its item_id. If it is plainly new, use "new" with a short label naming
  the thing as its owner would. If you cannot tell, use "unsure". Never invent an item_id.
- A deadline gives the sender's words and an ISO value, YYYY-MM-DD or YYYY-MM-DDTHH:MM, in the
  sender's local time. Add a time only if the sender states one.
- Use empty strings for item_id and deadline null when they do not apply."""

RESOLVE_SYSTEM = """You decide which known Item a phrase in an email refers to, or that it names
something new. Read the excerpt and the candidates. Answer with the candidate id, or "new" with the
kind and a short label. Prefer an existing candidate only when the excerpt and the candidate's
names, thread and recent claims make it the same thing."""

JUDGE_SYSTEM = """Two Items in a personal assistant's store may be one real thing recorded twice.
Read both, with their names, claims and neighbours, and say whether they are the same thing. Be
conservative: say same only when a careful person who saw both threads would agree."""


class _Claude:
    """Shared call path: structured output, explicit effort, server-side fallback on refusal."""

    def __init__(self, model: str, effort: str = "high", client: Any = None, max_tokens: int = 16000) -> None:
        import anthropic  # imported here so the engine and tests need no API key

        self.anthropic = anthropic
        if client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError("ANTHROPIC_API_KEY is not set")
            client = anthropic.Anthropic()
        self.client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens

    def call(self, system: str, user: str, json_schema: dict) -> dict:
        a = self.anthropic
        try:
            r = self.client.beta.messages.create(
                model=self.model, max_tokens=self.max_tokens, system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": json_schema}},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        except a.RateLimitError:
            raise
        except a.APIStatusError as e:
            raise RuntimeError(f"model call failed: {e.status_code}") from e
        except a.APIConnectionError as e:
            raise RuntimeError("model call could not connect") from e
        if r.stop_reason == "refusal":
            raise ModelRefused("the model declined this request")
        if r.stop_reason == "max_tokens":
            raise RuntimeError("model output was cut off at max_tokens")
        text = next(b.text for b in r.content if b.type == "text")
        return json.loads(text)


class ClaudeExtractor(_Claude):
    def extract(self, body: str, message: dict, pack: dict) -> list[dict]:
        user = json.dumps({"message": {k: message[k] for k in ("producer_id", "recipients", "sent_at")},
                           "body": body, "context_pack": pack}, indent=1)
        return self.call(EXTRACT_SYSTEM, user, PROPOSAL_SCHEMA)["proposals"]


class ClaudeResolver(_Claude):
    def resolve(self, mention: dict, excerpt: str, candidates: list[dict], seed: int) -> dict:
        user = json.dumps({"phrase": mention["text"], "proposed_kind": mention.get("kind"),
                           "excerpt": excerpt, "candidates": candidates}, indent=1)
        return self.call(RESOLVE_SYSTEM, user, VOTE_SCHEMA)


class ClaudeJudge(_Claude):
    def same(self, a: dict, b: dict, evidence: dict) -> tuple[bool, str]:
        r = self.call(JUDGE_SYSTEM, json.dumps({"a": a, "b": b, "evidence": evidence}, indent=1, default=str),
                      JUDGE_SCHEMA)
        return bool(r["same"]), r["reason"]
