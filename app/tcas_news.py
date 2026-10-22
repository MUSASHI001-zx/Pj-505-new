"""ดึงข่าวประกาศจาก myTCAS (แทน Make.com)

myTCAS เป็นเว็บ static (Astro) — หน้า /news/ มีรายการข่าวทั้งหมดใน HTML
และแต่ละข่าวอยู่ที่ /news/{id}/ จึงต้องไล่ดึงทีละหน้า

ข้อมูลที่ได้: หัวข้อ วันที่ประกาศ เนื้อหา รูปประกอบ ลิงก์เอกสาร PDF
"""
from __future__ import annotations

import asyncio
import html
import re
import time
from typing import Any
from urllib.parse import unquote

import httpx

MYTCAS_SITE = "https://www.mytcas.com"
NEWS_LIST = f"{MYTCAS_SITE}/news/"
UA = "TCASBuddy/1.0 (+https://www.mytcas.com)"

CACHE_TTL = 900.0  # 15 นาที — ข่าวเปลี่ยนไม่บ่อย
MAX_NEWS = 120  # myTCAS มีข่าวทั้งหมด 105 ข่าว
DETAIL_CONCURRENCY = 12

# รูปจากเว็บเอง (โลโก้/ไอคอน) — ไม่ใช่รูปประกอบข่าว
SITE_IMAGES = ("/img/", "/_astro/", "cover70", "logo", "icon-")

# อีโมจิ Facebook — เป็นไอคอนประกอบข้อความ ไม่ใช่รูปประกอบข่าว (ไฟล์เล็ก ~1KB)
EMOJI_IMAGES = ("fbcdn.net/images/emoji", "emoji.php", ".gif")

# โดเมนที่ปกข่าวควรเป็นภาพเอกสาร/โปสเตอร์จริง
GOOD_IMAGE_HOSTS = ("i.mytcas.com", "assets.mytcas.com", "mytcas.com", "seedcdn.com")

# พื้นหลังสำรองจาก myTCAS — ใช้เมื่อข่าวไม่มีรูปประกอบ
FALLBACK_COVERS = (
    f"{MYTCAS_SITE}/cover70.jpg",
    "https://assets.mytcas.com/70/TCAS70-A-Level.jpg",
    "https://assets.mytcas.com/70/TCAS70-TGAT-TPAT.jpg",
)

# cache
_cache: dict[str, tuple[float, Any]] = {}


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def strip_tags(fragment: str) -> str:
    """ถอดแท็กออกจาก HTML แล้ว decode entity"""
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", fragment)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|td)>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return _text(html.unescape(raw).replace("\xa0", " "))


def clean_content(text: str) -> str:
    """ตัดส่วนหัวที่เป็น breadcrumb (‹ ข่าวประกาศ) และหัวข้อซ้ำออกจากเนื้อหา"""
    cleaned = _text(text)
    # "‹ ข่าวประกาศ" คือลิงก์ย้อนกลับ ไม่ใช่เนื้อหา
    cleaned = re.sub(r"^‹\s*ข่าวประกาศ\s*", "", cleaned)
    return _text(cleaned)


def _parse_thai_date(text: str) -> str | None:
    """'19 ตุลาคม 2569' หรือ '19 ต.ค. 69' → '2569-10-19' (ปี พ.ศ.)

    myTCAS ใช้ปี 2 หลักในรายการข่าว (เช่น "ต.ค. 69" = พ.ศ. 2569) — ต้องเติมให้ครบ
    """
    months = {
        "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4, "พฤษภาคม": 5, "มิถุนายน": 6,
        "กรกฎาคม": 7, "สิงหาคม": 8, "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
        # รูปย่อที่ myTCAS ใช้
        "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4, "พ.ค.": 5, "มิ.ย.": 6,
        "ก.ค.": 7, "ส.ค.": 8, "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
    }
    raw = _text(text)
    # ปี 4 หลัก (พ.ศ. เต็ม)
    match = re.search(r"(\d{1,2})\s*([ก-๙]+[.ก-๙]*)\s*(25\d{2}|26\d{2})", raw)
    year = None
    if match:
        day, name, year_text = match.groups()
        year = int(year_text)
    else:
        # ปี 2 หลัก — "69" แปลว่า พ.ศ. 2569
        match = re.search(r"(\d{1,2})\s*([ก-๙]+[.ก-๙]*)\s*(\d{2})\b", raw)
        if not match:
            return None
        day, name, short_year = match.groups()
        short = int(short_year)
        # แปลงเป็น พ.ศ. เต็ม (ย่อมาจาก 2500-2599)
        year = 2500 + short
        if year > 2699:  # กรณีข้ามรอบ
            year -= 100
    month = months.get(name)
    if not month:
        # ลองหาเดือนที่อยู่ในข้อความแทน
        for name_full, number in months.items():
            if name_full in raw:
                month = number
                break
    if not month:
        return None
    return f"{year}-{month:02d}-{int(day):02d}"


