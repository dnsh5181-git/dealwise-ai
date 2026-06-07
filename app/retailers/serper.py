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

from ..brands import extract_brand
from .base import LiveProduct, RetailerProvider

_URL = "https://google.serper.dev/shopping"
_PRICE_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")

# Google Shopping mixes in listings that misrepresent the real "new" price:
# used/refurbished units, lease-to-own monthly payments, and accessories. These
# heuristics keep the catalog trustworthy (the user saw a TV at "$29.99 from My
# Way Leases" and a watch at a "Restored: Like New" price).

# Condition keywords in a title that mean it's not a new unit.
_USED_RE = re.compile(
    r"\b(renew(ed)?|refurb(ished)?|pre[- ]?owned|open[- ]?box|restored|"
    r"used|for parts|as[- ]is|scratch (and|&) dent)\b", re.I)

# Lease-to-own / rent-to-own — their "price" is a small monthly payment.
_LEASE_RE = re.compile(r"\b(lease|rent[- ]?to[- ]?own|month|/mo\b)", re.I)
_LEASE_SELLERS = {
    "my way leases", "flexshopper", "acima", "acima leasing", "katapult",
    "progressive leasing", "american first finance", "snap finance", "zibby",
    "aaron's", "rent-a-center", "rentacenter",
}

# How far below the median an offer may sit before we treat it as junk
# (accessory / lease payment / data error). 0.30 = drop anything under 30% of
# the median price in the result set.
_OUTLIER_FLOOR = 0.30


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


def _clean_store(store: str) -> str:
    """'Walmart - STARWAA WHOLESALE INC' -> 'Walmart'. Collapses a third-party
    marketplace seller suffix to the host store so the comparison stays clean."""
    base = re.split(r"\s[-–—]\s", store, maxsplit=1)[0].strip()
    return base or store


def _is_lease(store: str, title: str) -> bool:
    s = store.lower().strip()
    return (s in _LEASE_SELLERS or bool(_LEASE_RE.search(store))
            or bool(_LEASE_RE.search(title)))


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
        # Over-fetch so quality filtering still leaves ~limit clean offers.
        num = min(max(limit * 3, 10), 40)
        body = json.dumps({"q": query, "gl": self.country, "num": num}).encode("utf-8")
        req = urllib.request.Request(
            _URL, data=body, method="POST",
            headers={"X-API-KEY": self.api_key,
                     "Content-Type": "application/json",
                     "User-Agent": "DealWise-AI/0.1"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (https URL)
            data = json.loads(resp.read().decode("utf-8"))
        items = data.get("shopping", []) or []
        return self._clean(items, limit)

    def _clean(self, items: list[dict], limit: int) -> list[LiveProduct]:
        """Convert raw Serper items to LiveProducts, dropping non-new / lease /
        outlier listings so the catalog reflects real new-unit prices."""
        kept: list[LiveProduct] = []
        for it in items:
            title = (it.get("title") or "").strip()
            store = (it.get("source") or "").strip()
            if not title:
                continue
            if _USED_RE.search(title):          # refurbished / used / open-box
                continue
            if _is_lease(store, title):         # lease-to-own monthly payment
                continue
            lp = self._to_product(it)
            if lp.price > 0:
                kept.append(lp)
        # Outlier-low filter: drop offers far below the median (accessories,
        # lease payments, data errors). Needs a few points to be meaningful.
        if len(kept) >= 4:
            prices = sorted(p.price for p in kept)
            median = prices[len(prices) // 2]
            floor = median * _OUTLIER_FLOOR
            kept = [p for p in kept if p.price >= floor]
        return kept[:limit]

    def _to_product(self, it: dict) -> LiveProduct:
        raw_store = (it.get("source") or "").strip() or "Google Shopping"
        store = _clean_store(raw_store)
        title = (it.get("title") or "").strip()
        # Serper's productId is stable when present; otherwise derive a stable id
        # from store+title so re-ingests dedupe instead of duplicating.
        ext = str(it.get("productId") or "").strip()
        if not ext:
            ext = "gs-" + hashlib.sha1(f"{store}|{title}".encode()).hexdigest()[:16]
        return LiveProduct(
            external_id=ext,
            name=title,
            # Google Shopping has no clean brand field — derive it from the title.
            brand=extract_brand(title),
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
