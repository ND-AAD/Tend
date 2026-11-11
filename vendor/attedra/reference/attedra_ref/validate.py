"""Validation on write (spec 10.2) and the shapes of reserved members (2.4.4).

Every failure raises ``WriteError`` with the code of conformance README §6: the 10.2 rule
identifier, ``duplicate_key`` or ``number_out_of_range`` (both reported under 10.2.4), or
``occupied`` (10.2.1, raised by the write path).

Where a rule admits two readings the code says which one it takes:

* A missing member that a role requires is 10.2.3; an instant that is present but not in a
  4.2.1 form is 10.2.4, wherever it appears.
* A ``@targets``, ``@basis``, ``@establishes`` or ``@reaffirms`` that is not a list of
  references, and an ``@after``, ``@relates_to``, ``@successor``, ``@representative`` or
  ``@issuance`` that is not a single reference, is 10.2.2 as the rule states; a reference
  object of an undefined form is 10.2.4.
* A normalization (``@action: "reinterpret"``, 7.3.8) whose ``@targets`` is a list of references
  but not exactly one Item reference is 10.2.6; one whose ``@interpretation`` is missing or is
  neither ``null`` nor ``{"name", "version"}`` is 10.2.4; one whose well-formed
  ``@interpretation`` names an interpretation the reference does not have, and a ``replace``
  correction whose ``@corrected`` values are such a normalization, is 10.2.9, since recording it
  requires maintenance the reference cannot perform (7.3.8, 10.3; README §6, item 8). An
  identical write of one already recorded is a replay and never reaches validation (8.1.2).
* An extension act (an ``@action`` string this specification does not define, 10.4.1) is an
  act for 2.4.4: it may carry the members of every act (``@targets``, ``@basis``,
  ``@party``), ``@issuance`` (any act, 3.2.1), ``@after`` (any Assertion) and undefined
  members. Any other defined member is invalid on it: ``@effective`` under 10.2.7, the rest
  under 10.2.4.
* ``@producer``, ``@agent``, ``@distribution`` and ``@issuance`` are placed by the structural
  definitions of 2.4.4: a self-description, a milestone publication or a later distribution,
  and ``@issuance`` also on any act (``model.is_distribution_record``).
"""
from __future__ import annotations

from typing import Any, Protocol

from . import instants as T
from .errors import WriteError
from .interpretations import get_interpretation
from .model import (ACTIONS, CONTEXT_ROLES, DEFINED_VALUE_MEMBERS, DEFINITION_MEMBERS,
                    NEVER_WITHDRAWN_ACTIONS, OUTCOMES, STORY_KINDS, TIMING_TYPES, TRANSITIONS, Item, Triple,
                    has_effective, is_distribution_record, is_later_distribution, is_transition_record)
from .values import check_numbers, is_ref, iter_refs, ref_triple

LIST_REF_MEMBERS = ("@targets", "@basis", "@establishes", "@reaffirms")
SINGLE_REF_MEMBERS = ("@after", "@relates_to", "@successor", "@representative", "@issuance")


class Resolver(Protocol):
    """What validation needs to know about the store."""

    def item(self, item_id: str) -> Item | None: ...          # corrected Item, if it exists
    def item_exists(self, item_id: str) -> bool: ...
    def assertion_exists(self, triple: Triple) -> bool: ...
    def assertion_values(self, triple: Triple) -> dict | None: ...   # values in the account
    def connection_exists(self, pair: tuple[str, str]) -> bool: ...
    def connection_active_at(self, pair: tuple[str, str], at: T.Instant) -> bool | None: ...
    def context_instant(self, ctx_id: str) -> T.Instant | None: ...
    def story_kind(self, story_id: str) -> str | None: ...
    def schedule_ordinals(self, schedule_id: str, exclude: str | None) -> dict[str, Any]: ...


def fail(code: str, msg: str):
    raise WriteError(code, msg)


# ---------------------------------------------------------------------------------------
# references


