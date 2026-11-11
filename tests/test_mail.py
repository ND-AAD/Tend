"""SPEC §12 cases 1, 3 and 5: the mail walkthrough, audit refusals, confidence and holds."""
from __future__ import annotations

import fakes
from fakes import mail, mention, proposal

NICK = "nick@example.com"
DANA = "dana@acme.com"
ASK = ("Hi Nick, could you send me the revised Acme deck by Friday? Thanks, Dana")


def _ask(id="m1", thread="t1", body=ASK, sent="2026-11-10T09:00:00-08:00"):
    return mail(id, thread, DANA, [NICK], sent, body)


def _commit(quote="could you send me the revised Acme deck by Friday", party=DANA, **kw):
    return proposal("commitment", quote, [mention("the revised Acme deck", label="Acme deck")], "delivered", True,
                    obligated=NICK, party=party, deadline={"text": "by Friday", "value": "2026-11-13"}, **kw)


def _lines(app, cutoff="now"):
    return app.brief(cutoff).render()


def test_commitment_walkthrough(app):
    ex = fakes.Extractor({
        "m1": [_commit()],
        "m2": [proposal("statement", "Here is the revised Acme deck",
                        [mention("the revised Acme deck", "existing", "?")], "delivered", True)],
    })
    ing = app.mail(ex, fakes.Resolver(fakes.by_name))
    out = ing.ingest(_ask())
    assert out.written and not out.held
    b = app.brief("2026-11-11T09:00-08:00")
    assert [l.section for l in b.lines] == ["Your commitments"]
    assert "Deliver: Acme deck, due 2026-11-13-08:00, asked by dana@acme.com" in b.lines[0].text
    # the extractor saw the new Item in the pack for the reply
    out2 = ing.ingest(mail("m2", "t1", NICK, [DANA], "2026-11-11T10:00:00-08:00",
                           "Here is the revised Acme deck.\n\nOn Tue, Dana wrote:\n> could you send me"))
    assert out2.written, out2
    assert any(e["label"] == "Acme deck" for e in ex.seen[1]["pack"]["items"])
    c = app.ledger.claim(out2.written[0])
    assert c.subject_id == app.ledger.claim(out.written[0]).subject_id
    assert app.brief("2026-11-12T09:00-08:00").lines == []
    # the historical read still shows it open before the reply
    assert len(app.brief("2026-11-11T09:00-08:00").lines) == 1


def test_overdue(app):
    app.mail(fakes.Extractor({"m1": [_commit()]}), fakes.Resolver(fakes.by_name)).ingest(_ask())
    b = app.brief("2026-11-16T09:00-08:00")
    assert [l.section for l in b.lines] == ["Overdue"]


def test_audit_refusals(app):
    quoted = "Sounds good.\n\nOn Mon, Dana wrote:\n> could you send me the revised Acme deck by Friday?"
    ex = fakes.Extractor({
        "m1": [
            _commit(quote="send me the slides tonight"),                          # not in body
            proposal("statement", ASK[:20], [mention("the deck")], "colour", "blue"),  # outside schema
            proposal("commitment", "could you send me", [mention("the deck")], "delivered", True,
                     obligated="eve@elsewhere.com", party=DANA),                   # person not in message
            proposal("statement", "could you send", [mention("the deck")], "delivered", True, form="ask"),
        ],
        "m2": [_commit()],                                                         # quote only in quoted text
    })
    ing = app.mail(ex, fakes.Resolver(fakes.by_name))
    out = ing.ingest(_ask())
    assert [c for _, c in out.refused] == ["quote_not_in_body", "property_outside_schema",
                                           "person_not_in_message", "bad_kind"]
    assert any(r["detail"].get("property") == "colour" for r in app.ledger.revisions("vocabulary_gap"))
    out2 = ing.ingest(mail("m2", "t9", NICK, [DANA], "2026-11-10T10:00:00-08:00", quoted))
    assert [c for _, c in out2.refused] == ["quote_not_in_body"]
    assert app.ledger.active_claims() == []


def test_invented_id_and_new_collision(app):
    ex = fakes.Extractor({
        "m1": [_commit()],
        "m2": [proposal("statement", "the slides are done", [mention("the slides", "existing", "deliverable:made-up")],
                        "delivered", True)],
    })
    first = app.mail(ex, fakes.Resolver(fakes.by_name)).ingest(_ask())
    deck = app.ledger.claim(first.written[0]).subject_id
    # A sender and thread unrelated to the deck, so the pack is empty. The resolver invents ids on
    # even seeds and says "new" with the label "Acme deck" on odd seeds: those votes collide with the
    # recorded name, so the colliding Item is added to the candidates and the votes re-run.
    seen = []

    def rule(m, cands, seed):
        seen.append([c["id"] for c in cands])
        if deck in seen[-1] and len(seen) > 5:
            return deck
        return "deliverable:made-up" if seed % 2 == 0 else ("new", "deliverable", "Acme deck")
    ing = app.mail(ex, fakes.Resolver(rule))
    out = ing.ingest(mail("m2", "t2", "ann@acme.com", [NICK], "2026-11-10T11:00:00-08:00", "FYI the slides are done."))
    assert app.ledger.revisions("invented_id")
    assert seen[0] == [] and len(seen) == 10 and deck in seen[5]
    # unanimous, but nothing in this thread connects to the deck: held, not written
    assert out.held and app.ledger.claim(out.held[0]).subject_id == deck


