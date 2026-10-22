"""คลังข้อมูลข่าว/เรื่องราว TCAS จาก Dek-D (เด็กดี)

เด็กดี (dek-d.com) เป็นเว็บ PHP ไม่มี API สาธารณะ จึงต้อง parse HTML
หน้าที่ใช้:
- /tcas/home/more/alert/?page=N   — ข่าว TCAS Alert (แจ้งเตือนเร่งด่วน) 15 ข่าวต่อหน้า
- /tcas/home/more/article/?cat=N  — บทความ/คลิปเกี่ยวกับการสมัคร

ข้อมูลแต่ละรายการมี: id, หัวข้อ, ข้อความย่อ, วันเวลา, แท็ก, ลิงก์
"""
from __future__ import annotations

import asyncio
import html
import re
import time
from typing import Any

import httpx

DEKD_SITE = "https://www.dek-d.com"
ALERT_LIST = f"{DEKD_SITE}/tcas/home/more/alert/"
ARTICLE_LIST = f"{DEKD_SITE}/tcas/home/more/article/"
UA = "TCASBuddy/1.0 (+https://www.dek-d.com)"

CACHE_TTL = 900.0  # 15 นาที
MAX_PAGES = 12  # ดึงสูงสุดกี่หน้าต่อครั้ง (15 × 12 = 180 ข่าว)

# หมวดเนื้อหา — "alert" ใช้หน้าแจ้งเตือน, ที่เหลือใช้หน้าบทความตาม cat
CATEGORIES = {
    "alert": {"label": "TCAS Alert", "url": ALERT_LIST, "param": ""},
    "daily": {"label": "TCAS Daily", "url": ARTICLE_LIST, "param": "cat=1"},
    "review": {"label": "TCAS Review", "url": ARTICLE_LIST, "param": "cat=3"},
    "coach": {"label": "TCAS Coach", "url": ARTICLE_LIST, "param": "cat=2"},
    "tour": {"label": "TCAS School Tour", "url": ARTICLE_LIST, "param": "cat=10"},
    "event": {"label": "TCAS Event", "url": ARTICLE_LIST, "param": "cat=21"},
    "dreamcampus": {"label": "Dream Campus", "url": ARTICLE_LIST, "param": "cat=23"},
    "idol": {"label": "TCAS Idol", "url": ARTICLE_LIST, "param": "cat=25"},
    "tutoring": {"label": "ติว TCAS", "url": ARTICLE_LIST, "param": "cat=28"},
}

# แท็กจากสติกเกอร์ของเด็กดี — ใช้ค้นหาตามหัวข้อ
TAG_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("portfolio", ("portfolio", "แฟ้มสะสมผลงาน", "พอร์ตโฟลิโอ")),
    ("quota", ("โควตา", "quota")),
    ("tgat", ("tgat", "tgat")),
    ("tpat", ("tpat", "tpat")),
    ("a-level", ("a-level", "alevel", "เอ-เลเวล")),
    ("admission", ("admission", "รอบ 3", "รอบ admission")),
    ("dekd", ("เด็กดี", "dek-d", "dekd", "dek70")),
    ("scholarship", ("ทุนการศึกษา", "ทุน", "scholarship")),
    ("exam", ("สอบ", "ข้อสอบ", "exam", "pretest")),
)

