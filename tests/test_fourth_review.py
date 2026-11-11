"""Fourth review (2026-11-11): the five merge blockers (W1, W4, W11, W13, cost), and the
visibility invariant tested as a property over every automated rewrite path:

    No automated rewrite (re-check, correction, merge, unmerge, drop, set-aside record, re-derived
    event) ends or moves an open request without a line on the list saying what changed and why.
"""
from __future__ import annotations

import time

import pytest
from attedra_ref.errors import WriteError

import fakes
from fakes import mail, mention, proposal
from gh import REPO, pr_event
from tend import brief, gardener, ingest_github as gh, pack
from test_mail import DANA, NICK, _commit, _two_decks

ANN, BOB = "ann@acme.com", "bob@acme.com"


def ingest(app, name, payload):
    return gh.ingest(name, payload, app.cfg, app.ledger, app.projector)


def lines(app, cutoff="now"):
    return [(l.section, l.text) for l in app.brief(cutoff).lines]


def _req(text, label, who=ANN, quote=None):
    return proposal("commitment", quote or f"could you send me {text} by Friday", [mention(text, label=label)], "delivered",
                    True, obligated=NICK, party=who, deadline={"text": "by Friday", "value": "2026-11-13"})


def reader(m, cands, seed):
    """Names first; when the name does not decide, follow a delivered candidate."""
    words = set(m["text"].lower().split()) - {"the", "a", "an"}

    def score(c):
        return len(words & set(" ".join(c["names"] + [c["label"] or ""]).lower().split()))
    if not cands:
        return ("new", m.get("kind", "deliverable"), m.get("label") or m["text"])
    best = max(score(c) for c in cands)
    top = [c for c in cands if score(c) == best]
    if best > 0 and len(top) == 1:
        return top[0]["id"]
    for c in top:
        if any(lc["property"] == "delivered" and lc["kind"] == "statement" for lc in c["latest_claims"]):
            return c["id"]
    return sorted(c["id"] for c in top)[0]


# -- the invariant, as a property over the rewrite paths -------------------------------------------

def assert_visible(app, before: dict[str, str]):
    """Every request open before a rewrite is still open on the same Item, or has a line under
    "Changed by my re-checks"."""
    b = app.brief("now")
    after = app.projector.open_now()
    shown = {l.claim_id for l in b.lines if l.section == "Changed by my re-checks"} | b.changed
    for cid, subject in before.items():
        now = app.ledger.successor(cid)
        if now in after and app.ledger.root(after[now]) == app.ledger.root(subject):
            continue
        assert (now or cid) in shown or cid in shown, (cid, b.render())


def _world(app):
    """Two decks, a confident request on each, and a sender who talks about both."""
    v1, v2 = _two_decks(app)
    ex = fakes.Extractor({
        "r1": [_req("the Acme deck v1", "Acme deck v1", quote="could you send me the Acme deck v1 by Friday")],
        "r2": [_req("the Acme deck v2", "Acme deck v2", who=BOB, quote="could you send me the Acme deck v2 by Friday")],
    })
    app.mail(ex, fakes.Resolver(lambda m, c, s: v1)).ingest(
        mail("r1", "ta", ANN, [NICK], "2026-11-10T09:00:00-08:00", "Nick, could you send me the Acme deck v1 by Friday?"))
    app.mail(ex, fakes.Resolver(lambda m, c, s: v2)).ingest(
        mail("r2", "tb", BOB, [NICK], "2026-11-10T09:30:00-08:00", "Nick, could you send me the Acme deck v2 by Friday?"))
    app.brief("now")
    return v1, v2, ex


def _move_request(app, v1, v2, ex):
    r1 = [c for c in app.ledger.active_claims() if c.kind == "commitment" and c.subject_id == v1][0]
    with app.ledger.conn.transaction():
        app.ledger.supersede_claim(r1.id, "test", "re-resolved", subject_id=v2)


