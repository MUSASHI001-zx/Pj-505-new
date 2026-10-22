"""ซิงก์ข้อมูล myTCAS → ฐานข้อมูล (หน้า "ค้นหาโควตา / TCAS")

myTCAS เปิดข้อมูลเป็น JSON สาธารณะบน S3 (ไม่ต้องใช้ Make.com):
- universities.json          — รายชื่อมหาวิทยาลัย/สถาบัน (92 แห่ง)
- courses.json               — คณะ/หลักสูตร/สาขา พร้อมค่าเล่าเรียน อัตราการจ้างงาน เงินเดือน
- rounds/{programId}.json    — รอบรับสมัคร พร้อมเกณฑ์คะแนน โครงการ และวันสัมภาษณ์

ข้อมูลถูก cache ไว้ในตัวเซิร์ฟเวอร์ เพื่อไม่ให้ยิงเว็บต้นทางบ่อยเกินไป
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx

MYTCAS_API = "https://my-tcas.s3.ap-southeast-1.amazonaws.com/mytcas"
MYTCAS_SITE = "https://www.mytcas.com"
UA = "TCASBuddy/1.0 (+https://www.mytcas.com)"

CACHE_TTL = 3600.0  # 1 ชั่วโมง — ข้อมูลรอบรับเปลี่ยนบ่อยตอนเปิดรับ
ROUNDS_CONCURRENCY = 24
ROUNDS_BATCH_LIMIT = 600  # ดึงสูงสุดกี่ program ต่อครั้ง (ป้องกันค้างนานเกิน)

# ประเภทสถาบันจาก myTCAS (university_type) → ป้ายที่เราใช้
# อ้างอิงจาก courses.json ซึ่งมี university_type_name_th ติดมากับทุกหลักสูตร:
#   1 = ทปอ. (มหาวิทยาลัยรัฐ)   2 = มรภ. (มหาวิทยาลัยราชภัฏ — เป็นรัฐเช่นกัน)
#   3 = มทร. (ราชมงคล)         4 = เอกชน              5 = อื่น ๆ
# เดิมเข้าใจผิดว่า 2 = เอกชน ทำให้มหาวิทยาลัยราชภัฏ 16 แห่งถูกจัดผิดกลุ่ม
TYPE_LABELS = {
    "1": "รัฐ",
    "2": "รัฐ",
    "3": "ราชมงคล",
    "4": "เอกชน",
    "5": "อื่น ๆ",
}

# ป้ายย่อตามกลุ่ม (ใช้แสดงผลสั้น ๆ เช่น "ราชภัฏ" / "ทปอ.")
TYPE_ABBREVIATIONS = {
    "1": "ทปอ.",
    "2": "มรภ.",
    "3": "มทร.",
    "4": "เอกชน",
    "5": "อื่น ๆ",
}

# รอบรับสมัคร: "1_2570" → "รอบ 1"
ROUND_LABELS = {"1": "รอบ 1", "2": "รอบ 2", "3": "รอบ 3", "4": "รอบ 4"}


# ---------------------------------------------------------------------------
# cache ในหน่วยความจำ
# ---------------------------------------------------------------------------
_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl: float) -> Any | None:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    return None


def _store(key: str, value: Any) -> Any:
    _cache[key] = (time.monotonic(), value)
    return value


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _plain(value: Any, limit: int = 6000) -> str:
    """ตัดแท็ก HTML ออกจากเงื่อนไข/เกณฑ์ที่มหาวิทยาลัยเขียนมาแบบ Word

    ข้อมูลจาก myTCAS บางส่วนเป็น HTML ที่คัดลอกมาจาก Word (มี <p class="MsoList...">)
    ต้องถอดออกก่อนนำไปแสดง ไม่งั้นผู้ใช้จะเห็นแท็กในหน้าเว็บ
    """
    import html as _html

    raw = str(value or "")
    if "<" in raw:
        raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
        raw = re.sub(r"(?i)<br\s*/?>", " ", raw)
        raw = re.sub(r"(?i)</(p|div|li|tr|h[1-6])>", " ", raw)
        # แท็กที่ไม่มีจุดปิด (ข้อความที่คัดลอกมาจาก Word แล้วถูกตัด) — ให้ตัดทิ้งทั้งก้อน
        raw = re.sub(r"<[^>]*$", " ", raw)
        raw = re.sub(r"<[^>]+>", " ", raw)
    text = _text(_html.unescape(raw))
    if limit and len(text) > limit:
        text = text[:limit].rstrip() + " …"
    return text


# ---------------------------------------------------------------------------
# ดึงข้อมูลจาก myTCAS
# ---------------------------------------------------------------------------
async def _get_json(client: httpx.AsyncClient, path: str) -> Any:
    response = await client.get(f"{MYTCAS_API}/{path}")
    response.raise_for_status()
    return response.json()


async def fetch_universities(client: httpx.AsyncClient, force: bool = False) -> list[dict[str, Any]]:
    if not force:
        hit = _cached("universities", CACHE_TTL)
        if hit is not None:
            return hit
    data = await _get_json(client, "universities.json")
    return _store("universities", data)


async def fetch_courses(client: httpx.AsyncClient, force: bool = False) -> list[dict[str, Any]]:
    if not force:
        hit = _cached("courses", CACHE_TTL)
        if hit is not None:
            return hit
    data = await _get_json(client, "courses.json")
    return _store("courses", data)


async def fetch_rounds(client: httpx.AsyncClient, program_ids: list[str], force: bool = False) -> dict[str, list[dict[str, Any]]]:
    """ดึง rounds ของ program ที่ระบุ — คืน {program_id: [รอบ...]}"""
    pending = []
    result: dict[str, list[dict[str, Any]]] = {}
    for pid in program_ids:
        hit = _cached(f"rounds:{pid}", CACHE_TTL)
        if hit is None:
            pending.append(pid)
        else:
            result[pid] = hit
    if not pending:
        return result

    semaphore = asyncio.Semaphore(ROUNDS_CONCURRENCY)

    async def one(pid: str) -> None:
        async with semaphore:
            try:
                data = await _get_json(client, f"rounds/{pid}.json")
            except (httpx.HTTPError, ValueError):
                data = []
            _store(f"rounds:{pid}", data)
            result[pid] = data

    await asyncio.gather(*(one(pid) for pid in pending))
    return result


# ---------------------------------------------------------------------------
# แปลงข้อมูล
# ---------------------------------------------------------------------------
async def university_index() -> dict[str, dict[str, Any]]:
    """ดัชนีมหาวิทยาลัยจาก myTCAS ตาม tc_uid — ใช้เติมข้อมูลที่ตาราง institutions ยังไม่มี

    คืน {tc_uid: {name, name_en, kind, logo_url, website_url}}
    """
    hit = _cached("university_index", CACHE_TTL)
    if hit is not None:
        return hit
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        headers={"User-Agent": UA, "Accept": "application/json"},
    ) as client:
        universities = await fetch_universities(client)
    index: dict[str, dict[str, Any]] = {}
    for item in universities:
        record = university_record(item)
        uid = record["tc_uid"]
        if uid:
            index[uid] = record
    return _store("university_index", index)


def university_record(item: dict[str, Any]) -> dict[str, Any]:
    """แปลงมหาวิทยาลัยจาก myTCAS ให้เข้ากับตาราง institutions"""
    uid = _text(item.get("university_id"))
    type_code = _text(item.get("university_type"))
    name = _text(item.get("university_name"))
    # ลิงก์ประกาศรับสมัคร/เกณฑ์จาก myTCAS (มีบางมหาวิทยาลัยเท่านั้น)
    documents = [
        {"label": label, "url": url}
        for label, url in (
            ("ประกาศรับสมัคร รอบ 1", item.get("file_path_1")),
            ("ประกาศรับสมัคร รอบ 2", item.get("file_path_2")),
            ("ประกาศรับสมัคร รอบ 3", item.get("file_path_3")),
            ("ประกาศรับสมัคร รอบ 4", item.get("file_path_4")),
            ("แนวทางรับสมัครสำหรับผู้มีความทุพพลภาพ", item.get("file_path_handicap")),
        )
        if _text(url)
    ]
    return {
        "tc_uid": uid,
        "name": name,
        "name_en": _text(item.get("university_name_en")),
        # ชื่อย่อสำหรับโลโก้สี่เหลี่ยม — myTCAS ไม่มีชื่อย่อ ใช้ 2 อักษรแรกของชื่อไทย
        "short_name": name[:2] if name else "",
        "city": "",
        "kind": TYPE_LABELS.get(type_code, "อื่น ๆ"),
        "tc_type": type_code,
        "tc_type_name": TYPE_ABBREVIATIONS.get(type_code, "อื่น ๆ"),
        "website_url": f"{MYTCAS_SITE}/university/{uid}" if uid else None,
        "logoUrl": f"https://assets.mytcas.com/i/logo/{uid}.png" if uid else None,
        "documents": documents,
        "is_published": True,
        "updated_at": _now_iso(),
    }


def course_records(courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """แปลงคณะ/หลักสูตรจาก courses.json ให้เข้ากับตาราง faculties"""
    records: list[dict[str, Any]] = []
    for course in courses:
        program_id = _text(course.get("program_id"))
        faculty = _text(course.get("faculty_name_th"))
        if not program_id or not faculty:
            continue
        program_name = _text(course.get("program_name_th"))
        campus = _text(course.get("campus_name_th"))
        # ชื่อที่แสดง: "คณะวิศวกรรมศาสตร์" + สาขา/หลักสูตร
        name = faculty
        field = _text(course.get("field_name_th"))
        if field and field != program_name and program_name:
            name = f"{faculty} · {program_name}"
        elif campus:
            name = f"{faculty} ({campus})"
        records.append({
            "tc_uid": f"course:{program_id}",
            "tc_faculty_uid": f"{_text(course.get('university_id'))}:{_text(course.get('faculty_id'))}",
            "institution": _text(course.get("university_name_th")),
            "name": name[:200],
            "program": program_name[:200],
            "program_name_en": _text(course.get("program_name_en"))[:200],
            "degree": _text(course.get("program_type_name_th"))[:100],
            "campus": campus[:100],
            "field_name": field[:120],
            "program_id": program_id,
            "program_type": _text(course.get("program_type_name_th"))[:100],
            "cost": _text(course.get("cost"))[:500],
            "graduate_rate": _text(course.get("graduate_rate"))[:100],
            "employment_rate": _text(course.get("employment_rate"))[:100],
            "median_salary": _text(course.get("median_salary"))[:100],
            "source_url": f"{MYTCAS_SITE}/courses/detail/{program_id}" if program_id else None,
            "is_published": True,
            "updated_at": _now_iso(),
        })
    return records


def _round_label(round_type: str) -> str:
    """'1_2570' → 'รอบ 1'"""
    code = round_type.split("_")[0] if round_type else ""
    return ROUND_LABELS.get(code, f"รอบ {code}" if code else "รอบรับสมัคร")


def _closed_date(round_item: dict[str, Any]) -> str | None:
    """วันปิดรับ — อยู่ใน folio.closed_date ของรอบ 1/2"""
    folio = round_item.get("folio")
    if isinstance(folio, dict):
        raw = _text(folio.get("closed_date"))
        if raw:
            return raw[:10]
    return None


def admission_records(
    course: dict[str, Any],
    rounds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """แปลงรอบรับสมัครของหนึ่งหลักสูตรให้เข้ากับตาราง admissions"""
    program_id = _text(course.get("program_id"))
    faculty = _text(course.get("faculty_name_th"))
    program = _text(course.get("program_name_th"))
    institution = _text(course.get("university_name_th"))
    records: list[dict[str, Any]] = []

    for round_item in rounds:
        round_type = _text(round_item.get("type"))
        if not round_type:
            continue
        project_id = _text(round_item.get("project_id")) or "default"
        project_name = _text(round_item.get("project_name_th"))
        folio = round_item.get("folio") if isinstance(round_item.get("folio"), dict) else {}
        scores = round_item.get("scores") if isinstance(round_item.get("scores"), dict) else {}
        score_conditions = round_item.get("score_conditions") if isinstance(round_item.get("score_conditions"), dict) else {}

        # แยก "เกณฑ์ตัวเลข" (อ่านง่าย แสดงเป็นตาราง) ออกจาก "เงื่อนไขประกอบ" (ข้อความยาว)
        score_items: list[dict[str, Any]] = []
        if round_item.get("min_gpax"):
            score_items.append({"label": "GPA 10 วิชา", "value": round_item["min_gpax"], "unit": ""})
        for field, label in (
            ("min_gpa22", "GPA 22 วิชา"), ("min_gpa23", "GPA 23 วิชา"), ("min_gpa24", "GPA 24 วิชา"),
            ("min_credit_gpa22", "เกรดเฉลี่ย 22 วิชา"), ("min_credit_gpa23", "เกรดเฉลี่ย 23 วิชา"),
            ("min_credit_gpa24", "เกรดเฉลี่ย 24 วิชา"),
        ):
            if round_item.get(field):
                score_items.append({"label": label, "value": round_item[field], "unit": ""})
        if round_item.get("min_total_score"):
            score_items.append({"label": "คะแนนรวม TGAT/TPAT", "value": round_item["min_total_score"], "unit": "คะแนน"})
        for key, label in (("tgat", "TGAT"), ("tpat3", "TPAT 3"), ("a_lv_61", "A-Level 61"), ("a_lv_64", "A-Level 64"), ("a_lv_65", "A-Level 65")):
            if scores.get(key):
                score_items.append({"label": f"{label} (สูงสุด)", "value": scores[key], "unit": "คะแนน"})
        if round_item.get("min_age") is not None:
            score_items.append({"label": "อายุขั้นต่ำ", "value": round_item["min_age"], "unit": "ปี"})
        if round_item.get("max_age") is not None:
            score_items.append({"label": "อายุสูงสุด", "value": round_item["max_age"], "unit": "ปี"})

        # เงื่อนไขอื่น ๆ — แยกเป็นรายการย่อยเพื่อให้อ่านทีละบรรทัด
        notes: list[str] = []
        if round_item.get("condition"):
            notes.extend(_split_note(round_item["condition"]))
        if folio.get("criteria"):
            notes.extend(_split_note(folio["criteria"]))
        notes = [note for note in notes if note]

        criteria_parts = [
            f"{entry['label']} ไม่ต่ำกว่า {entry['value']}{' ' + entry['unit'] if entry['unit'] else ''}"
            for entry in score_items
        ]
        criteria_parts.extend(notes)
        closed = _closed_date(round_item)
        criteria = " · ".join(criteria_parts)[:4000] or "ดูรายละเอียดเพิ่มเติมที่ประกาศทางการของมหาวิทยาลัย"

        title = f"{_round_label(round_type)}"
        if project_name:
            title = f"{title} — {project_name}"

        records.append({
            # กุญแจกันข้อมูลซ้ำ: program + project + รอบ
            "tc_uid": f"admission:{program_id}:{project_id}:{round_type}",
            "institution": institution,
            "faculty": faculty,
            "program": program,
            "round": title,
            "round_type": round_type,
            "academic_year": round_type.split("_")[1] if "_" in round_type else None,
            "project_id": project_id,
            "project_name": project_name[:300],
            "project_name_en": _text(round_item.get("project_name_en"))[:300],
            "program_id": program_id,
            "quota": round_item.get("receive_student_number"),
            "min_gpax": round_item.get("min_gpax"),
            "min_total_score": round_item.get("min_total_score"),
            "min_gpa22": round_item.get("min_gpa22"),
            "min_gpa23": round_item.get("min_gpa23"),
            "min_gpa24": round_item.get("min_gpa24"),
            "min_credit_gpa22": round_item.get("min_credit_gpa22"),
            "min_credit_gpa23": round_item.get("min_credit_gpa23"),
            "min_credit_gpa24": round_item.get("min_credit_gpa24"),
            # โครงสร้างสำหรับแสดงผล: เกณฑ์ตัวเลข (อ่านง่าย) แยกจากเงื่อนไขข้อความ
            "score_items": score_items,
            "notes": notes,
            "min_age": round_item.get("min_age"),
            "max_age": round_item.get("max_age"),
            "condition": _plain(round_item.get("condition"), 6000),
            "description": _plain(round_item.get("description"), 3000),
            "interview_location": _text(round_item.get("interview_location"))[:300],
            "interview_date": _text(round_item.get("interview_date"))[:300],
            "interview_time": _text(round_item.get("interview_time"))[:100],
            "score_conditions": _dump_json(score_conditions),
            "scores": _dump_json(scores),
            "folio_criteria": _plain(folio.get("criteria"), 6000) if folio.get("criteria") else None,
            "closed_date": closed,
            "deadline": closed,
            "criteria": criteria,
            "source_url": _text(round_item.get("link")) or f"{MYTCAS_SITE}/courses/detail/{program_id}",
            "source_label": "myTCAS",
            "source": "mytcas",
            "is_published": True,
            "updated_at": _now_iso(),
        })
    return records


def _split_note(text: str) -> list[str]:
    """แยกเงื่อนไขยาว ๆ เป็นรายการย่อยเพื่อให้อ่านทีละบรรทัด

    myTCAS เก็บเงื่อนไขเป็นข้อความเดียวติดกัน เช่น
    "1. ประวัติผลงาน สัดส่วน 25.00 2. SOP สัดส่วน 5.00 3. ผลสอบ MCAT"
    ต้องแยกตามหมายเลขข้อ เพื่อให้ผู้ใช้อ่านออกว่ามีกี่ข้อและแต่ละข้อคืออะไร
    """
    raw = _plain(text)
    if not raw:
        return []
    # แยกหัวข้อที่ขึ้นต้นด้วย "1. " "2) " ฯลฯ
    # ต้องไม่ตัดกรณี "(ตามข้อ 9)" หรือ "ข้อ 9." ซึ่งเป็นการอ้างอิง ไม่ใช่หมายเลขข้อ
    parts = re.split(r"(?=(?:^|\s)\d{1,2}[.)]\s+(?!\d*\s*ข้อ))", raw)
    # ซ่อมกรณีที่วงเล็บคั่นทำให้ regex ตัดผิด: รวมชิ้นที่เปิดวงเล็บค้างไว้กับชิ้นก่อนหน้า
    merged: list[str] = []
    for part in parts:
        text = _text(part)
        if merged and merged[-1].count("(") > merged[-1].count(")"):
            merged[-1] = f"{merged[-1]} {text}"
        else:
            merged.append(text)
    items = [item for item in merged if item]
    # ถ้าแยกไม่ออก (ไม่มีหมายเลขข้อ) ให้ตัดตามประโยคแทน
    if len(items) <= 1:
        sentences = re.split(r"(?<=[.;])\s+", raw)
        items = [_text(sentence) for sentence in sentences if _text(sentence)]
    # ตัดหมายเลขข้อที่นำหน้าออก เพราะหน้าเว็บจะใส่เลขให้เอง
    return [re.sub(r"^\d{1,2}[.)]\s*", "", item).strip() for item in items if item]


def _dump_json(value: Any) -> str | None:
    if not value:
        return None
    import json
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


async def live_universities() -> list[dict[str, Any]]:
    """รายชื่อมหาวิทยาลัย/สถาบันทั้งหมดจาก myTCAS (ข้อมูลต้นทางจริง)

    คืนรายการที่แปลงเป็นรูปแบบเดียวกับตาราง institutions แล้ว พร้อม kind_label
    (ป้ายเต็มของกลุ่ม เช่น "รัฐ" / "ราชมงคล" / "เอกชน") เพื่อให้หน้าเว็บแสดงผลตรงต้นทาง
    """
    hit = _cached("live_universities", CACHE_TTL)
    if hit is not None:
        return hit
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        headers={"User-Agent": UA, "Accept": "application/json"},
    ) as client:
        universities = await fetch_universities(client)
    items: list[dict[str, Any]] = []
    for source in universities:
        record = university_record(source)
        if not record.get("name"):
            continue
        record["kind_label"] = TYPE_LABELS.get(record.get("tc_type") or "", "อื่น ๆ")
        items.append(record)
    return _store("live_universities", items)


# ---------------------------------------------------------------------------
# ซิงก์ลงฐานข้อมูล
# ---------------------------------------------------------------------------
async def _filter_columns(repo: Any, table: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ตัดคีย์ที่ตารางไม่มีออก — ให้ซิงก์ได้แม้ยังไม่ได้รัน migration 011

    คอลัมน์ที่อยู่ใน migration 011 (quota, min_gpax, score_conditions ฯลฯ) จะถูกข้ามไป
    จนกว่าจะรัน migration — ข้อมูลหลัก (ชื่อ คณะ รอบ เกณฑ์ ลิงก์) ยังเขียนได้ตามปกติ
    """
    if not records:
        return records
    sample = records[0]
    allowed: set[str] = set()
    for key in sample:
        if await repo.column_exists(table, key):
            allowed.add(key)
    if not allowed:
        return []
    return [{k: v for k, v in record.items() if k in allowed} for record in records]


