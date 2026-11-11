from tend import brief, ingest_github as gh
from gh import pr_event, review_submitted


def ingest(app, name, payload):
    return gh.ingest(name, payload, app.cfg, app.ledger, app.projector)


def test_review_request_opens_and_review_closes_it(app):
    ingest(app, "pull_request", pr_event("opened"))
    ingest(app, "pull_request", pr_event("review_requested", at="2026-11-10T17:05:00Z",
                                         requested_reviewer={"login": "ND-AAD"}))
    b = brief.build(app.session, app.ledger, app.cfg, cutoff="2026-11-11T09:00:00+00:00")
    mine = b.section("Your commitments")
    assert len(mine) == 1 and "Add ledger" in mine[0].text and "alice-dev" in mine[0].text
    ingest(app, "pull_request_review", review_submitted())
    b = brief.build(app.session, app.ledger, app.cfg, cutoff="2026-11-12T09:00:00+00:00")
    assert b.lines == []
    # the earlier cutoff still shows it: nothing was overwritten
    b = brief.build(app.session, app.ledger, app.cfg, cutoff="2026-11-11T09:00:00+00:00")
    assert len(b.section("Your commitments")) == 1


def test_review_request_removed_withdraws(app):
    ingest(app, "pull_request", pr_event("opened"))
    ingest(app, "pull_request", pr_event("review_requested", at="2026-11-10T17:05:00Z",
                                         requested_reviewer={"login": "ND-AAD"}))
    ingest(app, "pull_request", pr_event("review_request_removed", at="2026-11-10T19:00:00Z",
                                         requested_reviewer={"login": "ND-AAD"}))
    b = brief.build(app.session, app.ledger, app.cfg, cutoff="2026-11-11T09:00:00+00:00")
    assert b.lines == []


def test_replayed_event_is_idempotent(app):
    e = pr_event("review_requested", requested_reviewer={"login": "ND-AAD"})
    ingest(app, "pull_request", e)
    ingest(app, "pull_request", e)
    assert len(app.ledger.active_claims()) == 1


def test_review_requested_of_someone_else_is_not_mine(app):
    ingest(app, "pull_request", pr_event("review_requested", requested_reviewer={"login": "bob"}))
    assert app.ledger.active_claims() == []


# -- second review (2026-11-11): one test per fixed finding ------------------------------------

def _issue(action, n=3, at="2026-11-10T17:00:00Z", sender="alice-dev", **extra):
    from gh import REPO
    p = {"action": action, "repository": REPO, "sender": {"login": sender},
         "issue": {"number": n, "title": "Fix replay", "user": {"login": "alice-dev"},
                   "html_url": f"https://github.com/ND-AAD/attedra/issues/{n}", "created_at": at, "updated_at": at}}
    p.update(extra)
    return p


def _ing(app, name, payload):
    from tend import ingest_github as gh
    return gh.ingest(name, payload, app.cfg, app.ledger, app.projector)


def _texts(app, cutoff):
    return [l.text for l in app.brief(cutoff).lines]


def test_rerequested_review_reappears(app):
    from gh import pr_event, review_submitted
    _ing(app, "pull_request", pr_event("opened"))
    _ing(app, "pull_request", pr_event("review_requested", at="2026-11-10T17:05:00Z", requested_reviewer={"login": "ND-AAD"}))
    _ing(app, "pull_request_review", review_submitted(at="2026-11-11T18:00:00Z"))
    assert _texts(app, "2026-11-12T09:00:00+00:00") == []
    _ing(app, "pull_request", pr_event("review_requested", at="2026-11-12T10:00:00Z", requested_reviewer={"login": "ND-AAD"}))
    assert len(_texts(app, "2026-11-13T09:00:00+00:00")) == 1
    _ing(app, "pull_request_review", review_submitted(at="2026-11-13T18:00:00Z", review_id=100))
    assert _texts(app, "2026-11-14T09:00:00+00:00") == []


