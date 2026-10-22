"""ทดสอบเครื่องมือของ AI ที่ปรึกษา — ใช้ mock provider ไม่ต้องต่อเน็ตจริง

รัน: python tests/test_ai_tools.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {extra}")
        FAILURES.append(label)


def mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def main() -> int:
    import app.ai_chat as ai_chat
    from app.ai_tools import (
        TOOL_DEFINITIONS,
        parse_tool_call,
        run_tool,
        to_anthropic_tools,
        to_gemini_tools,
        to_openai_tools,
    )

    print("\n=== นิยามเครื่องมือ ===")
    names = {tool["name"] for tool in TOOL_DEFINITIONS}
    check("มี search_programs", "search_programs" in names)
    check("มี search_admissions", "search_admissions" in names)
    check("มี search_scholarships", "search_scholarships" in names)
    check("มี search_news", "search_news" in names)
    check("มี list_universities", "list_universities" in names)
    check("ทุกเครื่องมือมีคำอธิบาย", all(tool["description"] for tool in TOOL_DEFINITIONS))
    check("ทุกเครื่องมือมี parameters", all("parameters" in tool for tool in TOOL_DEFINITIONS))

    print("\n=== แปลงเป็นรูปแบบของแต่ละเจ้า ===")
    openai_tools = to_openai_tools()
    check("OpenAI: type=function", all(t["type"] == "function" for t in openai_tools))
    check("OpenAI: มี function.name", all("name" in t["function"] for t in openai_tools))
    gemini_tools = to_gemini_tools()
    check("Gemini: functionDeclarations", "functionDeclarations" in gemini_tools[0])
    check("Gemini: มีชื่อฟังก์ชัน", all("name" in d for d in gemini_tools[0]["functionDeclarations"]))
    anthropic_tools = to_anthropic_tools()
    check("Anthropic: input_schema", all("input_schema" in t for t in anthropic_tools))

    print("\n=== แปลงคำตอบที่มีการเรียกเครื่องมือ ===")
    openai_payload = {
        "choices": [{
            "message": {
                "tool_calls": [{
                    "id": "call_1",
                    "function": {"name": "search_programs", "arguments": json.dumps({"query": "วิศวกรรม"})},
                }],
            },
        }],
    }
    call = parse_tool_call("openai", openai_payload)
    check("OpenAI: อ่าน tool_call ได้", call is not None and call[0] == "search_programs", str(call))
    check("OpenAI: อ่าน arguments ได้", call and call[1].get("query") == "วิศวกรรม")

    gemini_payload = {
        "candidates": [{
            "content": {"parts": [{"functionCall": {"name": "search_news", "args": {"query": "portfolio"}}}]},
        }],
    }
    call = parse_tool_call("gemini", gemini_payload)
    check("Gemini: อ่าน functionCall ได้", call is not None and call[0] == "search_news", str(call))

    anthropic_payload = {
        "content": [{"type": "tool_use", "id": "tu_1", "name": "search_scholarships", "input": {"query": "ทุน"}}],
    }
    call = parse_tool_call("anthropic", anthropic_payload)
    check("Anthropic: อ่าน tool_use ได้", call is not None and call[0] == "search_scholarships", str(call))

    check("ไม่มี tool_call → None", parse_tool_call("openai", {"choices": [{"message": {"content": "hi"}}]}) is None)

    print("\n=== เรียกเครื่องมือที่ไม่มีอยู่ ===")
    result = await run_tool("ไม่มีเครื่องมือนี้", {})
    check("แจ้งว่าไม่รู้จัก", "ไม่รู้จักเครื่องมือ" in result, result)

    print("\n=== loop การเรียกเครื่องมือ (Gemini) ===")
    calls: list[dict[str, Any]] = []

    def gemini_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        calls.append(body)
        if len(calls) == 1:
            # รอบแรก — ขอเรียกเครื่องมือ
            return httpx.Response(200, json={
                "candidates": [{
                    "content": {"parts": [{"functionCall": {"name": "search_programs", "args": {"query": "วิศวกรรม"}}}]},
                }],
            })
        # รอบสอง — ตอบจริงหลังได้ผลจากเครื่องมือ
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": "คณะวิศวกรรมศาสตร์ ค่าเล่าเรียนภาคละ 25,500 บาท"}]}}],
        })

    async with httpx.AsyncClient(transport=mock_transport(gemini_handler)) as client:
        answer = await ai_chat._call_gemini(
            client, "gemini-3.6-flash",
            [{"role": "user", "content": "ค่าเล่าเรียนวิศวกรรมศาสตร์เท่าไหร่?"}],
        )

    check("เรียก provider 2 รอบ", len(calls) == 2, str(len(calls)))
    check("รอบแรกส่ง tools ไป", "tools" in calls[0], str(list(calls[0].keys())))
    check("รอบแรกมี functionDeclarations", "functionDeclarations" in calls[0].get("tools", [{}])[0])
    check("รอบสองส่งผลเครื่องมือกลับ", "functionResponse" in json.dumps(calls[1].get("contents", [])), json.dumps(calls[1].get("contents", []))[:120])
    check("ได้คำตอบสุดท้าย", "25,500" in answer, answer[:80])

    print("\n=== loop การเรียกเครื่องมือ (OpenAI) ===")
    openai_calls: list[dict[str, Any]] = []

    def openai_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        openai_calls.append(body)
        if len(openai_calls) == 1:
            return httpx.Response(200, json={
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "search_news", "arguments": json.dumps({"query": "portfolio"})},
                        }],
                    },
                }],
            })
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "พบข่าว Portfolio 3 ข่าว"}}],
        })

    async with httpx.AsyncClient(transport=mock_transport(openai_handler)) as client:
        answer = await ai_chat._call_openai(
            client, "gpt-6.1-sol",
            [{"role": "user", "content": "ข่าว portfolio ล่าสุด"}],
        )

    check("เรียก provider 2 รอบ", len(openai_calls) == 2, str(len(openai_calls)))
    check("รอบแรกส่ง tools ไป", "tools" in openai_calls[0])
    check("รอบสองส่ง role=tool", any(m.get("role") == "tool" for m in openai_calls[1].get("messages", [])))
    check("ได้คำตอบสุดท้าย", "ข่าว" in answer, answer[:80])

    print("\n=== สรุป ===")
    if FAILURES:
        print(f"ไม่ผ่าน {len(FAILURES)} ข้อ:")
        for item in FAILURES:
            print("  -", item)
        return 1
    print("ผ่านทั้งหมด")
    return 0


if __name__ == "__main__":
    import asyncio
    raise SystemExit(asyncio.run(main()))
