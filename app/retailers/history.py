"""Modeled price-history backfill for freshly ingested live products.

A live product enters the catalog with a single price point (today), so its
90-day chart is flat and its Deal Score has no signal. Until real tracking
accrues (the scheduled refresh records a genuine point each day), we backfill a
*modeled* baseline anchored on the current real price so the chart is populated
and the engines have something to score.

This is clearly labeled as modeled in the UI (see product.html) — it is a
plausible baseline, not claimed history. As real points accumulate they dominate
the recent window, and a future refresh naturally replaces the estimate.
"""

from __future__ import annotations

import math
import random
import sqlite3
from datetime import datetime, timedelta

DAYS = 90


def backfill_modeled_history(conn: sqlite3.Connection, product_id: int,
                             retailer_id: int, current_price: float,
                             days: int = DAYS) -> int:
    """Insert ``days``-1 modeled daily prices (ending yesterday) for one
    (product, retailer), anchored on ``current_price``. No-op if the pair already
    has prior history or the price is unusable. Returns rows inserted."""
    if current_price <= 0:
        return 0
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM prices WHERE product_id = ? AND retailer_id = ?",
        (product_id, retailer_id),
    ).fetchone()["n"]
    if n > 1:  # already has real/modeled history — don't double-fill
        return 0

    rng = random.Random(hash((product_id, retailer_id)) & 0xFFFFFFFF)
    today = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    phase = rng.uniform(0, 2 * math.pi)
    rows = []
    for d in range(days - 1, 0, -1):  # days-1 ago … 1 day ago (today already recorded)
        frac = d / days
        seasonal = 1.0 + 0.04 * math.sin(frac * 2 * math.pi + phase)
        # Mild drift so the past isn't identical to today (centered ~current).
        drift = 1.0 + 0.0004 * (d - days / 2)
        noise = rng.uniform(-0.02, 0.02)
        price = current_price * seasonal * drift * (1 + noise)
        if rng.random() < 0.05:  # occasional promo dip
            price *= rng.uniform(0.85, 0.95)
        recorded = today - timedelta(days=d)
        rows.append((product_id, retailer_id, round(price, 2), 1,
                     recorded.isoformat(sep=" ")))
    conn.executemany(
        "INSERT INTO prices (product_id, retailer_id, price, in_stock, recorded_at) "
        "VALUES (?,?,?,?,?)",
        rows,
    )
    return len(rows)
