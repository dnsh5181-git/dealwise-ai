# DealWise AI — Roadmap

## Why MVP-first

The full spec (10+ live retailer integrations, mobile apps, browser extension,
barcode scanning, LLM assistant, billion-row AWS data infra) is a multi-year,
multi-team effort. Building it all at once produces non-working stubs. This roadmap
sequences it so there's a **runnable, demoable product at every stage**.

---

## Phase 1 — 90-day MVP ✅ (this repo)

**Goal:** prove the core intelligence loop with real signal.

- Product search, catalog, multi-retailer price comparison
- 90-day price history + chart
- **Deal Score** and **Buy-Now** engines (deterministic, no LLM)
- Coupons, cashback, nearby inventory (seeded)
- Price alerts + monitor endpoint
- Barcode lookup API
- Clean web UI + JSON API + Swagger docs

**Stack:** FastAPI + SQLite, runs locally, zero cloud cost.

**Team:** 1–2 full-stack engineers.
**Cost:** ~$0 infra during build (local); <$50/mo if hosted on a single small instance.

### What's intentionally faked in the MVP
- Prices are synthetic seed data, not live retailer data.
- "Nearby inventory", coupons, cashback are seeded examples.
- No auth (alerts keyed by email string).

---

## Phase 2 — Next 6 months (first real data + apps)

- **Live retailer data** for 2–3 retailers first (start with affiliate feeds /
  official APIs — Amazon PA-API, Walmart, Target — before scrapers). Kafka ingestion.
- Migrate **SQLite → PostgreSQL** (Aurora), add OpenSearch for search.
- **User accounts** (JWT + OAuth), real push/email alerts via SNS + scheduled Lambda.
- **Browser extension** (Chrome/Edge) showing better prices on retailer pages.
- **AI Shopping Assistant** v1: an LLM that *calls the deterministic engines* for
  grounded answers ("best air fryer under $100").

**Team:** 4–6 (2 backend, 1 data/ingestion, 1 frontend, 1 ML, 1 part-time design).
**Cost:** ~$3–8k/mo AWS at early scale.

---

## Phase 3 — Next 12 months (scale + monetization)

- **Mobile apps** (React Native / Expo) with **barcode scanning**.
- Expand to **10+ retailers**, hundreds over time; canonical product graph + matching.
- Personalization & recommendation engine.
- Monetization live: affiliate commissions, premium subscription, sponsored listings,
  API access tier, enterprise retail-intelligence dashboards.
- Scale data tier to partitioned billion-row price history + Redis caching.

**Team:** 12–18 across backend, data, ML, mobile, web, design, growth.

---

## Monetization summary

| Source | Model |
|---|---|
| Affiliate commissions | % of sales from outbound retailer clicks (core early revenue) |
| Premium subscription | unlimited alerts, deeper history, advanced AI assistant (~$5–9/mo) |
| Sponsored listings | retailers pay for placement (clearly labeled) |
| API access | metered access to price/deal data for developers |
| Enterprise analytics | retail-intelligence dashboards for brands/retailers |

## Investor one-liner

DealWise turns scattered prices, coupons, cashback, and history into a single
**"should I buy this, and where?"** answer — the consumer-finance terminal for the
$5T+ retail market — starting with a deterministic deal-intelligence engine that
competitors (Honey, Rakuten, CamelCamelCamel) only partially cover.
