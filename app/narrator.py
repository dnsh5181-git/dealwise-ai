"""Optional LLM narration layer for the AI Shopping Assistant.

Takes the *grounded* payload from ``assistant.answer()`` and rewrites only its
``answer`` text in a warmer, more conversational tone — without inventing or
altering a single number, price, retailer, product, or recommendation. Every
figure it may use is already present in the deterministic payload, so the data
path stays hallucination-free even with an LLM in the loop.

This layer is **strictly optional**. It returns the deterministic answer
unchanged whenever the LLM isn't usable:
  * ``ANTHROPIC_API_KEY`` is not set, or
  * the ``anthropic`` package isn't importable, or
  * the API call raises / returns nothing.

So the app still runs fully offline; narration is pure enhancement.

Model defaults to ``claude-opus-4-8``; override with ``DEALWISE_LLM_MODEL``
(e.g. ``claude-haiku-4-5`` for a cheaper, faster narration).
"""

from __future__ import annotations

import json
import os
from typing import Any

DEFAULT_MODEL = "claude-opus-4-8"

# Static system prompt — kept byte-stable so the prompt-caching breakpoint below
# stays valid across requests. (Note: it's well under Opus 4.8's 4096-token
# minimum cacheable prefix, so caching only actually engages if this prompt
# grows substantially or a smaller-minimum model is configured. The breakpoint
# is correct either way.)
SYSTEM_PROMPT = """You are the voice of DealWise AI, a shopping-intelligence assistant.

You receive a JSON object produced by a deterministic engine: the user's `query`,
the detected `intent`, a plain `answer`, and a `results` list of products with real
prices, retailers, deal scores, and buy-now recommendations.

Rewrite the `answer` in a warm, concise, conversational tone (2-4 sentences).

Hard rules — non-negotiable:
- Use ONLY facts present in the JSON. Never invent or change a price, retailer,
  score, product name, or recommendation.
- Never introduce a product that isn't in `results`.
- Don't give shopping advice beyond what the answer/recommendation already states.
- If `intent` is "no_match", briefly and helpfully say nothing matched; do not
  name any product or price.
- Preserve currency formatting exactly as written (e.g. $78.92).
- Reply with ONLY the rewritten answer text: no preamble, no headers, no bullet
  lists, no surrounding quotes, no notes about your process."""


def is_enabled() -> bool:
    """True when an Anthropic API key is configured."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def narrate(payload: dict[str, Any]) -> dict[str, Any]:
    """Return ``payload`` with ``answer`` rephrased by the LLM when possible.

    Always adds ``narrated`` (bool). On the LLM path also adds ``answer_raw``
    (the original deterministic text). Falls back to the deterministic answer on
    any error so callers can use the result unconditionally.
    """
    deterministic = payload.get("answer", "")

    if not is_enabled():
        return {**payload, "narrated": False}

    try:
        import anthropic
    except ImportError:
        return {**payload, "narrated": False}

    model = os.environ.get("DEALWISE_LLM_MODEL", DEFAULT_MODEL)
    # Send only the grounding the model needs. sort_keys keeps the user turn
    # deterministic for a given query (stable bytes → cache-friendly).
    grounding = json.dumps(
        {
            "query": payload.get("query"),
            "intent": payload.get("intent"),
            "answer": deterministic,
            "results": payload.get("results", []),
        },
        sort_keys=True,
    )

    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model=model,
            max_tokens=512,
            thinking={"type": "disabled"},
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": grounding}],
        )
    except Exception:
        # Network error, auth error, rate limit, bad request — degrade silently.
        return {**payload, "narrated": False}

    text = "".join(b.text for b in message.content if b.type == "text").strip()
    if not text:
        return {**payload, "narrated": False}

    return {**payload, "answer": text, "answer_raw": deterministic, "narrated": True}
