"""ทดสอบระบบ AI ที่ปรึกษา — mock ผู้ให้บริการ AI ไม่ต้องต่อเน็ตจริง

รัน: python tests/test_ai_chat.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.ai_chat as ai_chat  # noqa: E402
from app.ai_chat import (  # noqa: E402
    SYSTEM_PROMPT,
    available_models,
    main_model,
    build_router,
    detect_provider,
    resolve_model,
)

FAILURES: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {extra}")
        FAILURES.append(label)


def mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def main() -> int:
    print("\n=== ตรวจ provider ===")
    saved = {k: os.environ.get(k) for k in ("BUILT_IN_FORGE_API_URL", "BUILT_IN_FORGE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")}
    for key in saved:
        os.environ.pop(key, None)

    check("ไม่มี key → ไม่พร้อมใช้งาน", detect_provider() is None)
    check("ไม่มี provider → ไม่มีโมเดลให้เลือก", available_models(None) == [])

    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    check("พบ Anthropic", detect_provider() == "anthropic")
    check("มีโมเดลสำรองให้สลับได้", len(available_models("anthropic")) > 0)
    check("โมเดลหลักของ Anthropic", main_model("anthropic")["key"] == "claude-sonnet-5-5", str(main_model("anthropic")))
    check("เลือกโมเดลที่ร้องขอได้", resolve_model("claude-sonnet-5-5", "anthropic") == "claude-sonnet-5-5")
    check("โมเดลที่ไม่รองรับ → ใช้ค่าเริ่มต้น", resolve_model("gpt-5", "anthropic") == "claude-sonnet-5-5", resolve_model("gpt-5", "anthropic"))

    os.environ["OPENAI_API_KEY"] = "test-key"
    check("Anthropic มาก่อน OpenAI", detect_provider() == "anthropic")
    os.environ.pop("ANTHROPIC_API_KEY")
    check("เหลือ OpenAI", detect_provider() == "openai")
    for key in saved:
        os.environ.pop(key, None)
        if saved.get(key):
            os.environ[key] = saved[key]

    print("\n=== ทดสอบ endpoint (mock provider) ===")
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    app = FastAPI()
    app.include_router(build_router())
    client = TestClient(app)

    # config ต้องรายงานว่าเชื่อมต่อแล้ว
    response = client.get("/api/ai/config")
    check("config ตอบ 200", response.status_code == 200)
    check("รายงานว่าเชื่อมต่อแล้ว", response.json()["configured"] is True)
    check("ระบุ provider", response.json()["provider"] == "anthropic")
    check("มีโมเดลหลัก", bool(response.json()["model"]), str(response.json().get("model")))
    check("มีชื่อโมเดลหลัก", bool(response.json()["model_label"]), str(response.json().get("model_label")))

    # ข้อความว่าง → 400
    response = client.post("/api/ai/chat", json={"message": "  "})
    check("ข้อความว่างถูกปฏิเสธ", response.status_code == 400, str(response.status_code))

    # mock การเรียก Anthropic
    captured: dict = {}

    def anthropic_handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("x-api-key")
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(200, json={
            "content": [
                {"type": "text", "text": "แนะนำให้เลือกคณะวิทยาศาสตร์ที่มีสายวิศวกรรมเป็นตัวเลือกด้านแรก"},
                {"type": "text", "text": "\n\n- เก็บ GPAX ให้ดี\n- ทำ Portfolio"},
            ],
        })

    original_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs["transport"] = mock_transport(anthropic_handler)
        return original_client(*args, **kwargs)

    httpx.AsyncClient = patched_client
    try:
        response = client.post("/api/ai/chat", json={
            "message": "ควรเลือกคณะอะไรดี",
            "model": "claude-sonnet-5-5",
            "history": [{"role": "user", "content": "สวัสดี"}, {"role": "assistant", "content": "หวัดดี"}],
        })
        check("ตอบ 200", response.status_code == 200, response.text[:200])
        data = response.json()
        check("configured = true", data["configured"] is True)
        check("ได้คำตอบ", "วิศวกรรม" in data["answer"], data.get("answer", "")[:80])
        check("ไม่มี error", not data.get("error"), str(data.get("error")))
        check("เรียก URL ถูก", "api.anthropic.com" in captured.get("url", ""), captured.get("url", ""))
        check("ส่ง API key", captured.get("auth") == "test-key")
        # Anthropic แยก system prompt ไว้ใน field "system" ไม่ใช่ใน messages
        check("ส่ง system prompt (field system)", '"system"' in captured.get("body", "") and "TCAS Buddy" in captured.get("body", ""))
        check("ส่งประวัติสนทนา", "สวัสดี" in captured.get("body", ""))
    finally:
        httpx.AsyncClient = original_client

    # ผู้ให้บริการล่ม → ต้องคืน error ที่อ่านเข้าใจ ไม่ใช่ 500
    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream boom")

    def patched_failing(*args, **kwargs):
        kwargs["transport"] = mock_transport(failing_handler)
        return original_client(*args, **kwargs)

    httpx.AsyncClient = patched_failing
    try:
        response = client.post("/api/ai/chat", json={"message": "ทดสอบ"})
        check("ผู้ให้บริการล่ม → ยังตอบ 200 พร้อม error", response.status_code == 200, str(response.status_code))
        check("มีข้อความแจ้ง error", bool(response.json().get("error")), str(response.json())[:120])
    finally:
        httpx.AsyncClient = original_client

    # ยังไม่ได้ตั้ง key → ต้องบอกว่าไม่พร้อม ไม่ใช่ error 500
    for key in saved:
        os.environ.pop(key, None)
        if saved.get(key):
            os.environ[key] = saved[key]
    # เอาคีย์ที่ตั้งไว้ในเครื่องออกชั่วคราว (เช่น GEMINI_API_KEY ที่ผู้ใช้ตั้งไว้)
    for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        os.environ.pop(key, None)
    ai_chat.detect_provider.cache_clear() if hasattr(ai_chat.detect_provider, "cache_clear") else None
    response = client.post("/api/ai/chat", json={"message": "ทดสอบ"})
    check("ยังไม่ได้ตั้ง key → บอกว่าไม่พร้อม", response.json().get("configured") is False, str(response.json())[:120])
    check("มีข้อความแนะนำ", bool(response.json().get("error")))

    # คืนค่าคีย์เดิม
    for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = saved.get(key)
        if value:
            os.environ[key] = value

    print("\n=== สรุป ===")
    if FAILURES:
        print(f"ไม่ผ่าน {len(FAILURES)} ข้อ:")
        for item in FAILURES:
            print("  -", item)
        return 1
    print("ผ่านทั้งหมด")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
