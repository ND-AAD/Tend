"""Sixth review (2026-11-11): a kill at any statement, and two commands at once.

The kill sweep (tests/crash/, adopted from the reviewer's probes) stops a real child process before a
chosen SQL statement of an operation, opens a fresh App as the next command would, reads the list,
then retries the operation and reads it again. By default every TEND_SWEEP_STRIDE-th statement and the
last fifteen are tried; TEND_SWEEP=all tries every statement (minutes per scenario).
"""
from __future__ import annotations

import os
import sys
import threading

import pytest

from gh import pr_event
from tend import ingest_github as gh
from tend.app import App
from tend.projector import Busy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "crash"))
import sweep  # noqa: E402

POINTS = "all" if os.environ.get("TEND_SWEEP") == "all" else f"stride={os.environ.get('TEND_SWEEP_STRIDE', '40')}"


@pytest.mark.parametrize("scenario", ["mail", "github", "late", "owner", "nightly"])
def test_a_kill_at_any_statement_leaves_a_true_list(scenario):
    r = sweep.sweep(scenario, POINTS)
    assert r["baseline_ok"]
    assert r["child_errors"] == []
    assert r["wrong_after_kill"] == [] and r["wrong_after_retry"] == [], r["examples"]
    assert r["retry_differs"] == [], r


# -- two commands at once (Z1) ----------------------------------------------------------------------

def _pr(action, at, reviewers, **x):
    p = pr_event(action, at=at, **x)
    p["pull_request"]["requested_reviewers"] = [{"login": r} for r in reviewers]
    return p


OPENED = ("pull_request", _pr("opened", "2026-11-05T10:00:00Z", []))
REQUESTED = ("pull_request", _pr("review_requested", "2026-11-05T11:00:00Z", ["ND-AAD"],
                                 requested_reviewer={"login": "ND-AAD"}))
REVIEW = "Review: Add ledger (attedra#7), asked by gh:alice-dev"


def _listed(app):
    return " ".join(l.text for l in app.brief("now").lines)


def test_an_event_ingested_while_another_command_rebuilds_waits_and_is_listed(app):
    """The second command starts between the first command's replay and its swap. It waits for
    the ledger, then appends into the projection the first command swapped in."""
    gh.ingest(*OPENED, app.cfg, app.ledger, app.projector)
    app.brief("now")
    other = App(app.cfg)
    real = app.projector._replay
    done = {}

    def second_command():
        try:
            done["id"] = gh.ingest(*REQUESTED, other.cfg, other.ledger, other.projector)
        except Exception as e:      # pragma: no cover - reported by the assertion below
            done["error"] = e

    t = threading.Thread(target=second_command)

    def replay_then_the_other_command_starts():
        real()
        t.start()
        t.join(0.5)                                  # it is waiting for the ledger, not writing
        assert t.is_alive() and not done
    app.projector._replay = replay_then_the_other_command_starts
    try:
        app.projector.rebuild("owner", "requested from the command line")
    finally:
        app.projector._replay = real
    t.join(10)
    other.close()
    assert "error" not in done and done.get("id")
    fresh = App(app.cfg)
    try:
        assert fresh.ledger.meta("stale") == "0" and fresh.ledger.unprojected() == []
        assert REVIEW in _listed(fresh)
    finally:
        fresh.close()


def test_a_command_that_cannot_get_the_ledger_records_nothing(app, monkeypatch):
    gh.ingest(*OPENED, app.cfg, app.ledger, app.projector)
    other = App(app.cfg)
    other.projector.lock_wait = 0.2
    n = len(app.ledger.messages())
    try:
        with app.projector.exclusive():
            with pytest.raises(Busy):
                gh.ingest(*REQUESTED, other.cfg, other.ledger, other.projector)
        assert len(app.ledger.messages()) == n
        gh.ingest(*REQUESTED, other.cfg, other.ledger, other.projector)     # run again: recorded and listed
    finally:
        other.close()
    assert REVIEW in _listed(app)


def test_a_process_follows_a_projection_another_command_swapped_in(app):
    gh.ingest(*OPENED, app.cfg, app.ledger, app.projector)
    other = App(app.cfg)
    try:
        before = app.projector.schema
        other.projector.rebuild("owner", "another command")       # drops the schema `app` was using
        gh.ingest(*REQUESTED, app.cfg, app.ledger, app.projector)
        assert app.projector.schema != before
        assert REVIEW in _listed(app) and REVIEW in _listed(other)
    finally:
        other.close()


# -- a kill at the end of a rebuild (Z2) --------------------------------------------------------------

def test_the_change_entries_commit_with_the_swap(app, monkeypatch):
    """A failure after the swap was prepared and before the entries are written leaves the old
    projection, the ledger still stale, and no entry; the next rebuild writes all of it."""
    gh.ingest(*OPENED, app.cfg, app.ledger, app.projector)
    gh.ingest(*REQUESTED, app.cfg, app.ledger, app.projector)
    app.brief("now")
    cid = [c.id for c in app.ledger.active_claims() if c.kind == "commitment"][0]
    with app.ledger.conn.transaction():
        app.ledger.drop_claim(cid, "test", "not a request after all")
    old = app.ledger.meta("projection_schema")
    real = app.projector._record_changes

    def killed(*a, **k):
        real(*a, **k)
        raise SystemExit("killed after the entries, before the commit")
    monkeypatch.setattr(app.projector, "_record_changes", killed)
    with pytest.raises(SystemExit):
        app.projector.rebuild("tend", "test")
    assert app.ledger.meta("projection_schema") == old and app.ledger.meta("stale") == "1"
    assert app.ledger.revisions("obligation_changed") == []
    monkeypatch.undo()
    out = " / ".join(l.text for l in app.brief("now").lines if l.section == "Changed by my re-checks")
    assert len(app.ledger.revisions("obligation_changed")) == 1 and "no longer open" in out
