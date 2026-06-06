# DealWise AI

[![CI](https://github.com/dnsh5181-git/dealwise-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/dnsh5181-git/dealwise-ai/actions/workflows/ci.yml)

**The Bloomberg Terminal for consumers** — an AI-powered shopping intelligence platform.

Search any product and instantly get the lowest price across retailers, a 0–100
**Deal Score**, an AI **Buy-Now** recommendation (Buy Now / Watch / Wait), 90 days
of price history, nearby availability, coupons, and price alerts.

> **This is the 90-day MVP.** It implements the core intelligence loop end-to-end
> on a stack that runs locally with zero cloud dependencies. The full enterprise
> vision (10+ live retailer integrations, mobile apps, browser extension, billion-row
> data infra on AWS) is documented in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
> and [`docs/ROADMAP.md`](docs/ROADMAP.md) as the scale-up target.

---

## What's in the MVP

| Module | Status | Where |
|---|---|---|
| Universal product search | ✅ | `app/main.py` (`/`, `/api/products`) |
| Multi-retailer price comparison | ✅ | `app/engines.py` `latest_prices()` |
| 90-day price history | ✅ | `/api/products/{id}/history` + SVG chart |
| **Deal Score Engine (0–100)** | ✅ | `app/engines.py` `deal_score()` |
| **Buy-Now AI Engine** | ✅ | `app/engines.py` `buy_now()` |
| Coupons & cashback | ✅ | seeded + shown on product page |
| Nearby inventory | ✅ | seeded + shown on product page |
| Price alerts + monitor | ✅ | `/alerts`, `POST /api/alerts/check` |
| Barcode lookup | ✅ | `GET /api/barcode/{code}` |
| AI Shopping Assistant | ✅ | `/assistant`, `POST /api/assistant` |
| Live retailer integration | ✅ | `/retailers`, `POST /api/retailers/ingest` |

The Deal Score and Buy-Now engines are **deterministic Python** computed from real
price history — **no LLM, no Bedrock, no hallucinations, no API keys**. The AI
Shopping Assistant is the same idea applied to natural language: it parses a
question ("best air fryer under $100", "should I buy the PS5 now?") into an intent
+ constraints and answers **only** from catalog data and the engines — so it never
invents a price, and says "no match" when nothing fits. An **optional LLM narration layer**
(`app/narrator.py`, Anthropic Claude) can rephrase that grounded answer in a friendlier tone;
it's off unless `ANTHROPIC_API_KEY` is set and degrades back to the deterministic text otherwise,
so the app still runs fully offline.

## Tech stack (MVP)

- **Backend & web:** Python + [FastAPI](https://fastapi.tiangolo.com/), server-rendered with Jinja2
- **Data:** SQLite (stdlib `sqlite3`) — maps to PostgreSQL in production
- **Frontend:** vanilla HTML/CSS/JS (no build step), premium minimal design

## Quick start

Requires **Python 3.11+** (tested on 3.13). No Node.js, no AWS, no accounts.

```powershell
# from the dealwise-ai folder
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

On first launch the database is created and seeded automatically (8 products,
6 retailers, ~4,300 price records over 90 days). Then open:

- **http://127.0.0.1:8000** — web app
- **http://127.0.0.1:8000/docs** — interactive API docs (Swagger)

To reseed manually: `python -m app.seed`

## Try it

- Search **“Ninja Air Fryer”**, **“PlayStation 5”**, or **“Dyson”**
- Open a product to see the deal score, buy-now call, price-history chart, and price comparison
- Set a price alert, then simulate the monitor:

```bash
curl -X POST http://127.0.0.1:8000/api/alerts/check
```

- Ask the assistant at **/assistant**: *"best air fryer under $100"*, *"should I buy the PlayStation 5 now?"*

## API examples

```bash
curl "http://127.0.0.1:8000/api/products?q=air%20fryer"
curl "http://127.0.0.1:8000/api/products/1"
curl "http://127.0.0.1:8000/api/products/1/history"
curl "http://127.0.0.1:8000/api/barcode/0622356561112"
curl -X POST http://127.0.0.1:8000/api/assistant \
  -H "Content-Type: application/json" \
  -d '{"query":"best air fryer under $100"}'
```

See [`docs/API.md`](docs/API.md) for the full reference.

## Live retailer data

Most of the catalog is seeded with 90 days of synthetic history (for a rich
deal-score demo). You can also pull **real** products and prices over HTTP via the
retailer-provider abstraction (`app/retailers/`). The first provider is
[DummyJSON](https://dummyjson.com) — a public, key-free commerce API standing in
for a real retailer; a production integration (Amazon PA-API, Walmart, Best Buy)
is just another class implementing the same `search()` interface.

Open **/retailers** and fetch a query (e.g. "phone"), or use the API:

```bash
curl -X POST http://127.0.0.1:8000/api/retailers/ingest \
  -H "Content-Type: application/json" -d '{"query":"laptop","limit":10}'
```

Ingested products land in the same tables and run through the same engines, so
they immediately appear in Search. Each ingest records a fresh timestamped price,
so repeated fetches accumulate real price history — which is what sharpens the
deal score over time. Failures (network/parse) return `502` and leave the catalog
untouched.

## Optional: AI narration

The assistant works fully offline. To have an LLM rephrase its grounded answers in
a friendlier tone, set an Anthropic key before launching:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."         # enables narration
$env:DEALWISE_LLM_MODEL = "claude-haiku-4-5"   # optional; default claude-opus-4-8
uvicorn app.main:app
```

`/api/assistant` responses then include `"narrated": true` and `answer_raw` (the
original deterministic text). The LLM only rewrites tone — it's instructed to use
**only** the numbers already in the grounded payload, and the app silently falls
back to the deterministic answer on any error or missing key.

## Project layout

```
dealwise-ai/
├─ app/
│  ├─ main.py        FastAPI app: JSON API + server-rendered pages
│  ├─ engines.py     Deal Score + Buy-Now engines (the "AI")
│  ├─ assistant.py   Grounded natural-language shopping assistant
│  ├─ narrator.py    Optional LLM narration layer (Anthropic Claude)
│  ├─ retailers/     Live retailer providers + catalog ingestion
│  ├─ db.py          SQLite schema & connection
│  ├─ seed.py        Sample-data generator (90 days of price history)
│  ├─ templates/     Jinja2 pages
│  └─ static/        CSS
├─ docs/             Architecture, roadmap, API reference
└─ requirements.txt
```

## Not in the MVP (by design)

Live retailer scrapers/APIs, mobile apps, browser extension, user accounts/auth,
and the AWS production infrastructure. These are scoped in
[`docs/ROADMAP.md`](docs/ROADMAP.md). (The optional LLM narration layer is built —
see "Optional: AI narration" above.)
