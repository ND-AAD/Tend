"""Third review (2026-11-11), findings V1 to V13. Each test is the reviewer's probe with its final
assertion inverted, plus a varied path where the probe alone would not pin the invariant down."""
from __future__ import annotations

import pytest
from attedra_ref.errors import WriteError

import fakes
from fakes import mail, mention, proposal
from gh import REPO, pr_event, review_submitted
from tend import gardener, ingest_github as gh
from test_mail import DANA, NICK, _ask, _commit, _two_decks

ANN, BOB = "ann@acme.com", "bob@acme.com"


def ingest(app, name, payload):
    return gh.ingest(name, payload, app.cfg, app.ledger, app.projector)


def lines(app, cutoff):
    return [l.text for l in app.brief(cutoff).lines]


def issue_event(action, n=3, at="2026-11-10T17:00:00Z", sender="alice-dev", assignees=(), **extra):
    p = {"action": action, "repository": REPO, "sender": {"login": sender},
         "issue": {"number": n, "title": "Fix replay", "user": {"login": "alice-dev"},
                   "assignees": [{"login": a} for a in assignees],
                   "html_url": f"https://github.com/ND-AAD/attedra/issues/{n}", "created_at": at, "updated_at": at}}
    p.update(extra)
    return p


# -- V1: work that still stands returns when a closed item is reopened ---------------------------

@pytest.mark.parametrize("closer", ["ND-AAD", "alice-dev"])
def test_V1_issue_reopened_while_still_assigned(app, closer):
    ingest(app, "issues", issue_event("opened"))
    ingest(app, "issues", issue_event("assigned", at="2026-11-10T17:05:00Z", assignee={"login": "ND-AAD"},
                                      assignees=["ND-AAD"]))
    ingest(app, "issues", issue_event("closed", at="2026-11-11T12:00:00Z", sender=closer, assignees=["ND-AAD"]))
    assert lines(app, "2026-11-11T13:00:00+00:00") == []
    ingest(app, "issues", issue_event("reopened", at="2026-11-12T12:00:00Z", assignees=["ND-AAD"]))
    assert len(lines(app, "2026-11-20T09:00:00+00:00")) == 1


def test_V1_issue_reopened_after_unassignment_stays_off(app):
    ingest(app, "issues", issue_event("opened"))
    ingest(app, "issues", issue_event("assigned", at="2026-11-10T17:05:00Z", assignee={"login": "ND-AAD"}))
    ingest(app, "issues", issue_event("unassigned", at="2026-11-10T18:00:00Z", assignee={"login": "ND-AAD"}))
    ingest(app, "issues", issue_event("closed", at="2026-11-11T12:00:00Z"))
    del_assignees = issue_event("reopened", at="2026-11-12T12:00:00Z")
    del del_assignees["issue"]["assignees"]          # the payload says nothing: the ledger decides
    ingest(app, "issues", del_assignees)
    assert lines(app, "2026-11-20T09:00:00+00:00") == []


def test_V1_pr_reopened_with_review_still_requested(app):
    ingest(app, "pull_request", pr_event("opened"))
    ingest(app, "pull_request", pr_event("review_requested", at="2026-11-10T17:05:00Z",
                                         requested_reviewer={"login": "ND-AAD"}))
    ingest(app, "pull_request", pr_event("closed", at="2026-11-11T12:00:00Z"))
    assert lines(app, "2026-11-11T13:00:00+00:00") == []
    ingest(app, "pull_request", pr_event("reopened", at="2026-11-12T12:00:00Z"))
    out = lines(app, "2026-11-20T09:00:00+00:00")
    assert len(out) == 1 and out[0].startswith("Review: Add ledger (attedra#7)")


def test_V1_assigned_pr_reopened_returns(app):
    ingest(app, "pull_request", pr_event("opened", n=9))
    ingest(app, "pull_request", pr_event("assigned", n=9, at="2026-11-10T17:05:00Z", assignee={"login": "ND-AAD"}))
    ingest(app, "pull_request", pr_event("closed", n=9, at="2026-11-11T12:00:00Z"))
    ingest(app, "pull_request", pr_event("reopened", n=9, at="2026-11-12T12:00:00Z"))
    assert len(lines(app, "2026-11-13T09:00:00+00:00")) == 1