def check_ref_shape(ref: dict, where: str) -> None:
    """A reference object has one of the forms of 2.4.1-2.4.3 (10.2.4)."""
    kind = ref.get("@ref")
    if kind == "assertion":
        for k in ("item", "context", "source"):
            if not isinstance(ref.get(k), str):
                fail("10.2.4", f"{where}: an Assertion reference needs string {k!r} (2.4.1)")
        if "property" in ref and not isinstance(ref["property"], str):
            fail("10.2.4", f"{where}: a property selector is a property name (2.4.3)")
        if "support" in ref:
            sup = ref["support"]
            if not (is_ref(sup) and sup.get("@ref") == "assertion"):
                fail("10.2.4", f"{where}: a support selector is an expectation reference (2.4.3)")
            check_ref_shape(sup, where)
    elif kind == "item":
        if not isinstance(ref.get("id"), str):
            fail("10.2.4", f"{where}: an Item reference needs a string id (2.4.2)")
    elif kind == "artifact":
        if not isinstance(ref.get("id"), str):
            fail("10.2.4", f"{where}: an artifact reference needs an id (2.4.2)")
    elif kind == "connection":
        if not (isinstance(ref.get("from"), str) and isinstance(ref.get("to"), str)):
            fail("10.2.4", f"{where}: a connection reference needs from and to (2.4.2)")
    else:
        fail("10.2.4", f"{where}: {kind!r} is not a defined reference form (2.4.1-2.4.2)")


def check_refs_resolve(value: Any, r: Resolver, where: str) -> None:
    """Every Item, Assertion or Connection reference resolves; artifact references are not
    resolved by the store (10.2.2)."""
    for ref in iter_refs(value):
        check_ref_shape(ref, where)
        kind = ref["@ref"]
        if kind == "item" and not r.item_exists(ref["id"]):
            fail("10.2.2", f"{where}: Item {ref['id']!r} does not resolve")
        if kind == "assertion" and not r.assertion_exists(ref_triple(ref)):
            fail("10.2.2", f"{where}: Assertion {ref['item']}|{ref['context']}|{ref['source']} does not resolve")
        if kind == "connection" and not r.connection_exists((ref["from"], ref["to"])):
            fail("10.2.2", f"{where}: Connection {ref['from']}->{ref['to']} does not resolve")


def _item_ref(v) -> bool:
    return is_ref(v) and v.get("@ref") == "item" and isinstance(v.get("id"), str)


def _assertion_ref(v) -> bool:
    return is_ref(v) and v.get("@ref") == "assertion"


def _instant_or_fail(v, where: str) -> T.Instant:
    i = T.parse_instant(v)
    if i is None:
        fail("10.2.4", f"{where}: {v!r} is not an instant in a 4.2.1 form")
    return i


# ---------------------------------------------------------------------------------------
# Item definitions (10.2.3, 8.3.8)


def validate_definition(item_id: str, definition: Any, r: Resolver, code_310_2_3: str = "10.2.3") -> None:
    """Validate an Item definition. Context definitions need a valid role and the members
    that role requires (4.1.1, 10.2.3). ``code_310_2_3`` lets a corrected Item report its
    failure as 10.2.5 (8.3.8)."""
    if not isinstance(definition, dict):
        fail("10.2.4", f"definition of {item_id!r} must be an object (2.1.2)")
    check_numbers(definition)
    for key in definition:
        if key.startswith("@") and key in DEFINED_VALUE_MEMBERS and key not in DEFINITION_MEMBERS:
            fail("10.2.4", f"{key} is not allowed in an Item definition (2.4.4)")
    if "@eligibility" in definition and not isinstance(definition["@eligibility"], bool):
        fail("10.2.4", "@eligibility is a boolean (3.3.2)")
    check_refs_resolve(definition, r, f"definition of {item_id!r}")
    if "@context" in definition:
        validate_context(item_id, definition["@context"], r, code_310_2_3)


