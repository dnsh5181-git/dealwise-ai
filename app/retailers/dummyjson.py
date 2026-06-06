"""First live retailer provider — DummyJSON (https://dummyjson.com).

DummyJSON is a free, key-free public commerce API. It stands in as the live
data source for the MVP: real HTTP, real JSON, real product/price fields, with
no credentials or ToS friction. A production retailer integration (PA-API,
Walmart, Best Buy) would subclass RetailerProvider the same way — only this file
changes, not the engines or ingestion.

Uses stdlib urllib so the project gains no extra runtime dependency.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .base import LiveProduct, RetailerProvider


class DummyJSONProvider(RetailerProvider):
    name = "DummyJSON"
    base_url = "https://dummyjson.com"

    def __init__(self, timeout: float = 8.0):
        self.timeout = timeout

    def search(self, query: str, limit: int = 10) -> list[LiveProduct]:
        params = urllib.parse.urlencode({"q": query, "limit": limit})
        url = f"{self.base_url}/products/search?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "DealWise-AI/0.1"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (https URL)
            data = json.loads(resp.read().decode("utf-8"))
        return [self._to_product(p) for p in data.get("products", [])]

    def _to_product(self, p: dict) -> LiveProduct:
        reviews = p.get("reviews")
        review_count = len(reviews) if isinstance(reviews, list) else 0
        return LiveProduct(
            external_id=str(p.get("id")),
            name=p.get("title", "").strip(),
            brand=(p.get("brand") or "Unknown").strip(),
            category=(p.get("category") or "").replace("-", " ").title(),
            description=p.get("description", ""),
            price=float(p.get("price") or 0.0),
            in_stock=int(p.get("stock") or 0) > 0,
            rating=float(p.get("rating") or 0.0),
            review_count=review_count,
            url=f"{self.base_url}/products/{p.get('id')}",
            image_url=p.get("thumbnail") or (p.get("images") or [""])[0] or "",
        )
