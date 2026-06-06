# DealWise AI — API Reference (MVP)

Base URL: `http://127.0.0.1:8000`
Interactive docs: `GET /docs` (Swagger), `GET /redoc`.

All responses are JSON. Errors use standard HTTP status codes with `{"detail": "..."}`.

---

## Health

### `GET /api/health`
```json
{ "status": "ok", "service": "dealwise-ai", "version": "0.1.0" }
```

---

## Products & search

### `GET /api/products`
Query params: `q` (text), `category`.
```bash
curl "http://127.0.0.1:8000/api/products?q=air%20fryer"
```
```json
{
  "count": 1,
  "results": [
    {
      "id": 1, "name": "Ninja Air Fryer Pro 5-Qt", "brand": "Ninja",
      "category": "Kitchen", "rating": 4.8, "review_count": 24130,
      "best_price": 84.21, "best_retailer": "Walmart",
      "deal_score": 88, "buy_now_score": 90, "recommendation": "Buy Now"
    }
  ]
}
```

### `GET /api/products/{id}`
Full detail: product, analysis (scores + offers + history), coupons, inventory.
```bash
curl "http://127.0.0.1:8000/api/products/1"
```
```json
{
  "product": { "id": 1, "name": "Ninja Air Fryer Pro 5-Qt", "...": "..." },
  "analysis": {
    "best_price": 84.21, "best_retailer": "Walmart",
    "deal_score": 88, "avg_90d": 99.4, "low_90d": 83.9, "high_90d": 112.3,
    "pct_below_avg": 15.3,
    "components": { "discount_vs_avg": 30.6, "range_position": 29.2,
                    "near_historical_low": 13.5, "retailer_spread": 11.1 },
    "buy_now_score": 90, "recommendation": "Buy Now", "confidence": 78,
    "trend_pct_14d": 1.2,
    "reason": "This is the lowest price in the last 90 days. Current price is 15% below the 90-day average.",
    "offers": [ { "retailer": "Walmart", "price": 84.21, "in_stock": true, "cashback_pct": 2.0 } ],
    "history": [ { "date": "2026-03-08", "price": 101.2 } ]
  },
  "coupons": [ { "code": "SAVE15", "description": "15% off with Kohl's card", "retailer": "Kohl's" } ],
  "inventory": [ { "store_name": "Walmart Supercenter", "distance_mi": 2.3, "in_stock": 1, "pickup": 1, "delivery": 1 } ]
}
```
Returns `404` if the product does not exist.

### `GET /api/products/{id}/history`
```json
{ "product_id": 1, "history": [ { "date": "2026-03-08", "price": 101.2 }, "..." ] }
```

### `GET /api/barcode/{code}`
Resolve a scanned barcode to a product + analysis.
```bash
curl "http://127.0.0.1:8000/api/barcode/0622356561112"
```
Returns `404` for an unknown barcode.

---

## Alerts

### `POST /api/alerts`
```bash
curl -X POST http://127.0.0.1:8000/api/alerts \
  -H "Content-Type: application/json" \
  -d '{"user_email":"you@example.com","product_id":1,"target_price":80}'
```
```json
{ "id": 1, "user_email": "you@example.com", "product_id": 1, "target_price": 80.0 }
```
Validates email and `target_price > 0`; returns `422` on bad input, `404` if product missing.

### `GET /api/alerts?email=you@example.com`
```json
{ "count": 1, "alerts": [ { "id": 1, "product_name": "Ninja Air Fryer Pro 5-Qt",
  "target_price": 80.0, "active": 1, "triggered_at": null } ] }
```

### `DELETE /api/alerts/{id}`
```json
{ "deleted": 1 }
```

### `POST /api/alerts/check`
Simulates the price monitor: evaluates all active alerts against current best
prices, trips matches, returns what fired.
```json
{ "triggered_count": 1,
  "triggered": [ { "alert_id": 1, "product_id": 1, "target_price": 80.0,
                   "triggered_price": 79.5, "retailer": "Walmart" } ] }
```

---

## AI Shopping Assistant

