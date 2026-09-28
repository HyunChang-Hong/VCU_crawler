from __future__ import annotations

import hashlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import desc

from config import (
    INACTIVE_AFTER_MISSES,
    MAX_CATEGORY_PAGES,
    MAX_PRODUCTS,
    MAX_CONCURRENT_REQUESTS,
    REQUEST_DELAY_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SITE,
)
from database import SessionLocal
from models import CrawlRun, Product, ProductHistory

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

PRODUCT_PATTERNS = [
    re.compile(r"/product/(?:[^/?#]+/)?(?P<no>\d+)(?:/|$)", re.I),
    re.compile(r"[?&]product_no=(?P<no>\d+)(?:&|$)", re.I),
]

_state_lock = threading.Lock()
_state = {
    "running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_status": "idle",
    "last_error": None,
    "last_discovered": 0,
    "last_changed": 0,
    "queued": 0,
    "processed": 0,
    "progress_pct": 0,
    "current_product": None,
    "new_count": 0,
    "updated_count": 0,
}


@dataclass
class ScrapedProduct:
    source_product_no: str
    name: str
    source_url: str
    price: int | None = None
    original_price: int | None = None
    product_code: str | None = None
    image_url: str | None = None
    category: str | None = None
    summary: str | None = None
    sold_out: bool = False
    currency: str = "KRW"

    def digest(self) -> str:
        raw = "|".join(
            str(x or "")
            for x in (
                self.name,
                self.price,
                self.original_price,
                self.product_code,
                self.image_url,
                self.category,
                self.sold_out,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_state() -> dict:
    with _state_lock:
        return dict(_state)


def _set_state(**kwargs):
    with _state_lock:
        _state.update(kwargs)


def _money(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^0-9]", "", text)
    return int(digits) if digits else None


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    value = re.sub(r"\s+", " ", text).strip()
    return value or None


def extract_product_no(url: str) -> str | None:
    for pattern in PRODUCT_PATTERNS:
        m = pattern.search(url)
        if m:
            return m.group("no")
    return None


def _absolute(base: str, href: str | None) -> str | None:
    if not href:
        return None
    if href.startswith("//"):
        return "https:" + href
    return urljoin(base, href)


def _same_host(url: str) -> bool:
    return urlparse(url).netloc == urlparse(TARGET_SITE).netloc


def extract_links(html: str, base_url: str) -> tuple[dict[str, str], set[str]]:
    soup = BeautifulSoup(html, "html.parser")
    products: dict[str, str] = {}
    categories: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = _absolute(base_url, a.get("href"))
        if not href or not _same_host(href):
            continue
        no = extract_product_no(href)
        if no:
            products.setdefault(no, href)
            continue
        low = href.lower()
        if "/product/list" in low or "/category/" in low or "cate_no=" in low:
            categories.add(href)

    return products, categories


def _with_page(url: str, page: int) -> str:
    parts = urlparse(url)
    q = parse_qs(parts.query, keep_blank_values=True)
    q["page"] = [str(page)]
    return urlunparse(parts._replace(query=urlencode(q, doseq=True)))


def _meta(soup: BeautifulSoup, *keys: tuple[str, str]) -> str | None:
    for attr, value in keys:
        tag = soup.find("meta", attrs={attr: value})
        if tag and tag.get("content"):
            return _clean(tag.get("content"))
    return None


def _text_first(soup: BeautifulSoup, selectors: Iterable[str]) -> str | None:
    for selector in selectors:
        el = soup.select_one(selector)
        if el:
            t = _clean(el.get_text(" ", strip=True))
            if t:
                return t
    return None


def _row_value(soup: BeautifulSoup, labels: Iterable[str]) -> str | None:
    labels = tuple(labels)
    for tr in soup.select("tr"):
        cells = tr.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        label = _clean(cells[0].get_text(" ", strip=True)) or ""
        if any(x in label for x in labels):
            return _clean(cells[-1].get_text(" ", strip=True))
    for li in soup.select("li"):
        text = _clean(li.get_text(" ", strip=True)) or ""
        for label in labels:
            if label in text:
                value = text.split(label, 1)[-1].strip(" :")
                if value:
                    return value
    return None


def parse_product(html: str, url: str) -> ScrapedProduct | None:
    soup = BeautifulSoup(html, "html.parser")
    no = extract_product_no(url)
    if not no:
        canonical = soup.find("link", rel="canonical")
        if canonical and canonical.get("href"):
            no = extract_product_no(canonical["href"])
    if not no:
        return None

    name = _text_first(
        soup,
        [
            ".xans-product-detail .headingArea h2",
            ".headingArea h2",
            ".infoArea h2",
            "h2.name",
            "h2",
        ],
    ) or _meta(soup, ("property", "og:title"), ("name", "twitter:title"))
    if not name:
        return None

    price_meta = _meta(
        soup,
        ("property", "product:price:amount"),
        ("property", "og:price:amount"),
    )
    sale_price_text = _row_value(soup, ["판매가", "할인가", "할인판매가", "최종판매가"])
    consumer_price_text = _row_value(soup, ["소비자가", "정가"])
    code = _row_value(soup, ["상품코드", "자체상품코드"])

    image = _meta(soup, ("property", "og:image"), ("name", "twitter:image"))
    if not image:
        img = soup.select_one(".keyImg img, .thumbnail img, .xans-product-image img")
        image = _absolute(url, img.get("src") or img.get("ec-data-src")) if img else None
    else:
        image = _absolute(url, image)

    description = _meta(soup, ("name", "description"), ("property", "og:description"))

    crumbs = []
    for a in soup.select(".path a, .breadcrumb a, [class*='breadcrumb'] a"):
        t = _clean(a.get_text(" ", strip=True))
        if t and t.lower() not in {"home", "홈"} and t not in crumbs:
            crumbs.append(t)
    category = " > ".join(crumbs[-3:]) if crumbs else None

    sold_out = bool(
        soup.select_one(".soldout, .soldOut, [class*='soldout'], img[alt*='품절'], img[alt*='SOLD OUT']")
    )
    if not sold_out:
        body_text = _clean(soup.get_text(" ", strip=True)) or ""
        sold_out = "SOLD OUT" in body_text.upper() or "품절" in body_text

    price = _money(price_meta) or _money(sale_price_text)
    original_price = _money(consumer_price_text)

    return ScrapedProduct(
        source_product_no=no,
        name=name,
        source_url=url,
        price=price,
        original_price=original_price,
        product_code=code,
        image_url=image,
        category=category,
        summary=description,
        sold_out=sold_out,
    )


class Cafe24Crawler:
    def __init__(self, target: str = TARGET_SITE):
        self.target = target
        self.client = httpx.Client(
            headers={
                "User-Agent": UA,
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=True,
        )

    def close(self):
        self.client.close()

    def fetch(self, url: str) -> str:
        r = self.client.get(url)
        r.raise_for_status()
        # Cafe24 pages can occasionally omit/incorrectly declare charset.
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.charset_encoding or "utf-8"
        time.sleep(REQUEST_DELAY_SECONDS)
        return r.text

    def discover(self) -> dict[str, str]:
        home = self.fetch(self.target)
        products, categories = extract_links(home, self.target)

        for category_url in sorted(categories):
            previous_signature = None
            for page in range(1, MAX_CATEGORY_PAGES + 1):
                if len(products) >= MAX_PRODUCTS:
                    break
                page_url = _with_page(category_url, page)
                try:
                    html = self.fetch(page_url)
                except httpx.HTTPError:
                    break
                found, _ = extract_links(html, page_url)
                signature = tuple(sorted(found.keys()))
                if not signature or signature == previous_signature:
                    break
                previous_signature = signature
                before = len(products)
                products.update(found)
                if len(products) == before and page > 1:
                    break

        return dict(list(products.items())[:MAX_PRODUCTS])

    def scrape_one(self, url: str) -> ScrapedProduct | None:
        try:
            return parse_product(self.fetch(url), url)
        except (httpx.HTTPError, ValueError):
            return None

    def scrape_stream(self):
        links = self.discover()
        items = list(links.items())[:MAX_PRODUCTS]
        _set_state(queued=len(items), processed=0, progress_pct=0, current_product=None)
        with ThreadPoolExecutor(max_workers=max(1, MAX_CONCURRENT_REQUESTS), thread_name_prefix="vcu-fetch") as pool:
            future_map = {pool.submit(self.scrape_one, url): (no, url) for no, url in items}
            for index, future in enumerate(as_completed(future_map), start=1):
                no, _ = future_map[future]
                product = future.result()
                _set_state(
                    processed=index,
                    progress_pct=int(index * 100 / max(1, len(items))),
                    current_product=product.name if product else f"상품번호 {no}",
                )
                if product:
                    yield product


def _change_type(existing: Product, scraped: ScrapedProduct) -> str:
    changes = []
    if existing.price != scraped.price:
        changes.append("price")
    if existing.sold_out != scraped.sold_out:
        changes.append("stock")
    if existing.name != scraped.name:
        changes.append("name")
    return "+".join(changes) if changes else "content"


def run_crawl() -> dict:
    if get_state()["running"]:
        return {"ok": False, "reason": "already_running"}

    started = datetime.utcnow()
    _set_state(
        running=True,
        last_started_at=started.isoformat(),
        last_status="running",
        last_error=None,
        last_discovered=0,
        last_changed=0,
        queued=0,
        processed=0,
        progress_pct=0,
        current_product="상품 URL 탐색 중",
        new_count=0,
        updated_count=0,
    )

    db = SessionLocal()
    run = CrawlRun(started_at=started, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    crawler = Cafe24Crawler()
    try:
        now = datetime.utcnow()
        seen = set()
        changed_count = 0
        discovered_count = 0
        new_count = 0
        updated_count = 0

        for scraped in crawler.scrape_stream():
            discovered_count += 1
            seen.add(scraped.source_product_no)
            digest = scraped.digest()
            existing = (
                db.query(Product)
                .filter(Product.source_product_no == scraped.source_product_no)
                .one_or_none()
            )
            if existing is None:
                existing = Product(
                    source_product_no=scraped.source_product_no,
                    product_code=scraped.product_code,
                    name=scraped.name,
                    price=scraped.price,
                    original_price=scraped.original_price,
                    currency=scraped.currency,
                    image_url=scraped.image_url,
                    source_url=scraped.source_url,
                    category=scraped.category,
                    summary=scraped.summary,
                    sold_out=scraped.sold_out,
                    is_active=True,
                    miss_count=0,
                    content_hash=digest,
                    first_seen_at=now,
                    last_seen_at=now,
                    updated_at=now,
                )
                db.add(existing)
                db.flush()
                changed_count += 1
                new_count += 1
                db.add(ProductHistory(
                    product_id=existing.id, captured_at=datetime.utcnow(), change_type="new",
                    name=scraped.name, price=scraped.price, original_price=scraped.original_price,
                    sold_out=scraped.sold_out,
                ))
            else:
                changed = existing.content_hash != digest or not existing.is_active
                if changed:
                    change_type = _change_type(existing, scraped)
                    changed_count += 1
                    updated_count += 1
                    db.add(ProductHistory(
                        product_id=existing.id, captured_at=datetime.utcnow(), change_type=change_type,
                        name=scraped.name, price=scraped.price, original_price=scraped.original_price,
                        sold_out=scraped.sold_out,
                    ))
                existing.product_code = scraped.product_code
                existing.name = scraped.name
                existing.price = scraped.price
                existing.original_price = scraped.original_price
                existing.currency = scraped.currency
                existing.image_url = scraped.image_url
                existing.source_url = scraped.source_url
                existing.category = scraped.category
                existing.summary = scraped.summary
                existing.sold_out = scraped.sold_out
                existing.is_active = True
                existing.miss_count = 0
                existing.content_hash = digest
                existing.last_seen_at = datetime.utcnow()
                if changed:
                    existing.updated_at = datetime.utcnow()

            db.commit()
            _set_state(
                last_discovered=discovered_count, last_changed=changed_count,
                new_count=new_count, updated_count=updated_count,
            )

        if discovered_count == 0:
            raise RuntimeError("상품을 한 건도 찾지 못했습니다. 대상 사이트 접속 여부 또는 Cafe24 마크업 변경을 확인하세요.")

        # Only after a full crawl finishes do we count misses.
        for p in db.query(Product).filter(Product.is_active.is_(True)).all():
            if p.source_product_no not in seen:
                p.miss_count += 1
                if p.miss_count >= INACTIVE_AFTER_MISSES:
                    p.is_active = False
                    p.updated_at = datetime.utcnow()
                    changed_count += 1
                    db.add(ProductHistory(
                        product_id=p.id, captured_at=datetime.utcnow(), change_type="ended",
                        name=p.name, price=p.price, original_price=p.original_price, sold_out=p.sold_out,
                    ))

        run.finished_at = datetime.utcnow()
        run.status = "success"
        run.discovered_count = discovered_count
        run.changed_count = changed_count
        db.commit()

        _set_state(
            running=False, last_finished_at=run.finished_at.isoformat(), last_status="success",
            last_error=None, last_discovered=discovered_count, last_changed=changed_count,
            processed=discovered_count, progress_pct=100, current_product=None,
            new_count=new_count, updated_count=updated_count,
        )
        return {"ok": True, "discovered": discovered_count, "changed": changed_count}

    except Exception as e:
        db.rollback()
        run = db.query(CrawlRun).filter(CrawlRun.id == run.id).one_or_none()
        if run:
            run.finished_at = datetime.utcnow()
            run.status = "failed"
            run.error_message = str(e)[:4000]
            db.commit()
        _set_state(
            running=False, last_finished_at=datetime.utcnow().isoformat(), last_status="failed",
            last_error=str(e), current_product=None,
        )
        return {"ok": False, "error": str(e)}
    finally:
        crawler.close()
        db.close()


def latest_run() -> CrawlRun | None:
    db = SessionLocal()
    try:
        return db.query(CrawlRun).order_by(desc(CrawlRun.id)).first()
    finally:
        db.close()
