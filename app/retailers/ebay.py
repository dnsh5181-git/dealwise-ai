"""eBay provider — real US marketplace data, free Developer Program (accepts a
personal email like Gmail).

Uses the **Browse API** (`item_summary/search`). Auth is OAuth2
client-credentials: create a free app at https://developer.ebay.com, take the
**App ID** (Client ID) and **Cert ID** (Client Secret) from your *production*
keyset, and put them in `.env`:

    EBAY_CLIENT_ID=...
    EBAY_CLIENT_SECRET=...

We fetch an application access token (~2h) and cache it module-side so we don't
re-auth on every search. Uses stdlib urllib (no extra dependency).

Note: eBay is a marketplace (new + used listings). The search summary has no
manufacturer model number or product-review score, so `model_number` is left
empty and `rating`/`review_count` are 0.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse
import urllib.request

from .base import LiveProduct, RetailerProvider

_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
_SCOPE = "https://api.ebay.com/oauth/api_scope"

# Module-level application-token cache (shared across provider instances).
_token_cache: dict[str, object] = {"value": "", "expires_at": 0.0}


class EbayProvider(RetailerProvider):
    name = "eBay"
    marketplace = "EBAY_US"

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout
        self.client_id = os.environ.get("EBAY_CLIENT_ID", "")
        self.client_secret = os.environ.get("EBAY_CLIENT_SECRET", "")

    def _get_token(self) -> str:
        now = time.time()
        cached = _token_cache["value"]
        if cached and float(_token_cache["expires_at"]) > now + 60:
            return str(cached)
        if not (self.client_id and self.client_secret):
            raise RuntimeError(
                "EBAY_CLIENT_ID / EBAY_CLIENT_SECRET not set. Add them to .env "
                "(free production keyset at https://developer.ebay.com)."
            )
        cred = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        body = urllib.parse.urlencode(
            {"grant_type": "client_credentials", "scope": _SCOPE}
        ).encode()
        req = urllib.request.Request(
            _TOKEN_URL, data=body, method="POST",
            headers={"Authorization": f"Basic {cred}",
                     "Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
        token = data["access_token"]
        _token_cache["value"] = token
        _token_cache["expires_at"] = now + float(data.get("expires_in", 7200))
        return token

    def search(self, query: str, limit: int = 10) -> list[LiveProduct]:
        token = self._get_token()
        params = urllib.parse.urlencode({"q": query, "limit": limit})
        req = urllib.request.Request(
            f"{_SEARCH_URL}?{params}",
            headers={"Authorization": f"Bearer {token}",
                     "X-EBAY-C-MARKETPLACE-ID": self.marketplace,
                     "User-Agent": "DealWise-AI/0.1"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
        return [self._to_product(it) for it in data.get("itemSummaries", [])]

    def _to_product(self, it: dict) -> LiveProduct:
        price = (it.get("price") or {}).get("value") or 0.0
        image = (it.get("image") or {}).get("imageUrl") or ""
        if not image:
            thumbs = it.get("thumbnailImages") or []
            image = (thumbs[0].get("imageUrl") if thumbs else "") or ""
        cats = it.get("categories") or []
        category = (cats[0].get("categoryName") if cats else "") or ""
        condition = it.get("condition") or ""
        return LiveProduct(
            external_id=str(it.get("itemId") or ""),
            name=(it.get("title") or "").strip(),
            brand="Unknown",
            category=category,
            description=f"Condition: {condition}" if condition else "",
            price=float(price),
            in_stock=True,
            rating=0.0,
            review_count=0,
            url=it.get("itemAffiliateWebUrl") or it.get("itemWebUrl") or "",
            image_url=image,
            model_number="",
        )
