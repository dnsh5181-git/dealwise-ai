"""Retailer integrations: a provider abstraction + concrete providers."""

from __future__ import annotations

from .base import LiveProduct, RetailerProvider
from .dummyjson import DummyJSONProvider


def default_provider() -> RetailerProvider:
    """The retailer provider used by the API/UI ingest endpoints."""
    return DummyJSONProvider()


__all__ = ["DummyJSONProvider", "LiveProduct", "RetailerProvider", "default_provider"]
