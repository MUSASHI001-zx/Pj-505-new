"""ตรรกะรายการ "คลังข้อสอบ" จาก myTCAS (ไม่พึ่ง FastAPI/httpx เพื่อทดสอบได้ตรง ๆ)

myTCAS มีข้อสอบ 2 ประเภท:
1) ข้อสอบพร้อมเฉลย A-Level (ไฟล์ PDF ดาวน์โหลดได้) — หน้า /answers-t69 (ปีถัดไปจะเป็น /answers-tNN)
   ไฟล์อยู่ที่ https://assets.mytcas.com/{ปี}/answer/tcas{ปี}-{รหัสวิชา}-a-level.pdf
2) โครงสร้างและตัวอย่างข้อสอบ TGAT / TPAT / A-Level — หน้า /blueprint/{slug}/ (อ่านออนไลน์ ไม่มีไฟล์ให้โหลด)

รายการจริงดึงสดจากหน้าเว็บของ myTCAS (ดู app/exams.py) ส่วน FALLBACK_* ใช้เมื่อดึงสดไม่ได้เท่านั้น
"""
from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

MYTCAS_SITE = "https://www.mytcas.com"
ASSETS_HOST = "assets.mytcas.com"

# URL ที่อนุญาตให้ดาวน์โหลดผ่านเซิร์ฟเวอร์เรา — เฉพาะไฟล์เฉลยบน assets.mytcas.com (กัน SSRF)
DOWNLOAD_RE = re.compile(r"^https://assets\.mytcas\.com/\d{2}/answer/[A-Za-z0-9._-]+\.pdf$")

GROUP_ORDER = ["คณิตศาสตร์", "วิทยาศาสตร์", "ภาษาและสังคม", "ภาษาต่างประเทศ", "ความถนัดทั่วไป", "ความถนัดเฉพาะ"]

# รหัสวิชาในชื่อไฟล์ -> (ชื่อไทย, กลุ่ม)
SUBJECTS: dict[str, tuple[str, str]] = {
    "math1": ("คณิตศาสตร์ประยุกต์ 1", "คณิตศาสตร์"),
    "math2": ("คณิตศาสตร์ประยุกต์ 2", "คณิตศาสตร์"),
    "sci": ("วิทยาศาสตร์ประยุกต์", "วิทยาศาสตร์"),
    "phy": ("ฟิสิกส์", "วิทยาศาสตร์"),
    "chem": ("เคมี", "วิทยาศาสตร์"),
    "bio": ("ชีววิทยา", "วิทยาศาสตร์"),
    "soc": ("สังคมศึกษา", "ภาษาและสังคม"),
    "thai": ("ภาษาไทย", "ภาษาและสังคม"),
    "eng": ("ภาษาอังกฤษ", "ภาษาและสังคม"),
    "fra": ("ภาษาฝรั่งเศส", "ภาษาต่างประเทศ"),
    "deu": ("ภาษาเยอรมัน", "ภาษาต่างประเทศ"),
    "jpn": ("ภาษาญี่ปุ่น", "ภาษาต่างประเทศ"),
    "kor": ("ภาษาเกาหลี", "ภาษาต่างประเทศ"),
    "chn": ("ภาษาจีน", "ภาษาต่างประเทศ"),
    "bal": ("ภาษาบาลี", "ภาษาต่างประเทศ"),
    "esp": ("ภาษาสเปน", "ภาษาต่างประเทศ"),
}
LEVELS = {"a-level": "A-Level", "tgat": "TGAT", "tpat": "TPAT"}

