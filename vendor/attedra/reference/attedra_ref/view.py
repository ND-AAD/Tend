"""The evaluation frame (spec 4.6), perspective and distribution (4.4.2), scope (2.1.5) and
Connection state (8.6.4, 8.6.6).

A ``View`` is a corrected account seen through a resolved frame. It answers the questions
every read asks first: is this record within the cutoff, and, in a participant perspective,
had it been distributed to the participant by the cutoff?

Three-valued answers (True, False, None) follow 4.2.5: None means the relation to the cutoff
is unspecified and the affected result must be reported as ambiguous (4.5.3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import instants as T
from .account import Account
from .instants import Instant
from .interpretations import LITERAL, LITERAL_REQUEST, Interpretation, get_interpretation
from .model import Rec, is_distribution_record
from .values import is_item_ref


def tri_and(*vals: bool | None) -> bool | None:
    if any(v is False for v in vals):
        return False
    if any(v is None for v in vals):
        return None
    return True


def tri_or(*vals: bool | None) -> bool | None:
    if any(v is True for v in vals):
        return True
    if any(v is None for v in vals):
        return None
    return False


class Limitation(Exception):
    """A read that cannot be evaluated as asked (9.6)."""

    def __init__(self, reason: str, **detail: Any) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass
class Frame:
    """A resolved frame (4.6.1). ``cutoff`` None means "no cutoff" (internal use only:
    whole-history evaluation for story timelines and removal planning).

    ``named`` says whether the frame names an interpretation. A frame that names one computes
    every comparison under it at every instant (``interp``). ``literal`` is a frame that
    requests literal comparison (``"interpretation": "literal"``, 4.6.1): it names literal
    comparison, so it is ``named`` with ``interp`` LITERAL, and only its resolved frame reports
    it as ``"literal"``. A frame that names none compares each value under the interpretation
    that applies to it (7.3.8, ``normalization.read_schedule``, ``expectations.own_schedule``);
    ``interp`` is then only a placeholder, and the resolved frame reports the interpretation in
    force for the read's scope at the cutoff, with the normalizations that put it in force
    (``inforce``, set by the read)."""

    cutoff: Instant | None
    perspective: str | None = None
    interp: Interpretation = LITERAL
    scope: Any = None
    cutoff_input: Any = None
    limitation: dict | None = None
    named: bool = False
    inforce: dict | None = None
    literal: bool = False

    def echo(self) -> dict:
        out = {"scope": self.scope,
               "cutoff": self.cutoff.text if self.cutoff else None,
               "perspective": self.perspective or "record",
               "interpretation": LITERAL_REQUEST if self.literal else self.interp.name,
               "interpretation_version": self.interp.version}
        if not self.named:
            out.update(self.inforce if self.inforce is not None else
                       {"interpretation": None, "interpretation_version": None, "normalization": None})
        if self.cutoff_input is not None and (self.cutoff is None or self.cutoff_input != self.cutoff.text):
            out["cutoff_input"] = self.cutoff_input
        return out


def resolve_frame(acc: Account, spec: dict | None, now: Instant | None = None) -> Frame:
    """Resolve a frame argument (README §5). A ``"now"`` cutoff resolves once, to the
    evaluation instant; a milestone cutoff resolves to its publication instant, and a
    planned milestone or one with competing instants cannot be a cutoff (4.6.1)."""
    spec = spec or {}
    scope = spec.get("scope")
    persp = spec.get("perspective", "record")
    if is_item_ref(persp):
        persp = persp["id"]
    perspective = None if persp in (None, "record") else persp
    interp_name = spec.get("interpretation")
    literal = interp_name == LITERAL_REQUEST
    interp = LITERAL if literal else get_interpretation(interp_name)
    cut = spec.get("cutoff", "now")
    frame = Frame(None, perspective, interp or LITERAL, scope, cut, named=interp_name is not None, literal=literal)
    if interp is None:
        frame.interp = Interpretation(interp_name, None)
        frame.limitation = {"limitation": "interpretation_unavailable", "interpretation": interp_name}
    if cut in (None, "now"):
        frame.cutoff = now or T.now_instant()
        return frame
    if isinstance(cut, dict) and is_item_ref(cut):
        cut = cut["id"]
    inst = T.parse_instant(cut) if isinstance(cut, str) else None
    if inst is not None:
        frame.cutoff = inst
        frame.cutoff_input = None
        return frame
    if isinstance(cut, str) and acc.role(cut) == "milestone":
        pub, issue = acc.publication_instant(cut)
        if pub is None or issue is not None:
            # README §5 Limitations: `planned_milestone` or `competing_publication_instants`,
            # naming the milestone
            frame.limitation = {"limitation": issue or "planned_milestone", "milestone": cut}
            return frame
        frame.cutoff = pub
        return frame
    frame.limitation = {"limitation": "cutoff_unresolvable", "cutoff": cut}
    return frame


@dataclass
class View:
    """A corrected account seen through a frame."""

    acc: Account
    frame: Frame
    excluded: set = field(default_factory=set)

    @property
    def cutoff(self) -> Instant | None:
        return self.frame.cutoff

    @property
    def interp(self) -> Interpretation:
        return self.frame.interp

    def within(self, inst: Instant | None, cutoff: Instant | None = None) -> bool | None:
        """Is the instant at or before the cutoff (4.6.1)?"""
        c = cutoff if cutoff is not None else self.cutoff
        if inst is None:
            return False
        if c is None:
            return True
        return T.at_or_before(inst, c)

    # -- perspective (4.6.1, 4.4.2) ------------------------------------------------------

    def is_communication_act(self, r: Rec) -> bool:
        """Acts recorded from a communication name the issuance that carries them (3.2.1).
        Without ``@issuance`` an act is treated as recorded without a communication."""
        return r.is_act and is_item_ref(r.values.get("@issuance")) and r.source != r.item

    def visible(self, r: Rec, cutoff: Instant | None = None) -> bool | None:
        """In a participant perspective, statements and communication-sourced acts count
        only once distributed to the participant (4.6.1). Corrections, detections and
        reconciliations, and acts recorded without a communication, are evaluated as in
        the record perspective. Expectations follow their supports."""
        p = self.frame.perspective
        if p is None:
            return True
        if r.kind == "expectation":
            return True
        if r.is_act:
            if r.action in ("correct", "detect", "reconcile") or not self.is_communication_act(r):
                return True
            out = self.issuance_covered(r.source, r.values["@issuance"]["id"], p, cutoff)
        else:
            out = self.statement_covered(r, p, cutoff)
        if out is not True:
            self.excluded.add(r.triple)
        return out

    def statement_covered(self, r: Rec, p: str, cutoff: Instant | None = None) -> bool | None:
        acc = self.acc
        if is_distribution_record(r.values, r.triple, acc.role(r.context), acc.role(r.item)):
            # 4.4.2: a self-description, publication or later-distribution Assertion is covered
            # for the participants it lists; a self-description is available to its producer
            if p in _ids(r.values.get("@distribution")):
                return True
            prod = r.values.get("@producer")
            if r.item == r.source and is_item_ref(prod) and prod["id"] == p:
                return True
        return self.issuance_covered(r.source, r.context, p, cutoff)

    def issuance_covered(self, source: str, ictx: str, p: str, cutoff: Instant | None = None) -> bool | None:
        """4.4.2: covered when, at or before the cutoff, the participant is listed in a
        ``@distribution`` of the issuance: the source's self-description at the issuance
        context or a later distribution naming that issuance; or the publication of a
        milestone context or a later distribution of it. An issuance is always available to
        its own ``@producer``."""
        acc = self.acc
        votes: list[bool | None] = []
        sd = acc.self_description(source, ictx)
        if sd is not None:
            when = self.within(acc.occurrence(sd), cutoff)
            prod = sd.values.get("@producer")
            if p in _ids(sd.values.get("@distribution")) or (is_item_ref(prod) and prod["id"] == p):
                votes.append(when)
        for r in acc.by_item.get(source, []):
            if r.kind != "statement" or r.context == ictx:
                continue
            iss = r.values.get("@issuance")
            if is_item_ref(iss) and iss["id"] == ictx and p in _ids(r.values.get("@distribution")):
                votes.append(self.within(acc.occurrence(r), cutoff))
        if acc.role(ictx) == "milestone":
            for r in acc.by_item.get(ictx, []):
                if r.kind != "statement" or p not in _ids(r.values.get("@distribution")):
                    continue
                if r.context == ictx or not is_item_ref(r.values.get("@issuance")):
                    votes.append(self.within(acc.occurrence(r), cutoff))
        return tri_or(*votes) if votes else False

    # -- frame membership ---------------------------------------------------------------

    def statement_in(self, r: Rec, cutoff: Instant | None = None) -> bool | None:
        """A statement contributes when it occurred at or before the cutoff and is visible."""
        occ = self.acc.occurrence(r)
        if occ is None:
            return False
        w = self.within(occ, cutoff)
        if w is False:
            return False
        return tri_and(w, self.visible(r, cutoff))

    def act_in(self, r: Rec, cutoff: Instant | None = None) -> bool | None:
        """An act is part of the frame when it occurred at or before the cutoff and, in a
        participant perspective, is visible. Its effect is then dated by its effective time."""
        if r.action in ("correct", "detect", "reconcile"):
            return True
        occ = self.acc.occurrence(r)
        if occ is None:
            return False
        w = self.within(occ, cutoff)
        if w is False:
            return False
        return tri_and(w, self.visible(r, cutoff))

    def effective_within(self, r: Rec, cutoff: Instant | None = None) -> bool | None:
        """An act in the frame whose effective time is at or before the cutoff."""
        return tri_and(self.act_in(r, cutoff), self.within(self.acc.effective(r), cutoff))


def _ids(lst) -> list[str]:
    return [x["id"] for x in lst if is_item_ref(x)] if isinstance(lst, list) else []


# ---------------------------------------------------------------------------------------
# Connections (8.6) and scope (2.1.5)


@dataclass
class ConnState:
    pair: tuple[str, str]
    connected_at: Instant | None
    events: list[tuple[Instant, str, Rec, bool]]  # (time, "disconnect"|"reconnect", act, effective)


def connection_state(acc: Account, pair: tuple[str, str], exclude=None) -> ConnState:
    """Derive a Connection's history from ``connected_at`` and its disconnect and reconnect
    acts in occurrence order, in the corrected account (8.6.6). An act that does not change
    the derived state is reported and otherwise ignored."""
    props = acc.rs.connections.get(pair) or {}
    cat_text = acc.connected_at.get(pair, props.get("connected_at"))
    cat = T.parse_instant(cat_text) if cat_text else None
    acts = []
    for r, _tg in acc.targets_of.get(("C", pair), []):
        if r.action in ("disconnect", "reconnect") and r.triple != exclude:
            t = acc.occurrence(r)
            if t is not None:
                acts.append((t, r))
    acts.sort(key=lambda x: (x[0].key, x[1].triple))
    events = []
    active = None
    for t, r in acts:
        if cat is None or T.before(t, cat) is True:
            events.append((t, r.action, r, False))
            continue
        if active is None:
            active = True
        if r.action == "disconnect" and active:
            active = False
            events.append((t, r.action, r, True))
        elif r.action == "reconnect" and not active:
            active = True
            events.append((t, r.action, r, True))
        else:
            events.append((t, r.action, r, False))
    return ConnState(pair, cat, events)


def connection_active_at(cs: ConnState, at: Instant | None) -> bool | None:
    """Active at an instant: connected at or before it, and the last effective lifecycle
    act at or before it was not a disconnection (8.6.4)."""
    if cs.connected_at is None:
        return None
    if at is not None and T.at_or_before(cs.connected_at, at) is not True:
        return False
    active = True
    for t, kind, _r, eff in cs.events:
        if not eff:
            continue
        if at is None or T.at_or_before(t, at) is True:
            active = kind == "reconnect"
    return active


def materialized_properties(acc: Account, pair: tuple[str, str]) -> dict:
    """The Connection's ``properties``: current state and most recent cycle, which MUST
    equal the derivation (2.2.4, 8.6.6)."""
    cs = connection_state(acc, pair)
    props = {"connected_at": cs.connected_at.text if cs.connected_at else None, "disconnected": False}
    for t, kind, r, eff in cs.events:
        if not eff:
            continue
        if kind == "disconnect":
            props["disconnected"] = True
            props["disconnected_at"] = t.text
            reason = r.values.get("reason")
            if reason is not None:
                props["disconnect_reason"] = reason
            else:
                props.pop("disconnect_reason", None)
        else:
            props["disconnected"] = False
            props["reconnected_at"] = t.text
    return props


def history(cs: ConnState, cutoff: Instant | None) -> list[dict]:
    """State segments of a Connection up to the cutoff (8.6.4)."""
    if cs.connected_at is None or (cutoff is not None and T.at_or_before(cs.connected_at, cutoff) is not True):
        return []
    segs = [{"state": "active", "from": cs.connected_at.text, "to": None}]
    for t, kind, _r, eff in cs.events:
        if not eff or (cutoff is not None and T.at_or_before(t, cutoff) is not True):
            continue
        segs[-1]["to"] = t.text
        segs.append({"state": "inactive" if kind == "disconnect" else "active", "from": t.text, "to": None})
    return segs


def scope_members(acc: Account, scope: Any, cutoff: Instant | None) -> set[str] | None:
    """The members of a scope at the cutoff (2.1.5): the scope Item itself and the Items
    reached forward from it over Connections active at the cutoff, transitively; or an
    explicit list. None means every Item in the store (allowed only in fixtures)."""
    if scope is None:
        return None
    if isinstance(scope, list):
        return {x["id"] if is_item_ref(x) else x for x in scope}
    root = scope["id"] if is_item_ref(scope) else scope
    # the members depend only on the account and the cutoff; a read asks for them more than once
    cache = acc.__dict__.setdefault("_scope_members", {})
    key = (root, cutoff.text if cutoff is not None else None)
    if key not in cache:
        cache[key] = _reach_active(acc, root, cutoff)
    return set(cache[key])


def _reach_active(acc: Account, root: str, cutoff: Instant | None) -> set[str]:
    out: set[str] = {root}
    frontier = [root]
    adjacency: dict[str, list[str]] = {}
    for (a, b) in acc.rs.connections:
        adjacency.setdefault(a, []).append(b)
    while frontier:
        n = frontier.pop()
        for m in adjacency.get(n, []):
            if m in out:
                continue
            if connection_active_at(connection_state(acc, (n, m)), cutoff) is True:
                out.add(m)
                frontier.append(m)
    return out