_cache: dict[str, tuple[float, Any]] = {}


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _strip_html(fragment: str) -> str:
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", fragment)
    raw = re.sub(r"(?i)<br\s*/?>", " ", raw)
    raw = re.sub(r"(?i)</(p|div|li|h[1-6]|td|tr)>", " ", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return _text(html.unescape(raw))


def parse_alert_page(page_html: str) -> list[dict[str, Any]]:
    """แยกรายการข่าวจากหน้า HTML ของเด็กดี"""
    items: list[dict[str, Any]] = []
    pattern = re.compile(
        r'<div class="tcas-alert-item[^"]*"[^>]*data-timestamp="(\d+)"[^>]*>(.*?)'
        r'(?=<div class="tcas-alert-item|</article>|\Z)',
        re.S,
    )
    for match in pattern.finditer(page_html):
        timestamp = int(match.group(1))
        block = match.group(2)

        date_text = ""
        date_match = re.search(r'<div class="datetime"[^>]*>(.*?)</div>', block, re.S)
        if date_match:
            date_text = _strip_html(date_match.group(1))

        message = ""
        message_match = re.search(r'<div class="message"[^>]*>(.*?)</div>', block, re.S)
        if message_match:
            message = _strip_html(message_match.group(1))

        url = ""
        link_match = re.search(r'href="(https://www\.dek-d\.com/tcas/\d+/)"', block)
        if link_match:
            url = link_match.group(1)

        if not (message or url):
            continue

        items.append({
            "id": str(timestamp),
            "timestamp": timestamp,
            "title": message[:300] or date_text,
            "summary": message[:500],
            "date_text": date_text,
            "date": _timestamp_to_date(timestamp),
            "url": url,
            "tags": _guess_tags(message),
        })
    return items


def _timestamp_to_date(timestamp: int) -> str:
    from datetime import datetime, timezone, timedelta
    # เด็กดีใช้เวลาไทย (UTC+7)
    moment = datetime.fromtimestamp(timestamp, tz=timezone(timedelta(hours=7)))
    return moment.strftime("%Y-%m-%d")


def _guess_tags(text: str) -> list[str]:
    lowered = text.lower()
    tags = [name for name, keywords in TAG_HINTS if any(keyword in lowered for keyword in keywords)]
    return tags


def _is_article_page(page_html: str) -> bool:
    return "tcas-alert-item" not in page_html and "article-item" in page_html


def parse_article_page(page_html: str) -> list[dict[str, Any]]:
    """แยกรายการบทความจากหน้า category — โครงสร้างคือ <article class="article-box">"""
    items: list[dict[str, Any]] = []
    pattern = re.compile(
        r'<article class="article-box[^"]*"(.*?)</article>',
        re.S,
    )
    for match in pattern.finditer(page_html):
        block = match.group(1)

        link = re.search(r'href="(/tcas/\d+/)"', block)
        if not link:
            continue
        url = f"{DEKD_SITE}{link.group(1)}"

        title = ""
        title_match = re.search(r'<a[^>]*class="title"[^>]*>(.*?)</a>', block, re.S)
        if not title_match:
            title_match = re.search(r'<span[^>]*>(.*?)</span>', block, re.S)
        if title_match:
            title = _strip_html(title_match.group(1))

        category = ""
        category_match = re.search(r'class="categorylink"[^>]*>(.*?)</a>', block, re.S)
        if category_match:
            category = _strip_html(category_match.group(1))

        image = ""
        image_match = re.search(r'data-background-url="([^"]+)"', block)
        if image_match:
            image = image_match.group(1)

        if not title:
            continue

        items.append({
            "id": url.rstrip("/").split("/")[-1],
            "title": title[:300],
            "summary": title[:500],
            "date_text": "",
            "date": "",
            "url": url,
            "image_url": image,
            "article_category": category,
            "tags": _guess_tags(f"{title} {category}"),
        })
    return items


async def _fetch_page(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url)
    response.raise_for_status()
    # เด็กดีบางหน้าเป็น TIS-620 — ต้อง decode ให้ถูก
    content = response.content
    for encoding in ("utf-8", "tis-620", "cp874", "iso-8859-11"):
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


async def fetch_category(
    key: str,
    pages: int = 1,
    force: bool = False,
) -> list[dict[str, Any]]:
    """ดึงรายการเนื้อหาหมวดที่ระบุจากเด็กดี"""
    config = CATEGORIES.get(key)
    if not config:
        return []
    cache_key = f"cat:{key}"
    if not force:
        hit = _cache.get(cache_key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL:
            return hit[1]

    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        headers={"User-Agent": UA},
        follow_redirects=True,
    ) as client:
        for page in range(1, max(1, min(pages, MAX_PAGES)) + 1):
            separator = "&" if "?" in config["url"] else "?"
            url = f"{config['url']}{separator}{config['param']}{'&' if config['param'] else ''}page={page}"
            try:
                page_html = await _fetch_page(client, url)
            except httpx.HTTPError:
                break
            items = parse_alert_page(page_html) if key == "alert" else parse_article_page(page_html)
            if not items:
                break
            for item in items:
                marker = item["url"] or item["id"]
                if marker in seen:
                    continue
                seen.add(marker)
                item["category"] = key
                item["category_label"] = config["label"]
                collected.append(item)

    collected.sort(key=lambda item: item.get("timestamp") or 0, reverse=True)
    _cache[cache_key] = (time.monotonic(), collected)
    return collected


async def fetch_all(pages: int = 2, force: bool = False) -> list[dict[str, Any]]:
    """รวมข้อมูลทุกหมวด — เรียงตามเวลาล่าสุด"""
    results = await asyncio.gather(
        *(fetch_category(key, pages=pages, force=force) for key in CATEGORIES)
    )
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in results:
        for item in group:
            marker = item["url"] or item["id"]
            if marker in seen:
                continue
            seen.add(marker)
            merged.append(item)
    merged.sort(key=lambda item: item.get("timestamp") or 0, reverse=True)
    return merged


def build_router(repo: Any = None) -> Any:
    from fastapi import APIRouter, HTTPException

    router = APIRouter(prefix="/api/dekd")

    @router.get("/library")
    async def library(cat: str = "", q: str = "", pages: int = 2) -> dict[str, Any]:
        """คลังข้อมูลเรื่องสอบ/ข่าว TCAS จากเด็กดี"""
        try:
            if cat and cat in CATEGORIES:
                items = await fetch_category(cat, pages=pages)
            else:
                items = await fetch_all(pages=pages)
        except Exception as exc:  # noqa: BLE001 — เว็บต้นทางมีปัญหาไม่ควรทำให้หน้าเว็บพัง
            raise HTTPException(status_code=502, detail=f"ดึงข้อมูลจากเด็กดีไม่สำเร็จ: {exc}") from None

        needle = q.strip().lower()
        if needle:
            items = [
                item for item in items
                if needle in f"{item.get('title', '')} {item.get('summary', '')} {' '.join(item.get('tags') or [])}".lower()
            ]

        return {
            "items": items,
            "total": len(items),
            "categories": [{"key": key, "label": value["label"]} for key, value in CATEGORIES.items()],
            "source": DEKD_SITE,
        }

    return router