# -- V2: every informed vote counts -------------------------------------------------------------

def test_V2_votes_for_new_count_when_the_collider_was_shown(app):
    ex = fakes.Extractor({
        "a": [proposal("statement", "The proposal is signed", [mention("the proposal", kind="document", label="Acme proposal")],
                       "signed", True)],
        "b": [proposal("commitment", "could you review the proposal by Friday",
                       [mention("the proposal", kind="document", label="Birch proposal")], "reviewed", True,
                       obligated=NICK, party=DANA, deadline={"text": "by Friday", "value": "2026-11-13"})],
    })
    ing = app.mail(ex, fakes.Resolver(lambda m, c, s: ("new", m["kind"], m["label"])))
    acme = app.ledger.claim(ing.ingest(mail("a", "t1", DANA, [NICK], "2026-11-09T09:00:00-08:00",
                                            "The proposal is signed")).written[0]).subject_id
    calls = []

    def rule(m, cands, seed):
        calls.append(seed)
        assert acme in [c["id"] for c in cands]              # the collider was shown
        return acme if seed == 0 else ("new", m["kind"], m["label"])
    out = app.mail(ex, fakes.Resolver(rule)).ingest(
        mail("b", "t2", DANA, [NICK], "2026-11-10T09:00:00-08:00", "Hi Nick, could you review the proposal by Friday? Dana"))
    c = app.ledger.claim((out.written + out.held)[0])
    assert len(calls) == 5                                    # one round: nothing was unseen
    assert c.subject_id != acme                               # four votes for new outweigh one
    assert app.ledger.item(c.subject_id)["label"] == "Birch proposal"


# -- V3: the vocabulary holds on the subject actually chosen --------------------------------------

def test_V3_exact_key_wins_and_the_vocabulary_refuses(app):
    ingest(app, "pull_request", pr_event("opened"))
    ex = fakes.Extractor({"m": [proposal("statement", "ND-AAD/attedra#7 is signed",
                                         [mention("ND-AAD/attedra#7", kind="document", label="ledger doc")], "signed", True)]})
    out = app.mail(ex, fakes.Resolver(lambda m, c, s: ("new", m["kind"], m["label"]))).ingest(
        mail("m", "t1", DANA, [NICK], "2026-11-11T09:00:00-08:00", "FYI ND-AAD/attedra#7 is signed"))
    assert out.refused == [(0, "property_outside_schema")] and not out.written and not out.held
    assert not [c for c in app.ledger.active_claims() if c.property == "signed"]
    assert any(r["detail"].get("quote") == "ND-AAD/attedra#7 is signed" for r in app.ledger.revisions("audit_refused"))


def test_V3_a_move_never_breaks_the_vocabulary(app):
    """Re-resolution onto an Item whose kind cannot carry the property moves nothing."""
    ingest(app, "pull_request", pr_event("opened"))
    ex = fakes.Extractor({"m": [proposal("statement", "the ledger doc is signed",
                                         [mention("the ledger doc", kind="document", label="ledger doc")], "signed", True)]})
    ing = app.mail(ex, fakes.Resolver(lambda m, c, s: ("new", m["kind"], m["label"])))
    cid = ing.ingest(mail("m", "t1", DANA, [NICK], "2026-11-11T09:00:00-08:00", "the ledger doc is signed")).written[0]
    c = app.ledger.claim(cid)
    assert not ing.fits(c, "pr") and ing.fits(c, "document")


# -- V4: evidence re-opens a confident pick ------------------------------------------------------

def sensible(v1, v2):
    def rule(m, cands, seed):
        ids_ = {c["id"]: c for c in cands}
        for cid, c in ids_.items():
            if any(lc["property"] == "delivered" and lc["kind"] == "statement" for lc in c["latest_claims"]):
                return cid
        return v1 if v1 in ids_ else ("new", m["kind"], m.get("label") or m["text"])
    return rule


