"""Fifth review (2026-11-11): the store must be provably caught up with the ledger before any
rewrite or list read (Y1, Y2), a re-derivation never deletes claims it cannot regenerate (Y3), and
an earlier met request does not explain a new wrong pick (Y4). The three blocking probes are
inverted here, and the fourth review's property test is run again with a message whose append did
not complete before the rewrite.
"""
from __future__ import annotations

import pytest
from attedra_ref.errors import WriteError

import fakes
from fakes import mail, mention, proposal
from gh import REPO, pr_event
from tend import ingest_github as gh
from tend.app import App
from tend.ledger import BehindLedger
from test_fourth_review import (_drop, _merge, _move_request, _move_statement_onto_request, _quarantine, _req,
                                _review_with_evidence, _sample, _unmerge, _world, assert_visible, reader)
from test_mail import NICK, _two_decks

ANN, BOB = "ann@acme.com", "bob@acme.com"
REQUEST = "Nick, could you send me the deck by Friday?"
CHANGED = "Changed by my re-checks"
OPEN = ("Overdue", "Your commitments", "Waiting on others", "Coming up")


def flat(app, cutoff="now"):
    return app.brief(cutoff).render().replace("\n", " / ")


def _wrong_pick(app):
    """Ann asks for "the deck"; it is read as v1 with confidence. She meant v2, which is then
    delivered to her."""
    v1, v2 = _two_decks(app)
    ex = fakes.Extractor({
        "r": [_req("the deck", "deck", quote="could you send me the deck by Friday")],
        "d": [proposal("statement", "the Acme deck v2 is delivered", [mention("Acme deck v2", "existing", v2)],
                       "delivered", True)],
    })
    return v1, v2, ex


def _breaks(app, monkeypatch, mid, error):
    """Make the append of one message fail once with `error`."""
    real = app.projector.project_message
    state = {"armed": True}

    def broken(m):
        if m == mid and state["armed"]:
            state["armed"] = False
            raise error
        return real(m)
    monkeypatch.setattr(app.projector, "project_message", broken)


# -- Y1: a failed append, then a rewrite of that request ------------------------------------------

def test_Y1_a_rewrite_after_a_failed_append_is_shown(app, monkeypatch):
    v1, v2, ex = _wrong_pick(app)
    app.brief("now")
    _breaks(app, monkeypatch, "ev:gmail:r", WriteError("occupied", "a transient store error"))
    with pytest.raises(WriteError):
        app.mail(ex, fakes.Resolver(lambda m, c, s: v1)).ingest(
            mail("r", "tc", ANN, [NICK], "2026-11-09T10:00:00-08:00", REQUEST))
    assert app.ledger.unprojected() == ["ev:gmail:r"]
    app.mail(ex, fakes.Resolver(lambda m, c, s: v2)).ingest(
        mail("d", "tb", NICK, [ANN, BOB], "2026-11-10T09:00:00-08:00", "Ann, Bob: the Acme deck v2 is delivered."))
    cid = [c.id for c in app.ledger.active_claims() if c.kind == "commitment"][0]
    app.mail(ex, fakes.Resolver(reader)).review(sample=0)        # the nightly review, before any list is read
    moved = app.ledger.claim(app.ledger.successor(cid))
    assert app.ledger.root(moved.subject_id) == v2
    assert app.ledger.unprojected() == []
    out = flat(app)
    assert len(app.ledger.revisions("obligation_changed")) == 1
    assert (f'{CHANGED} / - Deliver: Acme deck v1, asked by ann@acme.com, no longer open; '
            f'I re-read "could you send me the deck by Friday" as about Acme deck v2') in out


# -- Y2: an interrupted append, then a retry or a restart ----------------------------------------

