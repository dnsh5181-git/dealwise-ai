"""Seed the database with realistic sample data.

Generates 90 days of daily price history per (product, retailer) using a base
price + seasonal wave + mild trend + noise, plus occasional promo dips. This
gives the Deal Score and Buy-Now engines real signal to work with.

Run directly:  python -m app.seed
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta

from .db import get_conn, init_db

RANDOM_SEED = 42
DAYS = 90

RETAILERS = [
    ("Amazon", "https://amazon.com/dp/", 1.0),
    ("Walmart", "https://walmart.com/ip/", 2.0),
    ("Target", "https://target.com/p/", 1.5),
    ("Best Buy", "https://bestbuy.com/site/", 0.0),
    ("Kohl's", "https://kohls.com/product/", 5.0),
    ("Costco", "https://costco.com/", 2.0),
]

# (name, brand, category, base_price, rating, reviews, barcode, description)
PRODUCTS = [
    ("Ninja Air Fryer Pro 5-Qt", "Ninja", "Kitchen", 99.99, 4.8, 24130, "0622356561112",
     "5-quart air fryer with rapid hot-air circulation, 4 cooking programs, and a dishwasher-safe basket."),
    ("Samsung 65\" Class QLED 4K Smart TV", "Samsung", "Electronics", 999.99, 4.7, 8841, "0887276612345",
     "Quantum Dot QLED panel with 4K upscaling, HDR, and built-in streaming."),
    ("Dyson V11 Cordless Vacuum", "Dyson", "Home", 569.99, 4.6, 15203, "0885609018881",
     "Cordless stick vacuum with intelligent suction and up to 60 minutes of run time."),
    ("Apple Watch Series 9 (GPS, 45mm)", "Apple", "Wearables", 429.00, 4.9, 33120, "0194253938221",
     "Always-on Retina display, advanced health sensors, and crash detection."),
    ("KitchenAid Artisan Stand Mixer 5-Qt", "KitchenAid", "Kitchen", 449.99, 4.8, 27754, "0883049012345",
     "Tilt-head stand mixer with 10 speeds and a 5-quart stainless steel bowl."),
    ("Sony PlayStation 5 Slim Console", "Sony", "Gaming", 499.99, 4.8, 41902, "0711719577492",
     "Next-gen console with ultra-high-speed SSD and ray-traced 4K gaming."),
    ("Bose QuietComfort Ultra Headphones", "Bose", "Audio", 429.00, 4.7, 9620, "0017817847123",
     "Wireless noise-cancelling headphones with immersive spatial audio."),
    ("Instant Pot Duo 7-in-1 6-Qt", "Instant Pot", "Kitchen", 89.99, 4.7, 51877, "0840268931234",
     "7-in-1 multicooker: pressure cook, slow cook, rice, steam, sauté, and more."),
]


def _price_on_day(base: float, retailer_idx: int, day: int, rng: random.Random) -> float:
    """Synthetic but plausible daily price for one retailer."""
    # Each retailer sits at a slightly different baseline.
    retailer_factor = 1.0 + (retailer_idx - 2) * 0.012
    # Gentle seasonal wave across the 90-day window.
    seasonal = 1.0 + 0.05 * math.sin((day / DAYS) * 2 * math.pi + retailer_idx)
    # Mild overall trend (some products drift down, some up).
    trend = 1.0 + (0.0004 * day) * (1 if retailer_idx % 2 else -1)
    noise = rng.uniform(-0.015, 0.015)
    price = base * retailer_factor * seasonal * trend * (1 + noise)
    # Occasional promo dip (~6% of days), bigger near "today".
    if rng.random() < 0.06:
        price *= rng.uniform(0.82, 0.93)
    return round(price, 2)


def seed() -> None:
    rng = random.Random(RANDOM_SEED)
    init_db()
    with get_conn() as conn:
        cur = conn.cursor()

        # Wipe (idempotent reseed)
        for tbl in ("alerts", "inventory", "coupons", "prices", "products", "retailers"):
            cur.execute(f"DELETE FROM {tbl}")

        retailer_ids: dict[str, int] = {}
        for name, url, cashback in RETAILERS:
            cur.execute(
                "INSERT INTO retailers (name, affiliate_url, cashback_pct) VALUES (?,?,?)",
                (name, url, cashback),
            )
            retailer_ids[name] = cur.lastrowid

        today = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)

        for (name, brand, category, base, rating, reviews, barcode, desc) in PRODUCTS:
            cur.execute(
                """INSERT INTO products
                   (name, brand, category, description, image_url, rating, review_count, barcode)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (name, brand, category, desc, "", rating, reviews, barcode),
            )
            pid = cur.lastrowid

            # 90 days of history for every retailer.
            for r_idx, (r_name, _url, _cb) in enumerate(RETAILERS):
                rid = retailer_ids[r_name]
                for day in range(DAYS):
                    recorded = today - timedelta(days=(DAYS - 1 - day))
                    price = _price_on_day(base, r_idx, day, rng)
                    in_stock = 0 if rng.random() < 0.03 else 1
                    cur.execute(
                        """INSERT INTO prices
                           (product_id, retailer_id, price, in_stock, recorded_at)
                           VALUES (?,?,?,?,?)""",
                        (pid, rid, price, in_stock, recorded.isoformat(sep=" ")),
                    )

            # A couple of coupons per product.
            cur.execute(
                """INSERT INTO coupons (product_id, retailer_id, code, description, discount_type, value)
                   VALUES (?,?,?,?,?,?)""",
                (pid, retailer_ids["Kohl's"], "SAVE15", "15% off with Kohl's card", "percent", 15),
            )
            cur.execute(
                """INSERT INTO coupons (product_id, retailer_id, code, description, discount_type, value)
                   VALUES (?,?,?,?,?,?)""",
                (pid, retailer_ids["Target"], "TGT10", "$10 off orders $75+", "amount", 10),
            )

            # Nearby inventory across a few stores.
            store_blueprints = [
                ("Walmart Supercenter", "Walmart", 2.3, 1, 1, 1),
                ("Target", "Target", 4.1, 1, 1, 1),
                ("Best Buy", "Best Buy", 7.8, 0, 0, 1),
                ("Costco Wholesale", "Costco", 9.2, 1, 1, 0),
            ]
            for store_name, r_name, dist, stock, pickup, delivery in store_blueprints:
                # Vary stock a little per product.
                s = stock and (0 if rng.random() < 0.15 else 1)
                cur.execute(
                    """INSERT INTO inventory
                       (product_id, retailer_id, store_name, distance_mi, in_stock, pickup, delivery)
                       VALUES (?,?,?,?,?,?,?)""",
                    (pid, retailer_ids[r_name], store_name, dist, s, pickup if s else 0, delivery),
                )

        # Create attractive "today" deals for a subset so the catalog shows a
        # realistic mix of Buy Now / Watch / Wait. Factor is applied to each
        # product's prior 89-day low on its cheapest retailer today:
        #   < 1.0  -> new all-time low  -> Buy Now
        #   ~ 1.04 -> above low, below avg -> Watch Price
        deal_factors = {1: 0.96, 3: 0.97, 6: 0.975, 4: 1.04, 7: 1.05}
        today_str = today.date().isoformat()
        for pid, factor in deal_factors.items():
            prior = cur.execute(
                "SELECT MIN(price) AS m FROM prices "
                "WHERE product_id=? AND in_stock=1 AND date(recorded_at) < ?",
                (pid, today_str),
            ).fetchone()["m"]
            if prior is None:
                continue
            target = round(prior * factor, 2)
            row = cur.execute(
                "SELECT id FROM prices WHERE product_id=? AND date(recorded_at)=? "
                "ORDER BY price ASC LIMIT 1",
                (pid, today_str),
            ).fetchone()
            if row:
                cur.execute("UPDATE prices SET price=?, in_stock=1 WHERE id=?", (target, row["id"]))

        conn.commit()

        n_p = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
        n_pr = conn.execute("SELECT COUNT(*) AS n FROM prices").fetchone()["n"]
        print(f"Seeded {n_p} products and {n_pr:,} price records "
              f"across {len(RETAILERS)} retailers ({DAYS} days).")


if __name__ == "__main__":
    seed()
