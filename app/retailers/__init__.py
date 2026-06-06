"""Retailer integrations: a provider abstraction + a registry of providers.

Adding a retailer is one class implementing ``RetailerProvider.search()`` plus
one line in ``_PROVIDERS`` below — nothing else in the platform changes.
"""

from __future__ import annotations

from .base import LiveProduct, RetailerProvider
from .bestbuy import BestBuyProvider
from .dummyjson import DummyJSONProvider
from .fakestore import FakeStoreProvider

_PROVIDERS: dict[str, type[RetailerProvider]] = {
    "BestBuy": BestBuyProvider,
    "DummyJSON": DummyJSONProvider,
    "FakeStore": FakeStoreProvider,
}

# Real retailers vs. demo/testing APIs (surfaced in the UI so nothing fake looks real).
_DEMO_PROVIDERS = {"DummyJSON", "FakeStore"}

DEFAULT_PROVIDER = "BestBuy"


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
    "FakeStoreProvider",
    "LiveProduct",
    "RetailerProvider",
    "available",
    "default_provider",
    "get_provider",
    "is_demo",
]