def _interrupted(app, monkeypatch):
    v1, v2, ex = _wrong_pick(app)
    app.brief("now")
    _breaks(app, monkeypatch, "ev:gmail:r", KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        app.mail(ex, fakes.Resolver(lambda m, c, s: v1)).ingest(
            mail("r", "tc", ANN, [NICK], "2026-11-09T10:00:00-08:00", REQUEST))
    app.conn.rollback()
    assert app.ledger.meta("stale") != "1"                       # nothing marked the store stale
    assert app.ledger.unprojected() == ["ev:gmail:r"]            # but the ledger knows it is behind
    return v1, ex


def test_Y2_a_retry_of_an_interrupted_message_completes_the_projection(app, monkeypatch):
    v1, ex = _interrupted(app, monkeypatch)
    again = app.mail(ex, fakes.Resolver(lambda m, c, s: v1)).ingest(
        mail("r", "tc", ANN, [NICK], "2026-11-09T10:00:00-08:00", REQUEST))
    assert again.replay
    assert app.ledger.unprojected() == []
    assert "Deliver: Acme deck v1, due 2026-11-13-08:00, asked by ann@acme.com" in flat(app)


def test_Y2_a_list_read_after_an_interruption_shows_the_request(app, monkeypatch):
    _interrupted(app, monkeypatch)
    assert "Deliver: Acme deck v1, due 2026-11-13-08:00, asked by ann@acme.com" in flat(app)


def test_Y2_startup_reconciles_an_interrupted_message(app, monkeypatch):
    _interrupted(app, monkeypatch)
    monkeypatch.undo()
    app.conn.commit()
    restarted = App(app.cfg)
    try:
        assert restarted.ledger.unprojected() == []
        assert {r["reason"] for r in restarted.ledger.revisions("rebuild")} >= {"messages not yet projected"}
        assert "Deliver: Acme deck v1, due 2026-11-13-08:00, asked by ann@acme.com" in flat(restarted)
    finally:
        restarted.close()


# -- the guard: no rewrite while the store is behind ----------------------------------------------

def test_a_rewrite_while_the_store_is_behind_is_refused(app, monkeypatch):
    v1, ex = _interrupted(app, monkeypatch)
    cid = [c.id for c in app.ledger.active_claims() if c.kind == "commitment"][0]
    with pytest.raises(BehindLedger):
        with app.ledger.conn.transaction():
            app.ledger.supersede_claim(cid, "test", "re-resolved")
    with pytest.raises(BehindLedger):
        with app.ledger.conn.transaction():
            app.ledger.drop_claim(cid, "test", "not a request")
    assert app.ledger.claim(cid).status == "active"


# -- the property, with a message whose append did not complete ----------------------------------

@pytest.mark.parametrize("error", [WriteError("occupied", "a transient store error"), KeyboardInterrupt()],
                         ids=["failed", "interrupted"])
@pytest.mark.parametrize("path", [_move_request, _move_statement_onto_request, _merge, _unmerge, _drop, _quarantine,
                                  _review_with_evidence, _sample])
def test_no_rewrite_after_an_unprojected_message_ends_or_moves_a_request_unseen(app, path, error, monkeypatch):
    """The world of the fourth review, plus a third request on v1 whose append failed or was
    interrupted. Production rewrites settle the store first; the direct rewrites below are refused
    until it is settled. The baseline is the ledger-derived state, so it holds the third request."""
    v1, v2, ex = _world(app)
    ex.script["r4"] = [_req("the Acme deck v1", "Acme deck v1", who="cy@acme.com",
                            quote="could you send me the Acme deck v1 by Friday")]
    _breaks(app, monkeypatch, "ev:gmail:r4", error)
    with pytest.raises(type(error)):
        app.mail(ex, fakes.Resolver(lambda m, c, s: v1)).ingest(
            mail("r4", "td", "cy@acme.com", [NICK], "2026-11-10T09:45:00-08:00",
                 "Nick, could you send me the Acme deck v1 by Friday?"))
    app.conn.rollback()
    monkeypatch.undo()
    assert app.ledger.unprojected() == ["ev:gmail:r4"]
    r4 = [c.id for c in app.ledger.active_claims() if c.message_id == "ev:gmail:r4"][0]
    if path in (_move_request, _drop):
        with pytest.raises(BehindLedger):
            path(app, v1, v2, ex)
        app.conn.rollback()
    app.projector.settle("test")
    before = app.projector.open_now()
    assert len(before) == 3 and r4 in before
    args = (app, v1, v2, ex, monkeypatch) if path is _quarantine else (app, v1, v2, ex)
    before = path(*args) or before
    assert_visible(app, before)


# -- Y3: a re-derivation that cannot regenerate the later claims ----------------------------------

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
REVIEW = "Review: Add ledger (attedra#7), asked by gh:alice-dev"


def _open_lines(app):
    return tuple(sorted(l.text for l in app.brief("now").lines if l.section in OPEN))


def test_Y3_a_late_event_never_deletes_claims_without_payloads(app):
    for i in (0, 1, 3):
        gh.ingest(*FOUR[i], app.cfg, app.ledger, app.projector)
    assert _open_lines(app) == (REVIEW,)
    n = len(app.ledger.active_claims())
    app.ledger._q("DELETE FROM ledger.payloads")                 # a ledger older than stored payloads
    gh.ingest(*FOUR[2], app.cfg, app.ledger, app.projector)
    logged = {r["action"] for r in app.ledger.revisions()}
    assert "rederive_impossible" in logged and "rederived" not in logged
    assert len(app.ledger.active_claims()) > n                   # the later claims are kept, the close is added
    [entry] = app.ledger.revisions("rederive_impossible")
    assert entry["detail"]["omitted"]                            # the close's withdrawal, ended by the reopen
    assert _open_lines(app) == (REVIEW,)                         # reopened on GitHub, my review still requested


# -- Y4: an earlier met request does not explain a new delivery ------------------------------------

def test_Y4_an_earlier_met_request_does_not_mask_a_new_wrong_pick(app):
    v1, v2 = _two_decks(app)
    ex = fakes.Extractor({
        "o": [_req("the Acme deck v2", "Acme deck v2", quote="could you send me the Acme deck v2 by Friday")],
        "od": [proposal("statement", "the Acme deck v2 is delivered", [mention("Acme deck v2", "existing", v2)],
                        "delivered", True)],
        "r": [_req("the deck", "deck", quote="could you send me the deck by Friday")],
        "d": [proposal("statement", "the Acme deck v2 is delivered", [mention("Acme deck v2", "existing", v2)],
                       "delivered", True)],
    })
    to_v2 = fakes.Resolver(lambda m, c, s: v2)
    app.mail(ex, to_v2).ingest(mail("o", "tb", ANN, [NICK, BOB], "2026-11-02T09:00:00-08:00",
                                    "Nick, could you send me the Acme deck v2 by Friday?"))
    app.mail(ex, to_v2).ingest(mail("od", "tb", NICK, [ANN, BOB], "2026-11-03T09:00:00-08:00",
                                    "Ann: the Acme deck v2 is delivered."))
    r = app.mail(ex, fakes.Resolver(lambda m, c, s: v1)).ingest(
        mail("r", "tc", ANN, [NICK], "2026-11-09T10:00:00-08:00", REQUEST)).written[0]
    app.mail(ex, to_v2).ingest(mail("d", "tc", NICK, [ANN], "2026-11-10T09:00:00-08:00",
                                    "Ann: the Acme deck v2 is delivered."))
    nightly = app.mail(ex, fakes.Resolver(reader))
    assert "displaced" in (nightly.reasons().get(r) or set())
    assert r in nightly.review_queue()
