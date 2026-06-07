"""DealWise AI — FastAPI application (API + server-rendered web app)."""

from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, Field

from . import assistant, db, engines, narrator, retailers, specs, vision
from .retailers import ingest

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from a gitignored .env at the repo root into the
    environment (without overriding values already set). Keeps secrets like
    ANTHROPIC_API_KEY out of the codebase and out of the shell history."""
    env_path = BASE_DIR.parent / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    if db.is_empty():
        from .seed import seed
        seed()
    yield


app = FastAPI(title="DealWise AI", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def search_products(conn, q: str | None, category: str | None, limit: int = 50):
    sql = "SELECT * FROM products WHERE 1=1"
    params: list = []
    if q:
        sql += " AND (name LIKE ? OR brand LIKE ? OR category LIKE ?)"
        like = f"%{q}%"
        params += [like, like, like]
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY review_count DESC LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def preferred_live_provider():
    """The best-coverage real provider that's actually configured. Google
    Shopping (Serper) aggregates many US stores, so prefer it when its key is
    set; otherwise fall back to the registry default (eBay)."""
    if os.environ.get("SERPER_API_KEY"):
        return retailers.get_provider("GoogleShopping")
    return retailers.default_provider()


_SIMILAR_STOP = {"the", "with", "and", "for", "new", "in", "of", "a", "to", "by", "inch"}


def _name_tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (name or "").lower())
            if len(t) > 1 and t not in _SIMILAR_STOP}


def find_similar(conn, product_id: int, limit: int = 6) -> list[dict]:
    """Products related to ``product_id``: same category (or same brand), ranked
    by shared name words + price proximity. Excludes the product itself."""
    base = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not base:
        return []
    base_tokens = _name_tokens(base["name"])
    base_analysis = engines.analyze(conn, product_id)
    base_price = base_analysis["best_price"] if base_analysis else None

    candidates = conn.execute(
        """SELECT * FROM products
           WHERE id != ? AND (category = ? OR brand = ?)
           ORDER BY review_count DESC LIMIT 60""",
        (product_id, base["category"], base["brand"]),
    ).fetchall()

    scored = []
    for r in candidates:
        card = product_card(conn, r)
        if card["best_price"] is None:
            continue
        overlap = len(base_tokens & _name_tokens(r["name"]))
        # Price proximity in [0,1]: 1 when identical, decaying with relative gap.
        prox = 0.0
        if base_price and card["best_price"]:
            gap = abs(card["best_price"] - base_price) / base_price
            prox = max(0.0, 1.0 - min(gap, 1.0))
        same_brand = 1 if r["brand"] == base["brand"] and base["brand"] else 0
        score = overlap * 2 + prox + same_brand
        scored.append((score, card))
    scored.sort(key=lambda sc: sc[0], reverse=True)
    return [c for _, c in scored[:limit]]


def live_ingest_best_effort(conn, query: str) -> int:
    """Best-effort: pull live offers for ``query`` into the catalog so grounded
    features (search fallback, assistant, visual search) can use real retailer data.

    Returns the number of products ingested. Swallows provider/network errors
    (returns 0) so the caller always degrades to whatever is already in the
    catalog — live data is an enhancement, never a hard dependency.
    """
    if not query.strip():
        return 0
    try:
        summary = ingest.ingest_search(conn, preferred_live_provider(), query, 10,
                                       backfill_history=True)
        return len(summary.get("product_ids", []))
    except Exception:
        return 0


SORT_OPTIONS = [
    ("popularity", "Popularity"),
    ("price_low", "Price: Low to High"),
    ("price_high", "Price: High to Low"),
    ("deal", "Best deal score"),
    ("rating", "Top rated"),
    ("name_az", "Name: A–Z"),
    ("name_za", "Name: Z–A"),
]
_SORT_KEYS = {k for k, _ in SORT_OPTIONS}


def sort_cards(cards: list[dict], sort: str | None) -> list[dict]:
    """Order result cards by the chosen key. Unknown/None -> popularity.

    Price/deal sorts run here (not in SQL) because those values are computed by
    the engines per product, not stored on the row."""
    sort = sort if sort in _SORT_KEYS else "popularity"
    big = float("inf")
    if sort == "price_low":
        cards.sort(key=lambda c: (c["best_price"] is None, c["best_price"] if c["best_price"] is not None else big))
    elif sort == "price_high":
        cards.sort(key=lambda c: (c["best_price"] is not None, c["best_price"] or 0), reverse=True)
    elif sort == "deal":
        cards.sort(key=lambda c: (c["deal_score"] or 0), reverse=True)
    elif sort == "rating":
        cards.sort(key=lambda c: (c["rating"] or 0, c["review_count"] or 0), reverse=True)
    elif sort == "name_az":
        cards.sort(key=lambda c: c["name"].lower())
    elif sort == "name_za":
        cards.sort(key=lambda c: c["name"].lower(), reverse=True)
    else:  # popularity
        cards.sort(key=lambda c: (c["review_count"] or 0), reverse=True)
    return cards


def product_card(conn, row):
    """Lightweight summary used in list views (name + best price + scores)."""
    analysis = engines.analyze(conn, row["id"])
    return {
        "id": row["id"],
        "name": row["name"],
        "brand": row["brand"],
        "category": row["category"],
        "image_url": row["image_url"],
        "model_number": row["model_number"],
        "source": row["source"],
        "is_sample": row["source"] is None,
        "rating": row["rating"],
        "review_count": row["review_count"],
        "best_price": analysis["best_price"] if analysis else None,
        "best_retailer": analysis["best_retailer"] if analysis else None,
        "best_effective_price": analysis["best_effective_price"] if analysis else None,
        "best_effective_retailer": analysis["best_effective_retailer"] if analysis else None,
        "deal_score": analysis["deal_score"] if analysis else None,
        "buy_now_score": analysis["buy_now_score"] if analysis else None,
        "recommendation": analysis["recommendation"] if analysis else None,
    }


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "dealwise-ai", "version": app.version}


@app.get("/api/products")
def api_products(q: str | None = None, category: str | None = None):
    with db.get_conn() as conn:
        rows = search_products(conn, q, category)
        return {"count": len(rows), "results": [product_card(conn, r) for r in rows]}


@app.get("/api/products/{product_id}")
def api_product(product_id: int):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Product not found")
        analysis = engines.analyze(conn, product_id)
        coupons = conn.execute(
            """SELECT c.*, r.name AS retailer FROM coupons c
               LEFT JOIN retailers r ON r.id = c.retailer_id WHERE c.product_id = ?""",
            (product_id,),
        ).fetchall()
        inventory = conn.execute(
            """SELECT i.*, r.name AS retailer FROM inventory i
               JOIN retailers r ON r.id = i.retailer_id
               WHERE i.product_id = ? ORDER BY i.distance_mi ASC""",
            (product_id,),
        ).fetchall()
        return {
            "product": dict(row),
            "analysis": analysis,
            "coupons": [dict(c) for c in coupons],
            "inventory": [dict(i) for i in inventory],
        }


@app.get("/api/products/{product_id}/history")
def api_history(product_id: int):
    with db.get_conn() as conn:
        series = engines.daily_best_series(conn, product_id)
        if not series:
            raise HTTPException(404, "No price history")
        return {"product_id": product_id, "history": [{"date": d, "price": p} for d, p in series]}


@app.get("/api/products/{product_id}/similar")
def api_similar(product_id: int, limit: int = 6):
    """Products similar to this one (same category/brand, related name + price)."""
    with db.get_conn() as conn:
        if not conn.execute("SELECT 1 FROM products WHERE id = ?", (product_id,)).fetchone():
            raise HTTPException(404, "Product not found")
        return {"product_id": product_id, "similar": find_similar(conn, product_id, limit)}


@app.get("/api/products/{product_id}/specs")
def api_specs(product_id: int):
    """AI-generated specifications for a product (cached after first request)."""
    with db.get_conn() as conn:
        return specs.get_specs(conn, product_id)


@app.get("/api/suggest")
def api_suggest(q: str = "", limit: int = 8):
    """Typeahead suggestions: catalog product names + brands + categories that
    match the partial query. Powers the search-box autocomplete."""
    term = (q or "").strip()
    if len(term) < 2:
        return {"q": term, "suggestions": []}
    like = f"%{term}%"
    starts = f"{term}%"
    with db.get_conn() as conn:
        # Product names first (prefix matches ranked above contains-matches),
        # then distinct brands and categories that match.
        rows = conn.execute(
            """SELECT name AS text, 'product' AS kind,
                      CASE WHEN name LIKE ? THEN 0 ELSE 1 END AS rank
               FROM products
               WHERE name LIKE ?
               ORDER BY rank, review_count DESC
               LIMIT ?""",
            (starts, like, limit),
        ).fetchall()
        out = [{"text": r["text"], "kind": r["kind"]} for r in rows]
        seen = {r["text"].lower() for r in rows}
        for kind, col in (("brand", "brand"), ("category", "category")):
            if len(out) >= limit:
                break
            extra = conn.execute(
                f"SELECT DISTINCT {col} AS text FROM products "
                f"WHERE {col} LIKE ? AND {col} IS NOT NULL AND {col} != '' LIMIT ?",
                (like, limit),
            ).fetchall()
            for r in extra:
                if r["text"] and r["text"].lower() not in seen:
                    out.append({"text": r["text"], "kind": kind})
                    seen.add(r["text"].lower())
    return {"q": term, "suggestions": out[:limit]}


@app.get("/api/barcode/{code}")
def api_barcode(code: str):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM products WHERE barcode = ?", (code,)).fetchone()
        if not row:
            raise HTTPException(404, "Unknown barcode")
        return {"product": dict(row), "analysis": engines.analyze(conn, row["id"])}


# ----- Alerts ---------------------------------------------------------------

class AlertIn(BaseModel):
    user_email: EmailStr
    product_id: int
    target_price: float = Field(gt=0)


@app.post("/api/alerts")
def api_create_alert(alert: AlertIn):
    with db.get_conn() as conn:
        prod = conn.execute("SELECT id FROM products WHERE id = ?", (alert.product_id,)).fetchone()
        if not prod:
            raise HTTPException(404, "Product not found")
        cur = conn.execute(
            "INSERT INTO alerts (user_email, product_id, target_price) VALUES (?,?,?)",
            (alert.user_email, alert.product_id, alert.target_price),
        )
        conn.commit()
        return {"id": cur.lastrowid, **alert.model_dump()}


@app.get("/api/alerts")
def api_list_alerts(email: str):
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT a.*, p.name AS product_name FROM alerts a
               JOIN products p ON p.id = a.product_id
               WHERE a.user_email = ? ORDER BY a.created_at DESC""",
            (email,),
        ).fetchall()
        return {"count": len(rows), "alerts": [dict(r) for r in rows]}