def parse_list_page(page_html: str) -> list[dict[str, Any]]:
    """ดึงรายการข่าวจากหน้า /news/ — ได้ id, หัวข้อ, วันที่"""
    items: list[dict[str, Any]] = []
    # แต่ละรายการ: <div class="date"><div class="day">19</div><small> ต.ค. 66 </small></div> <a href="/news/105/" class="link">หัวข้อ</a>
    pattern = re.compile(
        r'<div[^>]*class="date"[^>]*>\s*<div[^>]*class="day"[^>]*>(\d{1,2})</div>\s*'
        r"<small[^>]*>(.*?)</small>\s*</div>\s*"
        r'<a[^>]*href="(/news/(\d+)/)"[^>]*class="link"[^>]*>(.*?)</a>',
        re.S,
    )
    for match in pattern.finditer(page_html):
        day, month_text, href, news_id, title = match.groups()
        date_raw = _text(html.unescape(re.sub(r"<[^>]+>", " ", month_text)).replace("\xa0", " "))
        date_raw = f"{day} {date_raw}".strip()
        items.append({
            "id": news_id,
            "url": f"{MYTCAS_SITE}{href}",
            "title": strip_tags(title),
            "date_text": date_raw,
            "date": _parse_thai_date(date_raw),
        })
    if items:
        return items
    # ทางสำรับ: ไม่มีวันที่ แต่มีลิงก์ข่าวอย่างเดียว
    for href, title in re.findall(r'<a[^>]*href="(/news/(\d+)/)"[^>]*class="link"[^>]*>(.*?)</a>', page_html, re.S):
        items.append({"id": href, "url": f"{MYTCAS_SITE}{href}", "title": strip_tags(title), "date_text": "", "date": None})
    return items


def _news_id_from_url(url: str) -> str:
    """ดึง id ข่าวจาก URL (/news/105/ → 105)"""
    match = re.search(r"/news/(\d+)/", url)
    return match.group(1) if match else ""


def _pick_cover(images: list[str], news_id: str = "") -> str:
    """เลือกรูปที่จะใช้เป็นปกข่าว

    ข่าวบางอันมีรูปหลายภาพ (เช่น โปสเตอร์ประกาศ + ภาพประกอบเล็ก ๆ)
    รูปจากแหล่งที่น่าเชื่อถือ (myTCAS, seedcdn) มาก่อน และข้ามรูปที่เป็นไฟล์ตัวเล็ก
    ถ้าไม่มีรูปเลย ใช้พื้นหลังจาก myTCAS (หมุนตาม id เพื่อไม่ให้ทุกใบเหมือนกัน)
    """
    for src in images:
        if not any(host in src for host in GOOD_IMAGE_HOSTS):
            continue
        # ไฟล์ที่ดูเหมือนไอคอน (emoji/วัสดุ 1-32) ให้ข้าม
        name = src.rsplit("/", 1)[-1].lower()
        if re.search(r"[-_](1x|2x|16|32|48|64|96|128)\.", name):
            continue
        if name.startswith("icon") or "icon-" in name:
            continue
        return src
    # ไม่มีรูปที่เหมาะสม — ใช้พื้นหลัง myTCAS
    index = int(news_id) % len(FALLBACK_COVERS) if news_id.isdigit() else 0
    return FALLBACK_COVERS[index]