def _move_statement_onto_request(app, v1, v2, ex):
    ex.script["s"] = [proposal("statement", "the Acme deck v2 is sent", [mention("Acme deck v2", "existing", v2)],
                               "delivered", True)]
    sid = app.mail(ex, fakes.Resolver(lambda m, c, s: v2)).ingest(
        mail("s", "tb", NICK, [BOB], "2026-11-10T12:00:00-08:00", "Bob: the Acme deck v2 is sent")).written[0]
    app.brief("now")
    before = app.projector.open_now()
    with app.ledger.conn.transaction():
        app.ledger.supersede_claim(sid, "test", "re-resolved", subject_id=v1)
    return before


def _merge(app, v1, v2, ex):
    ex.script["s"] = [proposal("statement", "the Acme deck v2 is sent", [mention("Acme deck v2", "existing", v2)],
                               "delivered", True)]
    app.mail(ex, fakes.Resolver(lambda m, c, s: v2)).ingest(
        mail("s", "tb", NICK, [BOB], "2026-11-10T12:00:00-08:00", "Bob: the Acme deck v2 is sent"))
    app.brief("now")
    before = app.projector.open_now()
    with app.ledger.conn.transaction():
        app.ledger.merge_items(v1, v2, "gardener", "judged the same")
    return before


def _unmerge(app, v1, v2, ex):
    with app.ledger.conn.transaction():
        app.ledger.merge_items(v1, v2, "gardener", "judged the same")
    app.brief("now")
    before = app.projector.open_now()
    with app.ledger.conn.transaction():
        app.ledger.unmerge(v2, "test", "judged apart")
    return before


def _drop(app, v1, v2, ex):
    r1 = [c for c in app.ledger.active_claims() if c.kind == "commitment" and c.subject_id == v1][0]
    with app.ledger.conn.transaction():
        app.ledger.drop_claim(r1.id, "test", "not a request after all")


def _quarantine(app, v1, v2, ex, monkeypatch):
    real = app.projector.project_message

    def poison(mid):
        if mid == "ev:gmail:r1":
            raise WriteError("occupied", "cannot be projected")
        return real(mid)
    monkeypatch.setattr(app.projector, "project_message", poison)
    app.ledger.mark_stale("test")


def _review_with_evidence(app, v1, v2, ex):
    ex.script["d"] = [proposal("statement", "the Acme deck v2 is delivered", [mention("Acme deck v2", "existing", v2)],
                               "delivered", True)]
    ex.script["r3"] = [_req("the deck", "deck", quote="could you send me the deck by Friday")]
    r3 = app.mail(ex, fakes.Resolver(lambda m, c, s: v1)).ingest(
        mail("r3", "tc", ANN, [NICK], "2026-11-10T10:00:00-08:00", "Nick, could you send me the deck by Friday?")).written[0]
    app.mail(ex, fakes.Resolver(lambda m, c, s: v2)).ingest(
        mail("d", "tc", NICK, [ANN], "2026-11-11T09:00:00-08:00", "Ann: the Acme deck v2 is delivered."))
    app.brief("now")
    before = app.projector.open_now()
    assert r3 in before
    app.mail(ex, fakes.Resolver(lambda m, c, s: v2)).review(sample=0)
    return before


def _sample(app, v1, v2, ex):
    app.mail(ex, fakes.Resolver(lambda m, c, s: v2)).review(sample=10)


@pytest.mark.parametrize("path", [_move_request, _move_statement_onto_request, _merge, _unmerge, _drop, _quarantine,
                                  _review_with_evidence, _sample])
def test_no_rewrite_ends_or_moves_an_open_request_unseen(app, path, monkeypatch):
    v1, v2, ex = _world(app)
    before = app.projector.open_now()
    assert len(before) == 2
    args = (app, v1, v2, ex, monkeypatch) if path is _quarantine else (app, v1, v2, ex)
    before = path(*args) or before
    assert_visible(app, before)


def test_the_sample_never_moves_a_confident_request(app):
    v1, v2, ex = _world(app)
    before = app.projector.open_now()
    app.mail(ex, fakes.Resolver(lambda m, c, s: v2)).review(sample=10)
    after = app.projector.open_now()
    for cid, subject in before.items():
        assert after.get(app.ledger.successor(cid)) == subject          # still open, on the same Item
    assert app.ledger.revisions("doubted")                            # the disagreement is recorded and flagged


