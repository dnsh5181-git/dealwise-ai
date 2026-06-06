"""AI Shopping Assistant — grounded, deterministic natural-language answers.

This is the "AI" the spec describes ("must use internal platform data, no
hallucinations"), implemented without an LLM: it parses a shopping question into
an intent + constraints, runs the matching query against the catalog and the
deal/buy-now engines, and narrates an answer built *only* from that real data.

In production (Phase 2) an LLM can sit on top of this as a narration layer, but
it must call these same grounded functions for every number it states — so the
data path stays hallucination-free either way.

Supported intents:
  * best_in_category  — "best air fryer under $100", "best 65-inch TV under $1000"
  * should_i_buy      — "should I buy this TV now?"
  * best_retailer     — "which retailer gives the best deal for the Dyson?"
  * product_lookup    — "how much is the Apple Watch?"  (fallback)
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from . import engines

PRICE_RE = re.compile(
    r"(?:under|below|less than|cheaper than|no more than|max(?:imum)?|up to)\s*\$?\s*(\d+(?:\.\d+)?)"
)

# Common nouns -> catalog category, to sharpen matching.
CATEGORY_HINTS = {
    "air fryer": "Kitchen", "fryer": "Kitchen", "mixer": "Kitchen",
    "instant pot": "Kitchen", "pressure cooker": "Kitchen", "multicooker": "Kitchen",
    "tv": "Electronics", "television": "Electronics",
    "vacuum": "Home",
    "watch": "Wearables", "smartwatch": "Wearables",
    "console": "Gaming", "playstation": "Gaming", "ps5": "Gaming",
    "headphones": "Audio", "headphone": "Audio", "earphones": "Audio", "earbuds": "Audio",
}

# Query tokens that should also try a synonym when matching product names.
ALIASES = {"ps5": "playstation"}

# Filler / intent words stripped before product matching (never product nouns).
STOPWORDS = {
    "the", "a", "an", "is", "are", "am", "be", "i", "me", "my", "you", "your", "we",
    "what", "whats", "which", "who", "where", "when", "why", "how",
    "should", "would", "could", "can", "do", "does", "did", "to", "of", "for",
    "in", "on", "at", "by", "with",
    "buy", "buying", "wait", "now", "or", "and", "but", "get", "getting",
    "find", "show", "tell", "give", "gives", "gave",
    "best", "top", "good", "great", "better", "recommend", "recommendation",
    "suggest", "pick", "worth",
    "under", "below", "less", "than", "cheaper", "cheap", "cheapest", "max",
    "maximum", "up", "price", "prices", "cost", "costs",
    "retailer", "retailers", "store", "stores", "place", "deal", "deals",
    "value", "time",
    "this", "that", "these", "those", "it", "its", "please", "any", "some",
    "right", "currently", "today", "about", "vs", "versus", "between", "much",
}


def _money(x: float) -> str:
    return f"${x:,.2f}"


def parse_query(text: str) -> dict[str, Any]:
    """Extract intent, price ceiling, search tokens, and a category hint."""
    low = text.lower().strip()

    m = PRICE_RE.search(low)
    max_price = float(m.group(1)) if m else None

    cleaned = PRICE_RE.sub(" ", low)
    words = re.findall(r"[a-z0-9]+", cleaned)
    tokens = [w for w in words if w not in STOPWORDS and len(w) > 1]
    for t in list(tokens):
        if t in ALIASES and ALIASES[t] not in tokens:
            tokens.append(ALIASES[t])

    category_hint = None
    for phrase, cat in CATEGORY_HINTS.items():
        if phrase in low:
            category_hint = cat
            break

    if any(k in low for k in (
        "should i buy", "buy now or wait", "good time to buy",
        "is it a good deal", "buy it now", "worth buying",
    )):
        intent = "should_i_buy"
    elif any(k in low for k in (
        "which retailer", "what retailer", "best retailer", "where can i buy",
        "where should i buy", "where to buy", "cheapest place",
        "which store", "what store",
    )):
        intent = "best_retailer"
    elif any(k in low for k in ("best", "top ", "recommend", "suggest", "good ")):
        intent = "best_in_category"
    else:
        intent = "product_lookup"

    return {
        "intent": intent,
        "max_price": max_price,
        "tokens": tokens,
        "category_hint": category_hint,
    }


def find_products(conn: sqlite3.Connection, tokens: list[str], category_hint: str | None):
    """Rank catalog products by how many query tokens they match."""
    rows = conn.execute("SELECT * FROM products").fetchall()
    scored = []
    for r in rows:
        hay = f"{r['name']} {r['brand']} {r['category']}".lower()
        score = sum(1 for t in set(tokens) if t in hay)
        if category_hint and r["category"].lower() == category_hint.lower():
            score += 1
        if score > 0:
            scored.append((score, r))
    scored.sort(key=lambda sr: (-sr[0], sr[1]["name"]))
    return [r for _, r in scored]


def _enrich(conn, products, max_price):
    """Attach analysis to each product and apply the price ceiling."""
    out = []
    for r in products:
        a = engines.analyze(conn, r["id"])
        if not a:
            continue
        if max_price is not None and a["best_price"] > max_price:
            continue
        out.append((r, a))
    return out


def _card(r, a) -> dict[str, Any]:
    """The grounding data behind an answer (every number the text cites)."""
    return {
        "id": r["id"], "name": r["name"], "brand": r["brand"], "category": r["category"],
        "image_url": r["image_url"], "model_number": r["model_number"],
        "is_sample": r["source"] is None,
        "best_price": a["best_price"], "best_retailer": a["best_retailer"],
        "deal_score": a["deal_score"], "buy_now_score": a["buy_now_score"],
        "recommendation": a["recommendation"],
    }


def answer(conn: sqlite3.Connection, text: str) -> dict[str, Any]:
    """Return a grounded answer payload for a natural-language shopping query."""
    p = parse_query(text)
    found = find_products(conn, p["tokens"], p["category_hint"])
    enriched = _enrich(conn, found, p["max_price"])
    base = {
        "query": text,
        "intent": p["intent"],
        "constraints": {"max_price": p["max_price"], "keywords": p["tokens"]},
    }

    if not enriched:
        if found and p["max_price"] is not None:
            msg = (f"I found matching products, but none at or below "
                   f"{_money(p['max_price'])} right now.")
        else:
            msg = ("I couldn't find a matching product in the DealWise catalog. "
                   "Try a name like “Ninja Air Fryer”, “Dyson”, or "
                   "“PlayStation 5”.")
        return {**base, "intent": "no_match", "answer": msg, "results": []}

    if p["intent"] == "best_in_category":
        ranked = sorted(enriched, key=lambda ra: (-ra[1]["deal_score"], ra[1]["best_price"]))
        r, a = ranked[0]
        cap = f" under {_money(p['max_price'])}" if p["max_price"] else ""
        text_out = (f"Best pick{cap}: {r['name']} — {_money(a['best_price'])} at "
                    f"{a['best_retailer']} (deal score {a['deal_score']}/100, "
                    f"{a['recommendation']}). {a['reason']}")
        alts = ranked[1:3]
        if alts:
            text_out += " Alternatives: " + "; ".join(
                f"{rr['name']} {_money(aa['best_price'])} (deal {aa['deal_score']})"
                for rr, aa in alts)
        return {**base, "answer": text_out, "results": [_card(rr, aa) for rr, aa in ranked[:3]]}

    if p["intent"] == "should_i_buy":
        r, a = enriched[0]
        text_out = (f"{r['name']}: {a['recommendation']} (buy-now score "
                    f"{a['buy_now_score']}/100, confidence {a['confidence']}%). "
                    f"{a['reason']} Best price now is {_money(a['best_price'])} at "
                    f"{a['best_retailer']}.")
        return {**base, "answer": text_out, "results": [_card(r, a)]}

    if p["intent"] == "best_retailer":
        r, a = enriched[0]
        offers = sorted(a["offers"], key=lambda o: o["price"])
        comparison = "; ".join(f"{o['retailer']} {_money(o['price'])}" for o in offers)
        text_out = (f"For {r['name']}, the best price is {_money(a['best_price'])} at "
                    f"{a['best_retailer']}. Full comparison: {comparison}.")
        return {**base, "answer": text_out, "results": [_card(r, a)]}

    # product_lookup (fallback)
    r, a = enriched[0]
    text_out = (f"{r['name']} — best price {_money(a['best_price'])} at "
                f"{a['best_retailer']} (deal score {a['deal_score']}/100, "
                f"{a['recommendation']}). {a['reason']}")
    return {**base, "answer": text_out, "results": [_card(r, a)]}
