"""ค้นหาโควตา / รอบรับสมัคร จาก myTCAS (ข้อมูลสด)

อ่านข้อมูลตรงจาก myTCAS แล้วรวมรอบรับสมัครเป็นรายการเดียว
ไม่ต้องรอซิงก์ลงฐานข้อมูล — เหมาะกับหน้า "ค้นหาโควตา / TCAS"

ข้อมูลต้นทาง:
- universities.json        — มหาวิทยาลัย/สถาบัน 92 แห่ง
- courses.json             — คณะ/หลักสูตร 4,619 รายการ
- rounds/{programId}.json  — รอบรับสมัคร (19,548 รายการ) พร้อมเกณฑ์คะแนน
"""
from __future__ import annotations

import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from .tcas_sync import (
    MYTCAS_SITE,
    admission_records,
    fetch_courses,
    fetch_rounds,
)

MAX_LIMIT = 120
DEFAULT_LIMIT = 24

# จำนวน program ที่ดึง rounds ต่อคำขอ — จำกัดไว้เพื่อไม่ให้รอนานเกิน
ROUNDS_FETCH_CAP = 400

# cache รายการหลักสูตรดิบ (ใช้ให้ AI ค้นหาเอง)
_courses_cache: dict[str, Any] = {}


async def _load_courses(query: str = "") -> list[dict[str, Any]]:
    """โหลดรายการหลักสูตรจาก myTCAS แล้วกรองตามคำค้น (ใช้เป็นข้อมูลให้ AI ค้นหา)

    คืนข้อมูลดิบจาก courses.json — ผู้เรียกต้องจัดรูปแบบเอง
    """
    cached = _courses_cache.get("rows")
    if cached is None:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=10.0),
            headers={"User-Agent": "TCASBuddy/1.0", "Accept": "application/json"},
            follow_redirects=True,
        ) as client:
            response = await client.get("https://my-tcas.s3.ap-southeast-1.amazonaws.com/mytcas/courses.json")
            response.raise_for_status()
            cached = response.json() or []
        _courses_cache["rows"] = cached

    needle = (query or "").strip().lower()
    if not needle:
        return list(cached)
    words = [word for word in needle.split() if len(word) >= 2]
    if not words:
        return list(cached)

    def haystack_of(row: dict[str, Any]) -> str:
        return " ".join(str(row.get(key) or "") for key in (
            "university_name_th", "faculty_name_th", "program_name_th",
            "field_name_th", "group_field_th", "campus_name_th",
        )).lower()

    # 1) ทุกคำต้องตรง (แม่นที่สุด)
    exact = [row for row in cached if all(word in haystack_of(row) for word in words)]
    if exact:
        return exact
    # 2) ไม่พบ — ลองแบบ "มีบางคำตรง" แต่ให้คะแนนคำที่ตรงมากที่สุดขึ้นก่อน
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in cached:
        haystack = haystack_of(row)
        hits = sum(1 for word in words if word in haystack)
        if hits:
            scored.append((hits, row))
    if not scored:
        return []
    best = max(hits for hits, _ in scored)
    # เก็บเฉพาะแถวที่ตรงได้มากที่สุดเท่ากัน (ไม่รวมคำที่ไม่ตรงเลย)
    return [row for hits, row in scored if hits == best]


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _haystack(item: dict[str, Any]) -> str:
    return " ".join([
        item.get("institution", ""),
        item.get("faculty", ""),
        item.get("program", ""),
        item.get("project", ""),
        item.get("round", ""),
        item.get("criteria", ""),
    ]).lower()


def _match(item: dict[str, Any], needle: str) -> bool:
    if not needle:
        return True
    text = _haystack(item)
    tokens = [token for token in needle.split() if len(token) >= 2]
    if not tokens:
        return True
    if all(token in text for token in tokens):
        return True
    # ไม่ตรงทุกคำ — ยอมรับถ้าตรงบางคำ (ให้ผลกว้างขึ้น)
    return any(token in text for token in tokens)


# คำที่บ่งบอกถึง "ประเภทโครงการ" — ใช้หาโครงการที่ตรงประเภทนี้
PROJECT_TYPE_KEYWORDS = {
    "portfolio": ("portfolio", "แฟ้มสะสมผลงาน", "พอร์ตโฟลิโอ"),
    "quota": ("โควตา", "quota"),
    "scholarship": ("ทุน", "ทุนการศึกษา", "scholarship"),
    "tgat": ("tgat",),
    "tpat": ("tpat",),
    "admission": ("admission", "รอบ 3", "รอบรับ"),
}


