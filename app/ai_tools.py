"""เครื่องมือให้ AI ที่ปรึกษาเรียกใช้เอง — ค้นข้อมูลจริงในระบบ

AI ที่ปรึกษาไม่ได้ตอบจากความจำอย่างเดียว แต่เรียก "เครื่องมือ" เหล่านี้เพื่อดึงข้อมูลสดจาก:
- myTCAS: หลักสูตร/คณะ/ค่าเล่าเรียน/รอบรับ/เกณฑ์คะแนน/โควตา
- เด็กดี: ข่าวและเรื่องราวเรื่องสอบ
- กสศ. + Scholarship.in.th: ทุนการศึกษา

ทุกเครื่องมือคืนข้อความสรุป (ไม่ใช่ JSON ดิบ) เพื่อประหยัดโทเคน
"""
from __future__ import annotations

import json
import re
from typing import Any

# จำนวนผลลัพธ์สูงสุดต่อการเรียก
MAX_RESULTS = 8
# ความยาวข้อความที่ส่งกลับให้ AI ไม่เกิน (ตัวอักษร)
MAX_OUTPUT = 6000


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()



# ---------------------------------------------------------------------------
# นิยามเครื่องมือ (สำหรับส่งให้โมเดลที่รองรับ function calling)
# ---------------------------------------------------------------------------
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "search_programs",
        "description": "ค้นหาหลักสูตร/คณะจาก myTCAS พร้อมค่าเล่าเรียน รอบรับสมัคร และเกณฑ์คะแนน ใช้เมื่อผู้ใช้ถามว่าคณะไหน/มหาวิทยาลัยไหนเปิดรับอะไรบ้าง",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "คำค้น เช่น 'วิศวกรรมศาสตร์ จุฬาฯ' หรือ 'แพทยศาสตร์'"},
                "university": {"type": "string", "description": "ชื่อมหาวิทยาลัย (ถ้าระบุ)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_admissions",
        "description": "ค้นหารอบรับสมัคร/โควตา/เกณฑ์รับของ TCAS จาก myTCAS ใช้เมื่อถามเรื่องรอบสมัคร โควตา หรือเกณฑ์การคัดเลือก",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "คำค้น เช่น 'โควตาผลิตครู' หรือ 'Portfolio จุฬาฯ'"},
                "round": {"type": "string", "description": "รอบ เช่น 'รอบ 1' หรือ '1_2570'"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_scholarships",
        "description": "ค้นหาทุนการศึกษาจากกสศ. และ Scholarship.in.th ใช้เมื่อถามเรื่องทุน เงื่อนไข และกำหนดปิดรับ",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "คำค้น เช่น 'วิศวกรรม' หรือ 'ปริญญาตรี'"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_news",
        "description": "ค้นหาข่าว/เรื่องราวเรื่องสอบ TCAS ล่าสุดจากเด็กดี (dek-d.com) ใช้เมื่อถามเรื่องข่าวที่เพิ่งประกาศ",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "คำค้น เช่น 'Portfolio' หรือ 'โควตา'"},
                "category": {"type": "string", "description": "หมวด: alert, daily, review, coach, tour, event, dreamcampus, idol, tutoring"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_universities",
        "description": "ดูรายชื่อมหาวิทยาลัย/สถาบันทั้งหมดในระบบ พร้อมประเภท ใช้เมื่อถามว่ามีมหาวิทยาลัยอะไรบ้าง",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "description": "กรองตามประเภท: รัฐ / เอกชน / ราชมงคล / นานาชาติ"},
            },
        },
    },
]


# ---------------------------------------------------------------------------
# การทำงานของเครื่องมือ
# ---------------------------------------------------------------------------
async def run_tool(name: str, arguments: dict[str, Any]) -> str:
    """เรียกเครื่องมือตามชื่อ — คืนข้อความสรุปให้ AI"""
    try:
        if name == "search_programs":
            return await _search_programs(arguments)
        if name == "search_admissions":
            return await _search_admissions(arguments)
        if name == "search_scholarships":
            return await _search_scholarships(arguments)
        if name == "search_news":
            return await _search_news(arguments)
        if name == "list_universities":
            return await _list_universities(arguments)
    except Exception as exc:  # noqa: BLE001 — เครื่องมือพังไม่ควรทำให้แชทล้ม
        return f"เรียกเครื่องมือ '{name}' ไม่สำเร็จ: {exc}"
    return f"ไม่รู้จักเครื่องมือ '{name}'"