### `POST /api/assistant`
Grounded natural-language answers built only from catalog data + the engines
(no LLM, no invented numbers).

```bash
curl -X POST http://127.0.0.1:8000/api/assistant \
  -H "Content-Type: application/json" \
  -d '{"query":"best air fryer under $100"}'
```
```json
{
  "query": "best air fryer under $100",
  "intent": "best_in_category",
  "constraints": { "max_price": 100.0, "keywords": ["air", "fryer"] },
  "answer": "Best pick under $100.00: Ninja Air Fryer Pro 5-Qt — $78.92 at Amazon (deal score 89/100, Buy Now). This is the lowest price in the last 90 days...",
  "results": [
    { "id": 1, "name": "Ninja Air Fryer Pro 5-Qt", "best_price": 78.92,
      "best_retailer": "Amazon", "deal_score": 89, "buy_now_score": 90,
      "recommendation": "Buy Now" }
  ]
}
```

Recognised intents: `best_in_category`, `should_i_buy`, `best_retailer`,
`product_lookup`, and `no_match` (returned with empty `results` when nothing in
the catalog fits — the assistant never fabricates a product or price). Empty
`query` returns `422`.

**Optional LLM narration.** If `ANTHROPIC_API_KEY` is set, the grounded answer is
rephrased by Claude (`app/narrator.py`) and the response gains `"narrated": true`
plus `answer_raw` (the original deterministic text). Without a key — or on any LLM
error — `"narrated": false` and `answer` is the deterministic text. The model is
configurable via `DEALWISE_LLM_MODEL` (default `claude-opus-4-8`). The LLM only
rewrites tone; every number still comes from the grounded payload.

---

## Live retailer integration

### `GET /api/retailers`
Lists configured retailer providers. `demo: true` marks public test APIs (not real
retailers). **eBay** (default) and **BestBuy** are real US sources; eBay needs
`EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET`, BestBuy needs `BESTBUY_API_KEY`.
```json
{ "providers": [ { "name": "eBay",      "live": true, "demo": false },
                 { "name": "BestBuy",   "live": true, "demo": false },
                 { "name": "DummyJSON", "live": true, "demo": true },
                 { "name": "FakeStore", "live": true, "demo": true } ] }
```

### `POST /api/retailers/ingest`
Fetches live offers for a query from the chosen `provider` (default if omitted)
and upserts them into the catalog. Makes an outbound HTTP call.

Dedupe/match per product:
- **updated** — same provider re-ingesting its own product (by provider id),
- **matched** — same product from a *different* retailer (by normalized name) —
  its price joins the existing entry for a cross-retailer comparison,
- **added** — a new product. Each call records a fresh timestamped price.

`provider` defaults to **eBay** (real US data, needs `EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET`).

```bash
curl -X POST http://127.0.0.1:8000/api/retailers/ingest \
  -H "Content-Type: application/json" \
  -d '{"query":"air fryer","limit":10,"provider":"eBay"}'
```
```json
{ "retailer": "eBay", "query": "air fryer", "fetched": 10,
  "added": 8, "updated": 1, "matched": 1, "product_ids": [9, 10, "..."] }
```
`limit` is 1–50 (default 10); empty `query` → `422`; unknown `provider` → `400`;
provider/network failure or missing API key → `502` (catalog unchanged). Ingested
products (incl. `model_number` and `buy_url`) are immediately searchable via
`GET /api/products`.

---

## Web routes (HTML)

| Route | Page |
|---|---|
| `GET /` | Search + product grid (`?q=`, `?category=`) |
| `GET /assistant` | AI assistant page (`?q=` runs a query) |
| `GET /retailers` | Live-data page (`?q=` fetches & ingests) |
| `GET /product/{id}` | Product detail (scores, history chart, comparison, alert form) |
| `GET /alerts` | Alerts dashboard (`?email=`) |
| `POST /alerts/create` | Create alert (form) |
| `POST /alerts/{id}/delete` | Delete alert (form) |

> Note: example numbers above depend on seeded data; exact values vary slightly but
> are reproducible (the seed uses a fixed random seed).
