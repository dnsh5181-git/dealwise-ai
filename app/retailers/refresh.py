"""Refresh prices for tracked queries — builds real price history over time.

Run on a schedule (cron / Task Scheduler / a worker on your app host):

    python -m app.retailers.refresh

Each run re-ingests the tracked queries and records a fresh timestamped price per
product. History accrues in our own DB, so the deal score becomes meaningful and
we never re-pay a provider for past prices.

Provider selection (in order): ``DEALWISE_REFRESH_PROVIDER`` env -> Google
Shopping when ``SERPER_API_KEY`` is set (broad multi-store coverage) -> the
registry default. Skips gracefully (exit 0) when the chosen provider has no
credentials, so a scheduled job without the secret is a no-op, not a failure.
"""

from __future__ import annotations

import os
import sys

from .. import db
from . import default_provider, get_provider, ingest
from .bootstrap import STARTER_QUERIES

# Override the tracked list via env: DEALWISE_TRACKED="air fryer,4k tv"
TRACKED = [
    q.strip() for q in os.environ.get("DEALWISE_TRACKED", "").split(",") if q.strip()
] or STARTER_QUERIES


def _refresh_provider():
    name = os.environ.get("DEALWISE_REFRESH_PROVIDER", "").strip()
    if name:
        return get_provider(name)
    if os.environ.get("SERPER_API_KEY"):
        return get_provider("GoogleShopping")
    return default_provider()


def main() -> int:
    db.init_db()
    provider = _refresh_provider()
    recorded = 0
    try:
        with db.get_conn() as conn:
            for query in TRACKED:
                summary = ingest.ingest_search(conn, provider, query, 10, backfill_history=True)
                recorded += summary["fetched"]
                print(f"  refreshed {query!r}: {summary['fetched']} prices recorded")
    except RuntimeError as exc:
        # Missing credentials -> no-op so a scheduled job stays green.
        print(f"Skipping refresh ({provider.name}): {exc}")
        return 0
    print(f"Done via {provider.name}. {recorded} price points across {len(TRACKED)} queries.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
