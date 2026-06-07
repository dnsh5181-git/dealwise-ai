"""Retailer integrations: a provider abstraction + a registry of providers.

Adding a retailer is one class implementing ``RetailerProvider.search()`` plus
one line in ``_PROVIDERS`` below — nothing else in the platform changes.
"""

from __future__ import annotations

from .base import LiveProduct, RetailerProvider
from .bestbuy import BestBuyProvider
from .dummyjson import DummyJSONProvider
from .ebay import EbayProvider
from .fakestore import FakeStoreProvider
from .serper import GoogleShoppingProvider

_PROVIDERS: dict[str, type[RetailerProvider]] = {
    "eBay": EbayProvider,
    "GoogleShopping": GoogleShoppingProvider,
    "BestBuy": BestBuyProvider,
    "DummyJSON": DummyJSONProvider,
    "FakeStore": FakeStoreProvider,
}

# Real retailers vs. demo/testing APIs (surfaced in the UI so nothing fake looks real).
_DEMO_PROVIDERS = {"DummyJSON", "FakeStore"}

# eBay is the default real source for v1 (free Developer Program accepts personal
# email; Best Buy requires a business-domain email for its key).
DEFAULT_PROVIDER = "eBay"


def available() -> list[str]:
    """Names of all configured retailer providers."""
    return list(_PROVIDERS)


def is_demo(name: str) -> bool:
    """True for demo/testing providers (not real retailers)."""
    return name in _DEMO_PROVIDERS


def get_provider(name: str | None = None) -> RetailerProvider:
    """Instantiate a provider by name. ``None`` -> the default. Unknown -> KeyError."""
    cls = _PROVIDERS[name or DEFAULT_PROVIDER]
    return cls()


def default_provider() -> RetailerProvider:
    return get_provider(DEFAULT_PROVIDER)


__all__ = [
    "DEFAULT_PROVIDER",
    "BestBuyProvider",
    "DummyJSONProvider",
    "EbayProvider",
    "FakeStoreProvider",
    "GoogleShoppingProvider",
    "LiveProduct",
    "RetailerProvider",
    "available",
    "default_provider",
    "get_provider",
    "is_demo",
]