def validate_context(item_id: str, ctx: Any, r: Resolver, code: str) -> None:
    if not isinstance(ctx, dict):
        fail(code, f"@context of {item_id!r} must be an object (4.1.1)")
    role = ctx.get("role")
    if role not in CONTEXT_ROLES:
        fail(code, f"{role!r} is not a context role (4.1.1)")
    if role == "event":
        if "at" not in ctx:
            fail(code, "an event context needs 'at' (4.1.1)")
        _instant_or_fail(ctx["at"], "event 'at'")
    elif role == "milestone":
        if not _item_ref(ctx.get("schedule")):
            fail(code, "a milestone needs a schedule reference (4.1.1, 10.2.3)")
        if not isinstance(ctx.get("stage"), str):
            fail(code, "a milestone needs a text 'stage' (4.1.1)")
        o = ctx.get("ordinal")
        if isinstance(o, bool) or not isinstance(o, int):
            fail(code, "a milestone needs an integer 'ordinal' (4.1.1)")
        others = r.schedule_ordinals(ctx["schedule"]["id"], exclude=item_id)
        if any(v == o for v in others.values()):
            fail(code, f"ordinal {o} duplicates another milestone of schedule {ctx['schedule']['id']!r} (4.3.2, 10.2.3)")
    elif role == "phase":
        if not _item_ref(ctx.get("schedule")):
            fail(code, "a phase needs a schedule reference (4.1.1)")
        for k in ("starts", "ends"):
            if k not in ctx:
                fail(code, f"a phase needs {k!r} (4.1.1)")
            v = ctx[k]
            if isinstance(v, str):
                _instant_or_fail(v, f"phase {k!r}")
            elif _item_ref(v):
                it = r.item(v["id"])
                if it is None or it.role != "milestone":
                    fail(code, f"phase {k!r} must be a milestone reference or an instant (4.1.1)")
            else:
                fail(code, f"phase {k!r} must be a milestone reference or an instant (4.1.1)")
    elif role == "expectation":
        timing = ctx.get("timing")
        if not isinstance(timing, dict) or timing.get("type") not in TIMING_TYPES:
            fail(code, "an expectation context needs a valid timing (6.2.1, 10.2.3)")
        tt = timing["type"]
        if tt == "at":
            m = timing.get("milestone")
            it = r.item(m["id"]) if _item_ref(m) else None
            if it is None or it.role != "milestone":
                fail(code, "'at' timing needs a milestone reference (6.2.1)")
        elif tt == "during":
            p = timing.get("phase")
            it = r.item(p["id"]) if _item_ref(p) else None
            if it is None or it.role != "phase":
                fail(code, "'during' timing needs a phase reference (6.2.1)")
        elif tt == "by":
            has_i, has_m = "instant" in timing, "milestone" in timing
            if has_i == has_m:
                fail(code, "'by' timing needs exactly one of 'instant' or 'milestone' (6.2.1)")
            if has_i:
                _instant_or_fail(timing["instant"], "'by' timing instant")
            else:
                it = r.item(timing["milestone"]["id"]) if _item_ref(timing["milestone"]) else None
                if it is None or it.role != "milestone":
                    fail(code, "'by' timing milestone must reference a milestone (6.2.1)")
        if "schedule" in ctx and ctx["schedule"] is not None and not _item_ref(ctx["schedule"]):
            fail(code, "an expectation context's schedule is an Item reference (6.2.4)")
        if "fresh" in ctx and not isinstance(ctx["fresh"], bool):
            fail(code, "'fresh' is a boolean (6.2.2)")
        # 4.1.1, 7.6.13, 7.7.2: an expectation context may name its interpretation and its
        # ending policy, each as {"name", "version"}
        for key in ("interpretation", "policy"):
            v = ctx.get(key)
            if v is None:
                continue
            if not (isinstance(v, dict) and set(v) == {"name", "version"} and isinstance(v["name"], str)
                    and isinstance(v["version"], str)):
                fail(code, f"an expectation context's {key!r} is {{\"name\", \"version\"}} (7.6.13, 7.7.2)")


# ---------------------------------------------------------------------------------------
# Assertion values (2.4.4, 10.2.2-10.2.8)