def _wrong_pick_then_delivery(app):
    v1, v2 = _two_decks(app)
    ex = fakes.Extractor({
        "m": [_commit(quote="could you send me the deck by Friday", party=ANN)],
        "n": [proposal("statement", "the Acme deck v2 is delivered", [mention("Acme deck v2", "existing", v2)], "delivered", True)],
    })
    cid = app.mail(ex, fakes.Resolver(lambda m, c, s: v1)).ingest(
        mail("m", "ta", ANN, [NICK], "2026-11-10T09:00:00-08:00", "Hi, could you send me the deck by Friday? Ann")).written[0]
    sid = app.mail(ex, fakes.Resolver(lambda m, c, s: v2)).ingest(
        mail("n", "tb", NICK, [BOB, ANN], "2026-11-11T09:00:00-08:00", "Bob, Ann: the Acme deck v2 is delivered.")).written[0]
    return v1, v2, ex, cid, sid


def test_V4_confident_wrong_pick_is_rewritten_on_evidence(app):
    v1, v2, ex, cid, sid = _wrong_pick_then_delivery(app)
    nightly = app.mail(ex, fakes.Resolver(sensible(v1, v2)))
    assert nightly.reasons()[cid] == {"displaced"} and nightly.review_queue()[0] == cid
    changed = nightly.review(sample=0)
    assert app.ledger.claim(cid).status == "superseded"
    assert app.ledger.claim(changed[0]).subject_id == v2
    b = app.brief("2026-11-12T09:00-08:00")
    assert [(l.section, l.text) for l in b.lines] == [("Changed by my re-checks",
        'Deliver: Acme deck v2 (was Acme deck v1), asked by ann@acme.com; '
        'I re-read "could you send me the deck by Friday" as about Acme deck v2')]   # closed, and shown
    assert nightly.review_queue() == []                      # the oddity is gone, nothing left to check


def test_V4_unconfirmed_pick_becomes_a_best_reading(app):
    """The re-check cannot decide: the claim stays where it is and the list says it is a guess."""
    v1, v2, ex, cid, sid = _wrong_pick_then_delivery(app)
    nightly = app.mail(ex, fakes.Resolver(lambda m, c, s: v1 if s < 3 else v2))
    nightly.review(sample=0)
    c = app.ledger.claim(cid)
    assert c.subject_id == v1 and "low_confidence" in c.flags
    assert lines(app, "2026-11-12T09:00-08:00")[0].endswith("(my best reading)")


def test_V4_conflicting_sources_queue_a_confident_pick(app):
    """Attedra's conflicts read: two senders disagree on the same property of the same Item."""
    v1, v2 = _two_decks(app)
    ex = fakes.Extractor({"m": [proposal("statement", "the deck is blocked", [mention("the deck")], "status", "blocked")]})
    ing = app.mail(ex, fakes.Resolver(lambda m, c, s: v1))
    cid = ing.ingest(mail("m", "tz", "zed@other.com", [NICK, ANN], "2026-11-10T09:00:00-08:00", "the deck is blocked")).written[0]
    assert "conflict" in ing.reasons()[cid]


def test_V4_sample_reaches_confident_claims_and_is_remembered(app):
    v1, v2 = _two_decks(app)
    ing = app.mail(fakes.Extractor({}), fakes.Resolver(fakes.by_name))
    assert ing.review_queue() == []
    ing.review(sample=1)
    ing.review(sample=1)
    sampled = [r["detail"]["claim"] for r in app.ledger.revisions("reviewed")]
    assert len(sampled) == 2 and len(set(sampled)) == 2      # never-checked first
    assert app.ledger.revisions("resolution_confirmed")


# -- V5: a re-check sees the store without the claim's own footprint -----------------------------

