"""The Claude call path, against a stub client: request shape, JSON parsing, refusal handling."""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from tend import llm


class Stub:
    def __init__(self, stop_reason="end_turn", payload=None):
        self.kw = None
        self.resp = NS(stop_reason=stop_reason, content=[NS(type="thinking"), NS(type="text", text=json.dumps(payload))])
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.kw = kw
        return self.resp


def test_extractor_request_shape():
    s = Stub(payload={"proposals": []})
    ex = llm.ClaudeExtractor("claude-opus-5-5", "high", client=s)
    assert ex.extract("body", {"producer_id": "p", "recipients": [], "sent_at": "x"}, {"items": []}) == []
    assert s.kw["model"] == "claude-opus-5-5"
    assert s.kw["output_config"]["effort"] == "high"
    assert s.kw["output_config"]["format"]["schema"] is llm.PROPOSAL_SCHEMA
    assert s.kw["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in s.kw["betas"]
    assert "temperature" not in s.kw


def test_refusal_raises():
    with pytest.raises(llm.ModelRefused):
        llm.ClaudeJudge("claude-opus-5-5", client=Stub("refusal", {})).same({}, {}, {})


def test_judge_parses():
    j = llm.ClaudeJudge("claude-opus-5-5", client=Stub(payload={"same": True, "reason": "same URL"}))
    assert j.same({"id": "a"}, {"id": "b"}, {}) == (True, "same URL")