async def live_faculty_search(needle: str, take: int = 8) -> list[dict[str, Any]]:
    """ค้นหาคณะ/หลักสูตรจาก courses.json ของ myTCAS โดยตรง (ไม่ต้องรอซิงก์ลงฐานข้อมูล)

    ใช้เป็นทางสำรอง/เสริมเมื่อตาราง faculties ยังว่างหรือค้นไม่ครบ
    """
    key = f"faculty_search:{needle.lower()}"
    hit = _cached(key, CACHE_TTL)
    if hit is not None:
        return hit

    import httpx

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(25.0, connect=10.0),
        headers={"User-Agent": UA, "Accept": "application/json"},
    ) as client:
        courses = await fetch_courses(client)

    lowered = needle.strip().lower()
    results: list[dict[str, Any]] = []
    for course in courses:
        faculty = _text(course.get("faculty_name_th"))
        program = _text(course.get("program_name_th"))
        institution = _text(course.get("university_name_th"))
        if not faculty:
            continue
        haystack = f"{faculty} {program} {institution}".lower()
        if lowered not in haystack:
            continue
        results.append({
            "name": faculty if faculty.lower() in haystack else f"{faculty} · {program}",
            "institution": institution,
            "program": program,
            "degree": _text(course.get("program_type_name_th")),
            "url": "/quota",
        })
        if len(results) >= take:
            break
    return _store(key, results)


