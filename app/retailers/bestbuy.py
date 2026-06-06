"""Best Buy provider — the first REAL US retailer integration.

Best Buy offers a free official Product API (https://developer.bestbuy.com).
This gives genuine US prices, product images, and manufacturer model numbers for
electronics and appliances (air fryers, TVs, laptops, headphones, etc.) — the
categories this app targets first.

Needs a free API key in the ``BESTBUY_API_KEY`` env var (auto-loaded from the
gitignored ``.env`` by ``app/main.py``). Uses stdlib urllib (no extra dep).

Compliance note: we link out to the Best Buy product URL to buy ("delivery" =
the retailer fulfills); the URL is the affiliate seam — append your Impact/CJ
affiliate parameters here once your Best Buy affiliate account is approved.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

from .base import LiveProduct, RetailerProvider

_SHOW = ",".join([
    "sku", "name", "manufacturer", "modelNumber",
    "salePrice", "regularPrice", "onlineAvailability",
    "image", "url", "customerReviewAverage", "customerReviewCount",
    "shortDescription", "categoryPath.name",
])


class BestBuyProvider(RetailerProvider):
    name = "BestBuy"
    base_url = "https://api.bestbuy.com/v1"

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout
        self.api_key = os.environ.get("BESTBUY_API_KEY", "")

    def search(self, query: str, limit: int = 10) -> list[LiveProduct]:
        if not self.api_key:
            raise RuntimeError(
                "BESTBUY_API_KEY is not set. Add it to .env "
                "(get a free key at https://developer.bestbuy.com)."
            )
        # Best Buy search syntax: products((search=air&search=fryer)) — words AND'd.
        terms = "&".join(f"search={urllib.parse.quote(w)}" for w in query.split() if w)
        path = f"products(({terms}))" if terms else "products"
        params = urllib.parse.urlencode({
            "apiKey": self.api_key, "format": "json",
            "pageSize": limit, "show": _SHOW,
        })
        url = f"{self.base_url}/{path}?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "DealWise-AI/0.1"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (https URL)
            data = json.loads(resp.read().decode("utf-8"))
        return [self._to_product(p) for p in data.get("products", [])]

    def _to_product(self, p: dict) -> LiveProduct:
        category = ""
        cats = p.get("categoryPath")
        if isinstance(cats, list) and cats:
            category = (cats[-1] or {}).get("name", "") or ""
        price = p.get("salePrice")
        if price is None:
            price = p.get("regularPrice") or 0.0
        return LiveProduct(
            external_id=str(p.get("sku")),
            name=(p.get("name") or "").strip(),
            brand=(p.get("manufacturer") or "Unknown").strip(),
            category=category,
            description=p.get("shortDescription", "") or "",
            price=float(price),
            in_stock=bool(p.get("onlineAvailability")),
            rating=float(p.get("customerReviewAverage") or 0.0),
            review_count=int(p.get("customerReviewCount") or 0),
            url=p.get("url", "") or "",
            image_url=p.get("image", "") or "",
            model_number=(p.get("modelNumber") or "").strip(),
        )