# หน้า blueprint: (slug, ชื่อ, กลุ่ม) — ใช้เป็นข้อมูลสำรอง
FALLBACK_BLUEPRINTS: list[tuple[str, str, str]] = [
    ("tgat1-91", "TGAT1 91 การสื่อสารภาษาอังกฤษ", "ความถนัดทั่วไป"),
    ("tgat2-92", "TGAT2 92 การคิดอย่างมีเหตุผล", "ความถนัดทั่วไป"),
    ("tgat3-93", "TGAT3 93 สมรรถนะการทำงาน", "ความถนัดทั่วไป"),
    ("tpat2-20", "TPAT2 20 ความถนัดศิลปกรรมศาสตร์", "ความถนัดเฉพาะ"),
    ("tpat3-30", "TPAT3 30 ความถนัดด้านวิทยาศาสตร์ เทคโนโลยี และวิศวกรรมศาสตร์", "ความถนัดเฉพาะ"),
    ("tpat4-40", "TPAT4 40 ความถนัดทางสถาปัตยกรรม", "ความถนัดเฉพาะ"),
    ("tpat5-50", "TPAT5 50 ความถนัดครุศาสตร์-ศึกษาศาสตร์", "ความถนัดเฉพาะ"),
    ("a-level-61-math1", "A-Level 61 Math1 วิชาคณิตศาสตร์ประยุกต์ 1", "คณิตศาสตร์"),
    ("a-level-62-math2", "A-Level 62 Math2 วิชาคณิตศาสตร์ประยุกต์ 2", "คณิตศาสตร์"),
    ("a-level-63-sci", "A-Level 63 Sci วิทยาศาสตร์ประยุกต์", "วิทยาศาสตร์"),
    ("a-level-64-phy", "A-Level 64 Phy วิชาฟิสิกส์", "วิทยาศาสตร์"),
    ("a-level-65-chem", "A-Level 65 Chem วิชาเคมี", "วิทยาศาสตร์"),
    ("a-level-66-bio", "A-Level 66 Bio วิชาชีววิทยา", "วิทยาศาสตร์"),
    ("a-level-70-soc", "A-Level 70 Soc สังคมศึกษา", "ภาษาและสังคม"),
    ("a-level-81-thai", "A-Level 81 Thai ภาษาไทย", "ภาษาและสังคม"),
    ("a-level-82-eng", "A-Level 82 Eng ภาษาอังกฤษ", "ภาษาและสังคม"),
    ("a-level-83-fra", "A-Level 83 Fra ภาษาฝรั่งเศส", "ภาษาต่างประเทศ"),
    ("a-level-84-deu", "A-Level 84 Deu ภาษาเยอรมัน", "ภาษาต่างประเทศ"),
    ("a-level-85-jpn", "A-Level 85 Jpn ภาษาญี่ปุ่น", "ภาษาต่างประเทศ"),
    ("a-level-86-kor", "A-Level 86 Kor ภาษาเกาหลี", "ภาษาต่างประเทศ"),
    ("a-level-87-chn", "A-Level 87 Chn ภาษาจีน", "ภาษาต่างประเทศ"),
    ("a-level-88-bal", "A-Level 88 Bal ภาษาบาลี", "ภาษาต่างประเทศ"),
    ("a-level-89-esp", "A-Level 89 Esp ภาษาสเปน", "ภาษาต่างประเทศ"),
]