def test_github_rederive_is_covered(app):
    ingest(app, "issues", _issue("opened"))
    ingest(app, "issues", _issue("assigned", at="2026-11-10T17:05:00Z", assignee={"login": "ND-AAD"}, assignees=["ND-AAD"]))
    app.brief("now")
    before = app.projector.open_now()
    ingest(app, "issues", _issue("closed", at="2026-11-10T16:00:00Z", sender="alice-dev", assignees=["ND-AAD"]))
    assert_visible(app, before)


# -- W4: a correct, open request is not closed by a delivery its own request explains -------------

def test_W4_a_delivery_that_meets_its_own_request_is_not_evidence(app):
    v1, v2 = _two_decks(app)
    ex = fakes.Extractor({
        "r1": [_req("the deck", "Acme deck v1", quote="could you send me the deck by Friday")],
        "r2": [_req("the Acme deck v2", "Acme deck v2", quote="could you also send me the Acme deck v2 by Friday")],
        "d2": [proposal("statement", "the Acme deck v2 is delivered", [mention("Acme deck v2", "existing", v2)], "delivered", True)],
    })
    r1 = app.mail(ex, fakes.Resolver(lambda m, c, s: v1)).ingest(
        mail("r1", "ta", ANN, [NICK], "2026-11-10T09:00:00-08:00", "Hi, could you send me the deck by Friday? Ann")).written[0]
    app.mail(ex, fakes.Resolver(lambda m, c, s: v2)).ingest(
        mail("r2", "tb", ANN, [NICK, BOB], "2026-11-10T10:00:00-08:00", "And could you also send me the Acme deck v2 by Friday? Ann"))
    app.mail(ex, fakes.Resolver(lambda m, c, s: v2)).ingest(
        mail("d2", "tb", NICK, [ANN, BOB], "2026-11-11T09:00:00-08:00", "Ann: the Acme deck v2 is delivered."))
    nightly = app.mail(ex, fakes.Resolver(reader))
    assert r1 not in nightly.reasons()
    nightly.review(sample=0)
    assert app.ledger.claim(r1).status == "active" and app.ledger.claim(r1).subject_id == v1
    assert lines(app, "2026-11-12T09:00-08:00") == [
        ("Your commitments", "Deliver: Acme deck v1, due 2026-11-13-08:00, asked by ann@acme.com")]


# -- W11: a request whose quote is not verbatim is still mentioned ----------------------------------

def test_W11_a_request_whose_quote_is_not_verbatim_is_named(app):
    ex = fakes.Extractor({"m": [proposal("commitment", "can you send me the Acme deck by Friday",
                                         [mention("the Acme deck", label="Acme deck")], "delivered", True,
                                         obligated=NICK, party=DANA, deadline={"text": "by Friday", "value": "2026-11-13"})]})
    out = app.mail(ex, fakes.Resolver(fakes.by_name)).ingest(
        mail("m", "t1", DANA, [NICK], "2026-11-10T09:00:00-08:00", "Nick, could you send me the Acme deck by Friday? Dana"))
    assert out.refused == [(0, "quote_not_in_body")]
    assert lines(app, "2026-11-11T09:00-08:00") == [("Could not place",
        "A request from dana@acme.com, 2026-11-10, that I could not read reliably (the words I extracted are not in the message)")]


# -- W13: a comment on a pull request is the pull request ---------------------------------------------

def _pr_comment(n, url, at):
    return {"action": "created", "repository": REPO, "sender": {"login": "alice-dev"},
            "issue": {"number": n, "title": "Add ledger", "user": {"login": "nd-aad"}, "html_url": url,
                      "pull_request": {"url": "x"}, "created_at": "2026-10-15T01:00:00Z", "updated_at": at},
            "comment": {"id": 1, "body": "looks good"}}