class Shape:
    """What a record is, for deciding where a defined member is allowed (2.4.4)."""

    def __init__(self, values: dict, triple: Triple, r: Resolver) -> None:
        self.values = values
        self.triple = triple
        self.action = values.get("@action")
        self.is_act = "@action" in values
        self.extension = self.is_act and self.action not in ACTIONS
        ctx = r.item(triple[1])
        self.ctx_role = ctx.role if ctx else None
        self.is_expectation = not self.is_act and self.ctx_role == "expectation"
        self.is_statement = not self.is_act and not self.is_expectation
        subj = r.item(triple[0])
        self.subject_is_eligibility = bool(subj and subj.is_eligibility)
        subject_role = subj.role if subj else None
        # 2.4.4: the records that carry attribution and distribution lists
        self.distribution_record = is_distribution_record(values, triple, self.ctx_role, subject_role)
        self.later_distribution = is_later_distribution(values, triple, self.ctx_role, subject_role)


def _allowed(key: str, s: Shape) -> str | None:
    """None when allowed; otherwise the code to fail with."""
    a = s.action
    if key == "@action":
        return None
    if key in ("@targets", "@basis", "@party"):
        return None if s.is_act else "10.2.4"
    if key == "@after":
        return None
    if key == "@issuance":
        # 2.4.4: a later distribution of a communication's issuance; any act (3.2.1)
        return None if (s.is_act or s.later_distribution) else "10.2.4"
    if key == "@effective":
        if not s.is_act:
            return "10.2.4"
        # 8.4.1: establish, reaffirm, withdraw, review, ignore, normalization, and a
        # reconciliation with outcome `adopt_policy`
        return None if has_effective(s.values) else "10.2.7"
    if s.extension:
        # 10.4.1: a member that 2.4.4 allows only on particular actions is invalid on an
        # extension act; an extension that needs another meaning uses an undefined member
        return "10.2.4"
    if key == "@outcome":
        return None if a in OUTCOMES else "10.2.4"
    if key == "@corrected":
        return None if a == "correct" else "10.2.4"
    if key in ("@establishes", "@reaffirms"):
        return None if a == "review" else "10.2.4"
    if key == "@frame":
        return None if a in ("detect", "review", "reconcile") else "10.2.4"
    if key == "@period":
        # 2.4.4: begin, end, and a reconciliation with outcome `revise`
        if a in ("begin", "end") or (a == "reconcile" and s.values.get("@outcome") == "revise"):
            return None
        return "10.2.4"
    if key in ("@story", "@relates_to"):
        return None if a == "detect" else "10.2.4"
    if key == "@transitions":
        story = s.values.get("@story")
        if a == "detect" and isinstance(story, dict) and story.get("kind") == "change":
            return None
        if a == "reconcile" and s.values.get("@outcome") == "reconstructed":
            return None
        return "10.2.4"
    if key in ("@successor", "@representative"):
        return None if a == "reconcile" else "10.2.4"
    if key == "@until":
        return None if a == "ignore" else "10.2.4"
    if key == "@interpretation":
        return None if a == "reinterpret" else "10.2.4"  # 2.4.4, 7.3.8
    if key in ("@producer", "@agent", "@distribution"):
        return None if s.distribution_record else "10.2.4"
    if key == "@published":
        ok = s.is_statement and s.triple[0] == s.triple[1] and s.ctx_role == "milestone"
        return None if ok else "10.2.4"
    if key == "@eligible":
        return None if (s.is_statement and s.subject_is_eligibility) else "10.2.4"
    return "10.2.4"  # @ref, @ask, @suggested, @context, @eligibility at the top of values


