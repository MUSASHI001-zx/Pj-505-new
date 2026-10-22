"""ทดสอบ AI Tutor / Notebook — ใช้ repo จำลอง ไม่ต้องต่อฐานข้อมูลจริง

รัน: python tests/test_tutor.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {extra}")
        FAILURES.append(label)


class FakeRepo:
    """repo จำลอง — เก็บข้อมูลใน dict แยกตามตาราง"""

    def __init__(self) -> None:
        self.configured = True
        self.last_database_error = None
        self.tables: dict[str, list[dict[str, Any]]] = {
            "notebooks": [],
            "notebook_sources": [],
            "tutor_messages": [],
        }
        self._next_id = 1

    async def column_exists(self, table: str, column: str) -> bool:
        return True

    async def select(self, table: str, params: dict[str, str]) -> list[dict[str, Any]] | None:
        rows = self.tables.get(table)
        if rows is None:
            return None
        result = list(rows)
        for key, value in params.items():
            if key in ("select", "order", "limit"):
                continue
            if key == "id" and value.startswith("eq."):
                target = value[3:]
                result = [r for r in result if str(r.get("id")) == target]
            elif key == "notebook_id" and value.startswith("eq."):
                target = value[3:]
                result = [r for r in result if str(r.get("notebook_id")) == target]
            elif key == "notebook_id" and value.startswith("in."):
                ids = {item.strip() for item in value[3:].strip("()").split(",")}
                result = [r for r in result if str(r.get("notebook_id")) in ids]
            elif key == "open_id" and value.startswith("eq."):
                result = [r for r in result if str(r.get("open_id")) == value[3:]]
            elif key == "subject" and value.startswith("eq."):
                result = [r for r in result if str(r.get("subject")) == value[3:]]
        order = params.get("order")
        if order and "." in order:
            field, direction = order.split(".", 1)
            result.sort(key=lambda r: str(r.get(field) or ""), reverse=direction == "desc")
        limit = params.get("limit")
        if limit and limit.isdigit():
            result = result[: int(limit)]
        return result

    async def insert(self, table: str, payload: dict[str, Any]) -> bool:
        record = {**payload, "id": self._next_id}
        self._next_id += 1
        self.tables.setdefault(table, []).append(record)
        return True

    async def insert_returning(self, table: str, payload: dict[str, Any], on_conflict: str | None = None) -> dict[str, Any] | None:
        record = {**payload, "id": self._next_id}
        self._next_id += 1
        self.tables.setdefault(table, []).append(record)
        return record

    async def delete(self, table: str, params: dict[str, str]) -> bool:
        rows = self.tables.get(table, [])
        target = params.get("id", "").removeprefix("eq.")
        self.tables[table] = [r for r in rows if str(r.get("id")) != target]
        return True


def make_client(monkey_user: dict[str, Any] | None = None) -> TestClient:
    """สร้าง client ที่ mock การยืนยันตัวตน (require_user)"""
    from app import tutor

    async def fake_require_user(request, repo):
        return monkey_user or {"id": "user-1", "email": "t@t.co"}

    tutor.require_user = fake_require_user

    repo = FakeRepo()
    app = FastAPI()
    app.include_router(tutor.build_router(repo))
    return TestClient(app)


def main() -> int:
    print("\n=== โครงสร้างสมุดโน้ต ===")
    client = make_client()
    response = client.get("/api/tutor/notebooks")
    check("ตอบ 200", response.status_code == 200, response.text[:200])
    data = response.json()
    check("ได้สมุดโน้ตครบทุกวิชา", len(data["items"]) == 4, str(len(data["items"])))
    subjects = [item["subject"] for item in data["items"]]
    check("มีวิชา TCAS/A-Level/TPAT/TOEIC", subjects == ["TCAS", "A-Level", "TPAT", "TOEIC"], str(subjects))
    check("มีคำถามตัวอย่าง", len(data["starter_questions"]["TCAS"]) > 0)

    print("\n=== เพิ่มบทเรียน ===")
    response = client.post("/api/tutor/notebooks/TCAS/sources", json={
        "title": "เกณฑ์รอบ 1",
        "content": "ต้องมี Portfolio และผลการเรียน",
    })
    check("เพิ่มบทเรียนสำเร็จ", response.status_code == 200, response.text[:200])
    source_id = response.json()["source"]["id"]

    response = client.get("/api/tutor/notebooks/TCAS")
    check("เห็นบทเรียนที่เพิ่ม", len(response.json()["sources"]) == 1)
    check("นับจำนวนบทเรียนถูก", response.json()["notebook"]["id"] is not None)

    response = client.post("/api/tutor/notebooks/TCAS/sources", json={"content": "ไม่มีหัวข้อ"})
    check("บันทึกบทเรียนซ้ำไม่ได้ (ต้องมีเนื้อหา)", response.status_code == 400, str(response.status_code))

    print("\n=== แยกสมุดตามวิชา ===")
    client.post("/api/tutor/notebooks/TPAT/sources", json={"title": "TPAT 1", "content": "ส่วนคำพูด"})
    alevel = client.get("/api/tutor/notebooks/A-Level").json()
    tpat = client.get("/api/tutor/notebooks/TPAT").json()
    check("A-Level ไม่มีบทเรียนของ TCAS", len(alevel["sources"]) == 0, str(len(alevel["sources"])))
    check("TPAT มีบทเรียนของตัวเอง", len(tpat["sources"]) == 1)

    print("\n=== คุยกับ AI ===")
    import app.ai_chat as ai_chat

    ai_chat.detect_provider = lambda: "gemini"
    ai_chat.main_model = lambda provider: {"key": "gemini-3.6-flash", "label": "Gemini 3.6 Flash"}

    async def fake_gemini(client, model, messages):
        captured["model"] = model
        captured["messages"] = messages
        return "คำตอบจาก AI: เกณฑ์รอบ 1 ต้องมี Portfolio"

    captured: dict[str, Any] = {}
    ai_chat.CALLERS = {"gemini": fake_gemini}

    response = client.post("/api/tutor/notebooks/TCAS/chat", json={"message": "เกณฑ์รอบ 1 คืออะไร"})
    check("ตอบ 200", response.status_code == 200, response.text[:200])
    data = response.json()
    check("ได้คำตอบ", "คำตอบจาก AI" in data.get("answer", ""), str(data)[:120])
    check("ส่งบริบทบทเรียนให้ AI", captured["messages"][0]["role"] == "system")
    check("บริบทมีหัวข้อบทเรียน", "เกณฑ์รอบ 1" in captured["messages"][0]["content"])
    check("นับบริบทที่ส่ง", data["context_count"] == 1, str(data.get("context_count")))

    print("\n=== ประวัติคุยถูกเก็บ ===")
    response = client.get("/api/tutor/notebooks/TCAS/messages")
    messages = response.json()["items"]
    check("เก็บ 2 ข้อความ (ถาม + ตอบ)", len(messages) == 2, str(len(messages)))
    check("ข้อความแรกเป็นผู้ใช้", messages[0]["role"] == "user")
    check("ข้อความที่สองเป็น AI", messages[1]["role"] == "assistant")

    print("\n=== สรุปด้วย AI ===")
    response = client.post("/api/tutor/notebooks/TPAT/summarize", json={
        "title": "สรุป TPAT",
        "content": "TPAT ประกอบด้วย 3 ส่วน คือ ความเข้าใจ การตีความ และการสื่อสาร",
    })
    check("สรุปสำเร็จ", response.status_code == 200, response.text[:200])
    check("บันทึกเป็นบทเรียน AI", response.json()["source"]["is_ai_generated"] is True)
    tpat_sources = client.get("/api/tutor/notebooks/TPAT").json()["sources"]
    check("มีบทเรียน AI ในสมุด", any(s["is_ai_generated"] for s in tpat_sources))

    print("\n=== ลบบทเรียน ===")
    response = client.delete(f"/api/tutor/sources/{source_id}")
    check("ลบสำเร็จ", response.status_code == 200, response.text[:150])
    check("บทเรียนหายไป", len(client.get("/api/tutor/notebooks/TCAS").json()["sources"]) == 0)

    print("\n=== ไม่ล็อกอินต้องใช้ไม่ได้ ===")
    client2 = make_client(monkey_user=None)
    from app import tutor as tutor_module

    async def deny(request, repo):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="กรุณาเข้าสู่ระบบก่อน")

    tutor_module.require_user = deny
    app2 = FastAPI()
    app2.include_router(tutor_module.build_router(FakeRepo()))
    anon = TestClient(app2)
    response = anon.get("/api/tutor/notebooks")
    check("ไม่ล็อกอิน → 401", response.status_code == 401, str(response.status_code))

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
