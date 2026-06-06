"""Bootstrap a real starter catalog from Best Buy.

Run once after setting BESTBUY_API_KEY in .env:

    python -m app.retailers.bootstrap

Ingests a handful of US categories so the default Search shows real products
(real prices, images, and model numbers) instead of only the demo seed data.
"""

from __future__ import annotations

import os
import sys

from .. import db
from . import get_provider, ingest

STARTER_QUERIES = [
    "air fryer",
    "65 inch tv",
    "laptop",
    "headphones",
    "robot vacuum",
    "smart watch",
]


def main() -> int:
    if not os.environ.get("BESTBUY_API_KEY"):
        print("BESTBUY_API_KEY is not set. Add it to .env "
              "(free key at https://developer.bestbuy.com), then re-run.")
        return 1

    db.init_db()
    provider = get_provider("BestBuy")
    totals = {"added": 0, "updated": 0, "matched": 0}
    with db.get_conn() as conn:
        for query in STARTER_QUERIES:
            summary = ingest.ingest_search(conn, provider, query, 10)
            for key in totals:
                totals[key] += summary[key]
            print(f"  {query:<14} fetched={summary['fetched']:>2} added={summary['added']:>2}")
    print(f"Done. added={totals['added']} updated={totals['updated']} matched={totals['matched']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