async def sync_institutions(repo: Any) -> dict[str, Any]:
    """ซิงก์เฉพาะรายชื่อมหาวิทยาลัย/สถาบันจาก myTCAS (เร็ว — ไม่ต้องดึงรอบรับ)

    เติมข้อมูลที่ตาราง institutions ยังขาด (tc_uid, name_en, kind, tc_type, website_url, โลโก้)
    และซ่อมแถวเก่าที่เคย seed มาโดยไม่มี tc_uid — เติมโดยจับคู่ด้วยชื่อ
    """
    summary: dict[str, Any] = {"total": 0, "updated": 0, "inserted": 0, "errors": []}
    if not repo.configured:
        summary["errors"].append("Supabase ยังไม่ได้ตั้งค่า")
        return summary

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(25.0, connect=10.0),
        headers={"User-Agent": UA, "Accept": "application/json"},
    ) as client:
        universities = await fetch_universities(client)

    records = [university_record(item) for item in universities]
    records = [record for record in records if record.get("tc_uid") and record.get("name")]
    summary["total"] = len(records)

    # แถวที่มีอยู่แล้วในตาราง — จับคู่ด้วย tc_uid หรือชื่อ (แถวเก่าที่ยังไม่มี tc_uid)
    existing = await repo.select("institutions", {"select": "id,name,tc_uid", "limit": "1000"})
    by_uid: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for row in existing or []:
        if row.get("tc_uid"):
            by_uid[str(row["tc_uid"])] = row
        if row.get("name"):
            by_name.setdefault(str(row["name"]), row)

    updated = 0
    inserted = 0
    for record in records:
        uid = str(record["tc_uid"])
        row = by_uid.get(uid) or by_name.get(str(record["name"]))
        payload = {
            "tc_uid": uid,
            "name": record["name"],
            "name_en": record["name_en"] or None,
            "kind": record["kind"],
            "tc_type": record["tc_type"],
            "website_url": record["website_url"],
            "logoUrl": record["logoUrl"],
            "short_name": record["short_name"] or None,
            "is_published": True,
            "updated_at": record["updated_at"],
        }
        payload = {key: value for key, value in payload.items() if await repo.column_exists("institutions", key)}
        if row is None:
            if await repo.upsert("institutions", payload, "tc_uid"):
                inserted += 1
        else:
            # อัปเดตแถวเดิมด้วย tc_uid (เดิมเป็น NULL) — ใช้ id เป็นเงื่อนไขกันชน unique index
            if await repo.update("institutions", {"id": f"eq.{row['id']}"}, payload):
                updated += 1

    summary["updated"] = updated
    summary["inserted"] = inserted
    return summary


