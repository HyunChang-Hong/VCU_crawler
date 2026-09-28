from __future__ import annotations

import csv
import io
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import asc, desc, func

from config import (
    APP_ENV,
    AUTO_CRAWL_ON_STARTUP,
    CRAWL_INTERVAL_MINUTES,
    DATABASE_URL,
    ENABLE_MANUAL_REFRESH,
    SCHEDULER_ENABLED,
    TARGET_SITE,
)
from crawler import get_state, run_crawl
from database import SessionLocal, init_db
from models import CrawlRun, Product, ProductHistory

BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger("uvicorn.error")
_scheduler_stop = threading.Event()
_scheduler_thread = None


def start_crawl_background():
    if not get_state()["running"]:
        threading.Thread(target=run_crawl, name="vcu-crawler", daemon=True).start()


def scheduler_loop():
    if AUTO_CRAWL_ON_STARTUP:
        start_crawl_background()
    seconds = max(60, CRAWL_INTERVAL_MINUTES * 60)
    while not _scheduler_stop.wait(seconds):
        start_crawl_background()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler_thread
    init_db()
    db_kind = "postgresql" if DATABASE_URL.startswith("postgresql") else "sqlite"
    logger.info(
        "VCU monitor starting env=%s target=%s db=%s scheduler=%s auto_crawl=%s",
        APP_ENV, TARGET_SITE, db_kind, SCHEDULER_ENABLED, AUTO_CRAWL_ON_STARTUP,
    )
    _scheduler_stop.clear()
    if SCHEDULER_ENABLED:
        _scheduler_thread = threading.Thread(target=scheduler_loop, name="vcu-scheduler", daemon=True)
        _scheduler_thread.start()
    elif AUTO_CRAWL_ON_STARTUP:
        start_crawl_background()
    yield
    _scheduler_stop.set()


app = FastAPI(title="VCU Product Monitor", version="2.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def money(value: int | None):
    return f"{value:,}원" if value is not None else "가격문의"


def dt_short(value: datetime | None):
    if not value:
        return "-"
    return value.strftime("%m-%d %H:%M")


def relative_time(value: datetime | None):
    if not value:
        return "-"
    seconds = max(0, int((datetime.utcnow() - value).total_seconds()))
    if seconds < 60:
        return "방금 전"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}분 전"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}시간 전"
    days = hours // 24
    return f"{days}일 전"


templates.env.filters["money"] = money
templates.env.filters["dt_short"] = dt_short
templates.env.filters["relative"] = relative_time


def _dashboard(db):
    active_count = db.query(Product).filter(Product.is_active.is_(True)).count()
    soldout_count = db.query(Product).filter(Product.is_active.is_(True), Product.sold_out.is_(True)).count()
    ended_count = db.query(Product).filter(Product.is_active.is_(False)).count()
    total_count = db.query(Product).count()

    price_row = (
        db.query(func.avg(Product.price), func.min(Product.price), func.max(Product.price))
        .filter(Product.is_active.is_(True), Product.price.isnot(None))
        .one()
    )
    avg_price = int(price_row[0]) if price_row[0] is not None else None
    min_price = int(price_row[1]) if price_row[1] is not None else None
    max_price = int(price_row[2]) if price_row[2] is not None else None

    since = datetime.utcnow() - timedelta(hours=24)
    changes_24h = db.query(ProductHistory).filter(ProductHistory.captured_at >= since).count()
    last_run = db.query(CrawlRun).order_by(desc(CrawlRun.id)).first()

    return {
        "active_count": active_count,
        "soldout_count": soldout_count,
        "ended_count": ended_count,
        "total_count": total_count,
        "avg_price": avg_price,
        "min_price": min_price,
        "max_price": max_price,
        "changes_24h": changes_24h,
        "last_run": last_run,
    }


def _query_products(db, q: str, status: str, category: str, sort: str, min_price: int | None, max_price: int | None):
    query = db.query(Product)
    if q:
        query = query.filter((Product.name.ilike(f"%{q}%")) | (Product.summary.ilike(f"%{q}%")))
    if status == "active":
        query = query.filter(Product.is_active.is_(True), Product.sold_out.is_(False))
    elif status == "soldout":
        query = query.filter(Product.is_active.is_(True), Product.sold_out.is_(True))
    elif status == "ended":
        query = query.filter(Product.is_active.is_(False))
    if category:
        query = query.filter(Product.category == category)
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)

    if sort == "newest":
        query = query.order_by(desc(Product.first_seen_at), desc(Product.id))
    elif sort == "price_asc":
        query = query.order_by(asc(Product.price), asc(Product.name))
    elif sort == "price_desc":
        query = query.order_by(desc(Product.price), asc(Product.name))
    elif sort == "name":
        query = query.order_by(asc(Product.name))
    else:
        query = query.order_by(desc(Product.updated_at), desc(Product.id))
    return query


