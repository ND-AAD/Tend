"""Deterministic Item ids (SPEC §3). A rebuild must reproduce the same store from the same ledger."""
from __future__ import annotations

import hashlib
import re


def _h(*parts: str, n: int = 16) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:n]


def person_email(address: str) -> str:
    return f"person:{address.strip().lower()}"


def person_gh(login: str) -> str:
    return f"person:gh:{login.strip().lower()}"


def stream(person_id: str) -> str:
    return f"corr:{person_id}"


def gh_log(repo: str) -> str:
    return f"ghlog:{repo.lower()}"


def event(provider: str, provider_id: str) -> str:
    return f"ev:{provider}:{provider_id}"


def thread(provider: str, thread_id: str) -> str:
    return f"thread:{provider}:{thread_id}"


def pr(repo: str, n: int) -> str:
    return f"pr:{repo.lower()}/{n}"


def issue(repo: str, n: int) -> str:
    return f"issue:{repo.lower()}/{n}"


def slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return s[:40] or "item"


def resolved_item(kind: str, label: str, message_id: str) -> str:
    return f"{kind}:{slug(label)}-{_h(message_id, label, n=6)}"


def claim(message_id: str, ordinal: int, extractor: str) -> str:
    return "c-" + _h(message_id, str(ordinal), extractor)


def expctx(claim_id: str) -> str:
    return f"expctx:{claim_id}"


def act(claim_id: str) -> str:
    return f"act:{claim_id}"


def elig(person_id: str) -> str:
    return f"elig:{person_id}"


SETUP_CONTEXT = "ev:setup"
ELIGIBILITY_CONTEXT = "ev:eligibility"   # dated at EPOCH so that evidence of any date qualifies (3.3.2)
EPOCH = "1970-01-01+00:00"
CONFIG_SOURCE = "src:assistant-config"
SCOPE = "scope:owner"
OWNER_REVIEW = "src:owner-review"


def owner_act(act_id: str) -> tuple[str, str]:
    return f"act:human:{act_id}", f"ev:human:{act_id}"
