"""The morning list (SPEC §10): Attedra's what-remains read, grouped and grounded.

Every line carries the exact references it relies on. A line whose references do not resolve
through the `exact` read is omitted and logged; the list never shows a claim the store lacks."""
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

    def section(self, name: str) -> list[Line]:
        return [l for l in self.lines if l.section == name]

    def render(self) -> str:
        out = [f"Morning list, as of {self.cutoff}"]
        for name in SECTIONS:
            ls = self.section(name)
            if ls:
                out.append(f"\n{name}")
                out += [f"- {l.text}" for l in ls]
        if len(out) == 1:
            out.append("\nNothing open.")
        return "\n".join(out)


# Quiet rule: a line is marked "untouched for N days" when no message has carried a claim about its
# subject for QUIET_DAYS. Derived at read time from the ledger, never written as a deadline.
QUIET_RULE = "quiet-v1"
QUIET_DAYS = 7


def last_activity(ledger: Ledger, subject: str, cutoff: str) -> str | None:
    """The latest message instant, not after the cutoff, carrying an active claim on the subject."""
    root = ledger.root(subject)
    end = instants.parse(cutoff)[1]
    best = None
    for c, m in ledger.message_claims():
        if ledger.root(c.subject_id) == root and instants.parse(m["sent_at"])[0] < end:
            if best is None or instants.sort_key(m["sent_at"]) > instants.sort_key(best):
                best = m["sent_at"]
    return best


def quiet_days(ledger: Ledger, subject: str, cutoff: str) -> int | None:
    last = last_activity(ledger, subject, cutoff)
    if last is None:
        return None
    days = (instants.parse(cutoff)[0] - instants.parse(last)[0]).days
    return days if days >= QUIET_DAYS else None


SECTIONS = ("Overdue", "Your commitments", "Waiting on others", "Coming up")


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
        if source == owner_elig:
            text += f", asked by {_person(ledger, c.party_id, cfg)}" if c.party_id != cfg.owner_id else ""
        else:
            text += f", owed by {_person(ledger, c.obligated_id, cfg)}"
        quiet = quiet_days(ledger, subject, brief.cutoff)
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
    brief.lines.sort(key=lambda l: (SECTIONS.index(l.section),
                                    0 if (ledger.claim(l.claim_id).form == "ask") else 1, l.text))
    return brief
