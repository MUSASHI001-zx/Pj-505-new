"""ทดสอบระบบหลังบ้านแอดมิน — ต้องมีสิทธิ์แอดมินเท่านั้นที่เข้าถึงได้

รัน: python tests/test_admin.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from tests.test_community_tickets import FakeRepo  # noqa: E402


def make_repo() -> FakeRepo:
    repo = FakeRepo()
    repo.tables["users"] = [
        {"id": "u-admin", "openId": "u-admin", "name": "Amin", "email": "amin@example.com", "role": "admin", "is_admin": True, "is_disabled": False, "lastSignedIn": "2026-10-20T10:00:00"},
        {"id": "u-user", "openId": "u-user", "name": "น้องเอย", "email": "user@example.com", "role": "student", "is_admin": False, "is_disabled": False, "lastSignedIn": "2026-10-21T09:00:00"},
        {"id": "u-guest", "openId": "u-guest", "name": "ผู้มาเยือน", "email": "guest@example.com", "role": "student", "is_admin": False, "is_disabled": False, "lastSignedIn": "2026-10-19T09:00:00"},
    ]
    repo.tables["user_settings"] = [
        {"open_id": "u-user", "display_name": "น้องเอย", "school": "โรงเรียนสุรนารีวิทยา", "grade_level": "ม.6", "interested_faculties": ["วิศวกรรมศาสตร์"]},
    ]
    repo.tables["community_posts"] = [
        {"id": 1, "open_id": "u-user", "author_name": "น้องเอย", "title": "กระทู้ทดสอบ", "body": "เนื้อหา", "tags": ["TCAS"], "created_at": "2026-10-20T10:00:00"},
    ]
    repo.tables["community_comments"] = [
        {"id": 1, "post_id": 1, "open_id": "u-guest", "author_name": "ผู้มาเยือน", "body": "ความคิดเห็นไม่สุภาพ", "created_at": "2026-10-20T11:00:00"},
    ]
    repo.tables["community_tags"] = [
        {"id": 1, "name": "TCAS", "color": "purple", "created_at": "2026-10-01T00:00:00"},
    ]
    repo.tables["institutions"] = [
        {"id": 1, "name": "จุฬาลงกรณ์มหาวิทยาลัย", "logoUrl": "https://x/1.png", "kind": "รัฐ", "city": "กรุงเทพฯ", "is_published": True},
    ]
    repo.tables["admissions"] = [
        {"id": 1, "institution": "จุฬาลงกรณ์มหาวิทยาลัย", "faculty": "วิศวกรรมศาสตร์", "round": "รอบ 1", "criteria": "ตามประกาศ", "source_url": "https://mytcas.com/x", "is_published": True},
    ]
    repo.tables["tickets"] = [
        {"id": 1, "open_id": "u-user", "subject": "ช่วยด้วย", "category": "ทั่วไป", "status": "open", "created_at": "2026-10-21T08:00:00", "updated_at": "2026-10-21T08:00:00"},
    ]
    repo.tables["ticket_messages"] = [
        {"id": 1, "ticket_id": 1, "sender_type": "user", "sender_name": "น้องเอย", "body": "ช่วยหน่อย", "created_at": "2026-10-21T08:00:00"},
    ]
    return repo


FAILURES: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {extra}")
        FAILURES.append(label)


def main() -> int:
    repo = make_repo()
    import app.admin as admin_module
    from app import auth as auth_module

    current_user = {"id": "u-admin"}

    async def fake_require_user(request, repo_arg):
        return {"id": current_user["id"], "email": f"{current_user['id']}@example.com", "user_metadata": {"full_name": "ผู้ดูแล"}}

    async def fake_is_admin(r, uid, email=None):
        return uid == "u-admin"

    admin_module.require_user = fake_require_user
    admin_module.is_admin = fake_is_admin

    # ให้ repo จำลองรองรับคอลัมน์ใหม่ของ migration 008
    async def column_exists(table: str, column: str) -> bool:
        rows = repo.tables.get(table) or []
        if not rows:
            return column in ("id", "open_id", "openId", "role", "is_admin", "is_disabled")
        return column in rows[0]

    repo.column_exists = column_exists  # type: ignore[method-assign]

    test_app = FastAPI()
    test_app.include_router(admin_module.build_router(repo))
    client = TestClient(test_app)

    print("\n=== สิทธิ์แอดมิน ===")
    current_user["id"] = "u-user"
    forbidden = client.get("/api/admin/users")
    check("ผู้ใช้ทั่วไปเรียก API แอดมินได้ = 403", forbidden.status_code == 403, str(forbidden.status_code))

    current_user["id"] = "u-admin"
    allowed = client.get("/api/admin/users")
    check("แอดมินเรียก API ได้", allowed.status_code == 200, allowed.text[:150])

    print("\n=== ผู้ใช้ & สิทธิ์ ===")
    users = allowed.json()["items"]
    check("อ่านรายชื่อผู้ใช้ได้", len(users) == 3, str(len(users)))
    found = next((item for item in users if item["open_id"] == "u-user"), None)
    check("แสดงชื่อที่ผู้ใช้ตั้งเอง", found and found["name"] == "น้องเอย", str(found and found["name"]))
    check("แสดงคณะที่สนใจ", found and found["faculties"] == ["วิศวกรรมศาสตร์"])
    check("นับกิจกรรมของผู้ใช้", found and found["posts"] == 1, str(found and found["posts"]))
    check("แสดงสถานะแอดมิน", any(item["is_admin"] for item in users))

    role = client.post("/api/admin/users/u-user/role", json={"role": "teacher"})
    check("เปลี่ยนบทบาทได้", role.status_code == 200 and role.json()["role"] == "teacher", role.text[:120])
    check("บทบาทถูกบันทึกจริง", repo.tables["users"][1].get("role") == "teacher", str(repo.tables["users"][1]))

    bad_role = client.post("/api/admin/users/u-user/role", json={"role": "hacker"})
    check("บทบาทผิดถูกปฏิเสธ", bad_role.status_code == 400)

    grant = client.post("/api/admin/users/u-guest/admin", json={"is_admin": True})
    check("แต่งตั้งสิทธิ์แอดมินได้", grant.status_code == 200 and grant.json()["is_admin"] is True, grant.text[:120])

    revoke = client.post("/api/admin/users/u-guest/admin", json={"is_admin": False})
    check("ถอดสิทธิ์แอดมินได้", revoke.status_code == 200 and revoke.json()["is_admin"] is False)

    self_revoke = client.post("/api/admin/users/u-admin/admin", json={"is_admin": False})
    check("ถอดสิทธิ์ตัวเองไม่ได้", self_revoke.status_code == 400, str(self_revoke.status_code))

    disable = client.post("/api/admin/users/u-guest/disabled", json={"is_disabled": True})
    check("ระงับบัญชีได้", disable.status_code == 200 and disable.json()["is_disabled"] is True)

    self_disable = client.post("/api/admin/users/u-admin/disabled", json={"is_disabled": True})
    check("ระงับบัญชีตัวเองไม่ได้", self_disable.status_code == 400)

    rename = client.post("/api/admin/users/u-guest/display-name", json={"display_name": "ชื่อใหม่"})
    check("ตั้งชื่อที่แสดงได้", rename.status_code == 200)
    settings = next((row for row in repo.tables["user_settings"] if row["open_id"] == "u-guest"), None)
    check("ชื่อใหม่ถูกบันทึก", settings and settings["display_name"] == "ชื่อใหม่")

    print("\n=== กระทู้ชุมชน (moderation) ===")
    posts = client.get("/api/admin/posts")
    check("อ่านกระทู้ทั้งหมดได้", posts.status_code == 200 and len(posts.json()["items"]) == 1)
    check("นับความคิดเห็น", posts.json()["items"][0]["comments"] == 1)

    comments = client.get("/api/admin/posts/1/comments")
    check("อ่านความคิดเห็นของกระทู้ได้", comments.status_code == 200 and len(comments.json()["items"]) == 1)

    del_comment = client.delete("/api/admin/comments/1")
    check("ลบความคิดเห็นได้", del_comment.status_code == 200)
    check("ความคิดเห็นถูกลบจริง", len(repo.tables["community_comments"]) == 0)

    del_post = client.delete("/api/admin/posts/1")
    check("ลบกระทู้ได้", del_post.status_code == 200)
    check("กระทู้ถูกลบจริง", len(repo.tables["community_posts"]) == 0)

    print("\n=== จัดการ tag ===")
    tags = client.get("/api/admin/tags")
    check("อ่านรายการ tag ได้", tags.status_code == 200 and len(tags.json()["items"]) == 1)
    check("นับจำนวนกระทู้ที่ใช้ tag", tags.json()["items"][0]["posts"] == 0, str(tags.json()["items"][0]))

    color = client.post("/api/admin/tags", json={"name": "TCAS", "color": "blue"})
    check("เปลี่ยนสี tag ได้", color.status_code == 200 and color.json()["color"] == "blue")

    new_tag = client.post("/api/admin/tags", json={"name": "ใหม่", "color": "teal"})
    check("สร้าง tag ใหม่ได้", new_tag.status_code == 200)

    # tag ถูกถอดออกจากกระทู้ที่ใช้
    repo.tables["community_posts"] = [
        {"id": 5, "open_id": "u-user", "author_name": "x", "title": "t", "body": "b", "tags": ["TCAS", "อื่น"], "created_at": "2026-10-20"},
    ]
    del_tag = client.delete("/api/admin/tags/TCAS")
    check("ลบ tag ได้", del_tag.status_code == 200)
    check("ถอด tag ออกจากกระทู้", "TCAS" not in repo.tables["community_posts"][0]["tags"], str(repo.tables["community_posts"][0]["tags"]))

    print("\n=== มหาวิทยาลัย + เกณฑ์รับ ===")
    inst = client.get("/api/admin/institutions")
    check("อ่านรายชื่อมหาวิทยาลัยได้", inst.status_code == 200 and len(inst.json()["items"]) == 1)

    created_inst = client.post("/api/admin/institutions", json={"name": "มหาวิทยาลัยใหม่", "kind": "รัฐ", "city": "เชียงใหม่"})
    check("เพิ่มมหาวิทยาลัยได้", created_inst.status_code == 200, created_inst.text[:150])
    check("มหาวิทยาลัยถูกเพิ่มจริง", any(row["name"] == "มหาวิทยาลัยใหม่" for row in repo.tables["institutions"]))

    no_name = client.post("/api/admin/institutions", json={"kind": "รัฐ"})
    check("มหาวิทยาลัยไม่มีชื่อถูกปฏิเสธ", no_name.status_code == 400)

    update_inst = client.put("/api/admin/institutions/1", json={"city": "กรุงเทพฯ", "is_published": False})
    check("แก้ไขมหาวิทยาลัยได้", update_inst.status_code == 200)
    check("การซ่อนถูกบันทึก", repo.tables["institutions"][0]["is_published"] is False)

    adm = client.get("/api/admin/admissions")
    check("อ่านรายการรับสมัครได้", adm.status_code == 200 and len(adm.json()["items"]) == 1)

    created_adm = client.post("/api/admin/admissions", json={
        "institution": "มหาวิทยาลัยใหม่", "faculty": "วิทยาศาสตร์", "round": "รอบ 2",
        "criteria": "ตามประกาศ", "source_url": "https://mytcas.com/y",
    })
    check("เพิ่มเกณฑ์รับได้", created_adm.status_code == 200, created_adm.text[:150])

    missing = client.post("/api/admin/admissions", json={"institution": "x"})
    check("เกณฑ์รับข้อมูลไม่ครบถูกปฏิเสธ", missing.status_code == 400)

    del_adm = client.delete("/api/admin/admissions/1")
    check("ลบเกณฑ์รับได้", del_adm.status_code == 200)

    print("\n=== คิว Ticket ===")
    tickets = client.get("/api/admin/tickets")
    check("อ่านคิว Ticket ได้", tickets.status_code == 200 and len(tickets.json()["items"]) == 1)
    check("นับสถานะ Ticket ได้", tickets.json()["counts"]["open"] == 1)

    detail = client.get("/api/admin/tickets/1")
    check("เปิดดู Ticket ได้", detail.status_code == 200 and len(detail.json()["messages"]) == 1)
    check("เห็นข้อมูลเจ้าของ Ticket", detail.json()["user"].get("email") == "user@example.com")

    reply = client.post("/api/admin/tickets/1/reply", json={"body": "เดี๋ยวช่วยดู"})
    check("ตอบกลับได้", reply.status_code == 200, reply.text[:150])
    check("สถานะเปลี่ยนเป็น 'ตอบแล้ว'", repo.tables["tickets"][0]["status"] == "answered", repo.tables["tickets"][0]["status"])

    close = client.post("/api/admin/tickets/1/status", json={"status": "closed"})
    check("ปิดตั๋วได้", close.status_code == 200 and close.json()["status"] == "closed")

    bad_status = client.post("/api/admin/tickets/1/status", json={"status": "deleted"})
    check("สถานะผิดถูกปฏิเสธ", bad_status.status_code == 400)

    print("\n=== ภาพรวม + บันทึกการทำงาน ===")
    stats = client.get("/api/admin/stats")
    check("อ่านสถิติได้", stats.status_code == 200, stats.text[:150])
    check("นับผู้ใช้ถูก", stats.json()["users"] == 3, str(stats.json().get("users")))
    check("แยกผู้ใช้ตามบทบาท", "student" in stats.json()["users_by_role"])

    audit = client.get("/api/admin/audit")
    check("อ่านบันทึกการทำงานได้", audit.status_code == 200)
    check("มีบันทึกการกระทำ", len(audit.json()["items"]) > 0, str(len(audit.json()["items"])))
    check("บันทึกมีชื่อผู้ทำ", all(item.get("action") for item in audit.json()["items"]))

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
