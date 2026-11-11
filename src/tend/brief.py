"""The morning list (SPEC §10): Attedra's what-remains read, grouped and grounded.

Every line carries the exact references it relies on. A line whose references do not resolve
through the `exact` read is omitted and logged; the list never shows a claim the store lacks.

Nothing Tend read is hidden: besides what remains, the list shows requests closed only on a best
reading, requests the audit could not place, and messages the store had to set aside."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import ids, instants, schema
from .config import Config
from .ledger import Ledger


@dataclass
class Line:
    section: str
    text: str
    refs: list[str]
    claim_id: str


@dataclass
class Brief:
    cutoff: str
    lines: list[Line] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)

    def section(self, name: str) -> list[Line]:
        return [l for l in self.lines if l.section == name]

    def render(self) -> str:
        out = [f"Morning list, as of {self.cutoff}"]
        out += [f"Note: {n}" for n in self.notices]
        if not any(l.section in OPEN_SECTIONS for l in self.lines):
            out.append("\nNothing open.")
        for name in SECTIONS:
            ls = self.section(name)
            if ls:
                out.append(f"\n{name}")
                out += [f"- {l.text}" for l in ls]
        return "\n".join(out)


# Quiet rule: a line is marked "untouched for N days" when no recorded message has touched its
# subject for QUIET_DAYS: a message carrying a claim about it, or any message in a thread linked to
# it (a review, a push, a reply that maps to no claim). Derived at read time, never a deadline.
QUIET_RULE = "quiet-v2"
QUIET_DAYS = 7
# Requests closed on a best reading, and requests the audit refused, are shown for this long.
RECENT_RULE = "recent-v1"
RECENT_DAYS = 14


def activity(ledger: Ledger) -> dict[str, list[str]]:
    """Each Item root with the instants of the messages that touched it, read once per list."""
    by_thread: dict[str, set[str]] = {}
    for f, t, _ in ledger.all_links():
        if f.startswith("thread:"):
            by_thread.setdefault(f, set()).add(ledger.root(t))
    out: dict[str, list[str]] = {}
    for m in ledger.messages():
        for r in by_thread.get(m["thread_id"] or "", ()):
            out.setdefault(r, []).append(m["sent_at"])
    for c, m in ledger.message_claims():
        out.setdefault(ledger.root(c.subject_id), []).append(m["sent_at"])
    return out


def last_activity(ledger: Ledger, subject: str, cutoff: str, act: dict | None = None) -> str | None:
    """The latest instant, not after the cutoff, of a message that touched the subject."""
    act = activity(ledger) if act is None else act
    end = instants.parse(cutoff)[1]
    times = [t for t in act.get(ledger.root(subject), []) if instants.parse(t)[0] < end]
    return max(times, key=instants.sort_key) if times else None


def quiet_days(ledger: Ledger, subject: str, cutoff: str, act: dict | None = None) -> int | None:
    last = last_activity(ledger, subject, cutoff, act)
    if last is None:
        return None
    days = (instants.parse(cutoff)[0] - instants.parse(last)[0]).days
    return days if days >= QUIET_DAYS else None


OPEN_SECTIONS = ("Overdue", "Your commitments", "Waiting on others", "Coming up")
SECTIONS = OPEN_SECTIONS + ("Closed on my best reading", "Could not place")


def _label(ledger: Ledger, item_id: str) -> str:
    it = ledger.item(item_id)
    return (it and it["label"]) or item_id


def _kind(ledger: Ledger, item_id: str) -> str:
    it = ledger.item(ledger.root(item_id))
    return it["kind"] if it else ""


def _person(ledger: Ledger, pid: str | None, cfg: Config) -> str:
    if not pid:
        return "someone"
    if pid == cfg.owner_id:
        return "you"
    return pid.split(":", 1)[-1]


def build(session, ledger: Ledger, cfg: Config, cutoff: str = "now") -> Brief:
    r = session.read("what_remains", {"frame": {"scope": ids.SCOPE, "cutoff": cutoff},
                                      "attention_filter": "ignore"})
    brief = Brief(cutoff=r["frame"]["cutoff"])
    owner_elig = ids.elig(cfg.owner_id)
    act = activity(ledger)
    deadline_words = {(x["detail"].get("message"), x["detail"].get("ordinal")): x["detail"].get("text")
                      for x in ledger.revisions("deadline_refused")}
    entries = [(e, False) for e in r["open"]] + [(e, True) for e in r["upcoming"]]
    for e, upcoming in entries:
        if e["kind"] != "expectation":
            continue
        unit = e["unit"]
        base, _, prop = unit.rpartition("#")
        subject, ctx, source = base.split("|")
        claim_id = ctx.removeprefix("expctx:")
        c = ledger.claim(claim_id)
        if c is None:
            ledger.log("brief", "ungrounded_line", "no ledger claim for unit", unit=unit)
            continue
        refs = [base, e["began"]["record"]] if e.get("began") else [base]
        if not all(session.read("exact", {"ref": ref}).get("status") == "found" for ref in refs):
            ledger.log("brief", "ungrounded_line", "reference did not resolve", unit=unit, refs=refs)
            continue
        standing = e.get("standing", {})
        what = schema.task(_kind(ledger, subject), prop, c.value, c.form)
        label = _label(ledger, subject)
        text = f"{what[0].upper()}{what[1:]}: {label}" if what in schema.TASKS.values() else f"{label} ({what})"
        if c.deadline:
            text += f", due {c.deadline}"
        elif "deadline_unchecked" in (c.flags or []) and deadline_words.get((c.message_id, c.ordinal)):
            text += f', they said "{deadline_words[(c.message_id, c.ordinal)]}" (date not checked)'
        if source == owner_elig:
            text += f", asked by {_person(ledger, c.party_id, cfg)}" if c.party_id != cfg.owner_id else ""
        else:
            text += f", owed by {_person(ledger, c.obligated_id, cfg)}"
        quiet = quiet_days(ledger, subject, brief.cutoff, act)
        if quiet is not None:
            text += f", untouched for {quiet} days"
        if "low_confidence" in (c.flags or []):
            text += " (my best reading)"
        if upcoming:
            section = "Coming up"
        elif source != owner_elig:
            section = "Waiting on others"
        elif standing.get("overdue"):
            section = "Overdue"
        else:
            section = "Your commitments"
        brief.lines.append(Line(section, text, refs, claim_id))
    open_ids = {l.claim_id for l in brief.lines}
    _closed_on_best_reading(session, ledger, cfg, brief, open_ids)
    _could_not_place(session, ledger, brief)
    brief.lines.sort(key=lambda l: (SECTIONS.index(l.section),
                                    0 if (ledger.claim(l.claim_id) and ledger.claim(l.claim_id).form == "ask") else 1,
                                    l.text))
    return brief


def _recent(at: str, cutoff: str) -> bool:
    end = instants.parse(cutoff)[1]
    return instants.parse(at)[0] < end and (end - instants.parse(at)[0]).days < RECENT_DAYS


def _grounded(session, ledger: Ledger, refs: list[str], what: str) -> bool:
    if all(session.read("exact", {"ref": ref}).get("status") == "found" for ref in refs):
        return True
    ledger.log("brief", "ungrounded_line", "reference did not resolve", line=what, refs=refs)
    return False


def _closed_on_best_reading(session, ledger: Ledger, cfg: Config, brief: Brief, open_ids: set[str]) -> None:
    """A request no longer open only because a best-reading statement (flagged `low_confidence`)
    said it was done. The closing is real in the store; the list says what it rests on."""
    pairs = ledger.message_claims()
    withdrawn = {ledger.successor(c.value["claim"]) for c, _ in pairs if c.kind == "withdrawal"}
    for c, m in pairs:
        if c.kind != "commitment" or c.form != "value" or c.id in open_ids or c.id in withdrawn:
            continue
        root = ledger.root(c.subject_id)
        closers = [(s, sm) for s, sm in pairs if s.kind == "statement" and ledger.root(s.subject_id) == root
                   and s.property == c.property and s.value == c.value
                   and instants.sort_key(sm["sent_at"]) >= instants.sort_key(m["sent_at"])
                   and instants.parse(sm["sent_at"])[0] < instants.parse(brief.cutoff)[1]]
        if not closers or any("low_confidence" not in (s.flags or []) for s, _ in closers):
            continue
        s, sm = min(closers, key=lambda x: instants.sort_key(x[1]["sent_at"]))
        if not _recent(sm["sent_at"], brief.cutoff):
            continue
        refs = [f"{root}|{ids.expctx(c.id)}|{ids.elig(cfg.owner_for(c.obligated_id))}",
                f"{root}|{ids.event(sm['provider'], sm['provider_id'])}|{sm['stream_id']}"]
        what = schema.task(_kind(ledger, root), c.property, c.value, c.form)
        text = (f"{what[0].upper()}{what[1:]}: {_label(ledger, root)}, closed by \"{s.quote}\" from "
                f"{_person(ledger, sm['producer_id'], cfg)} (my best reading)")
        if _grounded(session, ledger, refs, text):
            brief.lines.append(Line("Closed on my best reading", text, refs, c.id))


def _could_not_place(session, ledger: Ledger, brief: Brief) -> None:
    """Requests the audit refused (SPEC §6.3), with the sender's own words, and messages the store
    had to set aside (SPEC §8.2). Refused statements are counted, not listed."""
    seen, statements = set(), 0
    for r in ledger.revisions("audit_refused"):
        d = r["detail"]
        key = (d.get("message"), d.get("ordinal"))
        if key in seen or not d.get("sent_at") or not _recent(d["sent_at"], brief.cutoff):
            continue
        seen.add(key)
        if d.get("code") == "quote_not_in_body":
            continue          # the words are the extractor's, not the sender's: nothing to show
        if d.get("claim_kind") != "commitment":
            statements += 1
            continue
        m = ledger.message(d["message"])
        if not m:
            continue
        refs = [f"{m['stream_id']}|{ids.event(m['provider'], m['provider_id'])}|{m['stream_id']}"]
        sender = m["producer_id"].split(":", 1)[-1]
        why = {"property_outside_schema": "I have no word for what was asked",
               "person_not_in_message": "the person it names is not on the message"}.get(d["code"], d["code"])
        text = f"\"{d.get('quote')}\" from {sender}, {m['sent_at'][:10]} ({why})"
        if _grounded(session, ledger, refs, text):
            brief.lines.append(Line("Could not place", text, refs, ""))
    if statements:
        brief.notices.append(f"{statements} statement{'s' if statements > 1 else ''} in recent mail could not be "
                             "placed and changed nothing on this list")
