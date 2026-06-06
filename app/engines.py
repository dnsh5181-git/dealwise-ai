"""DealWise intelligence engines.

This module implements the two scoring engines that make DealWise more than a
price-comparison table:

* ``deal_score``  — 0-100 "is this a good price right now?" score.
* ``buy_now``     — Buy Now / Watch Price / Wait recommendation + confidence.

Everything is computed from the platform's own price-history data (no external
LLM calls, no hallucinations). The AI Shopping Assistant layer (Phase 2) is
designed to *call* these deterministic engines and narrate the result, so the
numbers always come from real data.
"""

from __future__ import annotations

import sqlite3
from statistics import mean
from typing import Any


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _slope(ys: list[float]) -> float:
    """Least-squares slope (price change per day) for a short series."""
    n = len(ys)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mx, my = mean(xs), mean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return num / den


def latest_prices(conn: sqlite3.Connection, product_id: int) -> list[sqlite3.Row]:
    """Most recent price per retailer for a product, cheapest first."""
    return conn.execute(
        """
        SELECT r.id AS retailer_id, r.name AS retailer, r.cashback_pct,
               p.price, p.in_stock, p.recorded_at
        FROM prices p
        JOIN retailers r ON r.id = p.retailer_id
        JOIN (
            SELECT retailer_id, MAX(recorded_at) AS mx
            FROM prices
            WHERE product_id = ?
            GROUP BY retailer_id
        ) latest
          ON latest.retailer_id = p.retailer_id AND latest.mx = p.recorded_at
        WHERE p.product_id = ?
        ORDER BY p.price ASC
        """,
        (product_id, product_id),
    ).fetchall()


def daily_best_series(conn: sqlite3.Connection, product_id: int) -> list[tuple[str, float]]:
    """Best in-stock price per day across all retailers (the price history line)."""
    rows = conn.execute(
        """
        SELECT date(recorded_at) AS d, MIN(price) AS best
        FROM prices
        WHERE product_id = ? AND in_stock = 1
        GROUP BY date(recorded_at)
        ORDER BY d ASC
        """,
        (product_id,),
    ).fetchall()
    return [(r["d"], r["best"]) for r in rows]


# ---------------------------------------------------------------------------
# Deal Score Engine
# ---------------------------------------------------------------------------
#
# DEAL SCORE (0-100) = C1 + C2 + C3 + C4
#
#   C1  Discount vs 90-day average        (0-40)  weight: how cheap vs typical
#   C2  Position within 90-day range      (0-30)  weight: near the floor or ceiling?
#   C3  Proximity to 90-day historical low (0-15) weight: bonus for record-low pricing
#   C4  Retailer competitiveness spread    (0-15) weight: how much the best beats the rest
#
# The weights bias toward "cheap vs its own history" (C1+C2+C3 = 85 pts), which
# is what actually signals a good buy, while C4 rewards finding the best seller.
# ---------------------------------------------------------------------------

def deal_score(best_now: float, prices_hist: list[float], max_now: float) -> dict[str, Any]:
    avg90 = mean(prices_hist)
    low90 = min(prices_hist)
    high90 = max(prices_hist)

    # C1 — discount vs 90-day average (20% below average == full 40 pts)
    pct_below_avg = (avg90 - best_now) / avg90 if avg90 else 0.0
    c1 = clamp(pct_below_avg * 200, 0, 40)

    # C2 — position within historical range (at the low == 30 pts, at the high == 0)
    rng = high90 - low90
    range_pos = (high90 - best_now) / rng if rng > 0 else 0.5
    c2 = clamp(range_pos * 30, 0, 30)

    # C3 — proximity to historical low (within ~10% of the floor earns the bonus)
    dist_low = (best_now - low90) / low90 if low90 else 1.0
    c3 = clamp(15 * (1 - dist_low / 0.10), 0, 15)

    # C4 — retailer competitiveness spread (best price vs the most expensive)
    spread = (max_now - best_now) / max_now if max_now else 0.0
    c4 = clamp(spread * 100, 0, 15)

    score = round(c1 + c2 + c3 + c4)
    return {
        "deal_score": int(clamp(score, 0, 100)),
        "avg_90d": round(avg90, 2),
        "low_90d": round(low90, 2),
        "high_90d": round(high90, 2),
        "pct_below_avg": round(pct_below_avg * 100, 1),
        "components": {
            "discount_vs_avg": round(c1, 1),
            "range_position": round(c2, 1),
            "near_historical_low": round(c3, 1),
            "retailer_spread": round(c4, 1),
        },
    }