@app.delete("/api/alerts/{alert_id}")
def api_delete_alert(alert_id: int):
    with db.get_conn() as conn:
        conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
        conn.commit()
        return {"deleted": alert_id}


@app.post("/api/alerts/check")
def api_check_alerts():
    """Evaluate active alerts against current best prices and trip any that match.

    In production this runs as a scheduled worker (EventBridge -> Lambda) that
    pushes notifications. Here it's an on-demand endpoint you can call to
    simulate the monitor.
    """
    triggered = []
    with db.get_conn() as conn:
        active = conn.execute("SELECT * FROM alerts WHERE active = 1").fetchall()
        for a in active:
            analysis = engines.analyze(conn, a["product_id"])
            if analysis and analysis["best_price"] <= a["target_price"]:
                conn.execute(
                    "UPDATE alerts SET active = 0, triggered_at = datetime('now'), triggered_price = ? WHERE id = ?",
                    (analysis["best_price"], a["id"]),
                )
                triggered.append({
                    "alert_id": a["id"],
                    "product_id": a["product_id"],
                    "target_price": a["target_price"],
                    "triggered_price": analysis["best_price"],
                    "retailer": analysis["best_retailer"],
                })
        conn.commit()
    return {"triggered_count": len(triggered), "triggered": triggered}


