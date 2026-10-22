"""ระบบ AI ที่ปรึกษา — คุยกับผู้ใช้ได้จริง

รองรับผู้ให้บริการหลายเจ้า — เลือกอัตโนมัติจากค่าใน .env:
- BUILT_IN_FORGE_API_URL + BUILT_IN_FORGE_API_KEY  (Manus WebDev runtime)
- ANTHROPIC_API_KEY                                (Claude)
- OPENAI_API_KEY                                    (OpenAI / GPT)
- GEMINI_API_KEY / GOOGLE_API_KEY                   (Gemini)

ถ้ายังไม่ได้ตั้ง key ใด ๆ ระบบจะตอบว่ายังไม่พร้อมใช้งาน (แต่ UI ยังคุยได้ตามปกติ)
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

# โหลดค่าจาก .env (โมดูลนี้อาจถูก import เดี่ยว ๆ โดยไม่ได้ผ่าน repository.py)
try:  # noqa: SIM105
    from .repository import _load_env_file

    _load_env_file()
except Exception:  # noqa: BLE001 — โหลดไม่ได้ก็ปล่อยไป ใช้ค่าจาก environment ตามปกติ
    pass

# ข้อจำกัดความยาว
MAX_MESSAGE = 4000
MAX_HISTORY = 20  # จำนวนข้อความย้อนหลังที่ส่งให้ AI
REQUEST_TIMEOUT = 60.0

# โมเดลเริ่มต้นต่อเจ้า — รหัสตาม API จริง
# (เลือกตัวที่นิ่ง ๆ ไว้ก่อน เพราะโมเดลใหม่/ยอดนิยมมักเต็ม 503 หรือโควตา key ฟรีหมดเร็ว)
DEFAULT_MODELS = {
    "forge": "gpt-6-luna",
    "anthropic": "claude-sonnet-5-5",
    "openai": "gpt-6.1-sol",
    "gemini": "gemini-3.6-flash",
}

# โมเดลที่ผู้ใช้เลือกได้ (แสดงใน dropdown) — รหัสตาม API จริงของแต่ละเจ้า
MODELS = [
    {"key": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5 · คำแนะนำละเอียด (แนะนำ)"},
    {"key": "claude-opus-5-5", "label": "Claude Opus 5.5 · คิดลึกที่สุด"},
    {"key": "claude-haiku-5-5", "label": "Claude Haiku 5.5 · ตอบเร็ว ประหยัด"},
    {"key": "claude-fable-5-1", "label": "Claude Fable 5.1 · งานซับซ้อน"},
    {"key": "gpt-6.1-sol", "label": "GPT-6.1 Sol · สมดุลความสามารถกับราคา"},
    {"key": "gpt-6-luna", "label": "GPT-6 Luna · ประหยัด ตอบเร็ว"},
    {"key": "gpt-6-astra", "label": "GPT-6 Astra · ความสามารถสูงสุด"},
    {"key": "gemini-3.6-flash", "label": "Gemini 3.6 Flash · ตอบเร็ว (แนะนำ)"},
    {"key": "gemini-3.5-flash", "label": "Gemini 3.5 Flash · ตอบเร็ว"},
    {"key": "gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash Lite · เร็วที่สุด"},
]

# คำแนะนำให้ AI ตอบตามบริบทของเว็บ TCAS Buddy
SYSTEM_PROMPT = """คุณคือ "TCAS Buddy" ผู้ช่วยแนะนำนักเรียนไทยที่กำลังเตรียมสมัครมหาวิทยาลัยผ่านระบบ TCAS

คุณมี "เครื่องมือ" สำหรับค้นข้อมูลจริงในระบบ — ใช้เมื่อคำถามเกี่ยวกับข้อมูลเฉพาะของปีการศึกษาปัจจุบัน:
- search_programs — หลักสูตร/คณะ ค่าเล่าเรียน รอบรับ เกณฑ์คะแนน (myTCAS)
- search_admissions — รอบรับสมัคร โควตา เกณฑ์การคัดเลือก (myTCAS)
- search_scholarships — ทุนการศึกษาและเงื่อนไข (กสศ. + Scholarship.in.th)
- search_news — ข่าว/เรื่องราวเรื่องสอบล่าสุด (เด็กดี)
- list_universities — รายชื่อมหาวิทยาลัยทั้งหมด