def _check_member_shape(key: str, v: Any, s: Shape) -> None:
    where = key
    if key == "@action":
        if not isinstance(v, str):
            fail("10.2.4", "@action is a string (2.4.4)")
    elif key in LIST_REF_MEMBERS:
        if not isinstance(v, list) or not all(is_ref(x) for x in v):
            fail("10.2.2", f"{key} must be a list of references (10.2.2)")
        for x in v:
            check_ref_shape(x, where)
        if key in ("@establishes", "@reaffirms") and not all(_assertion_ref(x) for x in v):
            fail("10.2.4", f"{key} lists exact expectation references (7.4.1)")
    elif key in SINGLE_REF_MEMBERS:
        if not is_ref(v):
            fail("10.2.2", f"{key} must be a single reference (10.2.2)")
        check_ref_shape(v, where)
        if key in ("@after", "@relates_to") and not _assertion_ref(v):
            fail("10.2.4", f"{key} is an exact Assertion reference (4.5.2, 7.3.1)")
        if key in ("@successor", "@representative", "@issuance") and not _item_ref(v):
            fail("10.2.4", f"{key} is an Item reference (7.3.3, 7.3.4, 3.2.1)")
    elif key == "@party":
        if not _item_ref(v):
            fail("10.2.4", "@party is an Item reference (3.2.1)")
    elif key == "@outcome":
        if v not in OUTCOMES.get(s.action, ()):
            fail("10.2.4", f"{v!r} is not an outcome of {s.action} (7.3, 7.4.1, 8.3.1)")
    elif key in ("@effective", "@until", "@published"):
        _instant_or_fail(v, key)
    elif key == "@frame":
        if not isinstance(v, dict):
            fail("10.2.4", "@frame is an object (5.5.5)")
        cut = v.get("cutoff")
        if isinstance(cut, str) and cut != "now":
            _instant_or_fail(cut, "@frame cutoff")
        elif cut is not None and not isinstance(cut, str) and not _item_ref(cut):
            fail("10.2.4", "@frame cutoff is an instant, a milestone reference or \"now\" (4.6.1)")
        interp = v.get("interpretation")
        if interp is not None and not isinstance(interp, str):
            fail("10.2.4", "@frame interpretation is a name or null (5.5.5)")
        persp = v.get("perspective")
        if persp is not None and persp != "record" and not _item_ref(persp):
            fail("10.2.4", "@frame perspective is \"record\" or a participant reference (4.6.1)")
        # 2.4.4, 5.5.5: `normalization`, beside a null interpretation, lists the normalizations
        # of an ambiguous interpretation in force. Only its shape is checked: validation never
        # compares a recorded frame with the interpretation in force (7.2.4)
        if "normalization" in v:
            n = v["normalization"]
            refs = n.get("ambiguous") if isinstance(n, dict) and set(n) == {"ambiguous"} else None
            if not (isinstance(refs, list) and refs and all(_assertion_ref(x) and "property" not in x
                                                          and "support" not in x for x in refs)):
                fail("10.2.4", "@frame normalization is {\"ambiguous\": [exact Assertion references]} (5.5.5)")
            if interp is not None or v.get("interpretation_version") is not None:
                fail("10.2.4", "@frame normalization appears only beside a null interpretation (2.4.4, 5.5.5)")
        # 2.4.4, 5.5.5, 7.7.2: `policy` and `policy_version` name an ending policy, on a
        # detection's or a reconciliation's @frame only
        if "policy" in v or "policy_version" in v:
            if s.action not in ("detect", "reconcile"):
                fail("10.2.4", "@frame keys policy and policy_version appear on detect and reconcile only (2.4.4)")
            for k in ("policy", "policy_version"):
                if v.get(k) is not None and not isinstance(v[k], str):
                    fail("10.2.4", f"@frame {k} is a string or null (7.7.2)")
            if s.values.get("@outcome") != "adopt_policy" and (v.get("policy") is None) != (v.get("policy_version") is None):
                fail("10.2.4", "@frame names a policy by both policy and policy_version, or neither (7.7.2)")
    elif key == "@period":
        _check_period_instants(v)
    elif key == "@interpretation":
        # 7.3.8: the interpretation a normalization names, as {"name", "version"}, or null for
        # literal comparison (5.5.1)
        if v is not None and not (isinstance(v, dict) and set(v) == {"name", "version"}
                                  and isinstance(v["name"], str) and isinstance(v["version"], str)):
            fail("10.2.4", "@interpretation is null or {\"name\", \"version\"} (7.3.8)")
    elif key == "@story":
        if not isinstance(v, dict) or v.get("kind") not in STORY_KINDS or not _item_ref(v.get("subject")):
            fail("10.2.4", "@story names its kind and an Item subject (7.2.1)")
        if v["kind"] == "conflict" and not isinstance(v.get("property"), str):
            fail("10.2.4", "a conflict story names its property (7.2.1)")
    elif key == "@transitions":
        if not isinstance(v, list):
            fail("10.2.4", "@transitions is a list (7.2.3)")
        for t in v:
            if not (isinstance(t, dict) and isinstance(t.get("property"), str) and t.get("transition") in TRANSITIONS):
                fail("10.2.4", "each transition gives a property and a 5.6.2 transition (7.2.3)")
            for k in ("prior", "new"):
                if t.get(k) is not None and not _assertion_ref(t.get(k)):
                    fail("10.2.4", f"a transition's {k!r} is an exact Assertion reference (7.2.3)")
                if t.get(k) is not None:
                    check_ref_shape(t[k], key)
        if s.action == "detect":
            # 7.2.3: every entry's `new` references the same Assertion, the revised Assertion
            # of the issuance; entries naming different ones are a wrong shape (10.2.4)
            news = {ref_triple(t["new"]) for t in v if _assertion_ref(t.get("new"))}
            if len(news) > 1:
                fail("10.2.4", "a change-story detection's @transitions name different `new` Assertions (7.2.3)")
    elif key == "@producer":
        if not _item_ref(v):
            fail("10.2.4", "@producer is an Item reference (3.1.2)")
    elif key in ("@agent", "@distribution"):
        if not isinstance(v, list) or not all(_item_ref(x) for x in v):
            fail("10.2.4", f"{key} is a list of Item references (3.1.2, 4.4)")
    elif key == "@eligible":
        if not isinstance(v, dict) or not _item_ref(v.get("party")):
            fail("10.2.4", "@eligible names a party (3.3.2)")
        if "agents" in v and (not isinstance(v["agents"], list) or not all(_item_ref(x) for x in v["agents"])):
            fail("10.2.4", "@eligible agents is a list of Item references (3.3.2)")