# ----- AI Shopping Assistant ------------------------------------------------

class AssistantIn(BaseModel):
    query: str = Field(min_length=1)
    live: bool = False


@app.post("/api/assistant")
def api_assistant(body: AssistantIn):
    with db.get_conn() as conn:
        ingested = 0
        if body.live:
            ingested = live_ingest_best_effort(conn, body.query)
        result = narrator.narrate(assistant.answer(conn, body.query))
        return {**result, "live_ingested": ingested}


# ----- Visual (photo) product search ----------------------------------------

class VisualSearchIn(BaseModel):
    image: str = Field(min_length=16)  # base64-encoded image (no data: prefix)
    media_type: str = "image/jpeg"
    live: bool = False


@app.post("/api/visual-search")
def api_visual_search(body: VisualSearchIn):
    """Identify a product from a photo (Claude vision) and return matching
    catalog products. Optionally pull live retailer offers for the match first.
    """
    ident = vision.identify(body.image, body.media_type)
    if not ident.get("ok"):
        return {"identified": ident, "count": 0, "results": []}
    query = ident["query"]
    with db.get_conn() as conn:
        ingested = 0
        if body.live:
            ingested = live_ingest_best_effort(conn, query)
        rows = search_products(conn, query, None, limit=24)
        cards = [product_card(conn, r) for r in rows]
    return {
        "identified": ident,
        "live_ingested": ingested,
        "count": len(cards),
        "results": cards,
    }


