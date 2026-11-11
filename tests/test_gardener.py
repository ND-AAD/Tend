"""SPEC §12 case 7: an Item split across two threads is merged, and evidence recorded against one
fulfils the expectation on the other after the rebuild."""
from __future__ import annotations

import fakes
from tend import gardener
from fakes import mail, mention, proposal
from test_mail import DANA, NICK, _ask, _commit


def test_merge_fulfils_split_expectation(app):
    ex = fakes.Extractor({
        "m1": [_commit()],
        # a new thread, and the resolver missed the link: a second Item for the same deck
        "m2": [proposal("statement", "Attached is the Q4 board deck", [mention("the Q4 board deck", label="Q4 board deck")],
                        "delivered", True)],
    })
    new_always = fakes.Resolver(lambda m, c, s: ("new", "deliverable", m["label"]))
    ing = app.mail(ex, new_always)
    a = app.ledger.claim(ing.ingest(_ask()).written[0]).subject_id
    b = app.ledger.claim(ing.ingest(mail("m2", "t2", NICK, [DANA], "2026-11-11T10:00:00-08:00",
                                         "Attached is the Q4 board deck.")).written[0]).subject_id
    assert a != b
    when = "2026-11-12T09:00-08:00"
    assert len(app.brief(when).lines) == 1                   # still open: the evidence is on b

    pairs = gardener.detect(app.ledger, app.cfg)
    assert (pairs[0].a, pairs[0].b) == tuple(sorted((a, b))) and pairs[0].rule == "neighbourhood"
    judge = fakes.Judge(True)
    merged = gardener.run(app.ledger, app.cfg, app.projector, judge)
    assert merged == [(a, b, "scripted judgement")]           # the older Item survives
    assert app.ledger.root(b) == a
    assert app.brief(when).lines == []


def test_judge_says_different(app):
    ex = fakes.Extractor({"m1": [_commit()], "m2": [proposal("statement", "Attached is the Q4 board deck",
                          [mention("the Q4 board deck")], "delivered", True)]})
    ing = app.mail(ex, fakes.Resolver(lambda m, c, s: ("new", "deliverable", m["label"])))
    ing.ingest(_ask())
    ing.ingest(mail("m2", "t2", NICK, [DANA], "2026-11-11T10:00:00-08:00", "Attached is the Q4 board deck."))
    assert gardener.run(app.ledger, app.cfg, app.projector, fakes.Judge(False)) == []
    assert app.ledger.revisions("judged")


def test_uncertainty_mass(app):
    ex = fakes.Extractor({"m1": [_commit()]})
    app.mail(ex, fakes.Resolver(fakes.by_name)).ingest(_ask())
    assert gardener.doubt(app.ledger) == {}     # a confident claim is not a best reading


def test_shared_correspondent_is_not_identity_and_verdicts_are_remembered(app):
    """Review defect 11."""
    labels = ["Acme deck", "Birch budget", "Cedar site plan"]
    ex = fakes.Extractor({f"m{i}": [proposal("statement", f"The {l} is started", [mention(f"the {l}", label=l)],
                                             "status", "in_progress")] for i, l in enumerate(labels)})
    ing = app.mail(ex, fakes.Resolver(lambda m, c, s: ("new", "deliverable", m["label"])))
    for i, l in enumerate(labels):
        ing.ingest(mail(f"m{i}", f"t{i}", DANA, [NICK], f"2026-11-0{i+5}T09:00:00-08:00", f"The {l} is started"))
    assert gardener.detect(app.ledger, app.cfg) == []


def test_different_verdict_not_asked_again_until_evidence_grows(app):
    ex = fakes.Extractor({"m1": [_commit()], "m2": [proposal("statement", "Attached is the Q4 board deck",
                          [mention("the Q4 board deck")], "delivered", True)],
                          "m3": [proposal("statement", "the Q4 board deck is final", [mention("the Q4 board deck")],
                                          "status", "done")]})
    ing = app.mail(ex, fakes.Resolver(lambda m, c, s: ("new", "deliverable", m["label"])))
    ing.ingest(_ask())
    ing.ingest(mail("m2", "t2", NICK, [DANA], "2026-11-11T10:00:00-08:00", "Attached is the Q4 board deck."))
    j = fakes.Judge(False)
    gardener.run(app.ledger, app.cfg, app.projector, j)
    n = len(j.asked)
    assert n >= 1
    gardener.run(app.ledger, app.cfg, app.projector, j)
    assert len(j.asked) == n                                  # same evidence: not asked again