async def _search_programs(arguments: dict[str, Any]) -> str:
    """ค้นหาหลักสูตรจาก myTCAS พร้อมค่าเล่าเรียนและรอบรับ"""
    from .tcas_live import _load_courses

    query = _text(arguments.get("query"))
    university = _text(arguments.get("university"))
    needle = f"{query} {university}".strip()

    rows = await _load_courses(needle)
    if not rows:
        return f"ไม่พบหลักสูตรที่ตรงกับ '{needle}' ในระบบ myTCAS"

    lines = []
    for row in rows[:MAX_RESULTS]:
        parts = [row.get("university_name_th", ""), row.get("faculty_name_th", "")]
        if row.get("field_name_th") and row["field_name_th"] not in (row.get("faculty_name_th") or ""):
            parts.append(row["field_name_th"])
        cost = _text(row.get("cost"))
        graduate = _text(row.get("graduate_rate"))
        detail = " | ".join(filter(None, [
            f"ค่าเล่าเรียน: {cost[:120]}" if cost else "",
            f"จบการศึกษา: {graduate}" if graduate and graduate != "0" else "",
            f"ประเภท: {row.get('program_type_name_th')}" if row.get("program_type_name_th") else "",
        ]))
        lines.append(f"• {' | '.join(p for p in parts if p)}" + (f"\n  {detail}" if detail else ""))

    return f"พบ {len(rows)} หลักสูตรที่ตรงกับ '{needle}':\n" + "\n".join(lines)


async def _search_admissions(arguments: dict[str, Any]) -> str:
    """ค้นหารอบรับสมัคร/โควตา/เกณฑ์จาก myTCAS"""
    from .tcas_live import load_live

    query = _text(arguments.get("query"))
    round_filter = _text(arguments.get("round"))
    data = await load_live(q=query, limit=60)
    items = data.get("items", [])
    if round_filter:
        items = [item for item in items if round_filter in (item.get("round") or "") or round_filter in (item.get("round_type") or "")]

    if not items:
        return f"ไม่พบรอบรับสมัครที่ตรงกับ '{query}' ในระบบ myTCAS"

    lines = []
    for item in items[:MAX_RESULTS]:
        bits = []
        if item.get("quota"):
            bits.append(f"รับ {item['quota']} คน")
        if item.get("min_gpax"):
            bits.append(f"GPA ≥ {item['min_gpax']}")
        if item.get("min_total_score"):
            bits.append(f"คะแนนรวม ≥ {item['min_total_score']}")
        if item.get("deadline"):
            bits.append(f"ปิด {item['deadline']}")
        lines.append(
            f"• {item.get('institution', '')} — {item.get('faculty', '')}\n"
            f"  {item.get('round', '')}\n"
            + (f"  {' · '.join(bits)}\n" if bits else "")
            + f"  {item.get('criteria', '')[:280]}"
        )
    return f"พบ {len(items)} รอบรับสมัครที่ตรงกับ '{query}':\n" + "\n".join(lines)


async def _search_scholarships(arguments: dict[str, Any]) -> str:
    """ค้นหาทุนการศึกษาจากกสศ. + Scholarship.in.th"""
    from .scholarships import search_items, load_items

    query = _text(arguments.get("query"))
    items, _ = await load_items()
    matched = search_items(items, query=query, limit=MAX_RESULTS)
    if not matched:
        return f"ไม่พบทุนการศึกษาที่ตรงกับ '{query}'"

    lines = []
    for item in matched:
        bits = []
        if item.get("amount"):
            bits.append(f"มูลค่า: {item['amount']}")
        if item.get("deadline"):
            bits.append(f"ปิด: {item['deadline']}")
        if item.get("sponsor"):
            bits.append(f"ผู้ให้ทุน: {item['sponsor'][:80]}")
        lines.append(
            f"• {item.get('title', '')} ({item.get('source_label', '')})\n"
            + (f"  {' · '.join(bits)}\n" if bits else "")
            + f"  {item.get('summary', '')[:200]}"
        )
    return f"พบ {len(matched)} ทุนการศึกษาที่ตรงกับ '{query}':\n" + "\n".join(lines)