# ----- Live retailer integration --------------------------------------------

class IngestIn(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)
    provider: str | None = None


@app.get("/api/retailers")
def api_retailers():
    return {"providers": [
        {"name": name, "live": True, "demo": retailers.is_demo(name)}
        for name in retailers.available()
    ]}


@app.post("/api/retailers/ingest")
def api_ingest(body: IngestIn):
    """Fetch live offers for a query and ingest them into the catalog.

    Makes an outbound HTTP call to the chosen retailer provider (default if
    unspecified). Unknown provider -> 400; provider/network failure -> 502 with
    the catalog left untouched.
    """
    try:
        provider = retailers.get_provider(body.provider)
    except KeyError:
        raise HTTPException(400, f"Unknown provider: {body.provider}") from None
    try:
        with db.get_conn() as conn:
            return ingest.ingest_search(conn, provider, body.query, body.limit,
                                        backfill_history=True)
    except Exception as exc:
        raise HTTPException(502, f"Live retailer fetch failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Web pages (server-rendered)
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request, q: str | None = None, category: str | None = None,
         sort: str | None = None):
    fetched_live = 0
    with db.get_conn() as conn:
        rows = search_products(conn, q, category)
        # If a real search returned nothing, fetch live from the best provider so
        # the user always sees results (the "search anything" path). Only on a
        # free-text query (not a category browse) to avoid surprise API calls.
        if q and not category and not rows and os.environ.get("SERPER_API_KEY"):
            fetched_live = live_ingest_best_effort(conn, q)
            if fetched_live:
                rows = search_products(conn, q, category)
        cards = sort_cards([product_card(conn, r) for r in rows], sort)
        cats = [r["category"] for r in conn.execute(
            "SELECT DISTINCT category FROM products ORDER BY category").fetchall()]
    return templates.TemplateResponse(request, "index.html", {
        "cards": cards, "q": q or "",
        "categories": cats, "active_category": category,
        "fetched_live": fetched_live,
        "sort_options": SORT_OPTIONS, "active_sort": sort if sort in _SORT_KEYS else "popularity",
    })


