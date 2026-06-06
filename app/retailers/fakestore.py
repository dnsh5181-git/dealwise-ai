"""Second live retailer provider — Fake Store API (https://fakestoreapi.com).

Another free, key-free public commerce API. Its only job is to prove the
``RetailerProvider`` abstraction: adding a retailer is exactly one class with a
``search()`` method — ingestion, the engines, the API, and the UI are unchanged.

Fake Store has no search endpoint, so we fetch the catalog and filter
client-side. Uses stdlib urllib (no extra runtime dependency).
"""

from __future__ import annotations

import json
import urllib.request

from .base import LiveProduct, RetailerProvider


class FakeStoreProvider(RetailerProvider):
    name = "FakeStore"
    base_url = "https://fakestoreapi.com"

    def __init__(self, timeout: float = 8.0):
        self.timeout = timeout

    def search(self, query: str, limit: int = 10) -> list[LiveProduct]:
        req = urllib.request.Request(
            f"{self.base_url}/products", headers={"User-Agent": "DealWise-AI/0.1"}
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (https URL)
            data = json.loads(resp.read().decode("utf-8"))

        q = query.lower().strip()
        out: list[LiveProduct] = []
        for p in data:
            haystack = f"{p.get('title', '')} {p.get('category', '')}".lower()
            if q and q not in haystack:
                continue
            out.append(self._to_product(p))
        return out[:limit]

    def _to_product(self, p: dict) -> LiveProduct:
        rating = p.get("rating") or {}
        return LiveProduct(
            external_id=str(p.get("id")),
            name=p.get("title", "").strip(),
            brand="Unknown",  # Fake Store has no brand field
            category=(p.get("category") or "").replace("-", " ").title(),
            description=p.get("description", ""),
            price=float(p.get("price") or 0.0),
            in_stock=True,  # Fake Store has no stock field
            rating=float(rating.get("rate") or 0.0),
            review_count=int(rating.get("count") or 0),
            url=f"{self.base_url}/products/{p.get('id')}",
        )