def _two_decks(app):
    ex = fakes.Extractor({
        "a": [proposal("statement", "The Acme deck v1 is started", [mention("Acme deck v1", label="Acme deck v1")],
                       "status", "in_progress")],
        "b": [proposal("statement", "The Acme deck v2 is started", [mention("Acme deck v2", label="Acme deck v2")],
                       "status", "in_progress")],
    })
    ing = app.mail(ex, fakes.Resolver(fakes.by_name))
    a = ing.ingest(mail("a", "ta", "ann@acme.com", [NICK], "2026-11-09T09:00:00-08:00", "The Acme deck v1 is started"))
    b = ing.ingest(mail("b", "tb", "bob@acme.com", [NICK], "2026-11-09T09:30:00-08:00", "The Acme deck v2 is started"))
    return app.ledger.claim(a.written[0]).subject_id, app.ledger.claim(b.written[0]).subject_id


def test_unanimous_vote_writes(app):
    v1, v2 = _two_decks(app)
    ex = fakes.Extractor({"m": [proposal("statement", "the deck is done", [mention("the deck")], "delivered", True)]})
    out = app.mail(ex, fakes.Resolver(lambda m, c, s: v1)).ingest(
        mail("m", "ta", "ann@acme.com", [NICK], "2026-11-10T09:00:00-08:00", "Update: the deck is done."))
    assert out.written and app.ledger.claim(out.written[0]).subject_id == v1


def test_split_vote_is_written_at_once_as_best_reading(app):
    """Review finding B: an uncertain request is shown at once, flagged, never hidden."""
    v1, v2 = _two_decks(app)
    ex = fakes.Extractor({"m": [_commit(quote="could you send me the deck by Friday", party="zed@other.com")]})
    split = fakes.Resolver(lambda m, c, s: v1 if s in (0, 1, 2) else v2)
    ing = app.mail(ex, split)
    out = ing.ingest(mail("m", "tz", "zed@other.com", [NICK, "ann@acme.com", "bob@acme.com"], "2026-11-10T09:00:00-08:00",
                          "Hi, could you send me the deck by Friday? Zed"))
    assert out.held and not out.written
    c = app.ledger.claim(out.held[0])
    assert c.status == "active" and c.subject_id == v1 and "low_confidence" in c.flags
    lines = app.brief("2026-11-10T10:00-08:00").lines
    assert len(lines) == 1 and lines[0].text.endswith("(my best reading)")
    assert ing.release_holds("2026-11-12T08:00:00-08:00") == []
    assert ing.release_holds("2026-11-13T09:01:00-08:00") == out.held
    assert app.ledger.holds() == [] and "low_confidence" in app.ledger.claim(out.held[0]).flags
    assert ing.review_queue() == out.held          # still watched by the review queue


def test_later_message_repoints_best_reading(app):
    """Self-correction: a later message in the thread settles the reading; the claim is
    superseded onto the other Item and the list follows after the rebuild."""
    v1, v2 = _two_decks(app)
    ex = fakes.Extractor({"m": [_commit(quote="could you send me the deck by Friday", party="zed@other.com")], "n": []})
    state = {"split": True}
    ing = app.mail(ex, fakes.Resolver(lambda m, c, s: (v1 if s < 3 else v2) if state["split"] else v2))
    out = ing.ingest(mail("m", "tz", "zed@other.com", [NICK, "ann@acme.com", "bob@acme.com"], "2026-11-10T09:00:00-08:00",
                          "Hi, could you send me the deck by Friday? Zed"))
    first = out.held[0]
    state["split"] = False
    out2 = ing.ingest(mail("n", "tz", "bob@acme.com", ["zed@other.com", NICK], "2026-11-10T10:00:00-08:00",
                           "Zed means the v2 deck."))
    assert len(out2.released) == 1 and out2.released[0] != first
    c = app.ledger.claim(out2.released[0])
    assert c.subject_id == v2 and "low_confidence" not in c.flags
    assert app.ledger.claim(first).status == "superseded"
    lines = app.brief("2026-11-10T11:00-08:00").lines
    assert len(lines) == 1 and lines[0].text.startswith("Deliver: Acme deck v2") and "best reading" not in lines[0].text


