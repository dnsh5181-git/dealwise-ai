"""AI-generated product specifications.

Retail/aggregator sources rarely return structured specs, so we synthesize them
from the product name + category with Claude and cache the JSON on the product
row (``products.specs``). Generation happens lazily on first product-page view.

Strictly optional, like ``vision.py`` / ``narrator.py``: without a usable LLM it
returns ``available=False`` and the product page simply omits the specs section.

Model defaults to ``claude-opus-4-8``; override with ``DEALWISE_LLM_MODEL``.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from typing import Any

DEFAULT_MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """You are a product-specifications expert for a shopping app.

Given a product name (and maybe a category), output its typical specifications as
a shopper would see on a spec sheet. Use widely-known facts for that exact model;
where a detail varies by configuration, give the common/base value.

Reply with ONLY a JSON object of this exact shape (no markdown, no prose):
{
  "summary": "<one-sentence plain-language description>",
  "groups": [
    {"name": "<section, e.g. 'Display'>",
     "specs": [{"label": "<attribute>", "value": "<value>"}]}
  ]
}

Rules:
- 3-6 groups, each with 2-6 specs. Be concrete (numbers, units).
- Only include specs you are reasonably confident apply to this product type.
- Never invent a precise model number or a price. No marketing fluff.
- If the product is too vague to spec, return {"summary": "", "groups": []}."""


def is_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


def _generate(name: str, category: str) -> dict[str, Any] | None:
    """Call Claude for specs. Returns the parsed dict, or None on any failure."""
    if not is_enabled():
        return None
    try:
        import anthropic
    except ImportError:
        return None
    model = os.environ.get("DEALWISE_LLM_MODEL", DEFAULT_MODEL)
    user = f"Product: {name}"
    if category:
        user += f"\nCategory: {category}"
    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model=model,
            max_tokens=900,
            thinking={"type": "disabled"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
    except Exception:
        return None
    text = "".join(b.text for b in message.content if b.type == "text").strip()
    data = _extract_json(text)
    if not isinstance(data, dict) or not data.get("groups"):
        return None
    # Keep only the well-formed shape we render.
    groups = []
    for g in data.get("groups", []):
        specs = [{"label": str(s.get("label", "")).strip(),
                  "value": str(s.get("value", "")).strip()}
                 for s in g.get("specs", [])
                 if str(s.get("label", "")).strip() and str(s.get("value", "")).strip()]
        if specs:
            groups.append({"name": str(g.get("name", "")).strip() or "Specs", "specs": specs})
    if not groups:
        return None
    return {"summary": str(data.get("summary", "")).strip(), "groups": groups}


def get_specs(conn: sqlite3.Connection, product_id: int) -> dict[str, Any]:
    """Return cached specs, generating + caching them on first request.

    Result always has ``available`` (bool). When available, also ``summary`` and
    ``groups``. Never raises.
    """
    row = conn.execute(
        "SELECT name, category, specs FROM products WHERE id = ?", (product_id,)
    ).fetchone()
    if not row:
        return {"available": False, "reason": "Product not found."}

    if row["specs"]:
        try:
            cached = json.loads(row["specs"])
            return {"available": True, **cached}
        except json.JSONDecodeError:
            pass  # corrupt cache -> regenerate

    data = _generate(row["name"], row["category"] or "")
    if not data:
        return {"available": False,
                "reason": "Specs unavailable (needs ANTHROPIC_API_KEY)."
                if not is_enabled() else "Couldn't generate specs for this product."}

    conn.execute("UPDATE products SET specs = ? WHERE id = ?",
                 (json.dumps(data), product_id))
    conn.commit()
    return {"available": True, **data}
