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
    def __init__(self, products, name="FakeMart"):
        self.name = name
        self._products = products

    def search(self, query, limit=10):
        return self._products[:limit]


def _lp(external_id="1", name="Test Widget", price=10.0, in_stock=True):
    return LiveProduct(
        external_id=external_id, name=name, brand="TestCo", category="Test",
        description="A thing.", price=price, in_stock=in_stock,
        rating=4.2, review_count=3, url="https://example.com/1",
        image_url="https://example.com/1.jpg", model_number="MDL-1",
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


# ----- Fake Store provider parsing (HTTP mocked) ----------------------------

def test_fakestore_parses_and_filters(monkeypatch):
    # Fake Store returns a JSON array with no search endpoint -> client-side filter.
    payload = [
        {"id": 1, "title": "Mens Cotton Jacket", "price": 55.99,
         "category": "men's clothing", "description": "Warm.",
         "rating": {"rate": 4.5, "count": 120}},
        {"id": 2, "title": "Steel Water Bottle", "price": 12.0,
         "category": "kitchen", "description": "Holds water.",
         "rating": {"rate": 4.0, "count": 30}},
    ]
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(payload))
    from app.retailers.fakestore import FakeStoreProvider
    offers = FakeStoreProvider().search("jacket")
    assert len(offers) == 1
    o = offers[0]
    assert o.name == "Mens Cotton Jacket"
    assert o.price == 55.99
    assert o.review_count == 120
    assert o.in_stock is True


# ----- Best Buy provider parsing (HTTP mocked) ------------------------------

def test_bestbuy_parses_real_fields(monkeypatch):
    monkeypatch.setenv("BESTBUY_API_KEY", "test-key")
    payload = {"products": [{
        "sku": 6377197, "name": "Ninja - Air Fryer Pro", "manufacturer": "Ninja",
        "modelNumber": "AF141", "salePrice": 129.99, "regularPrice": 159.99,
        "onlineAvailability": True, "image": "https://pisces.bbystatic.com/x.jpg",
        "url": "https://www.bestbuy.com/site/x/6377197.p",
        "customerReviewAverage": 4.7, "customerReviewCount": 7600,
        "shortDescription": "Air fry with little to no oil.",
        "categoryPath": [{"name": "Appliances"}, {"name": "Air Fryers"}],
    }]}
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(payload))
    from app.retailers.bestbuy import BestBuyProvider
    o = BestBuyProvider().search("air fryer")[0]
    assert o.external_id == "6377197"
    assert o.name == "Ninja - Air Fryer Pro"
    assert o.model_number == "AF141"
    assert o.price == 129.99            # salePrice preferred
    assert o.category == "Air Fryers"   # last categoryPath name
    assert o.in_stock is True
    assert o.review_count == 7600
    assert o.url.startswith("https://www.bestbuy.com")
    assert o.image_url.endswith(".jpg")


def test_bestbuy_missing_key_raises(monkeypatch):
    monkeypatch.delenv("BESTBUY_API_KEY", raising=False)
    from app.retailers.bestbuy import BestBuyProvider
    with pytest.raises(RuntimeError):
        BestBuyProvider().search("air fryer")


# ----- eBay provider parsing (OAuth + search, HTTP mocked) ------------------

def _ebay_urlopen(token_payload, search_payload):
    def _open(req, timeout=None):
        if "identity/v1/oauth2/token" in req.full_url:
            return _FakeResp(token_payload)
        return _FakeResp(search_payload)
    return _open


def test_ebay_parses_real_fields(monkeypatch):
    monkeypatch.setenv("EBAY_CLIENT_ID", "id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret")
    from app.retailers import ebay
    ebay._token_cache["value"] = ""          # reset module token cache
    ebay._token_cache["expires_at"] = 0.0
    token = {"access_token": "tok", "expires_in": 7200}
    search = {"itemSummaries": [{
        "itemId": "v1|123|0", "title": "Ninja Air Fryer Pro",
        "price": {"value": "129.99", "currency": "USD"},
        "image": {"imageUrl": "https://i.ebayimg.com/x.jpg"},
        "itemWebUrl": "https://www.ebay.com/itm/123",
        "categories": [{"categoryName": "Air Fryers"}],
        "condition": "New",
    }]}
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", _ebay_urlopen(token, search))
    o = ebay.EbayProvider().search("air fryer")[0]
    assert o.external_id == "v1|123|0"
    assert o.name == "Ninja Air Fryer Pro"
    assert o.price == 129.99
    assert o.category == "Air Fryers"
    assert o.image_url.endswith(".jpg")
    assert o.url.startswith("https://www.ebay.com")
    assert "New" in o.description


