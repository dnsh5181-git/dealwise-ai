"""DealWise AI — FastAPI application (API + server-rendered web app)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, Field

from . import db, engines

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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

def search_products(conn, q: Optional[str], category: Optional[str], limit: int = 50):
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


def product_card(conn, row):
    """Lightweight summary used in list views (name + best price + scores)."""
    analysis = engines.analyze(conn, row["id"])
    return {
        "id": row["id"],
        "name": row["name"],
        "brand": row["brand"],
        "category": row["category"],
        "rating": row["rating"],
        "review_count": row["review_count"],
        "best_price": analysis["best_price"] if analysis else None,
        "best_retailer": analysis["best_retailer"] if analysis else None,
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
def api_products(q: Optional[str] = None, category: Optional[str] = None):
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


# ---------------------------------------------------------------------------
# Web pages (server-rendered)
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request, q: Optional[str] = None, category: Optional[str] = None):
    with db.get_conn() as conn:
        rows = search_products(conn, q, category)
        cards = [product_card(conn, r) for r in rows]
        cats = [r["category"] for r in conn.execute(
            "SELECT DISTINCT category FROM products ORDER BY category").fetchall()]
    return templates.TemplateResponse(request, "index.html", {
        "cards": cards, "q": q or "",
        "categories": cats, "active_category": category,
    })


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
    return templates.TemplateResponse(request, "product.html", {
        "p": row, "a": analysis,
        "coupons": coupons, "inventory": inventory,
        "nearby_count": sum(1 for i in inventory if i["in_stock"]),
    })


@app.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request, email: str = "dnsh5181@gmail.com"):
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