def _related_programs(courses: list[dict[str, Any]], needle: str) -> list[dict[str, Any]]:
    """หาโครงการที่ตรงกับ "ประเภท" ของคำค้น เช่น "portfolio" → โครงการแบบ Portfolio

    คืนรายการหลักสูตรที่มีโอกาสเป็นเจ้าของโครงการประเภทนั้น (จำกัดจำนวนไว้ไม่ให้ดึง rounds นานเกิน)
    """
    lowered = needle.lower()
    kind = next((key for key, words in PROJECT_TYPE_KEYWORDS.items() if any(word in lowered for word in words)), "")
    if not kind:
        return []
    keywords = PROJECT_TYPE_KEYWORDS[kind]
    # คัดหลักสูตรที่คณะ/สาขาเกี่ยวข้องกับคำใบ้ (เช่น "วิศวกรรม" สำหรับโครงการ portfolio ของคณะวิศวกรรม)
    hint_words = [word for word in needle.split() if len(word) >= 3 and word not in keywords]
    related: list[dict[str, Any]] = []
    for course in courses:
        haystack = f"{course.get('university_name_th', '')} {course.get('faculty_name_th', '')} {course.get('field_name_th', '')}".lower()
        if not hint_words or any(word in haystack for word in hint_words):
            related.append(course)
        if len(related) >= ROUNDS_FETCH_CAP:
            break
    return related


def _sort_key(item: dict[str, Any]) -> tuple:
    """เรียง: มีวันปิดที่ยังไม่ผ่านขึ้นก่อน → ปิดเร็วที่สุดก่อน → ไม่มีวันปิดท้ายสุด"""
    deadline = item.get("closed_date")
    if not deadline:
        return (2, "9999-12-31", item.get("institution", ""))
    return (0 if deadline >= _today() else 1, deadline, item.get("institution", ""))


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


async def load_live(q: str = "", limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """ดึงรอบรับสมัครสดนจาก myTCAS ตามคำค้น"""
    needle = q.strip().lower()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        headers={"User-Agent": "TCASBuddy/1.0", "Accept": "application/json"},
    ) as client:
        courses = await fetch_courses(client)
        matches = [
            course for course in courses
            if not needle or needle in (
                f"{course.get('university_name_th', '')} {course.get('faculty_name_th', '')} "
                f"{course.get('program_name_th', '')} {course.get('field_name_th', '')}"
            ).lower()
        ]
        if not matches:
            # คำค้นไม่ตรงกับชื่อหลักสูตร (เช่น "portfolio", "โควตา") — ให้ไล่ดึงรอบรับของ
            # ทุกหลักสูตรแล้วค้นในชื่อโครงการ/เงื่อนไขแทน (ดึงเฉพาะคำที่ตรงก่อนเพื่อไม่หนักเกินไป)
            hint = _related_programs(courses, needle)
            matches = hint or courses[:ROUNDS_FETCH_CAP]
            if not matches:
                return {"items": [], "total": 0, "source": MYTCAS_SITE, "programs": 0}
        program_ids = sorted({str(c.get("program_id")) for c in matches if c.get("program_id")})[:ROUNDS_FETCH_CAP]
        rounds_map = await fetch_rounds(client, program_ids)

    items: list[dict[str, Any]] = []
    for course in matches:
        pid = str(course.get("program_id") or "")
        rounds = rounds_map.get(pid, [])
        if not rounds:
            continue
        university_id = str(course.get("university_id") or "")
        logo_url = f"https://assets.mytcas.com/i/logo/{university_id}.png" if university_id else None
        for record in admission_records(course, rounds):
            items.append({
                "id": record["tc_uid"],
                "institution": record["institution"],
                "university_id": university_id,
                "logo_url": logo_url,
                "faculty": record["faculty"],
                "program": record["program"],
                "round": record["round"],
                "project": record["project_name"],
                "round_type": record["round_type"],
                "academic_year": record["academic_year"],
                "quota": record["quota"],
                "min_gpax": record["min_gpax"],
                "min_total_score": record["min_total_score"],
                "criteria": record["criteria"],
                "score_items": record.get("score_items") or [],
                "notes": record.get("notes") or [],
                "closed_date": record["closed_date"],
                "deadline": record["deadline"],
                "condition": record["condition"],
                "interview_location": record["interview_location"],
                "interview_date": record["interview_date"],
                "interview_time": record["interview_time"],
                "scores": record["scores"],
                "score_conditions": record["score_conditions"],
                "source_url": record["source_url"],
                "source_label": "myTCAS",
                "source": "mytcas",
            })

    items = [item for item in items if _match(item, needle)]
    items.sort(key=_sort_key)
    total = len(items)
    return {
        "items": items[: max(1, min(limit, MAX_LIMIT))],
        "total": total,
        "programs": len(matches),
        "source": MYTCAS_SITE,
    }


def build_router(repo: Any = None) -> APIRouter:
    router = APIRouter(prefix="/api/tcas")

    @router.get("/quota")
    async def quota_search(q: str = "", limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
        """ค้นหารอบรับสมัคร/โควตาจาก myTCAS สด"""
        try:
            return await load_live(q=q, limit=limit)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"ดึงข้อมูล myTCAS ไม่สำเร็จ: {exc}") from None
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"ข้อมูล myTCAS ผิดรูปแบบ: {exc}") from None

    return router
