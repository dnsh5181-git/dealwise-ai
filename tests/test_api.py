"""API + web-route tests using FastAPI's TestClient.

The app is exercised against a throwaway SQLite database created in a temp
directory (via monkeypatching ``db.DB_PATH``), seeded once per module, so these
tests never touch the real ``dealwise.db`` or any developer data.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import db
from app import seed as seed_mod

# Ninja Air Fryer is product id 1 in the seed; this is its barcode.
NINJA_BARCODE = "0622356561112"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    original = db.DB_PATH
    db.DB_PATH = tmp_path_factory.mktemp("data") / "test.db"
    seed_mod.seed()
    from app.main import app
    with TestClient(app) as c:
        yield c
    db.DB_PATH = original


# ----- health & search ------------------------------------------------------

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_search_finds_product(client):
    r = client.get("/api/products", params={"q": "air fryer"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert any("Air Fryer" in x["name"] for x in body["results"])


def test_search_by_category(client):
    r = client.get("/api/products", params={"category": "Kitchen"})
    assert r.status_code == 200
    results = r.json()["results"]
    assert results and all(x["category"] == "Kitchen" for x in results)


# ----- sort + similar -------------------------------------------------------

def test_home_sort_price_low_to_high(client):
    html = client.get("/", params={"sort": "price_low"}).text
    import re as _re
    prices = [float(m) for m in _re.findall(r'best-price">\$([\d,]+\.\d\d)',
                                            html.replace(",", ""))]
    assert prices == sorted(prices)            # ascending


def test_home_sort_name_az(client):
    html = client.get("/", params={"sort": "name_az"}).text
    assert 'selected' in html and 'value="name_az"' in html  # dropdown reflects choice


def test_similar_products_endpoint(client):
    r = client.get("/api/products/1/similar")
    assert r.status_code == 200
    sim = r.json()["similar"]
    assert all(s["id"] != 1 for s in sim)      # never includes the product itself
    assert all("best_price" in s for s in sim)


def test_similar_unknown_product_404(client):
    assert client.get("/api/products/999999/similar").status_code == 404


# ----- autocomplete suggestions ---------------------------------------------

def test_suggest_returns_matches(client):
    r = client.get("/api/suggest", params={"q": "air"})
    assert r.status_code == 200
    body = r.json()
    texts = [s["text"].lower() for s in body["suggestions"]]
    assert texts and any("air" in t for t in texts)
    assert all({"text", "kind"} <= set(s) for s in body["suggestions"])


def test_suggest_short_query_is_empty(client):
    r = client.get("/api/suggest", params={"q": "a"})
    assert r.status_code == 200
    assert r.json()["suggestions"] == []


# ----- AI specs (graceful without API key) ----------------------------------

def test_specs_endpoint_degrades_without_key(client, monkeypatch):
    # No ANTHROPIC_API_KEY -> available False with a helpful reason, never a 500.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.get("/api/products/1/specs")
    assert r.status_code == 200
    assert r.json()["available"] is False


def test_specs_endpoint_serves_cache(client):
    # Seed a cached specs blob directly and confirm it is returned without an LLM.
    import json as _json
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE products SET specs = ? WHERE id = 1",
            (_json.dumps({"summary": "Cached.", "groups": [
                {"name": "General", "specs": [{"label": "Color", "value": "Black"}]}]}),),
        )
        conn.commit()
    r = client.get("/api/products/1/specs")
    body = r.json()
    assert body["available"] is True
    assert body["summary"] == "Cached."
    assert body["groups"][0]["specs"][0]["value"] == "Black"


# ----- search live fallback -------------------------------------------------

def test_home_search_falls_back_to_live(client, monkeypatch):
    """A search with no local match fetches live from the preferred provider."""
    from app import main as main_mod
    from app.retailers.base import LiveProduct, RetailerProvider

    class _Fake(RetailerProvider):
        name = "GoogleShopping"

        def search(self, query, limit=10):
            return [LiveProduct(
                external_id="zz9", name="Zzytron Mega Gizmo 9000", brand="Zzytron",
                category="Gadgets", description="", price=42.0, in_stock=True,
                rating=4.0, review_count=10, url="https://ex/9", retailer="Walmart")]

    monkeypatch.setenv("SERPER_API_KEY", "x")
    monkeypatch.setattr(main_mod, "preferred_live_provider", lambda: _Fake())
    r = client.get("/", params={"q": "Zzytron Mega Gizmo"})
    assert r.status_code == 200
    assert "Zzytron Mega Gizmo 9000" in r.text   # live-fetched product now shown


# ----- product detail / history / barcode -----------------------------------

def test_product_detail_shape(client):
    r = client.get("/api/products/1")
    assert r.status_code == 200
    body = r.json()
    assert body["product"]["id"] == 1
    a = body["analysis"]
    assert 0 <= a["deal_score"] <= 100
    assert a["recommendation"] in {"Buy Now", "Watch Price", "Wait"}
    assert len(a["offers"]) >= 1
    assert "coupons" in body and "inventory" in body


def test_product_not_found_returns_json_404(client):
    r = client.get("/api/products/999999")
    assert r.status_code == 404
    assert r.json()["detail"] == "Product not found"


def test_history_endpoint(client):
    r = client.get("/api/products/1/history")
    assert r.status_code == 200
    hist = r.json()["history"]
    assert len(hist) >= 1
    assert {"date", "price"} <= set(hist[0])


def test_barcode_known(client):
    r = client.get(f"/api/barcode/{NINJA_BARCODE}")
    assert r.status_code == 200
    assert "Air Fryer" in r.json()["product"]["name"]


def test_barcode_unknown_404(client):
    r = client.get("/api/barcode/0000000000000")
    assert r.status_code == 404


# ----- alerts ---------------------------------------------------------------

def test_alert_crud_and_check(client):
    # Create with a deliberately huge target so the monitor will trip it.
    r = client.post("/api/alerts", json={
        "user_email": "buyer@example.com", "product_id": 1, "target_price": 100000})
    assert r.status_code == 200
    alert_id = r.json()["id"]

    r = client.get("/api/alerts", params={"email": "buyer@example.com"})
    assert r.status_code == 200
    assert any(a["id"] == alert_id for a in r.json()["alerts"])

    r = client.post("/api/alerts/check")
    assert r.status_code == 200
    assert r.json()["triggered_count"] >= 1

    r = client.delete(f"/api/alerts/{alert_id}")
    assert r.status_code == 200
    assert r.json()["deleted"] == alert_id


def test_alert_rejects_bad_email(client):
    r = client.post("/api/alerts", json={
        "user_email": "not-an-email", "product_id": 1, "target_price": 10})
    assert r.status_code == 422


def test_alert_rejects_nonpositive_price(client):
    r = client.post("/api/alerts", json={
        "user_email": "a@b.com", "product_id": 1, "target_price": 0})
    assert r.status_code == 422


def test_alert_missing_product_404(client):
    r = client.post("/api/alerts", json={
        "user_email": "a@b.com", "product_id": 999999, "target_price": 10})
    assert r.status_code == 404


# ----- server-rendered web pages --------------------------------------------

def test_home_page_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "DealWise" in r.text


def test_product_page_renders(client):
    r = client.get("/product/1")
    assert r.status_code == 200
    assert "Compare prices" in r.text


def test_alerts_page_renders(client):
    r = client.get("/alerts")
    assert r.status_code == 200


def test_wishlist_page_renders(client):
    r = client.get("/wishlist")
    assert r.status_code == 200
    assert "wishlist" in r.text.lower()