async def sync_all(repo: Any, program_limit: int = ROUNDS_BATCH_LIMIT) -> dict[str, Any]:
    """ดึงข้อมูล myTCAS ทั้งหมดแล้ว upsert ลงฐานข้อมูล

    ใช้เวลาไม่มากนัก: รอบรับต้องยิง 1 request ต่อ program (4,142 program)
    จึงดึงครั้งละไม่เกิน program_limit ตัว แล้วเรียกซ้ำเพื่อดึงส่วนที่เหลือ
    """
    summary = {
        "institutions": 0,
        "faculties": 0,
        "admissions": 0,
        "program_limit": program_limit,
        "has_more": False,
        "errors": [],
    }
    if not repo.configured:
        summary["errors"].append("Supabase ยังไม่ได้ตั้งค่า")
        return summary

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(25.0, connect=10.0),
        headers={"User-Agent": UA, "Accept": "application/json"},
    ) as client:
        universities = await fetch_universities(client)
        courses = await fetch_courses(client)

        # 1) มหาวิทยาลัย
        inst_records = await _filter_columns(repo, "institutions", [university_record(item) for item in universities])
        summary["institutions"] = await repo.upsert_many("institutions", inst_records, "tc_uid")
        summary["institutions_total"] = len(inst_records)

        # 2) คณะ/หลักสูตร
        fac_records = await _filter_columns(repo, "faculties", course_records(courses))
        summary["faculties"] = await repo.upsert_many("faculties", fac_records, "tc_uid")
        summary["faculties_total"] = len(fac_records)

        # 3) รอบรับสมัคร (ดึงตาม program)
        program_ids = sorted({_text(c.get("program_id")) for c in courses if _text(c.get("program_id"))})
        target = program_ids[:program_limit]
        summary["has_more"] = len(program_ids) > program_limit
        summary["program_total"] = len(program_ids)

        rounds_map = await fetch_rounds(client, target)
        by_program = {}
        for course in courses:
            pid = _text(course.get("program_id"))
            if pid:
                by_program.setdefault(pid, course)

        admission_batch: list[dict[str, Any]] = []
        for pid, rounds in rounds_map.items():
            course = by_program.get(pid)
            if not course or not rounds:
                continue
            admission_batch.extend(admission_records(course, rounds))
        admission_batch = await _filter_columns(repo, "admissions", admission_batch)
        summary["admissions"] = await repo.upsert_many("admissions", admission_batch, "tc_uid")
        summary["admissions_total"] = len(admission_batch)

    return summary