def test_V5_reresolution_does_not_see_its_own_name(app):
    v1, v2 = _two_decks(app)
    ex = fakes.Extractor({"m": [_commit(quote="could you send me the deck by Friday", party="zed@other.com")], "n": []})
    first = app.mail(ex, fakes.Resolver(lambda m, c, s: ("new", "deliverable", "Acme deck") if s < 3 else v1))
    cid = first.ingest(mail("m", "tz", "zed@other.com", [NICK, ANN], "2026-11-10T09:00:00-08:00",
                            "Hi, could you send me the deck by Friday? Zed")).held[0]
    own = app.ledger.claim(cid).subject_id
    shown = []

    def same_split(m, cands, seed):
        shown.append({c["id"]: c["names"] for c in cands})
        return ("new", "deliverable", "Acme deck") if seed < 3 else v1
    o2 = app.mail(ex, fakes.Resolver(same_split)).ingest(
        mail("n", "tz", "zed@other.com", [NICK, ANN], "2026-11-10T12:00:00-08:00", "Thanks in advance!"))
    assert o2.released == []
    assert all(names == [] for s in shown for i, names in s.items() if i == own)   # its own name is hidden
    c = app.ledger.claim(cid)
    assert "low_confidence" in c.flags and c.subject_id == own
    assert app.ledger.names_of(own)                          # the rolled-back hiding left the record intact


# -- V6: the queue remembers what it checked -----------------------------------------------------

def test_V6_review_queue_moves_on(app):
    v1, v2 = _two_decks(app)
    ex = fakes.Extractor({f"q{i}": [proposal("statement", "the deck is done", [mention("the deck")], "delivered", True)]
                          for i in range(25)})
    split = fakes.Resolver(lambda m, c, s: v1 if s < 3 else v2)
    ing = app.mail(ex, split)
    ids_ = [(lambda o: (o.written + o.held)[0])(ing.ingest(mail(f"q{i}", f"tq{i}", "zed@other.com", [NICK, ANN, BOB],
                                                             f"2026-11-10T09:{i:02d}:00-08:00", "Update: the deck is done.")))
            for i in range(25)]
    night1 = ing.review_queue()
    ing.review(sample=0)
    night2 = ing.review_queue()
    assert len(night1) == 20 and not set(night1) & set(night2) and len(night2) == 5
    ing.review(sample=0)
    before = split.calls
    ing.review(sample=0)
    assert split.calls == before                             # nothing changed: nothing re-asked
    assert set(ids_) == {r["detail"]["claim"] for r in app.ledger.revisions("reviewed")}


# -- V7: a request closed on a guess says so -----------------------------------------------------

def test_V7_closed_on_a_best_reading_is_shown(app):
    v1, v2 = _two_decks(app)
    ex = fakes.Extractor({
        "m": [proposal("commitment", "could you send me the Acme deck v1 by Friday", [mention("Acme deck v1", "existing", v1)],
                       "delivered", True, obligated=NICK, party=ANN, deadline={"text": "by Friday", "value": "2026-11-13"})],
        "n": [proposal("statement", "the deck is done and sent", [mention("the deck")], "delivered", True)],
    })
    app.mail(ex, fakes.Resolver(lambda m, c, s: v1)).ingest(
        mail("m", "ta", ANN, [NICK], "2026-11-10T09:00:00-08:00", "Nick, could you send me the Acme deck v1 by Friday? Ann"))
    app.mail(ex, fakes.Resolver(lambda m, c, s: v1 if s < 3 else v2)).ingest(
        mail("n", "tc", NICK, [ANN, BOB], "2026-11-11T09:00:00-08:00", "Ann, Bob: the deck is done and sent."))
    b = app.brief("2026-11-12T09:00-08:00")
    assert [(l.section, l.text) for l in b.lines] == [
        ("Closed on my best reading", 'Deliver: Acme deck v1, closed by "the deck is done and sent" from you (my best reading)')]
    assert "Nothing open" in b.render()                       # nothing remains open; the guess is shown below
    assert app.brief("2026-11-30T09:00-08:00").lines == []    # shown for RECENT_DAYS


# -- V8: identity evidence must be specific ------------------------------------------------------

