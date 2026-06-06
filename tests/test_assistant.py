"""Tests for the grounded AI Shopping Assistant.

Covers the pure query parser, the grounded ``answer`` logic against a seeded
temp database, and the HTTP surface (POST /api/assistant + the /assistant page).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import assistant, db
from app import seed as seed_mod

# ----- query parsing (pure) -------------------------------------------------

def test_parse_extracts_price_and_intent():
    p = assistant.parse_query("What is the best air fryer under $100?")
    assert p["intent"] == "best_in_category"
    assert p["max_price"] == 100.0
    assert "air" in p["tokens"] and "fryer" in p["tokens"]
    assert p["category_hint"] == "Kitchen"
    # The price number must not leak into the search tokens.
    assert "100" not in p["tokens"]


def test_parse_should_i_buy_intent():
    p = assistant.parse_query("Should I buy the PlayStation 5 now?")
    assert p["intent"] == "should_i_buy"
    assert "playstation" in p["tokens"]


def test_parse_best_retailer_intent():
    p = assistant.parse_query("Which retailer gives the best deal for the Dyson?")
    assert p["intent"] == "best_retailer"
    assert "dyson" in p["tokens"]


def test_parse_product_lookup_fallback():
    p = assistant.parse_query("how much is the apple watch")
    assert p["intent"] == "product_lookup"
    assert "apple" in p["tokens"] and "watch" in p["tokens"]


@pytest.mark.parametrize("text,expected", [
    ("anything below 50", 50.0),
    ("less than 200 please", 200.0),
    ("up to $1000", 1000.0),
    ("no more than 75.50", 75.50),
])
def test_parse_price_variants(text, expected):
    assert assistant.parse_query(text)["max_price"] == expected


# ----- grounded answers (seeded temp DB) ------------------------------------

@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    original = db.DB_PATH
    db.DB_PATH = tmp_path_factory.mktemp("adata") / "test.db"
    seed_mod.seed()
    c = db.get_conn()
    yield c
    c.close()
    db.DB_PATH = original


def test_answer_best_in_category_respects_budget(conn):
    res = assistant.answer(conn, "What is the best air fryer under $100?")
    assert res["intent"] == "best_in_category"
    assert res["results"]
    top = res["results"][0]
    assert "Air Fryer" in top["name"]
    assert top["best_price"] <= 100
    assert "Best pick" in res["answer"]


def test_answer_best_tv_under_budget(conn):
    res = assistant.answer(conn, "best 65-inch TV under $1000")
    assert res["results"]
    assert "TV" in res["results"][0]["name"]
    assert res["results"][0]["best_price"] <= 1000


def test_answer_should_i_buy(conn):
    res = assistant.answer(conn, "Should I buy the PlayStation 5 now?")
    assert res["intent"] == "should_i_buy"
    assert "PlayStation" in res["results"][0]["name"]
    assert res["results"][0]["recommendation"] in res["answer"]


def test_answer_best_retailer(conn):
    res = assistant.answer(conn, "Which retailer gives the best deal for the Dyson?")
    assert res["intent"] == "best_retailer"
    assert "Dyson" in res["results"][0]["name"]
    assert res["results"][0]["best_retailer"] in res["answer"]


def test_answer_budget_too_low_is_no_match(conn):
    res = assistant.answer(conn, "best TV under $100")
    assert res["intent"] == "no_match"
    assert res["results"] == []
    assert "$100" in res["answer"]


def test_answer_unknown_product_is_no_match(conn):
    res = assistant.answer(conn, "best flying car please")
    assert res["intent"] == "no_match"
    assert res["results"] == []


def test_answer_only_cites_real_catalog_data(conn):
    # Grounding guarantee: the price stated for the top result must equal the
    # engine's computed best price (no invented numbers).
    res = assistant.answer(conn, "how much is the Apple Watch")
    top = res["results"][0]
    assert f"${top['best_price']:,.2f}" in res["answer"]


# ----- HTTP surface ---------------------------------------------------------

@pytest.fixture(scope="module")
def client(tmp_path_factory):
    original = db.DB_PATH
    db.DB_PATH = tmp_path_factory.mktemp("cdata") / "test.db"
    seed_mod.seed()
    from app.main import app
    with TestClient(app) as c:
        yield c
    db.DB_PATH = original


def test_api_assistant_ok(client):
    r = client.post("/api/assistant", json={"query": "best air fryer under $100"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"]
    assert body["results"]


def test_api_assistant_rejects_empty_query(client):
    r = client.post("/api/assistant", json={"query": ""})
    assert r.status_code == 422


def test_assistant_page_renders_answer(client):
    r = client.get("/assistant", params={"q": "Should I buy the PlayStation 5 now?"})
    assert r.status_code == 200
    assert "Answer:" in r.text
