"""Bootstrap a real starter catalog from Best Buy.

Run once after setting BESTBUY_API_KEY in .env:

    python -m app.retailers.bootstrap

Ingests a handful of US categories so the default Search shows real products
(real prices, images, and model numbers) instead of only the demo seed data.
"""

from __future__ import annotations

import sys

from .. import db
from ..config import load_dotenv
from . import get_provider, ingest

STARTER_QUERIES = [
    "air fryer",
    "65 inch tv",
    "4k tv",
    "laptop",
    "tablet",
    "smartphone",
    "headphones",
    "robot vacuum",
    "smart watch",
]


def main() -> int:
    load_dotenv()  # so the CLI picks up SERPER_API_KEY / provider keys from .env
    db.init_db()
    provider = get_provider()  # the default real provider
    totals = {"added": 0, "updated": 0, "matched": 0}
    try:
        with db.get_conn() as conn:
            for query in STARTER_QUERIES:
                summary = ingest.ingest_search(conn, provider, query, 10, backfill_history=True)
                for key in totals:
                    totals[key] += summary[key]
                print(f"  {query:<14} fetched={summary['fetched']:>2} added={summary['added']:>2}")
    except RuntimeError as exc:
        print(f"{provider.name}: {exc}")
        return 1
    print(f"Done via {provider.name}. "
          f"added={totals['added']} updated={totals['updated']} matched={totals['matched']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
