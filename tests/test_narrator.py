"""Tests for the optional LLM narration layer.

The Anthropic SDK is mocked, so these run with no API key and no network — CI
exercises every branch (disabled, narrated, model override, caching, fallbacks).
"""

from __future__ import annotations

import pytest

from app import narrator

BASE = {
    "query": "best air fryer under $100",
    "intent": "best_in_category",
    "answer": "Best pick under $100.00: Ninja Air Fryer Pro 5-Qt — $78.92 at Amazon "
              "(deal score 89/100, Buy Now).",
    "constraints": {"max_price": 100.0, "keywords": ["air", "fryer"]},
    "results": [{
        "id": 1, "name": "Ninja Air Fryer Pro 5-Qt", "best_price": 78.92,
        "best_retailer": "Amazon", "deal_score": 89, "buy_now_score": 90,
        "recommendation": "Buy Now",
    }],
}


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Msg:
    def __init__(self, text):
        self.content = [_Block(text)]


class _FakeMessages:
    def create(self, **kwargs):
        _FakeClient.last_kwargs = kwargs
        return _Msg(_FakeClient.reply)


class _FakeClient:
    last_kwargs = None
    reply = "Friendly rewrite."

    def __init__(self, *args, **kwargs):
        self.messages = _FakeMessages()


@pytest.fixture
def fake_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("DEALWISE_LLM_MODEL", raising=False)
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)
    _FakeClient.last_kwargs = None
    _FakeClient.reply = "Friendly rewrite."
    return _FakeClient


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = narrator.narrate(BASE)
    assert out["narrated"] is False
    assert out["answer"] == BASE["answer"]
    assert "answer_raw" not in out


def test_narrates_with_key(fake_anthropic):
    out = narrator.narrate(BASE)
    assert out["narrated"] is True
    assert out["answer"] == "Friendly rewrite."
    assert out["answer_raw"] == BASE["answer"]
    # Grounded fields pass through untouched.
    assert out["results"] == BASE["results"]
    assert out["intent"] == BASE["intent"]
    assert out["constraints"] == BASE["constraints"]


def test_uses_default_model_and_prompt_caching(fake_anthropic):
    narrator.narrate(BASE)
    kw = fake_anthropic.last_kwargs
    assert kw["model"] == "claude-opus-4-8"
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    # Grounding is sent as the user turn and includes the real price.
    user_content = kw["messages"][0]["content"]
    assert "78.92" in user_content


def test_model_override(fake_anthropic, monkeypatch):
    monkeypatch.setenv("DEALWISE_LLM_MODEL", "claude-haiku-4-5")
    narrator.narrate(BASE)
    assert fake_anthropic.last_kwargs["model"] == "claude-haiku-4-5"


def test_falls_back_on_exception(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    import anthropic

    class _Boom:
        def __init__(self, *a, **k):
            self.messages = self

        def create(self, **k):
            raise RuntimeError("network down")

    monkeypatch.setattr(anthropic, "Anthropic", _Boom)
    out = narrator.narrate(BASE)
    assert out["narrated"] is False
    assert out["answer"] == BASE["answer"]


def test_falls_back_on_empty_completion(fake_anthropic):
    fake_anthropic.reply = "   "
    out = narrator.narrate(BASE)
    assert out["narrated"] is False
    assert out["answer"] == BASE["answer"]