def _check_period_instants(v: Any) -> None:
    """10.2.4 (README §6, precedence 1): an `at` inside @period that is present but not an
    instant in a 4.2.1 form. Every other defect of the form is 10.2.9 (7.6.6)."""
    if isinstance(v, list):
        for x in v:
            _check_period_instants(x)
        return
    if not isinstance(v, dict) or "@ref" in v:
        return
    if v.get("at") is not None:
        _instant_or_fail(v["at"], "@period at")
    for k, x in v.items():
        if k in ("ambiguous",):
            _check_period_instants(x)


def _check_nested(value: Any, where: str, allow_ask: bool) -> None:
    """Inside a property value only references, extensions and (at the top of an
    expectation's property) the information-request form are allowed (2.4.4, 6.4.1)."""
    if isinstance(value, list):
        for x in value:
            _check_nested(x, where, False)
        return
    if not isinstance(value, dict):
        return
    if "@ref" in value:
        check_ref_shape(value, where)
        return
    keys = set(value)
    if "@ask" in keys or "@suggested" in keys:
        if not allow_ask:
            fail("10.2.4", f"{where}: @ask and @suggested appear only as an expectation's property value (6.4.1)")
        if value.get("@ask") is not True or not keys <= {"@ask", "@suggested"}:
            fail("10.2.4", f"{where}: an information request is {{\"@ask\": true}} with an optional @suggested (6.4.1)")
        return
    for k, v in value.items():
        if k.startswith("@") and k in DEFINED_VALUE_MEMBERS:
            fail("10.2.4", f"{where}: {k} is not allowed inside a property value (2.4.4)")
        _check_nested(v, f"{where}.{k}", False)


def validate_values(values: Any, triple: Triple, r: Resolver, nested_corrected: bool = False) -> Shape:
    """Validate the reserved members and references of an Assertion's values."""
    if not isinstance(values, dict):
        fail("10.2.4", "values must be an object (2.3.1)")
    s = Shape(values, triple, r)
    for key, v in values.items():
        if key.startswith("@"):
            if key not in DEFINED_VALUE_MEMBERS:
                continue  # an extension member (10.4)
            code = _allowed(key, s)
            if code:
                fail(code, f"{key} is not allowed on this record (2.4.4)")
            _check_member_shape(key, v, s)
            if key in ("@frame", "@story", "@eligible", "@transitions", "@period", "@interpretation"):
                _check_defined_object(v, key)
        else:
            _check_nested(v, key, allow_ask=s.is_expectation)
    if s.is_act and not s.extension:
        _check_act_requirements(s)
    if not nested_corrected:
        check_refs_resolve(values, r, "values")
    return s


