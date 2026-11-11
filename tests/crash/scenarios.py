"""Scenarios for the kill sweep (adopted from the sixth review's probes). Each has a setup (run to
completion), an operation (the one a kill interrupts) and a check of the list read afterwards by a
fresh process."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))      # tests/

import fakes                                                     # noqa: E402
from fakes import mail, mention, proposal                        # noqa: E402
from gh import pr_event                                          # noqa: E402
from tend import ingest_github as gh                             # noqa: E402
from tend.config import Config                                   # noqa: E402
from test_fourth_review import _req, reader                      # noqa: E402
from test_mail import NICK, _two_decks                           # noqa: E402

OWNER = "person:nick@example.com"
ANN, BOB = "ann@acme.com", "bob@acme.com"
REQUEST = "Nick, could you send me the deck by Friday?"
OPEN_LINE = "Deliver: Acme deck v1, due 2026-11-13-08:00, asked by ann@acme.com"
CHANGED_LINE = "Deliver: Acme deck v1, asked by ann@acme.com, no longer open"
REVIEW = "Review: Add ledger (attedra#7), asked by gh:alice-dev"


def cfg(dsn):
    c = Config(owner_id=OWNER, owner_identifiers=[OWNER, "person:gh:nd-aad"], setup_at="2026-11-01-08:00")
    c.database_url = dsn
    return c


def decks(app):
    by = {i["label"]: i["id"] for i in app.ledger.active_items()}
    return by["Acme deck v1"], by["Acme deck v2"]


def script():
    return fakes.Extractor({
        "r": [_req("the deck", "deck", quote="could you send me the deck by Friday")],
        "d": [proposal("statement", "the Acme deck v2 is delivered", [mention("Acme deck v2", "existing", "V2")],
                       "delivered", True)]})


def _ex(app):
    v1, v2 = decks(app)
    ex = script()
    ex.script["d"][0]["mentions"][0]["item_id"] = v2
    return v1, v2, ex


def _pr(action, at, reviewers, **x):
    p = pr_event(action, at=at, **x)
    p["pull_request"]["requested_reviewers"] = [{"login": r} for r in reviewers]
    return p


FOUR = [
    ("pull_request", _pr("opened", "2026-11-05T10:00:00Z", [])),
    ("pull_request", _pr("review_requested", "2026-11-05T11:00:00Z", ["ND-AAD"], requested_reviewer={"login": "ND-AAD"})),
    ("pull_request", _pr("closed", "2026-11-06T10:00:00Z", ["ND-AAD"])),
    ("pull_request", _pr("reopened", "2026-11-07T10:00:00Z", ["ND-AAD"])),
]


def _gh(app, i):
    return gh.ingest(*FOUR[i], app.cfg, app.ledger, app.projector)


# -- mail: a request arrives ----------------------------------------------------------------------
def mail_setup(app):
    _two_decks(app)
    app.brief("now")


def mail_op(app):
    v1, v2, ex = _ex(app)
    app.mail(ex, fakes.Resolver(lambda m, c, s: v1)).ingest(
        mail("r", "tc", ANN, [NICK], "2026-11-09T10:00:00-08:00", REQUEST))


def mail_ok(app, text):
    """Recorded in the ledger means on the list."""
    recorded = app.ledger.message("ev:gmail:r") is not None
    return (not recorded) or OPEN_LINE in text, f"recorded={recorded}"


# -- nightly: a re-check moves a wrong pick, which ends a request ---------------------------------
def nightly_setup(app):
    _two_decks(app)
    v1, v2, ex = _ex(app)
    app.mail(ex, fakes.Resolver(lambda m, c, s: v1)).ingest(
        mail("r", "tc", ANN, [NICK], "2026-11-09T10:00:00-08:00", REQUEST))
    app.mail(ex, fakes.Resolver(lambda m, c, s: v2)).ingest(
        mail("d", "tb", NICK, [ANN, BOB], "2026-11-10T09:00:00-08:00", "Ann, Bob: the Acme deck v2 is delivered."))
    app.brief("now")


def nightly_op(app):
    v1, v2, ex = _ex(app)
    app.mail(ex, fakes.Resolver(reader)).review(sample=0)
    app.projector.refresh()


def nightly_ok(app, text):
    """The request is open, or the list says a re-check ended it."""
    return (OPEN_LINE in text) or (CHANGED_LINE in text), ""


# -- github: a review request arrives --------------------------------------------------------------
def gh_setup(app):
    _gh(app, 0)
    app.brief("now")


def gh_op(app):
    _gh(app, 1)


def gh_ok(app, text):
    recorded = any(m["provider"] == "gh" and "review_requested" in m["id"] for m in app.ledger.messages()) \
        or len([m for m in app.ledger.messages() if m["provider"] == "gh"]) >= 2
    return (not recorded) or REVIEW in text, f"recorded={recorded}"


# -- github: a close arrives after the reopen that followed it ------------------------------------
def late_setup(app):
    for i in (0, 1, 3):
        _gh(app, i)
    app.brief("now")


def late_op(app):
    _gh(app, 2)


def late_ok(app, text):
    """Requested, closed, reopened: my review is requested whatever was interrupted."""
    return REVIEW in text, ""


# -- owner: I withdraw the review request -----------------------------------------------------------
def owner_setup(app):
    _gh(app, 0)
    _gh(app, 1)
    app.brief("now")


def owner_op(app):
    cid = [c.id for c in app.ledger.active_claims() if c.kind == "commitment"][0]
    app.owner_act("withdraw", cid, "2026-11-10T20:00:00+00:00", note="not mine to review")


def owner_ok(app, text):
    """Recorded means off the list."""
    recorded = len(app.ledger.owner_acts()) > 0
    return (not recorded) or REVIEW not in text, f"recorded={recorded}"


SCENARIOS = {
    "mail": (mail_setup, mail_op, mail_ok),
    "nightly": (nightly_setup, nightly_op, nightly_ok),
    "github": (gh_setup, gh_op, gh_ok),
    "late": (late_setup, late_op, late_ok),
    "owner": (owner_setup, owner_op, owner_ok),
}
