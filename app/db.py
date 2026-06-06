"""SQLite data layer for DealWise AI.

We use the stdlib ``sqlite3`` driver directly (no ORM) to keep the MVP
dependency-light and fully runnable on a stock Python install. In production
this maps cleanly onto PostgreSQL + a price-history table partitioned by month
(see docs/ARCHITECTURE.md).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "dealwise.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS retailers (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    affiliate_url   TEXT,
    cashback_pct    REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    brand           TEXT,
    category        TEXT,
    description     TEXT,
    image_url       TEXT,
    rating          REAL DEFAULT 0,
    review_count    INTEGER DEFAULT 0,
    barcode         TEXT,
    model_number    TEXT,            -- manufacturer model number / SKU (from real providers)
    buy_url         TEXT,            -- outbound product URL to buy at the retailer (affiliate seam)
    source          TEXT,            -- provider name for live-ingested products (NULL for seed)
    external_id     TEXT,            -- provider's product id, for dedupe across ingests
    norm_name       TEXT,            -- normalized name, for matching the same product across retailers
    created_at      TEXT DEFAULT (datetime('now'))
);

-- Price history. One row per (product, retailer, day). This is the table that
-- scales to "1 billion price records" in the production design.
CREATE TABLE IF NOT EXISTS prices (
    id              INTEGER PRIMARY KEY,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    retailer_id     INTEGER NOT NULL REFERENCES retailers(id),
    price           REAL NOT NULL,
    in_stock        INTEGER NOT NULL DEFAULT 1,
    recorded_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coupons (
    id              INTEGER PRIMARY KEY,
    product_id      INTEGER REFERENCES products(id),
    retailer_id     INTEGER REFERENCES retailers(id),
    code            TEXT,
    description     TEXT,
    discount_type   TEXT,            -- 'percent' | 'amount'
    value           REAL
);

CREATE TABLE IF NOT EXISTS inventory (
    id              INTEGER PRIMARY KEY,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    retailer_id     INTEGER NOT NULL REFERENCES retailers(id),
    store_name      TEXT,
    distance_mi     REAL,
    in_stock        INTEGER DEFAULT 1,
    pickup          INTEGER DEFAULT 0,
    delivery        INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS alerts (
    id              INTEGER PRIMARY KEY,
    user_email      TEXT NOT NULL,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    target_price    REAL NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now')),
    triggered_at    TEXT,
    triggered_price REAL
);

CREATE INDEX IF NOT EXISTS idx_prices_product   ON prices(product_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_prices_retailer  ON prices(product_id, retailer_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_products_name     ON products(name);
CREATE INDEX IF NOT EXISTS idx_alerts_email      ON alerts(user_email, active);
CREATE INDEX IF NOT EXISTS idx_inventory_product ON inventory(product_id);
"""


def get_conn() -> sqlite3.Connection:
    """Return a connection with row access by column name and FKs enforced."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create all tables and indexes if they do not yet exist, then migrate."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive, idempotent migrations for databases created before a column existed."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(products)").fetchall()}
    if "source" not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN source TEXT")
    if "external_id" not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN external_id TEXT")
    if "norm_name" not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN norm_name TEXT")
    if "model_number" not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN model_number TEXT")
    if "buy_url" not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN buy_url TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_products_source ON products(source, external_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_products_norm ON products(norm_name)"
    )


def is_empty() -> bool:
    """True if there are no products yet (used to auto-seed on first run)."""
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()
        return row["n"] == 0
