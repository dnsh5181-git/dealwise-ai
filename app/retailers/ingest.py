"""Ingest live retailer offers into the catalog.

Pulls products from a RetailerProvider and upserts them into the same
``products`` / ``retailers`` / ``prices`` tables the seed data uses, so the deal
and buy-now engines treat live products identically to seeded ones. Each ingest
records a fresh, timestamped price row — so repeated ingests accumulate genuine
price history, which is what makes the deal score meaningful over time.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from .base import LiveProduct, RetailerProvider


def normalize_name(name: str) -> str:
    """Lowercase alphanumeric tokens joined by single spaces — for cross-retailer matching."""
    return " ".join(re.findall(r"[a-z0-9]+", name.lower()))


def _ensure_retailer(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM retailers WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO retailers (name, affiliate_url, cashback_pct) VALUES (?, ?, 0)",
        (name, "https://dummyjson.com/products/"),
    )
    return cur.lastrowid


def _upsert_product(conn: sqlite3.Connection, source: str, lp: LiveProduct) -> tuple[int, str]:
    """Resolve a product id for a live offer. Returns (id, status).

    status is one of:
      * "updated" — same provider re-ingesting its own product (by external_id)
      * "matched" — same product from a *different* retailer (by normalized name);
                    its price attaches to the existing product, enabling
                    cross-retailer comparison without duplicating the catalog entry
      * "added"   — a genuinely new product

    Cross-retailer matching only considers other *live* products (``source`` not
    NULL), so it never merges into the curated seed catalog. It's a deliberately
    simple exact-normalized-name match — a stand-in for the production canonical
    product graph (entity resolution).
    """
    norm = normalize_name(lp.name)

    # 1) Same provider re-ingesting the same product -> refresh fields.
    row = conn.execute(
        "SELECT id FROM products WHERE source = ? AND external_id = ?",
        (source, lp.external_id),
    ).fetchone()
    if row:
        conn.execute(
            """UPDATE products
               SET name = ?, brand = ?, category = ?, description = ?,
                   rating = ?, review_count = ?, norm_name = ?, image_url = ?,
                   model_number = ?, buy_url = ?
               WHERE id = ?""",
            (lp.name, lp.brand, lp.category, lp.description,
             lp.rating, lp.review_count, norm, lp.image_url,
             lp.model_number, lp.url, row["id"]),
        )
        return row["id"], "updated"

    # 2) Same product from another retailer -> attach price to the existing row.
    if norm:
        row = conn.execute(
            "SELECT id FROM products WHERE source IS NOT NULL AND norm_name = ? LIMIT 1",
            (norm,),
        ).fetchone()
        if row:
            return row["id"], "matched"

    # 3) New product.
    cur = conn.execute(
        """INSERT INTO products
           (name, brand, category, description, image_url, rating, review_count,
            model_number, buy_url, source, external_id, norm_name)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (lp.name, lp.brand, lp.category, lp.description, lp.image_url,
         lp.rating, lp.review_count, lp.model_number, lp.url,
         source, lp.external_id, norm),
    )
    return cur.lastrowid, "added"


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

    counts = {"added": 0, "updated": 0, "matched": 0}
    product_ids: list[int] = []
    for lp in products:
        pid, status = _upsert_product(conn, provider.name, lp)
        _record_price(conn, pid, retailer_id, lp.price, lp.in_stock)
        product_ids.append(pid)
        counts[status] += 1

    conn.commit()
    return {
        "retailer": provider.name,
        "query": query,
        "fetched": len(products),
        **counts,
        "product_ids": product_ids,
    }
