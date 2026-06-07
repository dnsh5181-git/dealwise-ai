"""Google Shopping aggregator via Serper (https://serper.dev).

Unlike the single-retailer providers (eBay, Best Buy), this returns offers from
*many* US stores — Walmart, Target, Amazon, Home Depot, etc. — in one response.
Each offer carries its real store name in ``LiveProduct.retailer`` so the ingest
layer attributes its price to that store, which is what powers the app's
cross-retailer price comparison.

This is the practical way to cover dozens of retailers that have no free public
product API: one key, one call, many stores. Serper's free tier is ~2,500
queries/month (the same service used in the NutriLens project).

Needs ``SERPER_API_KEY`` in the gitignored ``.env`` (auto-loaded by
``app/main.py``). Uses stdlib urllib (no extra dependency).

Compliance note: results link out to the real store product page (``buy_url``);
that link is the affiliate seam — the store fulfills delivery.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request

from .base import LiveProduct, RetailerProvider

_URL = "https://google.serper.dev/shopping"
_PRICE_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")


def _parse_price(raw) -> float:
    """'$1,234.56' / '$78.92' / 78.92 -> float. Unparseable -> 0.0."""
    if isinstance(raw, (int, float)):
        return float(raw)
    if not raw:
        return 0.0
    m = _PRICE_RE.search(str(raw))
    if not m:
        return 0.0
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return 0.0


class GoogleShoppingProvider(RetailerProvider):
    name = "GoogleShopping"

    def __init__(self, timeout: float = 12.0, country: str = "us"):
        self.timeout = timeout
        self.country = country
        self.api_key = os.environ.get("SERPER_API_KEY", "")

    def search(self, query: str, limit: int = 10) -> list[LiveProduct]:
        if not self.api_key:
            raise RuntimeError(
                "SERPER_API_KEY is not set. Add it to .env "
                "(free tier ~2,500 queries/mo at https://serper.dev)."
            )
        body = json.dumps({"q": query, "gl": self.country, "num": limit}).encode("utf-8")
        req = urllib.request.Request(
            _URL, data=body, method="POST",
            headers={"X-API-KEY": self.api_key,
                     "Content-Type": "application/json",
                     "User-Agent": "DealWise-AI/0.1"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (https URL)
            data = json.loads(resp.read().decode("utf-8"))
        items = data.get("shopping", []) or []
        out = [self._to_product(it) for it in items[:limit]]
        # Drop offers with no usable price — they can't be compared or scored.
        return [p for p in out if p.price > 0]

    def _to_product(self, it: dict) -> LiveProduct:
        store = (it.get("source") or "").strip() or "Google Shopping"
        title = (it.get("title") or "").strip()
        # Serper's productId is stable when present; otherwise derive a stable id
        # from store+title so re-ingests dedupe instead of duplicating.
        ext = str(it.get("productId") or "").strip()
        if not ext:
            ext = "gs-" + hashlib.sha1(f"{store}|{title}".encode()).hexdigest()[:16]
        return LiveProduct(
            external_id=ext,
            name=title,
            brand="Unknown",  # Google Shopping doesn't return a clean brand field
            category="",
            description=(it.get("delivery") or "").strip(),
            price=_parse_price(it.get("price")),
            in_stock=True,
            rating=float(it.get("rating") or 0.0),
            review_count=int(it.get("ratingCount") or 0),
            url=(it.get("link") or "").strip(),
            image_url=(it.get("imageUrl") or "").strip(),
            model_number="",
            retailer=store,
        )
