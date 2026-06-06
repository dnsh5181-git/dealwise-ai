"""Retailer integrations: a provider abstraction + a registry of providers.

Adding a retailer is one class implementing ``RetailerProvider.search()`` plus
one line in ``_PROVIDERS`` below — nothing else in the platform changes.
"""

from __future__ import annotations

from .base import LiveProduct, RetailerProvider
from .dummyjson import DummyJSONProvider
from .fakestore import FakeStoreProvider

_PROVIDERS: dict[str, type[RetailerProvider]] = {
    "DummyJSON": DummyJSONProvider,
    "FakeStore": FakeStoreProvider,
}

DEFAULT_PROVIDER = "DummyJSON"


def available() -> list[str]:
    """Names of all configured retailer providers."""
    return list(_PROVIDERS)


def get_provider(name: str | None = None) -> RetailerProvider:
    """Instantiate a provider by name. ``None`` -> the default. Unknown -> KeyError."""
    cls = _PROVIDERS[name or DEFAULT_PROVIDER]
    return cls()


def default_provider() -> RetailerProvider:
    return get_provider(DEFAULT_PROVIDER)


__all__ = [
    "DEFAULT_PROVIDER",
    "DummyJSONProvider",
    "FakeStoreProvider",
    "LiveProduct",
    "RetailerProvider",
    "available",
    "default_provider",
    "get_provider",
]
