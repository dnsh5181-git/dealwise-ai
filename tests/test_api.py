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
