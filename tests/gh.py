"""GitHub webhook payload builders for tests."""
REPO = {"full_name": "ND-AAD/attedra"}


def pr_event(action, n=7, at="2026-11-10T17:00:00Z", sender="alice-dev", merged=False, **extra):
    p = {"action": action, "repository": REPO, "sender": {"login": sender},
         "pull_request": {"number": n, "title": "Add ledger", "user": {"login": "alice-dev"},
                          "html_url": f"https://github.com/ND-AAD/attedra/pull/{n}",
                          "created_at": at, "updated_at": at, "merged": merged}}
    p.update(extra)
    return p


def review_submitted(n=7, at="2026-11-11T18:00:00Z", reviewer="nd-aad", review_id=99):
    return {"action": "submitted", "repository": REPO, "sender": {"login": reviewer},
            "review": {"id": review_id, "submitted_at": at, "state": "approved"},
            "pull_request": {"number": n, "title": "Add ledger", "user": {"login": "alice-dev"},
                             "html_url": f"https://github.com/ND-AAD/attedra/pull/{n}",
                             "created_at": at, "updated_at": at}}
