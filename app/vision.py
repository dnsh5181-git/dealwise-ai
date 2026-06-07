"""Visual product search — identify a product from a photo with Claude vision.

The user snaps or uploads a photo; we ask Claude to name the product and produce
a short search query DealWise can run against its catalog (and live retailers).

This layer is **strictly optional**, mirroring ``narrator.py``: it degrades to a
clear "unavailable" result whenever the LLM isn't usable —
  * ``ANTHROPIC_API_KEY`` is not set, or
  * the ``anthropic`` package isn't importable, or
  * the API call raises / returns nothing usable.

So the app still runs fully offline; visual search is pure enhancement.

Model defaults to ``claude-opus-4-8``; override with ``DEALWISE_LLM_MODEL``
(e.g. ``claude-haiku-4-5`` for cheaper, faster vision).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

DEFAULT_MODEL = "claude-opus-4-8"

# Accepted inbound image media types (what browsers produce from a canvas/camera).
ALLOWED_MEDIA = {"image/jpeg", "image/png", "image/webp", "image/gif"}

SYSTEM_PROMPT = """You identify retail products from a photo for a shopping price-comparison app.

Look at the image and identify the single most prominent purchasable product.

Reply with ONLY a JSON object (no markdown, no prose) of this exact shape:
{
  "query": "<2-5 word search query a shopper would type, e.g. 'Ninja air fryer'>",
  "name": "<best full product name you can read or infer>",
  "brand": "<brand if visible, else empty string>",
  "category": "<one of: Electronics, Kitchen, Home, Wearables, Gaming, Audio, Other>",
  "confidence": <0-100 integer: how sure you are>
}

Rules:
- "query" must be generic enough to match listings (brand + product type), not a
  full marketing title.
- If you cannot identify any product, return query "" and confidence 0.
- Never invent a specific model number you cannot see."""


def is_enabled() -> bool:
    """True when an Anthropic API key is configured."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _unavailable(reason: str) -> dict[str, Any]:
    return {"ok": False, "reason": reason, "query": "", "confidence": 0}


def _extract_json(text: str) -> dict[str, Any] | None:
    """Parse the model's reply as JSON, tolerating stray code fences/prose."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def identify(image_b64: str, media_type: str = "image/jpeg") -> dict[str, Any]:
    """Identify a product from a base64-encoded image.

    Returns a dict with ``ok`` (bool). On success also: ``query``, ``name``,
    ``brand``, ``category``, ``confidence``. On failure: ``ok=False`` + ``reason``.
    Never raises — callers can use the result unconditionally.
    """
    if media_type not in ALLOWED_MEDIA:
        return _unavailable(f"Unsupported image type: {media_type}")
    if not is_enabled():
        return _unavailable("Visual search needs ANTHROPIC_API_KEY set in .env.")

    try:
        import anthropic
    except ImportError:
        return _unavailable("The 'anthropic' package isn't installed.")

    model = os.environ.get("DEALWISE_LLM_MODEL", DEFAULT_MODEL)
    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model=model,
            max_tokens=256,
            thinking={"type": "disabled"},
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": media_type, "data": image_b64,
                    }},
                    {"type": "text", "text": "Identify this product."},
                ],
            }],
        )
    except Exception as exc:  # network / auth / rate limit / bad request
        return _unavailable(f"Vision request failed: {exc}")

    text = "".join(b.text for b in message.content if b.type == "text").strip()
    data = _extract_json(text)
    if not data or not str(data.get("query", "")).strip():
        return _unavailable("Couldn't identify a product in that photo.")

    return {
        "ok": True,
        "query": str(data.get("query", "")).strip(),
        "name": str(data.get("name", "")).strip(),
        "brand": str(data.get("brand", "")).strip(),
        "category": str(data.get("category", "")).strip(),
        "confidence": int(data.get("confidence", 0) or 0),
    }