def _check_defined_object(v: Any, key: str) -> None:
    """The keys inside a defined member's object are defined by its rule: they are not
    otherwise @-prefixed, except for references (2.4.4)."""
    if isinstance(v, list):
        for x in v:
            _check_defined_object(x, key)
        return
    if not isinstance(v, dict) or "@ref" in v:
        return
    for k, x in v.items():
        if k.startswith("@") and k in DEFINED_VALUE_MEMBERS:
            fail("10.2.4", f"{k} is not allowed inside {key} (2.4.4)")
        _check_defined_object(x, key)


def _check_act_requirements(s: Shape) -> None:
    a, v = s.action, s.values
    if a in ("review", "reconcile", "correct") and "@outcome" not in v:
        fail("10.2.4", f"a {a} carries an @outcome (7.3, 7.4.1, 8.3.1)")
    if a == "detect" and "@story" not in v:
        fail("10.2.4", "a detection carries @story (7.2.1)")
    if a == "reinterpret" and "@interpretation" not in v:
        fail("10.2.4", "a normalization carries @interpretation (7.3.8, 10.2.4)")


def validate_act(values: dict, triple: Triple, r: Resolver, occurrence: T.Instant | None) -> None:
    """Act rules 10.2.5-10.2.8. The 10.2.9 rules for begin and end acts, `revise` and
    `adopt_policy` are checked in transitions.py, before these (README §6, precedence 6)."""
    a = values.get("@action")
    targets = values.get("@targets")
    if a in ("withdraw", "review", "reconcile", "ignore") and not targets:
        fail("10.2.6", f"a {a} needs a non-empty target list (10.2.6)")
    if a == "reinterpret":
        # 7.3.8, 10.2.6: exactly one target, an Item reference naming the scope Item
        if not (isinstance(targets, list) and len(targets) == 1 and _item_ref(targets[0])):
            fail("10.2.6", "a normalization has exactly one target, an Item reference naming a scope Item "
                           "(7.3.8, 10.2.6)")
        _check_normalization_available(values)
    if a == "correct":
        _validate_correction(values, triple, r)
    if a == "withdraw":
        for t in targets:
            _check_withdrawable(t, r)
    if a == "review" and values.get("@outcome") == "change_required":
        if not values.get("@establishes") and not values.get("@reaffirms"):
            for t in targets:
                story = _story_of_target(t, r)
                if story and r.story_kind(story) == "change":
                    fail("10.2.6", "a change_required review of a change story names the expectation it "
                                   "establishes or reaffirms (7.2.7)")
    if "@effective" in values and has_effective(values) and occurrence is not None:
        eff = T.parse_instant(values["@effective"])
        if eff is not None and T.before(eff, occurrence) is True:
            fail("10.2.7", "@effective precedes the act's occurrence time (8.4.1)")
    if a in ("disconnect", "reconnect"):
        conns = [t for t in (targets or []) if is_ref(t) and t.get("@ref") == "connection"]
        if not conns:
            fail("10.2.4", f"a {a} targets a connection reference (8.6.2)")
        for t in conns:
            pair = (t["from"], t["to"])
            if occurrence is None:
                continue
            active = r.connection_active_at(pair, occurrence)
            if a == "disconnect" and active is not True:
                fail("10.2.8", f"{pair[0]}->{pair[1]} is not active at the act's occurrence time (8.6.6)")
            if a == "reconnect" and active is not False:
                fail("10.2.8", f"{pair[0]}->{pair[1]} is not disconnected at the act's occurrence time (8.6.6)")


