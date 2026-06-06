"""Retailer-provider abstraction.

A ``RetailerProvider`` knows how to search one retailer/source and return
normalized ``LiveProduct`` records. The rest of the platform (ingestion, the
deal/buy-now engines, search) is provider-agnostic — adding a real retailer
(Amazon PA-API, Walmart, Best Buy) means writing one more class with a
``search()`` method, nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LiveProduct:
    """A product + current offer fetched live from a retailer."""
    external_id: str          # the provider's stable id, for dedupe across ingests
    name: str
    brand: str
    category: str
    description: str
    price: float
    in_stock: bool
    rating: float
    review_count: int
    url: str


class RetailerProvider:
    """Interface every retailer integration implements."""

    name: str = "base"

    def search(self, query: str, limit: int = 10) -> list[LiveProduct]:
        raise NotImplementedError