def _pdf_label(pdf_url: str) -> str:
    """ชื่อไฟล์ PDF ที่อ่านง่าย — ใช้เป็นคำอธิบายข่าวที่เนื้อหาอยู่ใน PDF เท่านั้น"""
    name = pdf_url.rsplit("/", 1)[-1]
    name = re.sub(r"\.(pdf|PDF)$", "", name)
    try:
        name = unquote(name)
    except Exception:  # noqa: BLE001 — ชื่อไฟล์ผิดรูปแบบก็ไม่เป็นไร
        pass
    name = name.replace("-", " ").replace("_", " ")
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        return "เอกสารประกาศ (PDF)"
    # ชื่อไฟล์ที่เป็นคำอังกฤษให้ใช้คำบรรยายทั่วไปแทน
    if re.fullmatch(r"[a-z0-9\s\-_.]+", name, re.I) and not re.search(r"[฀-๿]", name):
        return "เอกสารประกาศฉบับเต็ม (PDF)"
    return f"เอกสารประกาศ: {name}"


def parse_detail_page(page_html: str, url: str) -> dict[str, Any]:
    """ดึงเนื้อหาข่าวจากหน้า /news/{id}/"""
    start = page_html.find("<main")
    end = page_html.find("</main>")
    body = page_html[start:end] if start >= 0 and end > start else page_html

    title = ""
    heading = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    if heading:
        title = strip_tags(heading.group(1))

    content = clean_content(strip_tags(body))
    # เนื้อหาหลังหัวข้อและวันที่
    date_text = ""
    date_match = re.search(r"(\d{1,2}\s+[ก-๙]+\s+(?:25\d{2}|26\d{2}))", content)
    if date_match:
        date_text = date_match.group(1)

    images: list[str] = []
    for src in re.findall(r'<img[^>]*src="([^"]+)"', body):
        if any(src.startswith(prefix) for prefix in SITE_IMAGES):
            continue
        # อีโมจิ Facebook เป็นไอคอนประกอบข้อความ ไม่ใช่รูปประกอบข่าว
        if any(marker in src for marker in EMOJI_IMAGES):
            continue
        if src not in images:
            images.append(src)

    # เลือกรูปที่ใช้เป็นปก — ต้องเป็นภาพจากแหล่งที่น่าเชื่อถือ
    cover = _pick_cover(images, _news_id_from_url(url))
    has_own_cover = any(host in cover for host in GOOD_IMAGE_HOSTS)

    pdfs: list[str] = []
    for href in re.findall(r'href="([^"]+\.pdf)"', body):
        if href.startswith("/"):
            href = f"{MYTCAS_SITE}{href}"
        if href not in pdfs:
            pdfs.append(href)

    links: list[str] = []
    for href in re.findall(r'href="(https?://[^"]+)"', body):
        if "mytcas.com" in href and "/news/" not in href:
            continue
        if href not in links:
            links.append(href)

    # ตัดหัวข้อและวันที่ออกจากเนื้อหา — เก็บเฉพาะเนื้อหาจริง
    body_content = content
    if title and body_content.startswith(title):
        body_content = body_content[len(title):].strip()
    if date_text and body_content.startswith(date_text):
        body_content = body_content[len(date_text):].strip()
    body_content = _text(body_content)
    # ข่าวประกาศส่วนใหญ่เป็น PDF — เนื้อหาในหน้าเว็บจึงสั้นมาก
    # ใช้ชื่อไฟล์ PDF เป็นคำอธิบายแทนจะให้ผู้ใช้รู้ว่าต้องเปิดเอกสารอะไร
    if len(body_content) < 40 and pdfs:
        body_content = _pdf_label(pdfs[0])
    elif len(body_content) < 12:
        body_content = "ดูรายละเอียดเพิ่มเติมในเอกสารประกาศ"

    return {
        "title": title,
        "content": body_content,
        "date_text": date_text,
        "date": _parse_thai_date(date_text),
        "images": images,
        "cover": cover,
        "has_own_cover": has_own_cover,
        "pdfs": pdfs,
        "links": links,
        "url": url,
    }