def test_ebay_missing_creds_raises(monkeypatch):
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)
    from app.retailers import ebay
    ebay._token_cache["value"] = ""
    ebay._token_cache["expires_at"] = 0.0
    with pytest.raises(RuntimeError):
        ebay.EbayProvider().search("air fryer")


# ----- Google Shopping aggregator (Serper) parsing (HTTP mocked) ------------

def test_serper_parses_multi_store_offers(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "test-key")
    payload = {"shopping": [
        {"title": "Ninja Air Fryer Pro", "source": "Walmart",
         "link": "https://www.walmart.com/ip/123", "price": "$78.92",
         "imageUrl": "https://i.example/x.jpg", "rating": 4.7,
         "ratingCount": 1234, "productId": "1111"},
        {"title": "Ninja Air Fryer Pro", "source": "Target",
         "link": "https://www.target.com/p/456", "price": "$1,089.00",
         "productId": "2222"},
        {"title": "No Price Item", "source": "Amazon", "price": ""},  # dropped
    ]}
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(payload))
    from app.retailers.serper import GoogleShoppingProvider
    offers = GoogleShoppingProvider().search("air fryer")
    assert len(offers) == 2                       # priceless offer filtered out
    w = offers[0]
    assert w.retailer == "Walmart"                # the real store, per-offer
    assert w.external_id == "1111"
    assert w.price == 78.92
    assert w.review_count == 1234
    assert w.url.startswith("https://www.walmart.com")
    assert offers[1].retailer == "Target"
    assert offers[1].price == 1089.0              # thousands separator parsed


def test_serper_derives_id_when_missing(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "k")
    payload = {"shopping": [{"title": "Mystery Gadget", "source": "Costco", "price": "$9.99"}]}
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(payload))
    from app.retailers.serper import GoogleShoppingProvider
    o = GoogleShoppingProvider().search("gadget")[0]
    assert o.external_id.startswith("gs-")         # stable derived id
    assert o.retailer == "Costco"


def test_serper_missing_key_raises(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    from app.retailers.serper import GoogleShoppingProvider
    with pytest.raises(RuntimeError):
        GoogleShoppingProvider().search("air fryer")


def test_serper_filters_lease_used_and_outliers(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "k")
    payload = {"shopping": [
        {"title": "Samsung 65\" QLED 4K TV", "source": "Best Buy", "price": "$899.99", "productId": "1"},
        {"title": "Samsung 65\" QLED 4K TV", "source": "Walmart", "price": "$849.99", "productId": "2"},
        {"title": "Samsung 65\" QLED 4K TV", "source": "Target", "price": "$879.99", "productId": "3"},
        {"title": "Samsung 65\" QLED 4K TV", "source": "Costco", "price": "$929.99", "productId": "4"},
        {"title": "Samsung 65\" QLED 4K TV", "source": "My Way Leases", "price": "$29.99", "productId": "5"},   # lease
        {"title": "Samsung 65\" QLED 4K TV - Refurbished", "source": "eBay", "price": "$499.99", "productId": "6"},  # used
        {"title": "Samsung 65\" QLED 4K TV Remote", "source": "Amazon", "price": "$12.99", "productId": "7"},   # outlier-low
    ]}
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(payload))
    from app.retailers.serper import GoogleShoppingProvider
    offers = GoogleShoppingProvider().search("65 inch tv", limit=10)
    stores = {o.retailer for o in offers}
    assert "My Way Leases" not in stores            # lease dropped
    assert all("Refurbished" not in o.name for o in offers)  # used dropped
    assert all(o.price >= 100 for o in offers)      # $12.99 remote outlier dropped
    assert {"Best Buy", "Walmart", "Target", "Costco"} <= stores


def test_serper_cleans_marketplace_seller(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "k")
    payload = {"shopping": [
        {"title": "Galaxy Watch FE", "source": "Walmart - STARWAA WHOLESALE INC",
         "price": "$184.00", "productId": "9"},
    ]}
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(payload))
    from app.retailers.serper import GoogleShoppingProvider
    o = GoogleShoppingProvider().search("galaxy watch")[0]
    assert o.retailer == "Walmart"   # third-party seller suffix collapsed


