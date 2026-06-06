"""Refresh prices for tracked queries — builds real price history over time.

Run on a schedule (cron / Task Scheduler / a worker on your app host):

    python -m app.retailers.refresh

Each run re-ingests the tracked queries from Best Buy and records a fresh
timestamped price per product. History accrues in our own DB, so the deal score
becomes meaningful and we never re-pay a provider for past prices.

Skips gracefully (exit 0) when BESTBUY_API_KEY is absent, so a scheduled job
without the secret is a no-op rather than a failure.
"""

from __future__ import annotations

import os
import sys

from .. import db
from . import get_provider, ingest
from .bootstrap import STARTER_QUERIES

# Override the tracked list via env: DEALWISE_TRACKED="air fryer,4k tv"
TRACKED = [
    q.strip() for q in os.environ.get("DEALWISE_TRACKED", "").split(",") if q.strip()
] or STARTER_QUERIES


def main() -> int:
    if not os.environ.get("BESTBUY_API_KEY"):
        print("BESTBUY_API_KEY not set — skipping refresh (no-op).")
        return 0

    db.init_db()
    provider = get_provider("BestBuy")
    recorded = 0
    with db.get_conn() as conn:
        for query in TRACKED:
            summary = ingest.ingest_search(conn, provider, query, 10)
            recorded += summary["fetched"]
            print(f"  refreshed {query!r}: {summary['fetched']} prices recorded")
    print(f"Done. {recorded} price points recorded across {len(TRACKED)} queries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