async def _get(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url)
    response.raise_for_status()
    return response.text


async def fetch_news(force: bool = False, limit: int = MAX_NEWS) -> list[dict[str, Any]]:
    """ดึงข่าวจาก myTCAS — คืนรายการพร้อมเนื้อหา (เรียงใหม่สุดก่อน)"""
    news, _ = await fetch_news_with_total(force=force, limit=limit)
    return news


async def fetch_news_with_total(force: bool = False, limit: int = MAX_NEWS) -> tuple[list[dict[str, Any]], int]:
    """คืน (รายการข่าว, จำนวนข่าวทั้งหมดที่ myTCAS มี)

    ดึงรายละเอียดข่าวทั้งหมดเสมอ (myTCAS มี ~105 ข่าว ใช้เวลา ~3 วินาที)
    เพื่อให้นับจำนวนได้ถูกต้องและค้นหาเจอครบ — cache ไว้ 15 นาที
    """
    if not force:
        hit = _cache.get("news")
        if hit and time.monotonic() - hit[0] < CACHE_TTL:
            return hit[1][:limit], hit[2]

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        headers={"User-Agent": UA, "Accept": "text/html"},
        follow_redirects=True,
    ) as client:
        list_html = await _get(client, NEWS_LIST)
        entries = parse_list_page(list_html)
        if not entries:
            return [], 0

        # เรียงตาม id แปลว่าใหม่กว่า
        entries.sort(key=lambda item: int(item["id"]), reverse=True)
        total = len(entries)

        semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)

        async def detail(entry: dict[str, Any]) -> dict[str, Any] | None:
            async with semaphore:
                try:
                    page = await _get(client, entry["url"])
                except (httpx.HTTPError, ValueError):
                    return None
            parsed = parse_detail_page(page, entry["url"])
            return {
                "id": entry["id"],
                "title": parsed["title"] or entry["title"],
                "summary": _short_summary(parsed["content"]),
                "content": parsed["content"],
                "date": entry["date"] or parsed["date"],
                "date_text": entry["date_text"] or parsed["date_text"],
                "image_url": parsed["cover"],
                "has_own_image": parsed["has_own_cover"],
                "images": parsed["images"],
                "pdfs": parsed["pdfs"],
                "links": parsed["links"],
                "source_url": entry["url"],
                "source": "mytcas",
                "source_label": "myTCAS",
            }

        results = await asyncio.gather(*(detail(entry) for entry in entries))
        news = [item for item in results if item and item["title"]]

    _cache["news"] = (time.monotonic(), news, total)
    return news[:limit], total


def _short_summary(content: str, limit: int = 220) -> str:
    """ทำสรุปสั้น ๆ จากเนื้อหาข่าว — ตัดที่ประโยคแรกที่ยาวพอสมเหตุสมผล"""
    text = _text(content)
    if len(text) <= limit:
        return text
    # ตัดที่ประโยค (จุลภาค/เว้นวรรค) ถ้าเจอก่อนครบความยาว
    for separator in (". ", " โดย ", " และ ", " ซึ่ง ", ", "):
        index = text.find(separator, limit // 2)
        if index > 0:
            return text[:index].rstrip() + "…"
    return text[:limit].rstrip() + "…"


def build_router(repo: Any = None) -> Any:
    from fastapi import APIRouter, HTTPException

    router = APIRouter(prefix="/api/tcas")

    @router.get("/news")
    async def news(limit: int = 30) -> dict[str, Any]:
        """ข่าวประกาศจาก myTCAS (สด)"""
        try:
            items, total = await fetch_news_with_total(limit=min(max(limit, 1), MAX_NEWS))
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"ดึงข่าวจาก myTCAS ไม่สำเร็จ: {exc}") from None
        return {
            "items": items,
            "total": total,
            "returned": len(items),
            "source": MYTCAS_SITE,
        }

    return router
