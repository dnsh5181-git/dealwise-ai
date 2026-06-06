# DealWise AI — Architecture

This document separates **what the MVP actually runs today** from the **production
target architecture** so the two are never confused.

---

## 1. MVP architecture (what runs today)

```
                ┌──────────────────────────────┐
   Browser ───► │  FastAPI (uvicorn)            │
                │  ├─ Jinja2 server-rendered UI │
                │  ├─ JSON REST API             │
                │  └─ Intelligence engines      │
                │        deal_score / buy_now   │
                └──────────────┬───────────────┘
                               │
                        ┌──────▼──────┐
                        │  SQLite     │  products, retailers,
                        │ dealwise.db │  prices (history), coupons,
                        └─────────────┘  inventory, alerts
```

- **Single process**, no external services, no network calls.
- Price data is **seeded synthetically** (`app/seed.py`) to give the engines real
  signal. There are no live retailer integrations in the MVP.
- The engines are pure functions over the price-history table — fully testable and
  deterministic.

### Deal Score formula (implemented)

`deal_score = C1 + C2 + C3 + C4`, clamped to 0–100:

| Component | Range | Meaning |
|---|---|---|
| C1 discount vs 90-day average | 0–40 | 20% below average → full 40 |
| C2 position in 90-day range | 0–30 | at the floor → 30, at the ceiling → 0 |
| C3 proximity to 90-day low | 0–15 | within ~10% of the historical low |
| C4 retailer competitiveness | 0–15 | how much the best price beats the priciest |

### Buy-Now algorithm (implemented)

`buy_now_score = deal_score + trend_adjustment`, where `trend_adjustment ∈ [-10,+10]`
from the 14-day price slope (rising → buy before it climbs; falling → wait). An
all-time-low (within the window) forces a strong Buy Now. Thresholds: ≥78 **Buy Now**,
≥55 **Watch Price**, else **Wait**. Confidence blends how decisively the score clears
the nearest threshold with how much history exists.

---

## 2. Production target architecture (the vision)

```
                         ┌────────────── CloudFront (CDN) ──────────────┐
   Web / iOS / Android / │                                              │
   Browser Extension ───►│  API Gateway / ALB                          │
                         └───────┬──────────────────────────────────────┘
                                 │
            ┌────────────────────┼─────────────────────────────┐
            │ ECS Fargate microservices (FastAPI)               │
            │  search · catalog · pricing · deals · alerts · ai │
            └───┬───────────┬───────────┬───────────┬───────────┘
                │           │           │           │
        ┌───────▼──┐  ┌─────▼─────┐ ┌───▼────┐ ┌────▼─────────┐
        │ Aurora   │  │ OpenSearch│ │ Elasti │ │ Bedrock /    │
        │ Postgres │  │ (search)  │ │ Cache  │ │ LLM (assist) │
        │ (RDS)    │  │           │ │ Redis  │ │              │
        └──────────┘  └───────────┘ └────────┘ └──────────────┘
                │
   Ingestion:   ▼
   Retailer feeds/APIs/scrapers ─► Kafka ─► price-normalizer ─► Postgres + OpenSearch
   Scheduled price-monitor: EventBridge ─► Lambda ─► alert evaluator ─► SNS/push
```

### Mapping MVP → production

| MVP today | Production |
|---|---|
| SQLite `dealwise.db` | Aurora PostgreSQL; `prices` partitioned **monthly** by `recorded_at` |
| SQL `LIKE` search | OpenSearch with typo-tolerance, facets, ranking |
| In-process engines | `deals` + `alerts` microservices on ECS Fargate |
| Synthetic seed (sample) data **+ a live retailer-provider abstraction** (`app/retailers/`): real US data via `EbayProvider` (default; free, personal-email OK) and `BestBuyProvider` (free, business-email key), plus DummyJSON/FakeStore demo providers; `bootstrap`/`refresh` accrue real price history in our own DB; "Buy at retailer" deep-links out (affiliate seam) | Kafka ingestion from many retailer APIs/feeds + per-country affiliate networks, normalized into a canonical product graph; the `RetailerProvider.search()` interface is the seam where real retailers plug in. Amazon (Keepa/PA-API) and multi-country are the next phase |
| `POST /api/alerts/check` | EventBridge schedule → Lambda → SNS / push notifications |
| No caching | ElastiCache (Redis) for hot product/price reads |
| No LLM | Bedrock-backed AI assistant that **calls the deterministic engines** and narrates results (no free-form price hallucination) |

### Scale strategy (100M products, 1B price records, 10M users)

- **Partition** `prices` by month; keep a `current_prices` materialized table (latest
  per product×retailer) for fast comparison reads.
- **Index** on `(product_id, recorded_at)` and `(product_id, retailer_id, recorded_at)`
  (already present in the MVP schema).
- **Cache** product detail + best-price payloads in Redis with short TTLs; invalidate
  on price-ingest events.
- **Search** offloaded entirely to OpenSearch; Postgres stays the source of truth.
- **Ingestion** decoupled via Kafka so retailer volume spikes don't impact reads.

### Security (production)

JWT access/refresh tokens, OAuth social login, per-IP + per-key rate limiting at the
gateway, bot/fraud detection on the ingestion and affiliate-click paths, encryption
in transit (TLS) and at rest (KMS), and PII minimization for alert emails.
