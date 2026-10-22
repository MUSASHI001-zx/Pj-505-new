"""ตรวจระบบหลังบ้านกับฐานข้อมูลจริง — จำลองเฉพาะชั้น auth (ไม่สร้าง token จริง)

ใช้ค่า .env ของโปรเจกต์ จึงต้องรัน migration 008 ก่อนถึงจะได้ผลเต็ม
รัน: python tests/test_admin_live.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.repository import SupabaseRepository  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {extra}")
        FAILURES.append(label)


def main() -> int:
    repo = SupabaseRepository()
    if not repo.configured:
        print("Supabase ไม่ได้ตั้งค่า — ข้ามการทดสอบ")
        return 0

    import app.admin as admin_module

    async def fake_require_user(request, repo_arg):
        return {"id": "u-admin-test", "email": "admin.test@example.com", "user_metadata": {"full_name": "ผู้ดูแลทดสอบ"}}

    async def fake_is_admin(r, uid, email=None):
        return True

    admin_module.require_user = fake_require_user
    admin_module.is_admin = fake_is_admin

    test_app = FastAPI()
    test_app.include_router(admin_module.build_router(repo))

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await repo.aclose()

    test_app.router.lifespan_context = lifespan
    client = TestClient(test_app)

    print("\n=== ข้อมูลจริง: ผู้ใช้ ===")
    users = client.get("/api/admin/users?limit=5")
    check("อ่านรายชื่อผู้ใช้จริงได้", users.status_code == 200, users.text[:200])
    if users.status_code == 200:
        items = users.json()["items"]
        check("พบผู้ใช้ในระบบ", len(items) > 0, str(len(items)))
        check("แต่ละรายการมี open_id", all(item.get("open_id") for item in items))
        check("แต่ละรายการมี role", all(item.get("role") for item in items))
        print(f"      (ผู้ใช้ {users.json()['total']} คน, ตัวอย่าง: {items[0]['name'] if items else '-'})")

    print("\n=== ข้อมูลจริง: มหาวิทยาลัย ===")
    inst = client.get("/api/admin/institutions?limit=5")
    check("อ่านมหาวิทยาลัยจริงได้", inst.status_code == 200, inst.text[:200])
    if inst.status_code == 200:
        items = inst.json()["items"]
        check("พบมหาวิทยาลัยในระบบ", len(items) > 0, str(len(items)))
        print(f"      (มหาวิทยาลัย {len(items)} แห่ง, ตัวอย่าง: {items[0].get('name') if items else '-'})")

    print("\n=== ข้อมูลจริง: tag กระทู้ ===")
    tags = client.get("/api/admin/tags")
    check("อ่าน tag ได้", tags.status_code == 200, tags.text[:200])

    print("\n=== ข้อมูลจริง: Ticket ===")
    tickets = client.get("/api/admin/tickets")
    check("อ่านคิว Ticket ได้", tickets.status_code == 200, tickets.text[:200])

    print("\n=== ข้อมูลจริง: ภาพรวม ===")
    stats = client.get("/api/admin/stats")
    check("อ่านสถิติได้", stats.status_code == 200, stats.text[:250])
    if stats.status_code == 200:
        data = stats.json()
        print(f"      ผู้ใช้={data.get('users')} กระทู้={data.get('posts')} "
              f"views={data.get('views')} online={data.get('online')} ticket={data.get('tickets')}")

    print("\n=== ข้อมูลจริง: บันทึกการทำงาน ===")
    audit = client.get("/api/admin/audit")
    check("อ่าน audit ได้", audit.status_code == 200, audit.text[:200])

    print("\n=== สรุป ===")
    if FAILURES:
        print(f"ไม่ผ่าน {len(FAILURES)} ข้อ:")
        for item in FAILURES:
            print("  -", item)
        print("\nหมายเหตุ: ข้อความข้างบนจะระบุว่าต้องรัน migration ไหน (007 = กระทู้/Ticket, 008 = หลังบ้าน)")
        return 1
    print("ผ่านทั้งหมด")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