**กฎการตอบ:**
1. ถ้าคำถามเกี่ยวกับตัวเลขหรือข้อมูลเฉพาะ (เกณฑ์รับ โควตา ค่าเล่าเรียน รอบสมัคร ทุน ข่าวล่าสุด) ให้เรียกเครื่องมือก่อนตอบเสมอ อย่าเดาจากความจำ
2. เรียกเครื่องมือได้หลายครั้งถ้าจำเป็น แล้วสังเคราะห์คำตอบสุดท้ายให้ครบถ้วน
3. ถ้าเครื่องมือหาไม่พบข้อมูล ให้บอกตรง ๆ ว่าไม่พบ และแนะนำให้ดูที่ www.mytcas.com
4. ตอบเป็นภาษาไทย สุภาพ เป็นกันเอง ใช้ "คุณ" เรียกผู้ใช้
5. ตอบกระชับ ตรงประเด็น ใช้ย่อหน้าเมื่อเหมาะกับการอธิบายเรื่องยาว
6. ใช้รูปแบบ Markdown เบา ๆ (รายการย่อย เครื่องหมายขีด) ไม่ใช้ตาราง
7. ถ้าคำถามเกี่ยวกับเกณฑ์รับ โควตา หรือปฏิทิน TCAS ให้บอกผู้ใช้ว่าต้องตรวจสอบกับประกาศทางการของมหาวิทยาลัยเสมอ เพราะตัวเลขเปลี่ยนทุกปี
8. อย่ารับประกันผลการคัดเลือก และอย่าให้ข้อมูลที่คาดว่าจะผิด

