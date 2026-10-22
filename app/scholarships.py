"""ค้นหาทุนการศึกษา — รวมข้อมูลทุนจาก 2 แหล่ง

แหล่งข้อมูล:
1. กสศ. / findstudentship.eef.or.th  →  API สาธารณะ GET /api/v3/scholar
2. scholarship.in.th                  →  WordPress REST API GET /wp-json/wp/v2/posts

หมายเหตุเรื่องการค้นหา: API ของทั้งสองเว็บค้นคำภาษาไทยไม่ได้ (โทเคนไนเซอร์ของเว็บทำงานกับคำอังกฤษเท่านั้น)
ระบบจึงดึงรายการทั้งหมดมา cache ไว้ แล้วค้นหาแบบ substring ฝั่งเซิร์ฟเวอร์ เพื่อให้ค้นคำไทยได้จริง
"""
from __future__ import annotations

import asyncio
import html
import re
import time
from datetime import date, datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

EEF_API = "https://findstudentship.eef.or.th/api/v3/scholar"
EEF_SITE = "https://findstudentship.eef.or.th"
WP_API = "https://scholarship.in.th/wp-json/wp/v2/posts"
WP_SITE = "https://scholarship.in.th"

SOURCE_EEF = "eef"
SOURCE_SIT = "sit"

SOURCE_LABELS = {
    SOURCE_EEF: "กสศ. (findstudentship)",
    SOURCE_SIT: "Scholarship.in.th",
}

CACHE_TTL = 600.0  # 10 นาที — ข้อมูลทุนเปลี่ยนไม่บ่อย
DEFAULT_LIMIT = 24
MAX_LIMIT = 120
UA = "TCASBuddy/1.0 (+https://github.com/tcasbuddy)"

# ระดับชั้น → กลุ่มที่ใช้กรอง
LEVEL_GROUPS: dict[str, tuple[str, ...]] = {
    "ประถม-มัธยมต้น": ("อนุบาล", "ประถม", "มัธยมต้น"),
    "มัธยมปลาย-ปวช.": ("มัธยมปลาย", "ปวช.", "ปวช"),
    "ปวส.-ปริญญาตรี": ("ปวส.", "ปวส", "ปริญญาตรี", "หลักสูตรระยะสั้น"),
    "ปริญญาโท-เอก": ("ปริญญาโท", "ปริญญาเอก"),
}
ALL_LEVELS = tuple(LEVEL_GROUPS.keys())

# คำใบ้ระดับชั้นที่พบในหมวดของ scholarship.in.th
WP_LEVEL_HINTS: tuple[tuple[str, str], ...] = (
    ("ทุนปริญญาเอก", "ปริญญาเอก"),
    ("ทุนปริญญาโท", "ปริญญาโท"),
    ("ทุนปริญญาตรี", "ปริญญาตรี"),
    ("ปริญญาตรี", "ปริญญาตรี"),
    ("ปริญญาโท", "ปริญญาโท"),
    ("ปริญญาเอก", "ปริญญาเอก"),
)

# ---------------------------------------------------------------------------
# สถานะทุน — คำนวณเอง เพราะ API ของกสศ. ไม่มีตัวกรองสถานะที่ใช้ได้จริง
# ---------------------------------------------------------------------------
STATUS_OPEN = "เปิดรับสมัคร"
STATUS_CLOSING = "ใกล้ปิดรับ"
STATUS_CLOSED = "ปิดรับแล้ว"
STATUS_UNKNOWN = "ไม่ระบุ"
ALL_STATUS = (STATUS_OPEN, STATUS_CLOSING, STATUS_CLOSED, STATUS_UNKNOWN)

THAI_MONTHS = {
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4, "พฤษภาคม": 5, "มิถุนายน": 6,
    "กรกฎาคม": 7, "สิงหาคม": 8, "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
}

# เกณฑ์ว่า "ใกล้ปิดรับ" (วัน)
CLOSING_SOON_DAYS = 30