def test_V8_a_client_name_is_not_a_shared_word(app):
    labels = ["Acme deck", "Acme budget", "Acme site plan"]
    ex = fakes.Extractor({f"m{i}": [proposal("statement", f"The {l} is started", [mention(f"the {l}", label=l)], "status",
                                             "in_progress")] for i, l in enumerate(labels)})
    ing = app.mail(ex, fakes.Resolver(lambda m, c, s: ("new", "deliverable", m["label"])))
    for i, l in enumerate(labels):
        ing.ingest(mail(f"m{i}", f"t{i}", DANA, [NICK], f"2026-11-0{i+5}T09:00:00-08:00", f"The {l} is started"))
    assert gardener.detect(app.ledger, app.cfg) == []


def test_V8_a_new_claim_without_new_names_or_neighbours_is_not_asked_again(app):
    labels = ["Acme deck", "Acme deck plan"]
    ex = fakes.Extractor({f"m{i}": [proposal("statement", f"The {l} is started", [mention(f"the {l}", label=l)], "status",
                                             "in_progress")] for i, l in enumerate(labels)})
    ing = app.mail(ex, fakes.Resolver(lambda m, c, s: ("new", "deliverable", m["label"])))
    for i, l in enumerate(labels):
        ing.ingest(mail(f"m{i}", f"t{i}", DANA, [NICK], f"2026-11-0{i+5}T09:00:00-08:00", f"The {l} is started"))
    j = fakes.Judge(False)
    gardener.run(app.ledger, app.cfg, app.projector, j)
    assert len(j.asked) == 1
    ex.script["m9"] = [proposal("statement", "The Acme deck is done", [mention("the Acme deck", label="Acme deck")],
                                "status", "done")]
    deck = [i["id"] for i in app.ledger.active_items("deliverable") if i["label"] == "Acme deck"][0]
    app.mail(ex, fakes.Resolver(lambda m, c, s: deck)).ingest(
        mail("m9", "t0", DANA, [NICK], "2026-11-09T09:00:00-08:00", "The Acme deck is done"))
    gardener.run(app.ledger, app.cfg, app.projector, j)
    assert len(j.asked) == 1


# -- V9: one record costs that record, never the list --------------------------------------------

def test_V9_a_poison_message_is_set_aside_and_shown(app, monkeypatch):
    ex = fakes.Extractor({"m1": [_commit()], "m2": [proposal("statement", "Here is the revised Acme deck",
                          [mention("the revised Acme deck", "existing", "?")], "delivered", True)]})
    ing = app.mail(ex, fakes.Resolver(fakes.by_name))
    ing.ingest(_ask())
    real = app.projector.project_message

    def poison(mid):
        if mid == "ev:gmail:m2":
            raise WriteError("occupied", "this message cannot be projected")
        return real(mid)
    monkeypatch.setattr(app.projector, "project_message", poison)
    with pytest.raises(WriteError):
        ing.ingest(mail("m2", "t1", NICK, [DANA], "2026-11-11T10:00:00-08:00", "Here is the revised Acme deck."))
    for _ in range(3):
        b = app.brief("2026-11-12T09:00-08:00")
        assert len(b.lines) == 1
        assert any("set aside" in n for n in b.notices)
    assert list(app.projector.quarantined()) == ["ev:gmail:m2"]
    assert app.ledger.meta("stale") == "0"
    monkeypatch.undo()
    assert app.projector.release_quarantine() == ["ev:gmail:m2"]
    assert app.brief("2026-11-12T09:00-08:00").lines == []    # retried after the fix: the reply counts


def test_V9_an_unattributable_failure_serves_the_old_list(app, monkeypatch):
    ing = app.mail(fakes.Extractor({"m1": [_commit()]}), fakes.Resolver(fakes.by_name))
    ing.ingest(_ask())
    app.ledger.mark_stale("test")

    def boom():
        raise WriteError("occupied", "forced")
    monkeypatch.setattr(app.projector, "_fixed", boom)
    b = app.brief("2026-11-11T09:00-08:00")
    assert len(b.lines) == 1 and "may be out of date" in b.notices[0]


# -- V10: a wrong merge is undone by re-resolution -----------------------------------------------