def test_issue_closed_by_someone_else_leaves_the_list(app):
    _ing(app, "issues", _issue("opened"))
    _ing(app, "issues", _issue("assigned", at="2026-11-10T17:05:00Z", assignee={"login": "ND-AAD"}))
    _ing(app, "issues", _issue("closed", at="2026-11-11T12:00:00Z", sender="alice-dev"))
    assert _texts(app, "2026-11-20T09:00:00+00:00") == []


def test_merged_pr_withdraws_pending_review(app):
    from gh import pr_event
    _ing(app, "pull_request", pr_event("opened"))
    _ing(app, "pull_request", pr_event("review_requested", at="2026-11-10T17:05:00Z", requested_reviewer={"login": "ND-AAD"}))
    _ing(app, "pull_request", pr_event("closed", at="2026-11-11T12:00:00Z", merged=True))
    assert _texts(app, "2026-11-20T09:00:00+00:00") == []


def test_reopened_and_reassigned_issue_returns(app):
    _ing(app, "issues", _issue("opened"))
    _ing(app, "issues", _issue("assigned", at="2026-11-10T17:05:00Z", assignee={"login": "ND-AAD"}))
    _ing(app, "issues", _issue("closed", at="2026-11-11T12:00:00Z", sender="ND-AAD"))
    _ing(app, "issues", _issue("reopened", at="2026-11-12T12:00:00Z"))
    _ing(app, "issues", _issue("unassigned", at="2026-11-12T12:01:00Z", assignee={"login": "ND-AAD"}))
    _ing(app, "issues", _issue("assigned", at="2026-11-12T12:05:00Z", assignee={"login": "ND-AAD"}))
    assert len(_texts(app, "2026-11-13T09:00:00+00:00")) == 1


def test_evidence_before_setup_qualifies(app):
    from gh import pr_event, review_submitted
    _ing(app, "pull_request", pr_event("opened", at="2026-10-05T10:00:00Z"))
    _ing(app, "pull_request", pr_event("review_requested", at="2026-10-05T10:05:00Z", requested_reviewer={"login": "ND-AAD"}))
    _ing(app, "pull_request_review", review_submitted(at="2026-10-06T18:00:00Z"))
    assert _texts(app, "2026-11-11T09:00:00+00:00") == []


def test_open_prs_of_yours_wait_on_you(app):
    """Real-data finding (2026-11-11): agents open pull requests under the owner's account, so a
    PR the owner opened or was assigned is waiting on the owner to merge or close it."""
    from gh import pr_event
    _ing(app, "pull_request", pr_event("opened", n=8, sender="nd-aad", author="nd-aad"))
    _ing(app, "pull_request", pr_event("opened", n=9, sender="alice-dev"))
    _ing(app, "pull_request", pr_event("assigned", n=9, at="2026-11-10T17:05:00Z", assignee={"login": "ND-AAD"}))
    texts = _texts(app, "2026-11-11T09:00:00+00:00")
    assert sorted(texts) == ["Merge or close: Add ledger (attedra#8)", "Merge or close: Add ledger (attedra#9), asked by gh:alice-dev"]
    _ing(app, "pull_request", pr_event("closed", n=8, at="2026-11-11T12:00:00Z", sender="nd-aad", merged=True,
                                       author="nd-aad"))
    _ing(app, "pull_request", pr_event("closed", n=9, at="2026-11-11T12:00:00Z", sender="alice-dev", merged=True))
    assert _texts(app, "2026-11-12T09:00:00+00:00") == []


def test_quiet_work_is_marked_not_overdue(app):
    """A PR with no activity for QUIET_DAYS is marked untouched; it is not made overdue."""
    from gh import pr_event
    from tend import brief
    _ing(app, "pull_request", pr_event("opened", n=8, at="2026-10-15T01:00:00Z", sender="nd-aad", author="nd-aad"))
    lines = app.brief("2026-10-20T09:00:00+00:00").lines
    assert [l.text for l in lines] == ["Merge or close: Add ledger (attedra#8)"]
    lines = app.brief("2026-11-11T09:00:00+00:00").lines
    assert [(l.section, l.text) for l in lines] == [
        ("Your commitments", "Merge or close: Add ledger (attedra#8), untouched for 27 days")]
    assert brief.QUIET_RULE == "quiet-v1" and brief.QUIET_DAYS == 7