def test_W13_a_comment_on_a_pull_request_is_the_pull_request(app):
    url = "https://github.com/ND-AAD/attedra/pull/8"
    ingest(app, "pull_request", pr_event("opened", n=8, at="2026-10-15T01:00:00Z", sender="nd-aad", author="nd-aad"))
    ingest(app, "issue_comment", _pr_comment(8, url, "2026-11-10T08:00:00Z"))
    assert pack.keyed_items(app.ledger, f"see {url}") == ["pr:nd-aad/attedra/8"]
    assert not app.ledger.active_items("issue")
    pr = "pr:nd-aad/attedra/8"
    ex = fakes.Extractor({"m": [proposal("statement", f"{url} is merged", [mention(url, "existing", pr)], "merged", True)]})
    r = fakes.Resolver(lambda m, c, s: pr)
    o = app.mail(ex, r).ingest(mail("m", "t2", "erin@example.com", [NICK], "2026-11-11T09:00:00-08:00", f"FYI {url} is merged"))
    assert o.written and r.calls == 0                                 # still settled by the exact key


# -- W1: arrival order does not change what stands ----------------------------------------------------

def _issue(action, n=3, at="2026-11-10T17:00:00Z", sender="alice-dev", assignees=None, **extra):
    issue = {"number": n, "title": "Fix replay", "user": {"login": "alice-dev"},
             "html_url": f"https://github.com/ND-AAD/attedra/issues/{n}", "created_at": at, "updated_at": at}
    if assignees is not None:
        issue["assignees"] = [{"login": a} for a in assignees]
    p = {"action": action, "repository": REPO, "sender": {"login": sender}, "issue": issue}
    p.update(extra)
    return p


EVENTS = [("opened", {}), ("assigned", {"at": "2026-11-10T17:05:00Z", "assignee": {"login": "ND-AAD"}, "assignees": ["ND-AAD"]}),
          ("closed", {"at": "2026-11-11T12:00:00Z", "assignees": ["ND-AAD"]}),
          ("reopened", {"at": "2026-11-12T12:00:00Z", "assignees": ["ND-AAD"]})]


@pytest.mark.parametrize("order", [(0, 1, 2, 3), (0, 1, 3, 2), (3, 2, 1, 0), (1, 0, 3, 2), (2, 0, 3, 1)])
def test_W1_any_arrival_order_gives_the_same_list(app, order):
    for i in order:
        action, kw = EVENTS[i]
        ingest(app, "issues", _issue(action, **kw))
    out = [t for s, t in lines(app, "2026-11-20T09:00:00+00:00") if s != "Changed by my re-checks"]
    assert len(out) == 1 and out[0].startswith("Resolve: Fix replay (attedra#3), asked by gh:alice-dev")
    assert [t for s, t in lines(app, "2026-11-11T13:00:00+00:00") if s != "Changed by my re-checks"] == []


# -- cost: closed history does not slow the list ------------------------------------------------------

def test_cost_closed_history_is_not_quadratic(app, monkeypatch):
    for i in range(40):
        n = 1000 + i
        base = {"number": n, "title": f"Task {i}", "user": {"login": "alice-dev"},
                "html_url": f"https://github.com/ND-AAD/attedra/issues/{n}", "created_at": "2026-11-01T10:00:00Z"}
        for action, at, sender, x in (("opened", "2026-11-01T10:00:00Z", "alice-dev", {}),
                                      ("assigned", "2026-11-01T10:05:00Z", "alice-dev", {"assignee": {"login": "ND-AAD"}}),
                                      ("closed", "2026-11-02T10:00:00Z", "ND-AAD", {})):
            ingest(app, "issues", {"action": action, "repository": REPO, "sender": {"login": sender},
                                   "issue": {**base, "updated_at": at}, **x})
    app.brief("2026-11-11T09:00:00+00:00")
    roots = {"n": 0}
    real_root = app.ledger.root

    def counted(x):
        roots["n"] += 1
        return real_root(x)
    monkeypatch.setattr(app.ledger, "root", counted)
    t = time.perf_counter()
    brief._closed_on_best_reading(app.session, app.ledger, app.cfg, brief.Brief("2026-11-11T09:00:00+00:00"), set())
    assert roots["n"] == 0 and time.perf_counter() - t < 1.0        # no flagged statements: no work