def _check_normalization_available(values: dict) -> None:
    """10.2.9, 7.3.8: an implementation records a normalization only when it has the
    interpretation the normalization names, so that it can perform the maintenance the
    normalization requires; `null` names literal comparison, which every implementation has."""
    i = values.get("@interpretation")
    if not (isinstance(i, dict) and isinstance(i.get("name"), str)):
        return
    got = get_interpretation(i["name"])
    if got is None or got.version != i.get("version"):
        fail("10.2.9", f"the normalization names the interpretation {i['name']!r} version {i.get('version')!r}, "
                       "which this implementation does not have (7.3.8, 10.2.9)")


def _story_of_target(t: dict, r: Resolver) -> str | None:
    if t.get("@ref") == "item":
        return t["id"]
    if t.get("@ref") == "assertion":
        v = r.assertion_values(ref_triple(t))
        if v and v.get("@action") == "detect":
            return t["item"]
    return None


def _check_withdrawable(t: dict, r: Resolver) -> None:
    """6.7.9: detections, reconciliations, corrections, withdrawals, disconnect and
    reconnect acts, and publication, distribution and self-description Assertions (recognised
    structurally, 2.4.4) are never withdrawn (10.2.6). Extension acts may be withdrawn."""
    if t.get("@ref") != "assertion":
        return
    triple = ref_triple(t)
    v = r.assertion_values(triple)
    if v is None:
        return
    a = v.get("@action")
    if a in NEVER_WITHDRAWN_ACTIONS:
        fail("10.2.6", f"a {a} act is never withdrawn (6.7.9)")
    if a is None:
        ctx, subj = r.item(triple[1]), r.item(triple[0])
        if is_distribution_record(v, triple, ctx.role if ctx else None, subj.role if subj else None):
            fail("10.2.6", "publication, distribution and self-description Assertions are never withdrawn (6.7.9)")


def _validate_correction(values: dict, triple: Triple, r: Resolver) -> None:
    targets = values.get("@targets")
    if not isinstance(targets, list) or len(targets) != 1:
        fail("10.2.5", "a correction has exactly one target (8.3.1)")
    t = targets[0]
    kind = t.get("@ref")
    outcome = values.get("@outcome")
    corrected = values.get("@corrected")
    if kind == "assertion":
        if "property" in t or "support" in t:
            fail("10.2.5", "a correction targets one whole Assertion (8.3.1)")
        target_values = r.assertion_values(ref_triple(t))
        if target_values is not None and is_transition_record(target_values):
            # 6.7.9, 7.6.8: a begin or end act, or a revise, is never corrected; a transition
            # that changes is revised (7.6.10)
            fail("10.2.9", "a begin act, an end act or a revise is never corrected (7.6.8, 10.2.9)")
        if outcome == "replace":
            if not isinstance(corrected, dict):
                fail("10.2.5", "a replace carries the complete corrected values in @corrected (8.3.1)")
            validate_values(corrected, ref_triple(t), r, nested_corrected=True)
            if corrected.get("@action") == "reinterpret":
                _check_normalization_available(corrected)
        elif outcome == "relocated":
            if not _assertion_ref(corrected):
                fail("10.2.5", "a relocated correction's @corrected is an Assertion reference (8.3.1)")
    elif kind == "item":
        if outcome != "replace":
            fail("10.2.5", "an Item is corrected with replace (8.3.8)")
        if not isinstance(corrected, dict):
            fail("10.2.5", "a replace carries the corrected Item in @corrected (8.3.8)")
        if not isinstance(corrected.get("kind"), str) or not isinstance(corrected.get("definition", {}), dict):
            fail("10.2.5", "a corrected Item gives its kind, label and definition (8.3.8)")
        label = corrected.get("label")
        if label is not None and not isinstance(label, str):
            fail("10.2.5", "a corrected Item's label is text (8.3.8)")
        validate_definition(t["id"], corrected.get("definition", {}), r, code_310_2_3="10.2.5")
    elif kind == "connection":
        if outcome != "replace":
            fail("10.2.5", "a Connection is corrected with replace (8.3.9)")
        if not isinstance(corrected, dict) or "connected_at" not in corrected:
            fail("10.2.5", "a Connection correction carries the corrected connected_at (8.3.9)")
        _instant_or_fail(corrected["connected_at"], "@corrected connected_at")
    else:
        fail("10.2.5", "a correction targets one Assertion, one Item or one Connection (8.3.1)")