def test_V10_wrong_merge_is_repaired_by_reresolving(app):
    v1, v2 = _two_decks(app)
    with app.ledger.conn.transaction():
        app.ledger.merge_items(v1, v2, "gardener", "judged the same (wrongly)")
    claim_b = [c for c in app.ledger.active_claims() if c.subject_id == v2][0]
    ing = app.mail(fakes.Extractor({}), fakes.Resolver(lambda m, c, s: ("new", "deliverable", "Acme deck v2")))
    assert ing.reasons()[claim_b.id] == {"merged"}
    ing.review(sample=0)
    assert app.ledger.root(v2) == v2
    assert "acme deck v2" not in app.ledger.names_of(v1)      # what the merge copied is gone
    assert {i["id"] for i in app.ledger.active_items("deliverable")} == {v1, v2}
    assert gardener.run(app.ledger, app.cfg, app.projector, fakes.Judge(True)) == []   # not merged again


def test_V10_unmerge_of_a_chain(app):
    v1, v2 = _two_decks(app)
    with app.ledger.conn.transaction():
        app.ledger.ensure_item("deliverable:v0", "deliverable", "Acme deck v0")
        app.ledger.merge_items(v1, v2, "gardener", "test")
        app.ledger.merge_items("deliverable:v0", v1, "gardener", "test")
    assert app.ledger.root(v2) == "deliverable:v0"
    with app.ledger.conn.transaction():
        app.ledger.unmerge(v2, "test", "test")
    assert app.ledger.root(v2) == v2 and app.ledger.root(v1) == "deliverable:v0"
    assert "acme deck v2" not in app.ledger.names_of("deliverable:v0")
    assert "acme deck v1" in app.ledger.names_of("deliverable:v0")


# -- V11: nothing the audit refused is invisible -------------------------------------------------

def test_V11_refused_request_is_shown(app):
    ex = fakes.Extractor({"m": [proposal("commitment", "could you approve the Acme budget by Friday",
                                         [mention("the Acme budget", label="Acme budget")], "approved", True,
                                         obligated=NICK, party=DANA, deadline={"text": "by Friday", "value": "2026-11-13"})]})
    out = app.mail(ex, fakes.Resolver(fakes.by_name)).ingest(
        mail("m", "t1", DANA, [NICK], "2026-11-10T09:00:00-08:00", "Nick, could you approve the Acme budget by Friday? Dana"))
    assert out.refused == [(0, "property_outside_schema")]
    assert lines(app, "2026-11-11T09:00-08:00") == [
        '"could you approve the Acme budget by Friday" from dana@acme.com, 2026-11-10 (I have no word for what was asked)']


def test_V11_unverified_deadline_shows_the_senders_words(app):
    ex = fakes.Extractor({"m1": [proposal("commitment", "could you send me the revised Acme deck by Friday",
                                          [mention("the revised Acme deck", label="Acme deck")], "delivered", True,
                                          obligated=NICK, party=DANA, deadline={"text": "by Friday", "value": "2026-11-14"})]})
    app.mail(ex, fakes.Resolver(fakes.by_name)).ingest(_ask())
    assert lines(app, "2026-11-11T09:00-08:00") == [
        'Deliver: Acme deck, they said "by Friday" (date not checked), asked by dana@acme.com']


# -- V13: quiet means no recorded message, not no claim ------------------------------------------

def test_V13_quiet_counts_messages_that_map_to_no_claim(app):
    ingest(app, "pull_request", pr_event("opened", n=8, at="2026-10-15T01:00:00Z", sender="nd-aad", author="nd-aad"))
    r = review_submitted(n=8, at="2026-11-09T18:00:00Z")
    r["sender"] = {"login": "alice-dev"}
    r["pull_request"]["user"] = {"login": "nd-aad"}
    ingest(app, "pull_request_review", r)
    assert lines(app, "2026-11-11T09:00:00+00:00") == ["Merge or close: Add ledger (attedra#8)"]
    assert lines(app, "2026-11-20T09:00:00+00:00") == ["Merge or close: Add ledger (attedra#8), untouched for 10 days"]