@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    q: str = "",
    status: str = "all",
    category: str = "",
    sort: str = "changed",
    min_price: int | None = Query(default=None, ge=0),
    max_price: int | None = Query(default=None, ge=0),
):
    db = SessionLocal()
    try:
        products = _query_products(db, q, status, category, sort, min_price, max_price).limit(500).all()
        categories = [
            row[0]
            for row in db.query(Product.category)
            .filter(Product.category.isnot(None), Product.category != "")
            .distinct()
            .order_by(Product.category)
            .all()
            if row[0]
        ]
        recent_changes = (
            db.query(ProductHistory, Product)
            .join(Product, Product.id == ProductHistory.product_id)
            .order_by(desc(ProductHistory.captured_at))
            .limit(40)
            .all()
        )
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "products": products,
                "q": q,
                "status": status,
                "category": category,
                "sort": sort,
                "min_price": min_price,
                "max_price": max_price,
                "categories": categories,
                "recent_changes": recent_changes,
                "dashboard": _dashboard(db),
                "state": get_state(),
                "target_site": TARGET_SITE,
                "interval": CRAWL_INTERVAL_MINUTES,
                "manual_refresh": ENABLE_MANUAL_REFRESH,
            },
        )
    finally:
        db.close()


@app.get("/product/{product_id}", response_class=HTMLResponse)
def product_detail(request: Request, product_id: int):
    db = SessionLocal()
    try:
        product = db.query(Product).filter(Product.id == product_id).one_or_none()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        history = (
            db.query(ProductHistory)
            .filter(ProductHistory.product_id == product.id)
            .order_by(desc(ProductHistory.captured_at))
            .limit(100)
            .all()
        )
        return templates.TemplateResponse(
            request=request,
            name="product.html",
            context={"product": product, "history": history, "target_site": TARGET_SITE},
        )
    finally:
        db.close()


@app.get("/api/status")
def api_status():
    db = SessionLocal()
    try:
        state = get_state()
        state.update(_dashboard(db))
        last_run = state.pop("last_run", None)
        state["last_run"] = {
            "status": last_run.status,
            "started_at": last_run.started_at.isoformat() if last_run else None,
            "finished_at": last_run.finished_at.isoformat() if last_run and last_run.finished_at else None,
            "discovered_count": last_run.discovered_count if last_run else 0,
            "changed_count": last_run.changed_count if last_run else 0,
        } if last_run else None
        state["interval_minutes"] = CRAWL_INTERVAL_MINUTES
        state["target_site"] = TARGET_SITE
        return state
    finally:
        db.close()


@app.get("/api/recent-changes")
def api_recent_changes(limit: int = Query(default=20, ge=1, le=100)):
    db = SessionLocal()
    try:
        rows = (
            db.query(ProductHistory, Product)
            .join(Product, Product.id == ProductHistory.product_id)
            .order_by(desc(ProductHistory.captured_at))
            .limit(limit)
            .all()
        )
        return [
            {
                "change_type": h.change_type,
                "name": h.name,
                "price": h.price,
                "captured_at": h.captured_at.isoformat(),
                "product_id": p.id,
            }
            for h, p in rows
        ]
    finally:
        db.close()


@app.get("/api/products")
def api_products():
    db = SessionLocal()
    try:
        products = db.query(Product).order_by(desc(Product.updated_at), desc(Product.id)).all()
        return [
            {
                "id": p.id,
                "source_product_no": p.source_product_no,
                "name": p.name,
                "price": p.price,
                "original_price": p.original_price,
                "image_url": p.image_url,
                "source_url": p.source_url,
                "category": p.category,
                "sold_out": p.sold_out,
                "is_active": p.is_active,
                "first_seen_at": p.first_seen_at.isoformat() if p.first_seen_at else None,
                "last_seen_at": p.last_seen_at.isoformat() if p.last_seen_at else None,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            }
            for p in products
        ]
    finally:
        db.close()


@app.get("/export.csv")
def export_csv():
    db = SessionLocal()
    try:
        rows = db.query(Product).order_by(asc(Product.id)).all()
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["product_no", "product_code", "name", "category", "price", "original_price", "sold_out", "active", "first_seen_at", "last_seen_at", "source_url"])
        for p in rows:
            writer.writerow([
                p.source_product_no, p.product_code or "", p.name, p.category or "",
                p.price if p.price is not None else "", p.original_price if p.original_price is not None else "",
                p.sold_out, p.is_active, p.first_seen_at, p.last_seen_at, p.source_url,
            ])
        data = buffer.getvalue().encode("utf-8-sig")
        filename = f"vcu_products_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return StreamingResponse(iter([data]), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    finally:
        db.close()


@app.post("/api/refresh")
def api_refresh():
    if not ENABLE_MANUAL_REFRESH:
        raise HTTPException(status_code=403, detail="Manual refresh is disabled")
    if get_state()["running"]:
        return JSONResponse({"ok": False, "reason": "already_running"}, status_code=409)
    start_crawl_background()
    return {"ok": True, "started_at": datetime.utcnow().isoformat()}


@app.get("/health")
def health():
    return {"ok": True, "service": "vcu-product-monitor", "version": "2.1.0"}


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
