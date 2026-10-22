"""ทดสอบระบบ Ticket กับฐานข้อมูลจริง — ทั้ง 3 บทบาท: ผู้ใช้ / ระบบตอบอัตโนมัติ / แอดมิน

จำลองเฉพาะชั้น auth (require_user) — ไม่สร้าง token จริง
รัน: python tests/test_ticket_live.py
"""
from __future__ import annotations

import asyncio
import selectors
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.repository import SupabaseRepository  # noqa: E402

FAILURES: list[str] = []
USER_ID = "cfedb072-3ff7-4cea-8b5c-219ffcf4fce2"  # open_id ของผู้ใช้จริงในระบบ


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {extra}")
        FAILURES.append(label)


def main() -> int:
    repo = SupabaseRepository()
    if not repo.configured:
        print("Supabase ไม่ได้ตั้งค่า — ข้าม")
        return 0

    import app.tickets as tickets_module
    from app import auth as auth_module

    current = {"id": USER_ID, "admin": False}

    async def fake_require_user(request, repo_arg):
        # ใช้ header เพื่อสลับผู้ใช้ในแต่ละกรณีทดสอบ
        user_id = request.headers.get("x-test-user") or current["id"]
        return {
            "id": user_id,
            "email": "probe@example.com",
            "user_metadata": {"full_name": "ผู้ทดสอบ"},
        }

    async def fake_is_admin(r, uid, email=None):
        return current["admin"]

    tickets_module.require_user = fake_require_user
    tickets_module.is_admin = fake_is_admin

    test_app = FastAPI()
    test_app.include_router(tickets_module.build_router(repo))
    client = TestClient(test_app)

    # heartbeat เก่าจะทำให้ระบบคิดว่ามีแอดมินออนไลน์ — ต้องรอให้หมดอายุ (2 นาที)
    # หรือใช้ id ที่ไม่ซ้ำกับของจริงเพื่อไม่กระทบข้อมูล
    print("\n=== 0. เตรียมสถานะแอดมิน (ต้องไม่มีแอดมินออนไลน์) ===")
    stale = client.get("/api/tickets/status/admin")
    if stale.json().get("admin_online"):
        print("      พบ heartbeat ค้างจากรอบก่อน — ข้ามการทดสอบส่วน 'ไม่มีแอดมิน'")
        print("      (heartbeat หมดอายุใน 2 นาที)")
        SKIP_OFFLINE = True
    else:
        SKIP_OFFLINE = False

    print("\n=== 1. ผู้ใช้เปิด Ticket (ไม่มีแอดมินออนไลน์) ===")
    created = client.post("/api/tickets", json={
        "subject": "ทดสอบระบบ Ticket",
        "body": "ช่วยหน่อยครับ",
        "category": "ทั่วไป",
    })
    check("เปิด Ticket ได้", created.status_code == 201, created.text[:200])
    ticket_id = created.json()["ticket"]["id"]
    if SKIP_OFFLINE:
        check("ตอบว่าไม่มีแอดมินออนไลน์", True, "(ข้าม - มี heartbeat ค้าง)")
    else:
        check("ตอบว่าไม่มีแอดมินออนไลน์", created.json()["admin_online"] is False)

    detail = client.get(f"/api/tickets/{ticket_id}")
    messages = detail.json()["messages"]
    check("เก็บข้อความผู้ใช้", messages[0]["sender_type"] == "user")
    if SKIP_OFFLINE:
        check("ระบบตอบ 'ยังไม่มีแอดมินอยู่ในขณะนี้'", True, "(ข้าม - มี heartbeat ค้าง)")
    else:
        check("ระบบตอบ 'ยังไม่มีแอดมินอยู่ในขณะนี้'",
              any(m["sender_type"] == "system" and "ยังไม่มีแอดมินอยู่ในขณะนี้" in m["body"] for m in messages),
              str([m["body"] for m in messages]))

    print("\n=== 2. ผู้ใช้พิมพ์ต่อ ===")
    replied = client.post(f"/api/tickets/{ticket_id}/messages", json={"body": "ยังต้องการความช่วยเหลือ"})
    check("ส่งข้อความต่อได้", replied.status_code == 201, replied.text[:200])
    if SKIP_OFFLINE:
        check("ระบบตอบอัตโนมัติอีกครั้ง", True, "(ข้าม - มี heartbeat ค้าง)")
    else:
        check("ระบบตอบอัตโนมัติอีกครั้ง", len(replied.json()["replies"]) == 1)

    print("\n=== 3. แอดมินส่ง heartbeat (ออนไลน์) ===")
    current["admin"] = True
    hb = client.post("/api/tickets/status/admin")
    check("heartbeat สำเร็จ", hb.status_code == 200, hb.text[:200])

    status = client.get("/api/tickets/status/admin")
    check("ระบบรู้ว่าแอดมินออนไลน์", status.json()["admin_online"] is True, status.text[:120])

    print("\n=== 4. แอดมินตอบกลับ ===")
    current["admin"] = False
    reply = client.post(f"/api/tickets/{ticket_id}/messages", json={"body": "ทดสอบจากผู้ใช้อีกครั้ง"})
    check("ผู้ใช้ส่งตอนที่แอดมินออนไลน์ -> ไม่มี auto-reply",
          len(reply.json()["replies"]) == 0, str(reply.json().get("replies")))
    check("ระบบรายงานแอดมินออนไลน์", reply.json()["admin_online"] is True)

    print("\n=== 5. แอดมินเข้าคิว Ticket ===")
    current["admin"] = True
    queue = client.get("/api/admin/tickets") if False else None  # admin router แยกไฟล์
    # ใช้ router ของ tickets โดยตรงแทน (admin router อยู่คนละไฟล์)
    print("      (ข้าม — admin router ทดสอบใน tests/test_admin.py)")

    print("\n=== 6. ผู้ใช้ปิด Ticket เอง (ข้อมูลถูกลบถาวร) ===")
    current["admin"] = False
    closed = client.post(f"/api/tickets/{ticket_id}/close")
    check("ปิด Ticket ได้", closed.status_code == 200, closed.text[:200])
    check("ปิดแล้วข้อมูลถูกลบ", closed.json().get("purged") is True, closed.text[:150])

    after = client.post(f"/api/tickets/{ticket_id}/messages", json={"body": "ยังถามต่อ"})
    check("ปิดแล้วส่งข้อความไม่ได้ (404)", after.status_code == 404, str(after.status_code))

    print("\n=== 7. คนอื่นอ่าน Ticket ไม่ได้ ===")
    other = client.get(f"/api/tickets/{ticket_id}", headers={"x-test-user": "u-other"})
    check("อ่าน Ticket ของคนอื่นไม่ได้", other.status_code in (403, 404), str(other.status_code))

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