# ----- Provider registry ----------------------------------------------------

def test_registry_lists_providers_and_default_is_real():
    from app import retailers
    assert {"eBay", "GoogleShopping", "BestBuy", "DummyJSON", "FakeStore"} <= set(retailers.available())
    assert retailers.DEFAULT_PROVIDER == "eBay"
    assert retailers.get_provider().name == "eBay"
    assert retailers.get_provider("GoogleShopping").name == "GoogleShopping"
    assert retailers.is_demo("DummyJSON") and retailers.is_demo("FakeStore")
    assert not retailers.is_demo("eBay")
    assert not retailers.is_demo("GoogleShopping")
    assert not retailers.is_demo("BestBuy")


def test_registry_unknown_provider_raises():
    from app import retailers
    with pytest.raises(KeyError):
        retailers.get_provider("Nope")


def test_refresh_prefers_google_shopping_when_key_set(monkeypatch):
    from app.retailers import refresh
    monkeypatch.delenv("DEALWISE_REFRESH_PROVIDER", raising=False)
    monkeypatch.setenv("SERPER_API_KEY", "x")
    assert refresh._refresh_provider().name == "GoogleShopping"
    # Explicit override wins over the SERPER default.
    monkeypatch.setenv("DEALWISE_REFRESH_PROVIDER", "eBay")
    assert refresh._refresh_provider().name == "eBay"
    # No key, no override -> registry default.
    monkeypatch.delenv("DEALWISE_REFRESH_PROVIDER", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    assert refresh._refresh_provider().name == retailers_default_name()


def retailers_default_name():
    from app import retailers
    return retailers.DEFAULT_PROVIDER


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


def test_cross_provider_match_merges_into_one_comparison():
    """The payoff of the abstraction: the same product from two retailers becomes
    one catalog entry with a two-retailer price comparison."""
    conn = make_conn()
    ingest.ingest_search(
        conn, FakeProvider([_lp(external_id="a1", name="Acme Blender 3000", price=50.0)],
                           name="AlphaMart"), "blender")
    # Different provider + id, same normalized name (extra spaces), lower price.
    r = ingest.ingest_search(
        conn, FakeProvider([_lp(external_id="z9", name="Acme  Blender  3000", price=42.0)],
                           name="BetaMart"), "blender")

    assert r["matched"] == 1 and r["added"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"] == 1

    pid = conn.execute("SELECT id FROM products").fetchone()["id"]
    analysis = engines.analyze(conn, pid)
    assert {o["retailer"] for o in analysis["offers"]} == {"AlphaMart", "BetaMart"}
    assert analysis["best_price"] == 42.0
    assert analysis["best_retailer"] == "BetaMart"


def test_aggregator_attributes_prices_per_store():
    """An aggregator (one provider, many stores) yields a single catalog product
    with a real multi-retailer comparison — the price attaches to lp.retailer,
    not to the provider name."""
    conn = make_conn()
    walmart = _lp(external_id="w1", name="Ninja Air Fryer Pro", price=78.92)
    walmart.retailer = "Walmart"
    target = _lp(external_id="t1", name="Ninja Air Fryer Pro", price=84.50)
    target.retailer = "Target"
    provider = FakeProvider([walmart, target], name="GoogleShopping")

    summary = ingest.ingest_search(conn, provider, "air fryer")
    assert summary["stores"] == ["Target", "Walmart"]
    # One product (matched by name), priced at two real stores — not "GoogleShopping".
    assert conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"] == 1
    pid = conn.execute("SELECT id FROM products").fetchone()["id"]
    analysis = engines.analyze(conn, pid)
    assert {o["retailer"] for o in analysis["offers"]} == {"Walmart", "Target"}
    assert analysis["best_price"] == 78.92
    assert analysis["best_retailer"] == "Walmart"


def test_backfill_history_populates_90_days():
    conn = make_conn()
    walmart = _lp(external_id="w1", name="Test TV", price=500.0)
    walmart.retailer = "Walmart"
    provider = FakeProvider([walmart], name="GoogleShopping")
    ingest.ingest_search(conn, provider, "tv", backfill_history=True)
    pid = conn.execute("SELECT id FROM products").fetchone()["id"]
    series = engines.daily_best_series(conn, pid)
    assert len(series) >= 80          # ~90 days of modeled history + today
    analysis = engines.analyze(conn, pid)
    assert analysis["avg_90d"] > 0     # engine now has signal
    # Modeled prices are anchored on the current price — stay in a sane band.
    assert 250 <= analysis["low_90d"] <= 500 <= analysis["high_90d"] <= 750


def test_backfill_history_off_by_default():
    conn = make_conn()
    ingest.ingest_search(conn, FakeProvider([_lp(price=10.0)]), "widget")
    pid = conn.execute("SELECT id FROM products").fetchone()["id"]
    assert conn.execute("SELECT COUNT(*) AS n FROM prices WHERE product_id=?",
                        (pid,)).fetchone()["n"] == 1   # only today's real point


def test_cross_provider_match_skips_seed_catalog():
    """Live matching must not merge into curated seed products."""
    conn = make_conn()
    conn.execute("INSERT INTO products (name, norm_name) VALUES ('Acme Blender 3000', NULL)")
    conn.commit()
    ingest.ingest_search(
        conn, FakeProvider([_lp(external_id="a1", name="Acme Blender 3000")], name="AlphaMart"),
        "blender")
    # Seed row (1) + new live row (1) = 2; the live one did not merge into seed.
    assert conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"] == 2


def test_ingest_stores_per_offer_url_and_engine_exposes_best_url():
    conn = make_conn()
    lp = _lp(price=42.0)
    lp.url = "https://store.example/offer/42"
    ingest.ingest_search(conn, FakeProvider([lp]), "widget")
    pid = conn.execute("SELECT id FROM products").fetchone()["id"]
    analysis = engines.analyze(conn, pid)
    assert analysis["best_url"] == "https://store.example/offer/42"
    assert analysis["offers"][0]["url"] == "https://store.example/offer/42"
    assert analysis["best_recorded_at"]   # timestamped


def test_ingest_persists_model_number_and_buy_url():
    conn = make_conn()
    ingest.ingest_search(conn, FakeProvider([_lp()]), "widget")
    row = conn.execute(
        "SELECT model_number, buy_url, image_url FROM products "
        "WHERE source = 'FakeMart' AND external_id = '1'"
    ).fetchone()
    assert row["model_number"] == "MDL-1"
    assert row["buy_url"] == "https://example.com/1"
    assert row["image_url"] == "https://example.com/1.jpg"


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
    providers = {p["name"]: p for p in r.json()["providers"]}
    assert {"BestBuy", "DummyJSON", "FakeStore"} <= set(providers)
    assert providers["BestBuy"]["demo"] is False
    assert providers["DummyJSON"]["demo"] is True


def test_api_ingest_with_fake_provider(client, monkeypatch):
    from app import retailers
    monkeypatch.setattr(retailers, "get_provider",
                        lambda name=None: FakeProvider([_lp(external_id="100", name="Live Gadget")]))
    r = client.post("/api/retailers/ingest", json={"query": "gadget", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["retailer"] == "FakeMart"
    assert body["added"] == 1
    # It is now searchable through the normal catalog API.
    s = client.get("/api/products", params={"q": "Live Gadget"})
    assert any("Live Gadget" in p["name"] for p in s.json()["results"])


def test_api_ingest_provider_selection(client, monkeypatch):
    from app import retailers
    captured = {}

    def fake_get(name=None):
        captured["name"] = name
        return FakeProvider([_lp(external_id="200", name="Sel Gadget")], name="ChosenMart")

    monkeypatch.setattr(retailers, "get_provider", fake_get)
    r = client.post("/api/retailers/ingest", json={"query": "x", "provider": "ChosenMart"})
    assert r.status_code == 200
    assert captured["name"] == "ChosenMart"
    assert r.json()["retailer"] == "ChosenMart"


def test_api_ingest_unknown_provider_400(client):
    r = client.post("/api/retailers/ingest", json={"query": "x", "provider": "DoesNotExist"})
    assert r.status_code == 400


def test_api_ingest_rejects_empty_query(client):
    assert client.post("/api/retailers/ingest", json={"query": ""}).status_code == 422


def test_api_ingest_returns_502_on_provider_error(client, monkeypatch):
    from app import retailers

    class _Boom(RetailerProvider):
        name = "Boom"

        def search(self, query, limit=10):
            raise RuntimeError("network down")

    monkeypatch.setattr(retailers, "get_provider", lambda name=None: _Boom())
    r = client.post("/api/retailers/ingest", json={"query": "x"})
    assert r.status_code == 502