# ---------------------------------------------------------------------------
# Buy Now Engine
# ---------------------------------------------------------------------------
#
# buy_now_score = deal_score + trend_adjustment
#
#   trend_adjustment in [-10, +10] from the 14-day price slope:
#     prices rising  -> +pts  (buy before it gets more expensive)
#     prices falling -> -pts  (wait, it's still dropping)
#
# Recommendation thresholds:
#   >= 78  Buy Now
#   >= 55  Watch Price
#   <  55  Wait
# An all-time-low (within the 90-day window) forces a strong Buy Now.
# ---------------------------------------------------------------------------

def buy_now(deal: dict[str, Any], best_now: float, prices_hist: list[float]) -> dict[str, Any]:
    avg90 = mean(prices_hist)
    low90 = deal["low_90d"]
    recent = prices_hist[-14:]
    slope = _slope(recent)
    # Total expected change across the window as a fraction of the average price.
    trend_pct = (slope * len(recent)) / avg90 if avg90 else 0.0
    trend_adj = clamp(trend_pct * 200, -10, 10)

    base = deal["deal_score"]
    buy_score = clamp(base + trend_adj, 0, 100)

    # An all-time low only counts when the floor is meaningfully below the
    # typical price — otherwise a perfectly flat price would "tie" its own low
    # and falsely look like a deal.
    at_record_low = best_now <= low90 * 1.005 and deal["pct_below_avg"] >= 1.0
    if at_record_low:
        buy_score = max(buy_score, 90)

    if buy_score >= 78:
        rec = "Buy Now"
    elif buy_score >= 55:
        rec = "Watch Price"
    else:
        rec = "Wait"

    # Confidence: how decisively the score clears the nearest threshold, blended
    # with how much price history we have.
    nearest = min(abs(buy_score - 78), abs(buy_score - 55))
    decisiveness = clamp(nearest / 25, 0, 1)
    data_conf = clamp(len(prices_hist) / 90, 0, 1)
    confidence = round((0.65 * decisiveness + 0.35 * data_conf) * 100)

    reasons: list[str] = []
    if at_record_low:
        reasons.append("This is the lowest price in the last 90 days.")
    if deal["pct_below_avg"] >= 3:
        reasons.append(f"Current price is {deal['pct_below_avg']:.0f}% below the 90-day average.")
    elif deal["pct_below_avg"] <= -3:
        reasons.append(f"Current price is {abs(deal['pct_below_avg']):.0f}% above the 90-day average.")
    if trend_pct > 0.01:
        reasons.append("Prices have been trending up recently — waiting may cost more.")
    elif trend_pct < -0.01:
        reasons.append("Prices have been trending down recently — it may drop further.")
    if not reasons:
        reasons.append("Price is close to its typical level with no strong signal either way.")

    return {
        "buy_now_score": int(buy_score),
        "recommendation": rec,
        "confidence": confidence,
        "trend_pct_14d": round(trend_pct * 100, 1),
        "reason": " ".join(reasons),
    }


def analyze(conn: sqlite3.Connection, product_id: int) -> dict[str, Any] | None:
    """Full intelligence payload for a product: best price, deal score, buy-now."""
    latest = latest_prices(conn, product_id)
    series = daily_best_series(conn, product_id)
    if not latest or not series:
        return None

    in_stock = [r for r in latest if r["in_stock"]]
    pool = in_stock or latest
    best_row = min(pool, key=lambda r: r["price"])
    best_now = best_row["price"]
    max_now = max(r["price"] for r in latest)
    prices_hist = [p for _, p in series]

    deal = deal_score(best_now, prices_hist, max_now)
    decision = buy_now(deal, best_now, prices_hist)

    return {
        "best_price": round(best_now, 2),
        "best_retailer": best_row["retailer"],
        "offers": [
            {
                "retailer": r["retailer"],
                "price": round(r["price"], 2),
                "in_stock": bool(r["in_stock"]),
                "cashback_pct": r["cashback_pct"],
            }
            for r in latest
        ],
        "history": [{"date": d, "price": round(p, 2)} for d, p in series],
        **deal,
        **decision,
    }
