"""Ingest live retailer offers into the catalog.

Pulls products from a RetailerProvider and upserts them into the same
``products`` / ``retailers`` / ``prices`` tables the seed data uses, so the deal
and buy-now engines treat live products identically to seeded ones. Each ingest
records a fresh, timestamped price row — so repeated ingests accumulate genuine
price history, which is what makes the deal score meaningful over time.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .base import LiveProduct, RetailerProvider


def _ensure_retailer(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM retailers WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO retailers (name, affiliate_url, cashback_pct) VALUES (?, ?, 0)",
        (name, "https://dummyjson.com/products/"),
    )
    return cur.lastrowid


def _upsert_product(conn: sqlite3.Connection, source: str, lp: LiveProduct) -> tuple[int, bool]:
    """Insert or update a product keyed by (source, external_id). Returns (id, created)."""
    row = conn.execute(
        "SELECT id FROM products WHERE source = ? AND external_id = ?",
        (source, lp.external_id),
    ).fetchone()
    if row:
        conn.execute(
            """UPDATE products
               SET name = ?, brand = ?, category = ?, description = ?,
                   rating = ?, review_count = ?
               WHERE id = ?""",
            (lp.name, lp.brand, lp.category, lp.description,
             lp.rating, lp.review_count, row["id"]),
        )
        return row["id"], False
    cur = conn.execute(
        """INSERT INTO products
           (name, brand, category, description, rating, review_count, source, external_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (lp.name, lp.brand, lp.category, lp.description,
         lp.rating, lp.review_count, source, lp.external_id),
    )
    return cur.lastrowid, True


def _record_price(conn: sqlite3.Connection, product_id: int, retailer_id: int,
                  price: float, in_stock: bool) -> None:
    conn.execute(
        """INSERT INTO prices (product_id, retailer_id, price, in_stock, recorded_at)
           VALUES (?, ?, ?, ?, datetime('now'))""",
        (product_id, retailer_id, price, 1 if in_stock else 0),
    )


def ingest_search(conn: sqlite3.Connection, provider: RetailerProvider,
                  query: str, limit: int = 10) -> dict[str, Any]:
    """Fetch live offers for ``query`` and upsert them. Returns a summary."""
    products = provider.search(query, limit)
    retailer_id = _ensure_retailer(conn, provider.name)

    added = 0
    updated = 0
    product_ids: list[int] = []
    for lp in products:
        pid, created = _upsert_product(conn, provider.name, lp)
        _record_price(conn, pid, retailer_id, lp.price, lp.in_stock)
        product_ids.append(pid)
        added += int(created)
        updated += int(not created)

    conn.commit()
    return {
        "retailer": provider.name,
        "query": query,
        "fetched": len(products),
        "added": added,
        "updated": updated,
        "product_ids": product_ids,
    }
