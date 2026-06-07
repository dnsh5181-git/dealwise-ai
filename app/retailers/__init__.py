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
    "GoogleShopping": GoogleShoppingProvider,
    "eBay": EbayProvider,
    "BestBuy": BestBuyProvider,
    "DummyJSON": DummyJSONProvider,
    "FakeStore": FakeStoreProvider,
}

# Real retailers vs. demo/testing APIs (surfaced in the UI so nothing fake looks real).
_DEMO_PROVIDERS = {"DummyJSON", "FakeStore"}

# Google Shopping (Serper) is the default real source: one key aggregates many US
# stores (Walmart/Target/Amazon/Best Buy/…). eBay and Best Buy remain available
# for anyone with those keys. (eBay's free Developer Program can reject personal
# registrations, so it's no longer the default.)
DEFAULT_PROVIDER = "GoogleShopping"


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