_ANCHOR_RE = re.compile(r"""<a\b[^>]*?\bhref\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_ANSWER_FILE_RE = re.compile(r"/(\d{2})/answer/(tcas(\d{2})-([a-z0-9]+)-([a-z0-9-]+))\.pdf$", re.I)
_ANSWER_PAGE_RE = re.compile(r"/answers-t(\d{2})/?$", re.I)
_BLUEPRINT_RE = re.compile(r"/blueprint/([a-z0-9][a-z0-9-]*)/?$", re.I)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", fragment))).strip()


def _anchors(page_html: str, base_url: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for href, inner in _ANCHOR_RE.findall(page_html or ""):
        found.append((urljoin(base_url, html.unescape(href.strip())), _text(inner)))
    return found


def _group_of_slug(slug: str, name: str) -> str:
    if slug.startswith("tgat"):
        return "ความถนัดทั่วไป"
    if slug.startswith("tpat"):
        return "ความถนัดเฉพาะ"
    code = slug.rsplit("-", 1)[-1]
    if code in SUBJECTS:
        return SUBJECTS[code][1]
    return "อื่น ๆ"


def answer_item(year: str, stem: str, code: str, level_key: str, url: str, anchor_text: str = "") -> dict[str, Any]:
    subject, group = SUBJECTS.get(code.lower(), (anchor_text or code.upper(), "อื่น ๆ"))
    level = LEVELS.get(level_key.lower(), level_key.upper())
    return {
        "id": stem.lower(),
        "kind": "answer",
        "title": f"ข้อสอบ {level} {subject} พร้อมเฉลย",
        "subject": subject,
        "group": group,
        "level": level,
        "year": f"TCAS{year}",
        "url": url,
        "download": bool(DOWNLOAD_RE.match(url)),
        "format": "PDF",
    }


def parse_answer_page(page_html: str, page_url: str) -> list[dict[str, Any]]:
    """ดึงลิงก์ไฟล์ PDF เฉลยจากหน้า /answers-tNN (ไม่ซ้ำ รักษาลำดับตามหน้า)"""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url, text in _anchors(page_html, page_url):
        clean = url.split("?")[0]
        # รับเฉพาะไฟล์ที่โฮสต์บน myTCAS เอง — ลิงก์โดเมนอื่นที่ชื่อไฟล์เหมือนกันต้องไม่ถูกนำมาแสดง
        if urlsplit(clean).hostname != ASSETS_HOST:
            continue
        match = _ANSWER_FILE_RE.search(clean)
        if not match:
            continue
        _, stem, year, code, level_key = match.groups()
        if stem.lower() in seen:
            continue
        seen.add(stem.lower())
        items.append(answer_item(year, stem, code, level_key, url.split("?")[0], text))
    return items


def discover_answer_pages(home_html: str) -> list[str]:
    """หน้า answers-tNN ทั้งหมดที่หน้าแรก myTCAS ลิงก์ไว้ (ปีใหม่ ๆ จะโผล่เอง) — เสมอมี t69"""
    pages = {f"{MYTCAS_SITE}/answers-t69"}
    for url, _ in _anchors(home_html, MYTCAS_SITE + "/"):
        if url.startswith(MYTCAS_SITE) and _ANSWER_PAGE_RE.search(url.split("?")[0].split("#")[0]):
            pages.add(url.split("?")[0].split("#")[0].rstrip("/"))
    return sorted(pages, reverse=True)


def blueprint_item(slug: str, title: str, group: str) -> dict[str, Any]:
    level_key = "tgat" if slug.startswith("tgat") else "tpat" if slug.startswith("tpat") else "a-level"
    return {
        "id": f"blueprint-{slug}",
        "kind": "blueprint",
        "title": title,
        "subject": title,
        "group": group,
        "level": LEVELS[level_key],
        "year": "",
        "url": f"{MYTCAS_SITE}/blueprint/{slug}/",
        "download": False,
        "format": "เว็บ",
    }


def parse_blueprint_index(page_html: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url, text in _anchors(page_html, MYTCAS_SITE + "/blueprint/"):
        path = url.split("?")[0].split("#")[0]
        if not path.startswith(MYTCAS_SITE):
            continue
        match = _BLUEPRINT_RE.search(path)
        if not match:
            continue
        slug = match.group(1).lower()
        if slug in seen or slug == "blueprint":
            continue
        seen.add(slug)
        items.append(blueprint_item(slug, text or slug, _group_of_slug(slug, text)))
    return items


def fallback_answers(year: str = "69") -> list[dict[str, Any]]:
    return [
        answer_item(year, f"tcas{year}-{code}-a-level", code, "a-level", f"https://{ASSETS_HOST}/{year}/answer/tcas{year}-{code}-a-level.pdf")
        for code in SUBJECTS
    ]


def fallback_blueprints() -> list[dict[str, Any]]:
    return [blueprint_item(slug, title, group) for slug, title, group in FALLBACK_BLUEPRINTS]


def search_items(items: list[dict[str, Any]], q: str = "", kind: str = "", group: str = "") -> list[dict[str, Any]]:
    needle = q.strip().casefold()
    out = []
    for item in items:
        if kind and item["kind"] != kind:
            continue
        if group and item["group"] != group:
            continue
        if needle and needle not in " ".join((item["title"], item["subject"], item["level"], item["year"], item["id"])).casefold():
            continue
        out.append(item)
    return out


def group_counts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item["group"]] = counts.get(item["group"], 0) + 1
    ordered = [g for g in GROUP_ORDER if g in counts] + sorted(g for g in counts if g not in GROUP_ORDER)
    return [{"group": g, "count": counts[g]} for g in ordered]
