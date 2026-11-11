"""The three primitives (spec §2) and the model's reserved vocabulary (2.1.6, 2.4.4).

Records are plain data. An Assertion is identified only by its triple (2.3.2); what kind of
record it is (statement, expectation or act) follows from its context's role and its
reserved members, never from any Item's ``kind`` (2.1.6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

Triple = tuple[str, str, str]

# 2.4.4: the defined @action values.
ACTIONS = frozenset({"establish", "reaffirm", "withdraw", "review", "detect", "reconcile", "reinterpret",
                     "correct", "ignore", "disconnect", "reconnect", "begin", "end"})
# 7.6.4, 7.6.5: the acts that record the beginning and the end of one period of a unit of work.
TRANSITION_ACTIONS = frozenset({"begin", "end"})
SUPPORT_ACTIONS = frozenset({"establish", "reaffirm"})
# 8.4.1: acts that may carry @effective: these, and a reconciliation with outcome `adopt_policy`
# (``has_effective``). A normalization (``reinterpret``, 7.3.8) is an event in the work, like an
# `adopt_policy` (7.7.3): it takes effect when it is made.
EFFECTIVE_ACTIONS = frozenset({"establish", "reaffirm", "withdraw", "review", "ignore", "reinterpret"})
# 7.4.1, 7.3, 8.3.1: the outcomes defined for each act that has one.
OUTCOMES = {
    "review": frozenset({"change_required", "no_change"}),
    "reconcile": frozenset({"split", "continuous", "boundary", "reconstructed", "revise", "adopt_policy"}),
    "correct": frozenset({"replace", "erroneous", "relocated"}),
}
# 6.7.9: acts that are never withdrawn.
NEVER_WITHDRAWN_ACTIONS = frozenset({"detect", "reconcile", "reinterpret", "correct", "withdraw", "disconnect",
                                     "reconnect", "begin", "end"})
# 4.1.1: the context roles.
CONTEXT_ROLES = frozenset({"event", "milestone", "phase", "expectation"})
TIMING_TYPES = frozenset({"at", "during", "by", "any"})
# 5.6.2: property transitions.
TRANSITIONS = frozenset({"introduced", "changed", "cleared", "withdrawn", "reasserted", "unchanged"})
STORY_KINDS = frozenset({"conflict", "change"})

# 2.4.4: every defined member, and where it may appear. Keys are the members; values name
# the record shapes that admit them (checked in validate.py).
DEFINED_VALUE_MEMBERS = frozenset({
    "@ref", "@action", "@targets", "@basis", "@party", "@outcome", "@corrected", "@effective",
    "@establishes", "@reaffirms", "@frame", "@story", "@transitions", "@relates_to",
    "@successor", "@representative", "@until", "@producer", "@agent", "@distribution",
    "@issuance", "@published", "@eligible", "@ask", "@suggested", "@after",
    "@context", "@eligibility", "@period", "@interpretation",
})
DEFINITION_MEMBERS = frozenset({"@context", "@eligibility"})
# 10.4.4: the extension the reference declares (conformance README §5, "Declared extension"):
# a list of Item id strings, a reference form other than 2.4.1-2.4.2. A record carrying it
# has downstream impact by definition (8.5.2(e)).
DECLARED_REFERENCE_EXTENSION = "@x-fixture-refs"


def carries_member(value: Any, member: str) -> bool:
    """True when an object at any depth of ``value`` has the member ``member``."""
    if isinstance(value, dict):
        return member in value or any(carries_member(v, member) for v in value.values())
    if isinstance(value, list):
        return any(carries_member(v, member) for v in value)
    return False


@dataclass(frozen=True)
class Item:
    """An Item (2.1.2). ``definition`` is fixed at creation; reads use the corrected Item
    (8.3.8)."""

    id: str
    kind: str
    label: str | None
    definition: dict

    @property
    def context(self) -> dict | None:
        c = self.definition.get("@context")
        return c if isinstance(c, dict) else None

    @property
    def role(self) -> str | None:
        c = self.context
        return c.get("role") if c else None

    @property
    def is_eligibility(self) -> bool:
        return self.definition.get("@eligibility") is True


@dataclass
class Rec:
    """An Assertion (2.3.1) as it stands in an account: ``values`` is the content that the
    account uses (after correction, 8.3.3); ``recorded`` is the content as written."""

    triple: Triple
    values: dict
    recorded: dict
    recorded_at: Any = None
    recorded_by: str | None = None
    kind: str = "statement"  # "statement" | "expectation" | "act"
    corrected_by: Triple | None = None  # the applicable `replace` correction, if any
    notes: dict = field(default_factory=dict)

    @property
    def item(self) -> str:
        return self.triple[0]

    @property
    def context(self) -> str:
        return self.triple[1]

    @property
    def source(self) -> str:
        return self.triple[2]

    @property
    def action(self) -> str | None:
        a = self.values.get("@action")
        return a if isinstance(a, str) else None

    @property
    def is_act(self) -> bool:
        return self.kind == "act"

    @property
    def is_extension_act(self) -> bool:
        return self.is_act and self.action not in ACTIONS

    @property
    def is_transition_act(self) -> bool:
        """A begin act, an end act or a ``revise`` reconciliation (7.6.4, 7.6.5, 7.6.10)."""
        return is_transition_record(self.values)


def has_effective(values: dict) -> bool:
    """8.4.1: an act that takes effect at ``@effective`` when it carries one: establish,
    reaffirm, withdraw, review, ignore, a normalization (``reinterpret``) and a reconciliation
    with outcome ``adopt_policy``."""
    a = values.get("@action")
    return a in EFFECTIVE_ACTIONS or (a == "reconcile" and values.get("@outcome") == "adopt_policy")


def act_targets(values: dict) -> list[dict]:
    t = values.get("@targets")
    return [r for r in t if isinstance(r, dict) and "@ref" in r] if isinstance(t, list) else []


def is_transition_record(values: dict) -> bool:
    """A begin act, an end act or a ``revise`` reconciliation (7.6.4, 7.6.5, 7.6.10): the
    recorded interpretations that are never withdrawn, corrected or removed (6.7.9, 8.5.2)."""
    a = values.get("@action")
    return a in TRANSITION_ACTIONS or (a == "reconcile" and values.get("@outcome") == "revise")


def ref_list(values: dict, key: str) -> list[dict]:
    t = values.get(key)
    return [r for r in t if isinstance(r, dict) and "@ref" in r] if isinstance(t, list) else []


def record_kind(values: dict, context_role: str | None) -> str:
    """Statement, expectation or act (2.3.1, 4.1, 6.1.1). An Assertion carrying ``@action``
    is an act; one at an expectation context is an expectation; anything else is a
    statement (I-6)."""
    if "@action" in values:
        return "act"
    if context_role == "expectation":
        return "expectation"
    return "statement"


# 2.4.4: the records that may carry @producer, @agent, @distribution and @issuance are
# recognised by their coordinates and members, never by kind (2.1.6). Each predicate takes
# the record's values and triple, the role of its context Item and the role of its subject
# Item (both as corrected, 8.3.8).


def is_self_description(values: dict, triple: Triple, ctx_role: str | None) -> bool:
    """A statement whose ``item`` and ``source`` are the same Item (3.1.2)."""
    return record_kind(values, ctx_role) == "statement" and triple[0] == triple[2]


def is_publication(values: dict, triple: Triple, ctx_role: str | None) -> bool:
    """A statement whose ``item`` and ``context`` are the same milestone and which carries
    ``@published`` (4.4.1)."""
    return (record_kind(values, ctx_role) == "statement" and triple[0] == triple[1]
            and ctx_role == "milestone" and "@published" in values)


def is_later_distribution(values: dict, triple: Triple, ctx_role: str | None, subject_role: str | None) -> bool:
    """A statement at an event context that carries ``@distribution`` and either is about a
    milestone or names ``@issuance`` (4.4.1)."""
    return (record_kind(values, ctx_role) == "statement" and ctx_role == "event" and "@distribution" in values
            and (subject_role == "milestone" or "@issuance" in values))


def is_distribution_record(values: dict, triple: Triple, ctx_role: str | None, subject_role: str | None) -> bool:
    """A self-description, a milestone publication or a later distribution: the records
    that carry attribution and distribution lists (2.4.4, 4.4.2)."""
    return (is_self_description(values, triple, ctx_role) or is_publication(values, triple, ctx_role)
            or is_later_distribution(values, triple, ctx_role, subject_role))
