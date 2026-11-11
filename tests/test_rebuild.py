"""SPEC §12 cases 6, 8 and 9: rebuild reproduces the store, owner acts survive it, a failed
rebuild keeps the previous projection."""
from __future__ import annotations

import pytest
from attedra_ref.errors import WriteError

import fakes
from tend.projector import RebuildFailed
from test_mail import NICK, _ask, _commit


def snapshot(app) -> dict:
    s = app.ledger.meta("projection_schema")
    q = app.ledger._q
    return {
        "items": q(f'SELECT id, kind, label, definition::text FROM "{s}".items ORDER BY id'),
        "assertions": q(f'SELECT item_id, context_id, source_id, "values"::text, recorded_by FROM "{s}".assertions '
                        "ORDER BY 1, 2, 3"),
        "connections": q(f'SELECT from_id, to_id, properties::text FROM "{s}".connections ORDER BY 1, 2'),
    }


def _seed(app):
    ex = fakes.Extractor({"m1": [_commit()]})
    out = app.mail(ex, fakes.Resolver(fakes.by_name)).ingest(_ask())
    return out.written[0]


def test_rebuild_reproduces_store(app):
    _seed(app)
    before = snapshot(app)
    assert before["assertions"]
    assert app.projector.rebuild("test") == "proj_2"
    assert snapshot(app) == before
    app.projector.rebuild("test")
    assert snapshot(app) == before


def test_supersede_rewrites_without_trace(app):
    cid = _seed(app)
    new = app.ledger.supersede_claim(cid, "tend", "misread the deadline", deadline="2026-11-14-08:00")
    app.projector.rebuild("tend", "correction")
    s = snapshot(app)
    ctx = [a for a in s["assertions"] if a[1].startswith("expctx:")]
    assert [a[1] for a in ctx] == ["expctx:" + new]
    assert not any(cid + '"' in a[3] or a[0] == "act:" + cid for a in s["assertions"])
    assert app.ledger.revisions("supersede_claim")[0]["detail"]["successor"] == new


def test_owner_acts_survive_rebuild(app):
    cid = _seed(app)
    when = "2026-11-11T09:00-08:00"
    assert len(app.brief(when).lines) == 1
    app.owner_act("snooze", cid, "2026-11-10T12:00:00-08:00", until="2026-11-12-08:00")
    assert app.brief(when).lines == []
    new = app.ledger.supersede_claim(cid, "tend", "deadline was Monday", deadline="2026-11-16-08:00")
    app.projector.rebuild()
    assert app.brief(when).lines == []                       # the snooze now targets the successor
    assert len(app.brief("2026-11-13T09:00-08:00").lines) == 1   # and lapses at its @until
    app.ledger.drop_claim(new, "tend", "not a request after all")
    app.projector.rebuild()
    assert app.ledger.revisions("owner_act_dropped")
    assert app.brief("2026-11-13T09:00-08:00").lines == []


def test_withdraw_act(app):
    cid = _seed(app)
    app.owner_act("withdraw", cid, "2026-11-10T12:00:00-08:00", note="Dana cancelled in person")
    assert app.brief("2026-11-11T09:00-08:00").lines == []


def test_failed_rebuild_keeps_projection(app, monkeypatch):
    _seed(app)
    before, schema = snapshot(app), app.ledger.meta("projection_schema")

    def boom(_id):
        raise WriteError("occupied", "forced")
    monkeypatch.setattr(app.projector, "project_message", boom)
    with pytest.raises(RebuildFailed):
        app.projector.rebuild("test")
    assert app.ledger.meta("projection_schema") == schema
    assert snapshot(app) == before
    assert app.ledger.revisions("rebuild_failed")
    assert len(app.brief("2026-11-11T09:00-08:00").lines) == 1


# -- second review (2026-11-11) ----------------------------------------------------------------

def test_any_rebuild_failure_restores(app, monkeypatch):
    _seed(app)
    before = snapshot(app)

    def boom(_id):
        raise ValueError("not a WriteError")
    monkeypatch.setattr(app.projector, "project_message", boom)
    with pytest.raises(RebuildFailed):
        app.projector.rebuild("test")
    monkeypatch.undo()
    assert app.projector.schema == app.ledger.meta("projection_schema") == "proj_1"
    assert snapshot(app) == before


def test_failed_append_is_repaired_by_refresh(app, monkeypatch):
    ing = app.mail(fakes.Extractor({"m1": [_commit()]}), fakes.Resolver(fakes.by_name))

    def boom(_id):
        raise WriteError("occupied", "forced")
    monkeypatch.setattr(app.projector, "project_message", boom)
    with pytest.raises(WriteError):
        ing.ingest(_ask())
    monkeypatch.undo()
    assert app.ledger.meta("stale") == "1"
    assert ing.ingest(_ask()).replay                      # the ledger kept it
    assert len(app.brief("2026-11-11T09:00-08:00").lines) == 1   # the list rebuilt first
    assert app.ledger.meta("stale") == "0"


def test_out_of_order_arrival_matches_rebuild(app):
    from fakes import mail, mention, proposal
    from test_mail import DANA
    ex = fakes.Extractor({"m1": [_commit()], "m2": [proposal("statement", "Here is the revised Acme deck",
                          [mention("the revised Acme deck", "existing", "?")], "delivered", True)]})
    ing = app.mail(ex, fakes.Resolver(fakes.by_name))
    ing.ingest(mail("m2", "t1", NICK, [DANA], "2026-11-11T10:00:00-08:00", "Here is the revised Acme deck."))
    ing.ingest(_ask())                                      # sent earlier, arrives later
    assert app.ledger.meta("stale") == "1"
    mid = [l.text for l in app.brief("2026-11-11T09:00-08:00").lines]   # refresh rebuilds
    in_order = snapshot(app)
    app.projector.rebuild("test")
    assert snapshot(app) == in_order
    assert len(mid) == 1


def test_rebuild_reproduces_two_messages(app):
    from fakes import mail, mention, proposal
    from test_mail import DANA
    ex = fakes.Extractor({"m1": [_commit()], "m2": [proposal("statement", "Here is the revised Acme deck",
                          [mention("the revised Acme deck", "existing", "?")], "delivered", True)]})
    ing = app.mail(ex, fakes.Resolver(fakes.by_name))
    ing.ingest(_ask())
    ing.ingest(mail("m2", "t1", NICK, [DANA], "2026-11-11T10:00:00-08:00", "Here is the revised Acme deck."))
    before = snapshot(app)
    app.projector.rebuild("test")
    assert snapshot(app) == before