หัวข้อที่ช่วยได้: การเตรียมตัว TCAS, การเลือกคณะ/สาขา, เกณฑ์รับและโควตา, ทุนการศึกษา, การเตรียมเอกสาร, A-Level/TGAT/TPAT, ความเครียดและการวางแผน"""


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def detect_provider() -> str | None:
    """ตรวจว่าเชื่อมต่อผู้ให้บริการ AI เจ้าใดได้บ้าง"""
    if _env("BUILT_IN_FORGE_API_URL") and _env("BUILT_IN_FORGE_API_KEY"):
        return "forge"
    if _env("ANTHROPIC_API_KEY"):
        return "anthropic"
    if _env("OPENAI_API_KEY"):
        return "openai"
    if _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY"):
        return "gemini"
    return None


def available_models(provider: str | None) -> list[dict[str, str]]:
    """โมเดลที่ใช้ได้จริงกับ provider ที่เชื่อมต่ออยู่

    ระบบใช้โมเดลหลักตัวเดียวต่อเจ้า (ผู้ใช้ไม่ต้องเลือก) — รายการนี้มีไว้ให้สลับโมเดลสำรอง
    ตอนโมเดลหลักตอบว่า "คนเยอะชั่วคราว" เท่านั้น
    """
    if not provider:
        return []
    allowed = {
        "anthropic": {"claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5", "claude-fable-5-1"},
        "openai": {"gpt-6.1-sol", "gpt-6-luna", "gpt-6-astra"},
        "gemini": {"gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite"},
        "forge": {"gpt-6-luna", "gpt-6.1-sol", "gemini-3.6-flash"},
    }.get(provider, set())
    models = [item for item in MODELS if item["key"] in allowed]
    return models or [{"key": DEFAULT_MODELS.get(provider, "gpt-6-luna"), "label": "โมเดลหลัก"}]


def main_model(provider: str | None) -> dict[str, str]:
    """โมเดลหลักตัวเดียวที่ระบบใช้ — ผู้ใช้ไม่ต้องเลือก"""
    if not provider:
        return {"key": "", "label": ""}
    key = DEFAULT_MODELS.get(provider, "")
    label = next((item["label"] for item in MODELS if item["key"] == key), key)
    return {"key": key, "label": label}


def resolve_model(requested: str, provider: str | None) -> str:
    """เลือกโมเดลที่จะใช้ — ถ้าที่ขอใช้ไม่ได้กับ provider นี้ ให้ใช้โมเดลหลัก"""
    models = available_models(provider)
    keys = {item["key"] for item in models}
    if requested and requested in keys:
        return requested
    if provider:
        return DEFAULT_MODELS.get(provider, models[0]["key"] if models else "gpt-6-luna")
    return requested or "gpt-6-luna"


def _clean_messages(history: Any) -> list[dict[str, str]]:
    """แปลงประวัติสนทนาให้สะอาด — เก็บเฉพาะ role ที่รองรับ"""
    if not isinstance(history, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in history[-MAX_HISTORY:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        cleaned.append({"role": role, "content": content[:MAX_MESSAGE]})
    return cleaned


# ---------------------------------------------------------------------------
# การเรียกผู้ให้บริการแต่ละเจ้า
# ---------------------------------------------------------------------------
# จำนวนรอบที่ AI เรียกเครื่องมือได้สูงสุด (กันวนไม่รู้จบ)
MAX_TOOL_ROUNDS = 4


def _split_system(messages):
    """แยก system prompt ออกจาก messages (Anthropic/Gemini ต้องการแยกชัดเจน)"""
    system = SYSTEM_PROMPT
    if messages and messages[0].get("role") == "system":
        system = messages[0]["content"]
        messages = messages[1:]
    return system, messages


async def _call_forge(client, model, messages):
    from .ai_tools import parse_tool_call, run_tool, to_openai_tools

    base = _env("BUILT_IN_FORGE_API_URL").rstrip("/")
    history = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]
    for _ in range(MAX_TOOL_ROUNDS):
        response = await client.post(
            f"{base}/chat/completions",
            headers={
                "Authorization": f"Bearer {_env('BUILT_IN_FORGE_API_KEY')}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": history,
                "tools": to_openai_tools(),
                "tool_choice": "auto",
                "stream": False,
            },
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices") or []
        message = (choices[0].get("message") if choices else {}) or {}
        call = parse_tool_call("openai", payload)
        if not call:
            return str(message.get("content") or payload.get("content") or payload.get("text") or "").strip()
        name, arguments = call
        result = await run_tool(name, arguments)
        history.append({**message, "tool_calls": (message.get("tool_calls") or [])})
        history.append({"role": "tool", "tool_call_id": (message.get("tool_calls") or [{}])[0].get("id", ""), "content": result})
    return ""


async def _call_anthropic(client, model, messages):
    from .ai_tools import parse_tool_call, run_tool, to_anthropic_tools

    system, chat = _split_system(messages)
    for _ in range(MAX_TOOL_ROUNDS):
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": _env("ANTHROPIC_API_KEY"),
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 2048,
                "system": system,
                "messages": chat,
                "tools": to_anthropic_tools(),
            },
        )
        response.raise_for_status()
        payload = response.json()
        call = parse_tool_call("anthropic", payload)
        if not call:
            parts = [str(block.get("text") or "") for block in payload.get("content") or [] if isinstance(block, dict)]
            return "".join(parts).strip()
        name, arguments = call
        result = await run_tool(name, arguments)
        tool_blocks = [b for b in payload.get("content") or [] if isinstance(b, dict) and b.get("type") == "tool_use"]
        chat = [
            *chat,
            {"role": "assistant", "content": tool_blocks},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": (b or {}).get("id", ""), "content": result} for b in tool_blocks]},
        ]
    return ""


async def _call_openai(client, model, messages):
    from .ai_tools import parse_tool_call, run_tool, to_openai_tools

    history = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]
    for _ in range(MAX_TOOL_ROUNDS):
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {_env('OPENAI_API_KEY')}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": history,
                "tools": to_openai_tools(),
                "tool_choice": "auto",
            },
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices") or []
        message = (choices[0].get("message") if choices else {}) or {}
        call = parse_tool_call("openai", payload)
        if not call:
            return str(message.get("content") or "").strip()
        name, arguments = call
        result = await run_tool(name, arguments)
        history.append({**message, "tool_calls": (message.get("tool_calls") or [])})
        history.append({"role": "tool", "tool_call_id": (message.get("tool_calls") or [{}])[0].get("id", ""), "content": result})
    return ""


async def _call_gemini(client, model, messages):
    from .ai_tools import parse_tool_call, run_tool, to_gemini_tools

    key = _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY")
    system, chat = _split_system(messages)
    contents = [
        {"role": "user" if item["role"] == "user" else "model", "parts": [{"text": item["content"]}]}
        for item in chat
    ]
    for _ in range(MAX_TOOL_ROUNDS):
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json={
                "contents": contents,
                "systemInstruction": {"parts": [{"text": system}]},
                "tools": to_gemini_tools(),
                "tool_config": {"function_calling_config": {"mode": "AUTO"}},
                "generationConfig": {"maxOutputTokens": 2048},
            },
        )
        response.raise_for_status()
        payload = response.json()
        call = parse_tool_call("gemini", payload)
        if not call:
            parts = []
            for candidate in payload.get("candidates") or []:
                for part in (candidate.get("content") or {}).get("parts") or []:
                    if isinstance(part, dict) and part.get("text"):
                        parts.append(str(part["text"]))
            return "".join(parts).strip()
        name, arguments = call
        result = await run_tool(name, arguments)
        contents.append({
            "role": "user",
            "parts": [{"functionResponse": {"name": name, "response": {"result": result}}}],
        })
    return ""


CALLERS = {
    "forge": _call_forge,
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "gemini": _call_gemini,
}


# สถานะที่แปลว่า "โมเดลนี้คนเยอะ/ชั่วคราวใช้ไม่ได้" — ควรลองโมเดลอื่น
OVERLOAD_STATUS = (429, 500, 502, 503, 529)
OVERLOAD_MARKERS = ("high demand", "overloaded", "rate limit", "too many requests", "capacity", "unavailable")

# โควตาของ key หมด (ต่างจากโมเดลคนเยอะ — ลองโมเดลอื่นก็ไม่ช่วย)
QUOTA_MARKERS = ("exceeded your current quota", "quota", "billing", "insufficient_quota")


def _is_overload(status: int, body: str) -> bool:
    """ตรวจว่า error เกิดจากโมเดลคนเยอะ (ควรลองตัวอื่น) หรือ key/พารามิเตอร์ผิด (ต้องแก้โดยผู้ใช้)"""
    if status in OVERLOAD_STATUS:
        lowered = body.lower()
        if any(marker in lowered for marker in OVERLOAD_MARKERS):
            return True
    return False


def _is_quota_exhausted(body: str) -> bool:
    """ตรวจว่าโควตาของ API key หมดแล้ว — ลองโมเดลอื่นก็ไม่ช่วย ต้องแจ้งผู้ดูแล"""
    lowered = body.lower()
    return any(marker in lowered for marker in QUOTA_MARKERS)


async def call_with_fallback(
    client: httpx.AsyncClient,
    provider: str,
    model: str,
    messages: list[dict[str, str]],
) -> tuple[str, str, str | None]:
    """เรียก AI แล้วถ้าโมเดลที่เลือกล้ม (คนเยอะ) ให้ลองโมเดลอื่นของเจ้าเดียวกัน

    คืน (คำตอบ, โมเดลที่ใช้จริง, ข้อความ error)
    """
    candidates = [model]
    # เตรียมโมเดลสำรองของเจ้าเดียวกันไว้ลองตาม
    for item in available_models(provider):
        if item["key"] != model and item["key"] not in candidates:
            candidates.append(item["key"])

    last_error: str | None = None
    for index, candidate in enumerate(candidates):
        try:
            answer = await CALLERS[provider](client, candidate, messages)
        except httpx.HTTPStatusError as exc:
            body = ""
            try:
                body = exc.response.text[:300]
            except Exception:  # noqa: BLE001
                pass
            # โควตาของ key หมด — ลองโมเดลอื่นก็ไม่ช่วย
            if _is_quota_exhausted(body):
                return "", candidate, "โควตาการใช้งาน AI ของเซิร์ฟเวอร์หมดแล้ว กรุณาลองใหม่ภายหลัง หรือให้ผู้ดูแลเพิ่มโควตาในแผนของผู้ให้บริการ"
            if _is_overload(exc.response.status_code, body):
                last_error = f"โมเดล {candidate} คนเยอะชั่วคราว ({exc.response.status_code})"
                continue  # ลองโมเดลถัดไป
            return "", candidate, f"บริการ AI ตอบกลับผิดพลาด ({exc.response.status_code}): {body}"
        except (httpx.HTTPError, ValueError) as exc:
            detail = str(exc).strip() or type(exc).__name__
            return "", candidate, f"ติดต่อบริการ AI ไม่สำเร็จ: {detail}"
        if answer:
            return answer, candidate, None
        last_error = f"โมเดล {candidate} ไม่ได้ส่งคำตอบกลับมา"
    return "", model, last_error or "บริการ AI ไม่สามารถตอบได้ในขณะนี้"


def build_router(repo: Any = None) -> APIRouter:
    router = APIRouter(prefix="/api/ai")

    @router.get("/config")
    async def config() -> dict[str, Any]:
        """บอกหน้าเว็บว่าเชื่อมต่อ AI ได้หรือยัง และโมเดลหลักที่ใช้"""
        provider = detect_provider()
        model = main_model(provider)
        return {
            "configured": provider is not None,
            "provider": provider or "",
            "model": model["key"],
            "model_label": model["label"],
        }

    @router.post("/chat")
    async def chat(payload: dict[str, Any]) -> dict[str, Any]:
        """คุยกับ AI — รับ {message, model, history:[{role,content}]}"""
        message = str(payload.get("message") or "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="กรุณาพิมพ์คำถามก่อนนะ")
        if len(message) > MAX_MESSAGE:
            message = message[:MAX_MESSAGE]

        provider = detect_provider()
        if not provider:
            return {
                "configured": False,
                "provider": "",
                "model": str(payload.get("model") or ""),
                "answer": "",
                "error": "ยังไม่ได้เชื่อมต่อบริการ AI — เจ้าหน้าที่ต้องตั้งค่า API key ก่อน",
            }

        model = resolve_model(str(payload.get("model") or ""), provider)
        history = _clean_messages(payload.get("history"))
        messages = [*history, {"role": "user", "content": message}]

        async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=10.0)) as client:
            answer, used_model, error = await call_with_fallback(client, provider, model, messages)

        if not answer:
            return {
                "configured": True,
                "provider": provider,
                "model": used_model or model,
                "answer": "",
                "error": error or "บริการ AI ไม่ได้ส่งคำตอบกลับมา",
            }
        return {"configured": True, "provider": provider, "model": used_model, "answer": answer}

    return router