# ค่าที่ไม่ใช่ตัวเลขเงินจริง
NON_AMOUNT_VALUES = {"-", "ไม่ระบุ", "ไม่ระบุราคา", "ตามจริง", "N/A", "n/a", ""}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dates_in_text(raw: str) -> list[date]:
    """หาวันที่ทั้งหมดที่พบในข้อความ (รองรับช่วงวันที่)"""
    found: list[date] = []
    # "2022/2/1" หรือ "2022-02-01" — ค.ศ.
    for match in re.finditer(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", raw):
        year, month, day = (int(part) for part in match.groups())
        try:
            found.append(date(year, month, day))
        except ValueError:
            pass
    if found:
        return found
    # "31/10/2569" — ปี พ.ศ.
    for match in re.finditer(r"(\d{1,2})/(\d{1,2})/(25\d{2})", raw):
        day, month, year = (int(part) for part in match.groups())
        try:
            found.append(date(year - 543, month, day))
        except ValueError:
            pass
    if found:
        return found
    # "31 ตุลาคม 2569" — ปี พ.ศ. (ปีมักอยู่หลังเดือน หรือท้ายข้อความ)
    for match in re.finditer(r"(25[6-9]\d|26\d\d)", raw):
        year = int(match.group(1)) - 543
        for name, month in THAI_MONTHS.items():
            pos = raw.find(name)
            if pos < 0:
                continue
            # เลขวันที่ที่อยู่ก่อนชื่อเดือน (เช่น "31 ตุลาคม")
            before = re.findall(r"(\d{1,2})\s*$", raw[:pos])
            day = int(before[-1]) if before else 1
            try:
                found.append(date(year, month, day))
            except ValueError:
                pass
            break
    if found:
        return found
    # ปี 2 หลัก เช่น "ภายใน 31 มกราคม 68" — เติมเป็น พ.ศ. 25xx
    for match in re.finditer(r"\b(6\d|7\d)\b", raw):
        year = 2500 + int(match.group(1))
        for name, month in THAI_MONTHS.items():
            pos = raw.find(name)
            if pos < 0:
                continue
            before = re.findall(r"(\d{1,2})\s*$", raw[:pos])
            day = int(before[-1]) if before else 1
            try:
                found.append(date(year - 543, month, day))
            except ValueError:
                pass
            break
    return found


def parse_thai_date(text: str) -> date | None:
    """แปลงวันที่ไทยเป็น date (ค.ศ.) — รองรับ "31 ตุลาคม 2569", "31/10/2569", "2022/2/1"

    ถ้าเป็นช่วงวันที่ ("ตั้งแต่ 1 ก.ค. 2568 ถึง 28 ก.พ. 2569") คืนวันที่สิ้นสุด เพราะเป็นวันปิดรับ
    คืน None ถ้าไม่มีปี พ.ศ. ในข้อความ (ข้อความแบบ "ตลอดทั้งปี" หรือ "ของทุกปี")
    """
    raw = _text(text)
    if not raw:
        return None
    found = _dates_in_text(raw)
    return max(found) if found else None


def extract_deadline_date(item: dict[str, Any]) -> date | None:
    """หาวันปิดรับจริง — ใช้ end_date ก่อน (โครงสร้างถูกต้อง) แล้วค่อย parse ข้อความ start_at"""
    end_date = _text(item.get("end_date"))
    if end_date:
        try:
            return datetime.fromisoformat(end_date.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    return parse_thai_date(_text(item.get("start_at")))


# ข้อความที่แปลว่าทุนยังเปิดอยู่ แต่ไม่มีวันปิดชัดเจน
RECURRING_MARKERS = ("ตลอดทั้งปี", "ของทุกปี", "ทุกปี", "เปิดรับสมัครตลอด")


def compute_status(item: dict[str, Any]) -> str:
    """สถานะทุน: เปิดรับ / ใกล้ปิด / ปิดแล้ว / ไม่ระบุ

    - วันที่ชัดเจนและเลยมาแล้ว → ปิดรับแล้ว
    - วันที่ชัดเจนและยังไม่ถึง → เปิดรับ (หรือใกล้ปิดถ้าเหลือไม่ถึง 30 วัน)
    - ไม่มีวันที่ แต่เป็นทุนที่เปิดต่อเนื่อง ("ตลอดทั้งปี", "ของทุกปี") → เปิดรับสมัคร
    - ไม่มีวันที่และไม่ใช่ทุนต่อเนื่อง → ไม่ระบุ
    """
    deadline_text = _text(item.get("deadline"))
    deadline = item.get("deadline_date")
    if not deadline:
        if any(marker in deadline_text for marker in RECURRING_MARKERS):
            return STATUS_OPEN
        return STATUS_UNKNOWN
    today = _now().date()
    if deadline < today:
        return STATUS_CLOSED
    if (deadline - today).days <= CLOSING_SOON_DAYS:
        return STATUS_CLOSING
    return STATUS_OPEN


# cache: source -> (timestamp, items)
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


# ---------------------------------------------------------------------------
# เครื่องมือช่วยแปลงข้อมูล
# ---------------------------------------------------------------------------
def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def strip_html(value: Any) -> str:
    """ตัดแท็ก HTML ออกจากเนื้อหา WordPress แล้ว decode entity"""
    raw = str(value or "")
    raw = re.sub(r"<[^>]+>", " ", raw)
    return _text(html.unescape(raw))


def _list_of_str(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def normalize_eef(item: dict[str, Any]) -> dict[str, Any]:
    """แปลงรายการทุนจากกสศ. ให้อยู่ในรูปแบบเดียวกัน"""
    genres = _list_of_str(item.get("genres"))
    requirements = _list_of_str(item.get("requirement"))
    budget = _text(item.get("budget"))
    channel = _text(item.get("channel"))
    sponsor = _text(item.get("sponsor"))
    grade = _text(item.get("grade"))
    # ช่องทางสมัครบางรายการเป็น URL แทนที่จะเป็นข้อความ — เก็บไว้เป็นลิงก์แทน
    channel_text = "" if channel.startswith("http") else channel
    summary = " · ".join(part for part in (budget, channel_text) if part)
    # มูลค่าทุนที่ไม่ใช่ตัวเลขจริง ("-", "ไม่ระบุ") — ไม่แสดงเป็นตัวเลข
    amount = "" if budget in NON_AMOUNT_VALUES else budget
    deadline_text = _text(item.get("start_at"))
    if deadline_text == "-":
        deadline_text = ""
    normalized = {
        "id": f"{SOURCE_EEF}:{_text(item.get('id'))}",
        "source": SOURCE_EEF,
        "source_label": SOURCE_LABELS[SOURCE_EEF],
        "title": _text(item.get("title")) or "(ไม่มีหัวข้อ)",
        "summary": summary,
        "sponsor": sponsor,
        "amount": amount,
        "deadline": deadline_text,
        "channel": channel_text,
        "levels": [grade] if grade else [],
        "tags": genres,
        "requirements": requirements,
        "image_url": _text(item.get("images")),
        # หน้ารายละเอียดบนเว็บกสศ. ใช้เป็นลิงก์หลัก — ส่วน apply_url คือประกาศ/ใบสมัครต้นทาง
        "url": f"{EEF_SITE}/scholarship/{_text(item.get('id'))}",
        "apply_url": _text(item.get("source_url")),
        "site_url": EEF_SITE,
        "published_at": _text(item.get("created_at")),
    }
    normalized["deadline_date"] = extract_deadline_date(item)
    normalized["status"] = compute_status(normalized)
    return normalized


def normalize_wp(post: dict[str, Any], embedded: dict[str, Any]) -> dict[str, Any]:
    """แปลงโพสต์จาก scholarship.in.th ให้อยู่ในรูปแบบเดียวกัน"""
    title = strip_html((post.get("title") or {}).get("rendered"))
    summary = strip_html((post.get("excerpt") or {}).get("rendered"))
    link = _text(post.get("link"))

    terms = embedded.get("wp:term") or []
    category_names: list[str] = []
    for group in terms if isinstance(terms, list) else []:
        for term in group if isinstance(group, list) else []:
            name = _text(term.get("name"))
            if name and name not in category_names:
                category_names.append(name)

    levels: list[str] = []
    for name in category_names:
        for hint, level in WP_LEVEL_HINTS:
            if hint in name and level not in levels:
                levels.append(level)
                break

    image = ""
    media = embedded.get("wp:featuredmedia") or []
    if media:
        sizes = (media[0].get("media_details") or {}).get("sizes") or {}
        image = _text(sizes.get("medium", {}).get("source_url")) or _text(media[0].get("source_url"))

    tags = [name for name in category_names if name != "บทความ"]
    normalized = {
        "id": f"{SOURCE_SIT}:{_text(post.get('id'))}",
        "source": SOURCE_SIT,
        "source_label": SOURCE_LABELS[SOURCE_SIT],
        "title": title or "(ไม่มีหัวข้อ)",
        "summary": summary,
        "sponsor": "",
        "amount": "",
        "deadline": "",
        "channel": "",
        "levels": levels,
        "tags": tags,
        "requirements": [],
        "image_url": image,
        "url": link or WP_SITE,
        "apply_url": link or WP_SITE,
        "site_url": WP_SITE,
        "published_at": _text(post.get("date")),
        # หมวด "บทความ" ของ scholarship.in.th คือบทความ/เคล็ดลับ ไม่ใช่ทุนที่สมัครได้
        "is_article": "บทความ" in category_names or not levels,
        "deadline_date": None,
    }
    normalized["status"] = STATUS_UNKNOWN
    return normalized


# ---------------------------------------------------------------------------
# ดึงข้อมูลจากแต่ละแหล่ง
# ---------------------------------------------------------------------------
async def _fetch_eef(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await client.get(
        EEF_API,
        params={"limit": 1000, "order": "created_at,desc"},
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("items") if isinstance(payload, dict) else payload
    return [normalize_eef(item) for item in items or [] if isinstance(item, dict)]


async def _fetch_sit(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for page in range(1, 6):  # ดึงได้สูงสุด 5 หน้า (500 โพสต์)
        response = await client.get(
            WP_API,
            params={"per_page": 100, "page": page, "_embed": 1},
            headers={"Accept": "application/json"},
        )
        if response.status_code == 400:  # หน้าเกินขอบเขตที่ WP ตั้งไว้
            break
        response.raise_for_status()
        posts = response.json()
        if not isinstance(posts, list) or not posts:
            break
        for post in posts:
            if not isinstance(post, dict):
                continue
            embedded = post.get("_embedded") or {}
            normalized = normalize_wp(post, embedded)
            # ข้ามบทความ/เคล็ดลับ — เหลือเฉพาะประกาศทุนที่สมัครได้จริง
            if normalized["is_article"]:
                continue
            results.append(normalized)
        if len(posts) < 100:
            break
    return results


async def load_items(force: bool = False) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """ดึงข้อมูลทุนจากทั้งสองแหล่ง (ใช้ cache 10 นาที) — คืน (รายการที่รวมกัน, ข้อความ error รายแหล่ง)"""
    now = time.monotonic()
    cached = {source: value for source, value in _cache.items() if not force and now - value[0] < CACHE_TTL}
    if len(cached) == 2:
        return _merge(cached[SOURCE_EEF][1], cached[SOURCE_SIT][1]), {}

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0), headers={"User-Agent": UA}, follow_redirects=True) as client:
        results = await asyncio.gather(
            _fetch_eef(client),
            _fetch_sit(client),
            return_exceptions=True,
        )

    errors: dict[str, str] = {}
    fresh: dict[str, list[dict[str, Any]]] = {}
    for source, result in zip((SOURCE_EEF, SOURCE_SIT), results):
        if isinstance(result, BaseException):
            errors[source] = f"{SOURCE_LABELS[source]}: {result}"
            previous = _cache.get(source)
            if previous and not force:
                fresh[source] = previous[1]  # ใช้ข้อมูลเก่าแทนชั่วคราว
            continue
        fresh[source] = result
        _cache[source] = (now, result)

    for source, value in cached.items():
        fresh.setdefault(source, value[1])

    return _merge(fresh.get(SOURCE_EEF, []), fresh.get(SOURCE_SIT, [])), errors


def _merge(eef_items: list[dict[str, Any]], sit_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list(eef_items) + list(sit_items)


# ---------------------------------------------------------------------------
# การค้นหาและกรอง
# ---------------------------------------------------------------------------
def haystack(item: dict[str, Any]) -> str:
    parts = [
        item.get("title", ""),
        item.get("summary", ""),
        item.get("sponsor", ""),
        item.get("amount", ""),
        item.get("deadline", ""),
        item.get("channel", ""),
        " ".join(item.get("levels") or []),
        " ".join(item.get("tags") or []),
        " ".join(item.get("requirements") or []),
    ]
    return " ".join(_text(part) for part in parts).lower()


# ความยาวขั้นต่ำของ "หางคำ" ที่ยอมให้จับคู่แบบ prefix — กันการ match กับคำสั้นจนไร้ความหมาย
MIN_PREFIX_LEN = 4

EXACT = 2
PREFIX = 1


def token_score(token: str, text: str) -> int:
    """ให้คะแนนการจับคู่คำเดียว: 2 = ตรงทั้งคำ, 1 = เป็นส่วนต้นของคำในข้อมูล, 0 = ไม่พบ

    ภาษาไทยไม่มีการเว้นวรรคระหว่างคำ ผู้ใช้จึงมักพิมพ์คำที่ยาวกว่าที่เว็บต้นทางบันทึกไว้
    (เช่นค้นว่า "วิศวกรรมศาสตร์" แต่ข้อมูลมีแค่ "วิศวกรรม") การจับคู่แบบ prefix ช่วยให้ค้นเจอ
    โดยให้คะแนนต่ำกว่าการตรงทั้งคำ เพื่อให้ผลที่ตรงที่สุดอยู่บน
    """
    if token in text:
        return EXACT
    for size in range(len(token) - 1, MIN_PREFIX_LEN - 1, -1):
        if token[:size] in text:
            return PREFIX
    return 0


def score_query(item: dict[str, Any], query: str) -> int:
    """คะแนนรวมของทุนหนึ่งรายการต่อคำค้น — ทุกคำต้องเจอ แล้วเรียงตามคะแนน (สูง = ตรงที่สุด)

    คำที่เจอในชื่อทุนได้คะแนนเพิ่ม เพื่อให้ผลที่ตรงคำค้นที่สุดขึ้นมาก่อน
    """
    needle = _text(query).lower()
    if not needle:
        return EXACT
    text = haystack(item)
    title = _text(item.get("title")).lower()
    total = 0
    for token in needle.split():
        score = token_score(token, text)
        if score == 0:
            return 0
        total += score
        if token_score(token, title) > 0:
            total += 1
    return total


def matches_query(item: dict[str, Any], query: str) -> bool:
    """ทุกคำในคำค้นต้องอยู่ในข้อมูลทุน (ค้นภาษาไทยได้ เพราะเป็น substring)"""
    return score_query(item, query) > 0


def level_of(item: dict[str, Any]) -> str:
    """จับกลุ่มระดับชั้นของทุน (คืนกลุ่มแรกที่ตรง)"""
    levels = item.get("levels") or []
    for group, members in LEVEL_GROUPS.items():
        if any(level in members for level in levels):
            return group
    return ""


def matches_level(item: dict[str, Any], level: str) -> bool:
    if not level or level == "ทั้งหมด":
        return True
    return level_of(item) == level


def matches_source(item: dict[str, Any], source: str) -> bool:
    if not source or source == "ทั้งหมด":
        return True
    return item.get("source") == source


def matches_status(item: dict[str, Any], status: str) -> bool:
    if not status or status == "ทั้งหมด":
        return True
    return item.get("status") == status


def build_facets(items: list[dict[str, Any]]) -> dict[str, Any]:
    """นับจำนวนตามระดับชั้น / แหล่งข้อมูล / ประเภททุน / สถานะ เพื่อทำตัวกรองแบบไดนามิก"""
    levels: dict[str, int] = {}
    sources: dict[str, int] = {}
    genres: dict[str, int] = {}
    statuses: dict[str, int] = {}
    for item in items:
        group = level_of(item)
        if group:
            levels[group] = levels.get(group, 0) + 1
        source = item.get("source", "")
        if source:
            sources[source] = sources.get(source, 0) + 1
        for tag in item.get("tags") or []:
            genres[tag] = genres.get(tag, 0) + 1
        status = item.get("status", STATUS_UNKNOWN)
        statuses[status] = statuses.get(status, 0) + 1
    return {
        "levels": [{"key": key, "label": key, "count": value} for key, value in sorted(levels.items())],
        "sources": [
            {"key": key, "label": SOURCE_LABELS.get(key, key), "count": sources.get(key, 0)}
            for key in (SOURCE_EEF, SOURCE_SIT)
        ],
        "genres": [{"key": key, "label": key, "count": value} for key, value in sorted(genres.items(), key=lambda pair: -pair[1])],
        "statuses": [
            {"key": key, "label": key, "count": statuses.get(key, 0)}
            for key in ALL_STATUS
        ],
    }


def search_items(
    items: list[dict[str, Any]],
    query: str = "",
    level: str = "",
    source: str = "",
    genre: str = "",
    status: str = "",
    limit: int = DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """กรอง + จัดอันดับผลค้นหา — คะแนนสูง (ตรงคำค้นมากกว่า) อยู่บนสุด"""
    matched, _ = search_items_with_total(items, query=query, level=level, source=source, genre=genre, status=status, limit=limit)
    return matched


# ลำดับสถานะที่น่าสนใจก่อน (เปิดรับ → ใกล้ปิด → ไม่ระบุ → ปิดแล้ว)
STATUS_RANK = {STATUS_OPEN: 0, STATUS_CLOSING: 1, STATUS_UNKNOWN: 2, STATUS_CLOSED: 3}


def search_items_with_total(
    items: list[dict[str, Any]],
    query: str = "",
    level: str = "",
    source: str = "",
    genre: str = "",
    status: str = "",
    limit: int = DEFAULT_LIMIT,
) -> tuple[list[dict[str, Any]], int]:
    """คืน (รายการที่จัดอันดับแล้ว, จำนวนรายการที่ตรงทั้งหมด)

    เรียงลำดับ: ตรงคำค้นก่อน → ทุนที่ยังเปิดอยู่ก่อนทุนที่ปิดแล้ว → ประกาศใหม่กว่าอยู่บน
    """
    scored: list[tuple[int, int, str, dict[str, Any]]] = []
    for item in items:
        if not matches_level(item, level) or not matches_source(item, source):
            continue
        if not matches_status(item, status):
            continue
        if genre and genre not in (item.get("tags") or []):
            continue
        score = score_query(item, query)
        if score <= 0:
            continue
        rank = STATUS_RANK.get(item.get("status", STATUS_UNKNOWN), 2)
        scored.append((score, rank, item.get("published_at") or "", item))
    scored.sort(key=lambda row: (row[2],), reverse=True)
    scored.sort(key=lambda row: row[1])
    scored.sort(key=lambda row: row[0], reverse=True)
    total = len(scored)
    return [item for _, _, _, item in scored[: max(1, min(limit, MAX_LIMIT))]], total


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
def build_router(repo: Any = None) -> APIRouter:
    router = APIRouter(prefix="/api/scholarships")

    @router.get("")
    async def list_scholarships(q: str = "", level: str = "", source: str = "", genre: str = "", status: str = "", limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
        """ค้นหาทุนการศึกษาจากกสศ. และ scholarship.in.th"""
        if level and level not in ALL_LEVELS:
            raise HTTPException(status_code=400, detail="ระดับชั้นไม่ถูกต้อง")
        if source and source not in {SOURCE_EEF, SOURCE_SIT}:
            raise HTTPException(status_code=400, detail="แหล่งข้อมูลไม่ถูกต้อง")
        if status and status not in ALL_STATUS:
            raise HTTPException(status_code=400, detail="สถานะทุนไม่ถูกต้อง")
        try:
            items, errors = await load_items()
        except Exception as exc:  # noqa: BLE001 — ป้องกันหน้าเว็บพังเมื่อเว็บต้นทางมีปัญหา
            raise HTTPException(status_code=502, detail=f"ดึงข้อมูลทุนไม่สำเร็จ: {exc}") from None

        matched, total = search_items_with_total(items, query=q, level=level, source=source, genre=genre, status=status, limit=limit)
        return {
            "items": matched,
            "total": total,
            "returned": len(matched),
            "query": _text(q),
            "level": level,
            "source": source,
            "genre": genre,
            "status": status,
            "facets": build_facets(items),
            "errors": errors,
            "sources": [
                {"key": SOURCE_EEF, "label": SOURCE_LABELS[SOURCE_EEF], "url": EEF_SITE},
                {"key": SOURCE_SIT, "label": SOURCE_LABELS[SOURCE_SIT], "url": WP_SITE},
            ],
        }

    return router
