"""Unit + integration tests for the DealWise intelligence engines.

The pure scoring functions (clamp, _slope, deal_score, buy_now) are tested
directly. `analyze` is tested against a throwaway in-memory SQLite database
built from the real schema, so no files or seed data are touched.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest

from app import db, engines


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_conn() -> sqlite3.Connection:
    """A fresh in-memory DB with the production schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA)
    return conn


def seed_history(conn, *, flat_price=100.0, days=30, final_price=None,
                 final_retailer="Walmart", retailers=("Amazon", "Walmart")):
    """Insert `days` of flat prices for each retailer, optionally dropping one
    retailer's price on the final day to `final_price` (to simulate a deal)."""
    retailer_ids = {}
    for name in retailers:
        cur = conn.execute("INSERT INTO retailers (name) VALUES (?)", (name,))
        retailer_ids[name] = cur.lastrowid
    pid = conn.execute(
        "INSERT INTO products (name, brand, category) VALUES (?,?,?)",
        ("Test Widget", "TestCo", "Test"),
    ).lastrowid

    today = datetime(2026, 6, 6, 12, 0, 0)
    for day in range(days):
        recorded = (today - timedelta(days=(days - 1 - day))).isoformat(sep=" ")
        for name in retailers:
            price = flat_price
            is_final = day == days - 1
            if is_final and final_price is not None and name == final_retailer:
                price = final_price
            conn.execute(
                "INSERT INTO prices (product_id, retailer_id, price, in_stock, recorded_at) "
                "VALUES (?,?,?,1,?)",
                (pid, retailer_ids[name], price, recorded),
            )
    conn.commit()
    return pid


# ---------------------------------------------------------------------------
# clamp
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("val,lo,hi,expected", [
    (5, 0, 10, 5),
    (-3, 0, 10, 0),
    (42, 0, 10, 10),
    (0, 0, 10, 0),
    (10, 0, 10, 10),
])
def test_clamp(val, lo, hi, expected):
    assert engines.clamp(val, lo, hi) == expected


# ---------------------------------------------------------------------------
# _slope
# ---------------------------------------------------------------------------

def test_slope_rising():
    assert engines._slope([1, 2, 3, 4]) == pytest.approx(1.0)


def test_slope_falling():
    assert engines._slope([4, 3, 2, 1]) == pytest.approx(-1.0)


def test_slope_flat_is_zero():
    assert engines._slope([5, 5, 5, 5]) == 0.0


def test_slope_degenerate_inputs():
    assert engines._slope([]) == 0.0
    assert engines._slope([7]) == 0.0


# ---------------------------------------------------------------------------
# deal_score
# ---------------------------------------------------------------------------

def test_deal_score_has_expected_shape():
    d = engines.deal_score(90.0, [100.0] * 90, 100.0)
    assert set(d) >= {"deal_score", "avg_90d", "low_90d", "high_90d",
                      "pct_below_avg", "components"}
    assert set(d["components"]) == {"discount_vs_avg", "range_position",
                                    "near_historical_low", "retailer_spread"}


def test_deal_score_at_historical_low_is_high():
    hist = [100.0] * 89 + [80.0]
    d = engines.deal_score(80.0, hist, 100.0)
    assert d["deal_score"] >= 90
    assert d["low_90d"] == 80.0
    assert d["high_90d"] == 100.0


def test_deal_score_at_historical_high_is_low():
    hist = [80.0] * 89 + [100.0]
    d = engines.deal_score(100.0, hist, 100.0)
    assert d["deal_score"] <= 10


def test_deal_score_always_within_bounds():
    for best, hist, mx in [
        (50.0, [100.0] * 90, 120.0),
        (200.0, [100.0] * 90, 200.0),
        (100.0, [100.0] * 90, 100.0),
        (1.0, [100.0] * 90, 100.0),
    ]:
        d = engines.deal_score(best, hist, mx)
        assert 0 <= d["deal_score"] <= 100


def test_deal_score_pct_below_avg_sign():
    cheap = engines.deal_score(80.0, [100.0] * 90, 100.0)
    pricey = engines.deal_score(120.0, [100.0] * 90, 120.0)
    assert cheap["pct_below_avg"] > 0      # below average
    assert pricey["pct_below_avg"] < 0     # above average


# ---------------------------------------------------------------------------
# buy_now
# ---------------------------------------------------------------------------

def test_buy_now_record_low_forces_buy_now():
    hist = [100.0] * 89 + [80.0]
    deal = engines.deal_score(80.0, hist, 100.0)
    bn = engines.buy_now(deal, 80.0, hist)
    assert bn["recommendation"] == "Buy Now"
    assert bn["buy_now_score"] >= 90
    assert "lowest price" in bn["reason"].lower()


def test_buy_now_wait_when_expensive():
    hist = [80.0] * 89 + [100.0]
    deal = engines.deal_score(100.0, hist, 100.0)
    bn = engines.buy_now(deal, 100.0, hist)
    assert bn["recommendation"] == "Wait"
    assert bn["buy_now_score"] < 55


def test_buy_now_thresholds_consistent_with_score():
    # The textual recommendation must agree with the numeric thresholds.
    for hist, best in [
        ([100.0] * 89 + [70.0], 70.0),
        ([90.0] * 89 + [88.0], 88.0),
        ([80.0] * 89 + [100.0], 100.0),
    ]:
        deal = engines.deal_score(best, hist, max(hist))
        bn = engines.buy_now(deal, best, hist)
        s = bn["buy_now_score"]
        if bn["recommendation"] == "Buy Now":
            assert s >= 78
        elif bn["recommendation"] == "Watch Price":
            assert 55 <= s < 78
        else:
            assert s < 55


def test_buy_now_confidence_in_range():
    hist = [100.0] * 90
    deal = engines.deal_score(100.0, hist, 100.0)
    bn = engines.buy_now(deal, 100.0, hist)
    assert 0 <= bn["confidence"] <= 100


# ---------------------------------------------------------------------------
# analyze (DB-backed integration)
# ---------------------------------------------------------------------------

def test_analyze_returns_none_without_prices():
    conn = make_conn()
    pid = conn.execute(
        "INSERT INTO products (name) VALUES ('Empty')").lastrowid
    conn.commit()
    assert engines.analyze(conn, pid) is None


def test_analyze_picks_cheapest_retailer_and_full_payload():
    conn = make_conn()
    pid = seed_history(conn, flat_price=100.0, days=30,
                       final_price=70.0, final_retailer="Walmart")
    result = engines.analyze(conn, pid)

    assert result is not None
    assert result["best_price"] == 70.0
    assert result["best_retailer"] == "Walmart"
    assert len(result["offers"]) == 2                 # two retailers
    assert len(result["history"]) == 30               # one best price per day
    # A fresh all-time low should read as a strong Buy Now.
    assert result["recommendation"] == "Buy Now"
    assert result["deal_score"] >= 80
    # Offers are sorted cheapest-first.
    prices = [o["price"] for o in result["offers"]]
    assert prices == sorted(prices)


def test_analyze_flat_history_is_not_a_deal():
    conn = make_conn()
    pid = seed_history(conn, flat_price=100.0, days=30, final_price=None)
    result = engines.analyze(conn, pid)
    assert result["best_price"] == 100.0
    # No discount vs a perfectly flat history -> not a Buy Now.
    assert result["recommendation"] != "Buy Now"
    assert result["deal_score"] < 60
