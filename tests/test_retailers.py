"""Tests for the live retailer integration.

No real network calls: the provider's HTTP layer is mocked with canned JSON,
ingestion is exercised against an in-memory DB, and the API endpoint is driven
with a fake provider. This keeps CI hermetic.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from app import db, engines
from app.retailers import ingest
from app.retailers.base import LiveProduct, RetailerProvider


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(db.SCHEMA)
    return conn


class FakeProvider(RetailerProvider):
    name = "FakeMart"

    def __init__(self, products):
        self._products = products

    def search(self, query, limit=10):
        return self._products[:limit]


def _lp(external_id="1", name="Test Widget", price=10.0, in_stock=True):
    return LiveProduct(
        external_id=external_id, name=name, brand="TestCo", category="Test",
        description="A thing.", price=price, in_stock=in_stock,
        rating=4.2, review_count=3, url="https://example.com/1",
    )


# ----- DummyJSON provider parsing (HTTP mocked) -----------------------------

class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_dummyjson_parses_response(monkeypatch):
    payload = {"products": [{
        "id": 42, "title": "Ninja Air Fryer", "brand": "Ninja",
        "category": "home-appliances", "description": "Hot air.",
        "price": 89.99, "stock": 12, "rating": 4.8,
        "reviews": [{"r": 1}, {"r": 2}],
    }]}
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(payload))

    from app.retailers.dummyjson import DummyJSONProvider
    offers = DummyJSONProvider().search("air fryer")
    assert len(offers) == 1
    o = offers[0]
    assert o.external_id == "42"
    assert o.name == "Ninja Air Fryer"
    assert o.category == "Home Appliances"   # hyphen -> spaced + title-cased
    assert o.price == 89.99
    assert o.in_stock is True
    assert o.review_count == 2


def test_dummyjson_handles_missing_fields(monkeypatch):
    payload = {"products": [{"id": 7, "title": "Bare", "price": 5, "stock": 0}]}
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(payload))
    from app.retailers.dummyjson import DummyJSONProvider
    o = DummyJSONProvider().search("bare")[0]
    assert o.brand == "Unknown"
    assert o.in_stock is False
    assert o.review_count == 0


# ----- Ingestion ------------------------------------------------------------

def test_ingest_adds_then_dedupes_and_records_history():
    conn = make_conn()
    provider = FakeProvider([_lp(price=10.0)])

    r1 = ingest.ingest_search(conn, provider, "widget")
    assert r1["added"] == 1 and r1["updated"] == 0
    assert r1["retailer"] == "FakeMart"

    # Re-ingest the same product (now cheaper): no new product, new price row.
    provider._products = [_lp(price=8.0)]
    r2 = ingest.ingest_search(conn, provider, "widget")
    assert r2["added"] == 0 and r2["updated"] == 1

    assert conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM prices").fetchone()["n"] == 2


def test_ingested_product_flows_through_engine():
    conn = make_conn()
    ingest.ingest_search(conn, FakeProvider([_lp(price=10.0)]), "widget")
    pid = conn.execute(
        "SELECT id FROM products WHERE source = 'FakeMart' AND external_id = '1'"
    ).fetchone()["id"]

    analysis = engines.analyze(conn, pid)
    assert analysis is not None
    assert analysis["best_price"] == 10.0
    assert analysis["best_retailer"] == "FakeMart"
    assert analysis["recommendation"] in {"Buy Now", "Watch Price", "Wait"}


# ----- API surface (fake provider, no network) ------------------------------

@pytest.fixture
def client(tmp_path_factory, monkeypatch):
    from app import seed as seed_mod
    db.DB_PATH = tmp_path_factory.mktemp("rdata") / "test.db"
    seed_mod.seed()
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c


def test_api_list_retailers(client):
    r = client.get("/api/retailers")
    assert r.status_code == 200
    assert r.json()["providers"][0]["name"] == "DummyJSON"


def test_api_ingest_with_fake_provider(client, monkeypatch):
    from app import retailers
    monkeypatch.setattr(retailers, "default_provider",
                        lambda: FakeProvider([_lp(external_id="100", name="Live Gadget")]))
    r = client.post("/api/retailers/ingest", json={"query": "gadget", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["retailer"] == "FakeMart"
    assert body["added"] == 1
    # It is now searchable through the normal catalog API.
    s = client.get("/api/products", params={"q": "Live Gadget"})
    assert any("Live Gadget" in p["name"] for p in s.json()["results"])


def test_api_ingest_rejects_empty_query(client):
    assert client.post("/api/retailers/ingest", json={"query": ""}).status_code == 422


def test_api_ingest_returns_502_on_provider_error(client, monkeypatch):
    from app import retailers

    class _Boom(RetailerProvider):
        name = "Boom"

        def search(self, query, limit=10):
            raise RuntimeError("network down")

    monkeypatch.setattr(retailers, "default_provider", lambda: _Boom())
    r = client.post("/api/retailers/ingest", json={"query": "x"})
    assert r.status_code == 502