async def _search_news(arguments: dict[str, Any]) -> str:
    """ค้นหาข่าว/เรื่องราวจากเด็กดี"""
    from .dekd import fetch_all, fetch_category, CATEGORIES

    query = _text(arguments.get("query"))
    category = _text(arguments.get("category"))
    if category and category in CATEGORIES:
        items = await fetch_category(category, pages=1)
    else:
        items = await fetch_all(pages=1)
    if query:
        items = [
            item for item in items
            if query.lower() in f"{item.get('title', '')} {item.get('summary', '')} {' '.join(item.get('tags') or [])}".lower()
        ]
    if not items:
        return f"ไม่พบข่าวที่ตรงกับ '{query}' ในเด็กดี"

    lines = []
    for item in items[:MAX_RESULTS]:
        date = item.get("date_text") or item.get("date") or ""
        lines.append(f"• {item.get('title', '')}\n  {date} · {item.get('category_label', '')} · {item.get('url', '')}")
    return f"พบ {len(items)} ข่าว/เรื่องราวที่ตรงกับ '{query}':\n" + "\n".join(lines)


async def _list_universities(arguments: dict[str, Any]) -> str:
    """ดูรายชื่อมหาวิทยาลัยในระบบ"""
    from .tcas_live import _load_courses  # noqa: F401 — ใช้เพื่อให้โหลดข้อมูล courses ครั้งเดียว

    rows = await _load_courses("")
    kind = _text(arguments.get("kind"))
    names: dict[str, set[str]] = {}
    for row in rows:
        name = _text(row.get("university_name_th"))
        if not name:
            continue
        names.setdefault(name, set()).add(_text(row.get("university_type_name_th")))

    lines = []
    for name in sorted(names):
        types = ", ".join(sorted(t for t in names[name] if t))
        lines.append(f"• {name}" + (f" ({types})" if types else ""))

    if kind:
        lines = [line for line in lines if kind in line]
    return f"มีมหาวิทยาลัย/สถาบันในระบบ {len(lines)} แห่ง:\n" + "\n".join(lines[:40])


# ---------------------------------------------------------------------------
# แปลง tool ให้เข้ากับแต่ละผู้ให้บริการ
# ---------------------------------------------------------------------------
def to_openai_tools() -> list[dict[str, Any]]:
    """แปลงนิยามเครื่องมือเป็นรูปแบบของ OpenAI"""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            },
        }
        for tool in TOOL_DEFINITIONS
    ]


def to_gemini_tools() -> list[dict[str, Any]]:
    """แปลงนิยามเครื่องมือเป็นรูปแบบของ Gemini"""
    return [
        {
            "functionDeclarations": [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                }
                for tool in TOOL_DEFINITIONS
            ]
        }
    ]


def to_anthropic_tools() -> list[dict[str, Any]]:
    """แปลงนิยามเครื่องมือเป็นรูปแบบของ Anthropic"""
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": tool["parameters"],
        }
        for tool in TOOL_DEFINITIONS
    ]


# ---------------------------------------------------------------------------
# แปลงคำตอบที่มีการเรียกเครื่องมือ
# ---------------------------------------------------------------------------
def parse_tool_call(provider: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """ดึงคำขอเรียกเครื่องมือออกจาก response ของแต่ละเจ้า — คืน (ชื่อเครื่องมือ, อาร์กิวเมนต์)"""
    if provider == "openai":
        choices = payload.get("choices") or []
        if not choices:
            return None
        calls = (choices[0].get("message") or {}).get("tool_calls") or []
        if not calls:
            return None
        function = calls[0].get("function") or {}
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except (TypeError, ValueError):
            arguments = {}
        return function.get("name"), arguments

    if provider == "anthropic":
        for block in payload.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                return block.get("name"), (block.get("input") or {})
        return None

    if provider == "gemini":
        for candidate in payload.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                function_call = part.get("functionCall") if isinstance(part, dict) else None
                if function_call:
                    return function_call.get("name"), (function_call.get("args") or {})
        return None

    # forge ใช้รูปแบบเดียวกับ OpenAI
    choices = payload.get("choices") or []
    if not choices:
        return None
    calls = (choices[0].get("message") or {}).get("tool_calls") or []
    if not calls:
        return None
    function = calls[0].get("function") or {}
    try:
        arguments = json.loads(function.get("arguments") or "{}")
    except (TypeError, ValueError):
        arguments = {}
    return function.get("name"), arguments