@app.get("/assistant", response_class=HTMLResponse)
def assistant_page(request: Request, q: str | None = None, live: bool = False):
    result = None
    if q:
        with db.get_conn() as conn:
            if live:
                live_ingest_best_effort(conn, q)
            result = narrator.narrate(assistant.answer(conn, q))
    examples = [
        "What is the best air fryer under $100?",
        "Best 65-inch TV under $1000",
        "Should I buy the PlayStation 5 now?",
        "Which retailer gives the best deal for the Dyson?",
    ]
    return templates.TemplateResponse(request, "assistant.html", {
        "q": q or "", "result": result, "examples": examples, "live": live,
    })


@app.get("/retailers", response_class=HTMLResponse)
def retailers_page(request: Request, q: str | None = None, provider: str | None = None):
    try:
        prov = retailers.get_provider(provider)
    except KeyError:
        prov = retailers.default_provider()
    summary = None
    error = None
    cards = []
    if q:
        try:
            with db.get_conn() as conn:
                summary = ingest.ingest_search(conn, prov, q, 12, backfill_history=True)
                for pid in summary["product_ids"]:
                    row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
                    if row:
                        cards.append(product_card(conn, row))
        except Exception as exc:
            error = str(exc)
    return templates.TemplateResponse(request, "retailers.html", {
        "q": q or "", "summary": summary, "error": error, "cards": cards,
        "providers": [{"name": n, "demo": retailers.is_demo(n)} for n in retailers.available()],
        "selected": prov.name,
    })


@app.get("/wishlist", response_class=HTMLResponse)
def wishlist_page(request: Request):
    # Wishlist is stored client-side (localStorage); the page hydrates via the API.
    return templates.TemplateResponse(request, "wishlist.html", {})


@app.get("/product/{product_id}", response_class=HTMLResponse)
def product_page(request: Request, product_id: int):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Product not found")
        analysis = engines.analyze(conn, product_id)
        coupons = conn.execute(
            """SELECT c.*, r.name AS retailer FROM coupons c
               LEFT JOIN retailers r ON r.id = c.retailer_id WHERE c.product_id = ?""",
            (product_id,),
        ).fetchall()
        inventory = conn.execute(
            """SELECT i.*, r.name AS retailer FROM inventory i
               JOIN retailers r ON r.id = i.retailer_id
               WHERE i.product_id = ? ORDER BY i.distance_mi ASC""",
            (product_id,),
        ).fetchall()
        similar = find_similar(conn, product_id, limit=6)
    return templates.TemplateResponse(request, "product.html", {
        "p": row, "a": analysis,
        "coupons": coupons, "inventory": inventory,
        "nearby_count": sum(1 for i in inventory if i["in_stock"]),
        "similar": similar,
    })


@app.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request, email: str = "demo@example.com"):
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT a.*, p.name AS product_name FROM alerts a
               JOIN products p ON p.id = a.product_id
               WHERE a.user_email = ? ORDER BY a.created_at DESC""",
            (email,),
        ).fetchall()
    return templates.TemplateResponse(request, "alerts.html", {
        "alerts": rows, "email": email,
    })


@app.post("/alerts/create")
def alerts_create(email: str = Form(...), product_id: int = Form(...), target_price: float = Form(...)):
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO alerts (user_email, product_id, target_price) VALUES (?,?,?)",
            (email, product_id, target_price),
        )
        conn.commit()
    return RedirectResponse(url=f"/alerts?email={email}", status_code=303)


@app.post("/alerts/{alert_id}/delete")
def alerts_delete(alert_id: int, email: str = Form(...)):
    with db.get_conn() as conn:
        conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
        conn.commit()
    return RedirectResponse(url=f"/alerts?email={email}", status_code=303)


@app.exception_handler(404)
async def not_found(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.detail}, status_code=404)
    return templates.TemplateResponse(request, "404.html", status_code=404)