def test_never_drops_a_request_with_a_colliding_name(app):
    """Review defect 4: every vote says new and collides with a recorded name."""
    ex = fakes.Extractor({
        "a": [proposal("statement", "The proposal is signed", [mention("the proposal", kind="document", label="Acme proposal")], "signed", True)],
        "b": [proposal("commitment", "could you review the proposal by Friday", [mention("the proposal", kind="document", label="Birch proposal")],
                       "reviewed", True, obligated=NICK, party="bo@birch.org", deadline={"text": "by Friday", "value": "2026-11-13"})],
    })
    ing = app.mail(ex, fakes.Resolver(lambda m, c, s: ("new", m["kind"], m["label"])))
    ing.ingest(mail("a", "t1", DANA, [NICK], "2026-11-09T09:00:00-08:00", "The proposal is signed"))
    b = ing.ingest(mail("b", "t2", "bo@birch.org", [NICK], "2026-11-10T09:00:00-08:00",
                        "Hi Nick, could you review the proposal by Friday? Bo"))
    assert not b.refused and (b.written or b.held)
    lines = app.brief("2026-11-11T09:00-08:00").lines
    assert len(lines) == 1 and lines[0].text.startswith("Review: Birch proposal")


def test_candidates_are_filtered_by_kind(app):
    """Review defect 6: a deliverable's property is never written on a document."""
    ex = fakes.Extractor({
        "a": [proposal("statement", "The Acme contract is signed", [mention("the Acme contract", kind="document", label="Acme contract")], "signed", True)],
        "b": [proposal("statement", "the Acme deck is delivered", [mention("the Acme deck", kind="deliverable", label="Acme deck")], "delivered", True)],
    })
    ing = app.mail(ex, fakes.Resolver(lambda m, c, s: ("new", m["kind"], m["label"])))
    doc = app.ledger.claim(ing.ingest(mail("a", "t1", DANA, [NICK], "2026-11-09T09:00:00-08:00", "The Acme contract is signed")).written[0]).subject_id
    seen = []
    ing2 = app.mail(ex, fakes.Resolver(lambda m, c, s: (seen.append([x["id"] for x in c]), doc)[1]))
    out = ing2.ingest(mail("b", "t1", DANA, [NICK], "2026-11-10T09:00:00-08:00", "FYI the Acme deck is delivered"))
    assert all(doc not in ids_ for ids_ in seen)
    c = app.ledger.claim((out.written + out.held)[0])
    assert app.ledger.item(c.subject_id)["kind"] == "deliverable"


def test_name_check_on_existing_pick(app):
    """Nick's mechanism: a pick of an existing Item is checked against its recorded names."""
    v1, v2 = _two_decks(app)
    ex = fakes.Extractor({"m": [proposal("statement", "the budget is done", [mention("the budget", label="budget")],
                                         "delivered", True)]})
    out = app.mail(ex, fakes.Resolver(lambda m, c, s: v1)).ingest(
        mail("m", "tx", "ann@acme.com", [NICK], "2026-11-10T09:00:00-08:00", "Update: the budget is done."))
    assert app.ledger.revisions("name_check_failed")
    c = app.ledger.claim((out.written + out.held)[0])
    assert c.subject_id == v1 and "low_confidence" in c.flags


def test_model_failure_stores_nothing_and_retries(app):
    class Down:
        def extract(self, *a):
            raise RuntimeError("model call could not connect")
    import pytest
    with pytest.raises(RuntimeError):
        app.mail(Down(), fakes.Resolver(fakes.by_name)).ingest(_ask())
    assert app.ledger.message("ev:gmail:m1") is None
    out = app.mail(fakes.Extractor({"m1": [_commit()]}), fakes.Resolver(fakes.by_name)).ingest(_ask())
    assert out.written and not out.replay


def test_review_queue_catches_a_confident_pick_made_doubtful(app):
    """Review finding A: a confident pick enters the review queue once its name is shared by a
    second Item, and re-resolution rewrites it."""
    ex = fakes.Extractor({
        "a": [proposal("statement", "The proposal is signed", [mention("the proposal", kind="document", label="Acme proposal")], "signed", True)],
        "b": [proposal("statement", "the proposal was sent", [mention("the proposal", kind="document")], "sent", True)],
        "c": [proposal("statement", "the Birch proposal is reviewed", [mention("the proposal", kind="document", label="Birch proposal")],
                       "reviewed", True)],
    })
    target = {}
    ing = app.mail(ex, fakes.Resolver(lambda m, c, s: target.get("id") or ("new", m["kind"], m["label"])))
    a = app.ledger.claim(ing.ingest(mail("a", "t1", DANA, [NICK], "2026-11-09T09:00:00-08:00", "The proposal is signed")).written[0])
    target["id"] = a.subject_id                    # a unanimous pick of the Acme proposal
    b = ing.ingest(mail("b", "t1", DANA, [NICK], "2026-11-10T09:00:00-08:00", "FYI the proposal was sent")).written[0]
    assert ing.review_queue() == []
    target.clear()                                 # a second "proposal" arrives
    ing.ingest(mail("c", "t2", "bo@birch.org", [NICK], "2026-11-10T10:00:00-08:00", "the Birch proposal is reviewed"))
    assert b in ing.review_queue()
    birch = [i["id"] for i in app.ledger.active_items("document") if i["label"] == "Birch proposal"][0]
    target["id"] = birch
    app.ledger.link("thread:gmail:t1", birch, "2026-11-10T10:30:00-08:00")   # structure now supports Birch
    changed = ing.review()
    assert any(app.ledger.claim(x).subject_id == birch for x in changed)
    assert app.ledger.claim(b).status == "superseded"
