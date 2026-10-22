"""ทดสอบระบบกระทู้ + Ticket ด้วย repository จำลอง (ไม่ต้องต่อฐานข้อมูลจริง)

รัน: python tests/test_community_tickets.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402


class FakeRepo:
    """repository จำลองที่เก็บข้อมูลใน memory — เลียนแบบพฤติกรรม PostgREST ที่ใช้ในโค้ดจริง"""

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.next_id: dict[str, int] = {}
        self.configured = True
        self.auth_configured = True
        self.url = "https://fake.supabase.co"
        self.anon_key = "anon"
        self.service_key = "service"
        self.last_database_error: str | None = None
        self._column_cache: dict[str, bool] = {}
        self._role_column: str | None = "role"

    # --- helpers ใช้ในเทสต์ ---
    def _table(self, name: str) -> list[dict[str, Any]]:
        return self.tables.setdefault(name, [])

    def _match(self, row: dict[str, Any], params: dict[str, str]) -> bool:
        for key, value in params.items():
            if key in ("select", "order", "limit"):
                continue
            if key == "or":
                continue
            if key in ("open_id", "openId", "post_id", "ticket_id", "id", "admin_id", "code",
                       "name", "tc_uid", "tc_faculty_uid", "institution", "faculty", "round"):
                actual = str(row.get(key, ""))
                if value.startswith("eq."):
                    if actual != value[3:]:
                        return False
                elif value.startswith("is.null"):
                    if actual not in ("", None):
                        return False
                elif value.startswith("gt."):
                    if actual <= value[3:]:
                        return False
                elif value.startswith("ilike."):
                    pattern = value[6:].strip("*")
                    if pattern.lower() not in actual.lower():
                        return False
                elif value.startswith("in."):
                    allowed = value[3:].strip("(){}").split(",")
                    if actual not in allowed:
                        return False
        return True

    async def select(self, table: str, params: dict[str, str]) -> list[dict[str, Any]] | None:
        rows = [row for row in self._table(table) if self._match(row, params)]
        if "tags" in params and params["tags"].startswith("cs."):
            wanted = params["tags"][3:].strip("{}")
            rows = [row for row in rows if wanted in (row.get("tags") or [])]
        limit = int(params.get("limit", 1000))
        return rows[:limit]

    async def insert(self, table: str, payload: dict[str, Any]) -> bool:
        self._table(table).append(dict(payload))
        return True

    async def insert_returning(self, table: str, payload: dict[str, Any], on_conflict: str | None = None) -> dict[str, Any] | None:
        rows = self._table(table)
        if on_conflict and on_conflict in payload:
            for existing in rows:
                if existing.get(on_conflict) == payload[on_conflict]:
                    existing.update(payload)
                    return existing
        self.next_id[table] = self.next_id.get(table, 0) + 1
        record = {"id": self.next_id[table], **payload}
        rows.append(record)
        return record

    async def upsert(self, table: str, record: dict[str, Any], on_conflict: str) -> dict[str, Any] | None:
        rows = self._table(table)
        for existing in rows:
            if existing.get(on_conflict) == record.get(on_conflict):
                existing.update(record)
                return existing
        rows.append(dict(record))
        return record

    async def update(self, table: str, params: dict[str, str], record: dict[str, Any]) -> bool:
        for row in self._table(table):
            if self._match(row, params):
                row.update(record)
                return True
        return False

    async def delete(self, table: str, params: dict[str, str]) -> bool:
        rows = self._table(table)
        keep = [row for row in rows if not self._match(row, params)]
        self.tables[table] = keep
        return True

    async def column_exists(self, table: str, column: str) -> bool:
        rows = self._table(table)
        if not rows:
            return column in ("id", "open_id", "openId", "role", "is_admin")
        return column in rows[0]

    async def user_role_column(self) -> str:
        return "role"

    async def user_role(self, open_id: str) -> str | None:
        rows = await self.select("users", {"select": "name,role", "openId": f"eq.{open_id}", "limit": "1"})
        return rows[0].get("role") if rows else None

    async def _count(self, table: str, filters: dict[str, str] | None = None) -> int | None:
        rows = await self.select(table, filters or {"limit": "10000"})
        return len(rows or [])


FAILURES: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {extra}")
        FAILURES.append(label)


def make_repo() -> FakeRepo:
    repo = FakeRepo()
    repo.tables["users"] = [
        {"id": "u-admin", "openId": "u-admin", "name": "Amin", "role": "admin", "is_admin": True},
        {"id": "u-user", "openId": "u-user", "name": "น้องเอย", "role": "student", "is_admin": False},
    ]
    repo.tables["user_settings"] = [
        {"open_id": "u-user", "display_name": "น้องเอย", "avatar_key": "a01"},
    ]
    return repo


def main() -> int:
    repo = make_repo()
    import app.community as community_module
    import app.tickets as tickets_module
    import app.admin as admin_module
    from fastapi import FastAPI

    # mock require_user ในทุกโมดูล (เลียนแบบการล็อกอินด้วย header ในเทสต์)
    async def fake_require_user(request, repo_arg):
        header = request.headers.get("x-test-user", "u-user")
        return {"id": header, "email": f"{header}@example.com", "user_metadata": {"full_name": "ผู้ใช้ทดสอบ"}}

    async def fake_is_admin(r, uid, email=None):
        return uid == "u-admin"

    community_module.require_user = fake_require_user
    tickets_module.require_user = fake_require_user
    admin_module.require_user = fake_require_user
    community_module.is_admin = fake_is_admin
    tickets_module.is_admin = fake_is_admin
    admin_module.is_admin = fake_is_admin

    # สร้างแอปใหม่ที่ผูก router กับ repo จำลอง
    test_app = FastAPI()
    test_app.include_router(community_module.build_router(repo))
    test_app.include_router(tickets_module.build_router(repo))
    test_app.include_router(admin_module.build_router(repo))

    client = TestClient(test_app)
    print("\n=== ระบบกระทู้ชุมชน ===")
    tags = client.get("/api/community/tags")
    check("อ่านรายการ tag ได้", tags.status_code == 200 and len(tags.json()["items"]) > 0)

    created = client.post("/api/community/posts", json={
        "title": "ควรเลือกคณะอะไรดี?",
        "body": "ช่วยกันตัดสินใจหน่อย",
        "tags": ["TCAS", "คณะในฝัน", "แท็กใหม่"],
        "options": ["วิทยาศาสตร์", "วิศวกรรม", "วิทยาศาสตร์"],
    })
    check("สร้างกระทู้ได้", created.status_code == 201, created.text[:200])
    post = created.json()["post"]
    check("ตัด tag ซ้ำให้เหลือ 3 ตัว", len(post["tags"]) == 3, str(post.get("tags")))
    check("ตัวเลือกโพลถูกตัดซ้ำเหลือ 2", len(post["options"]) == 2, str([o["label"] for o in post.get("options", [])]))

    listed = client.get("/api/community/posts")
    check("แสดงรายการกระทู้ได้", listed.status_code == 200 and len(listed.json()["items"]) == 1)

    by_tag = client.get("/api/community/posts", params={"tag": "TCAS"})
    check("กรองตาม tag ได้", len(by_tag.json()["items"]) == 1)
    by_tag2 = client.get("/api/community/posts", params={"tag": "ไม่มีจริง"})
    check("กรอง tag ที่ไม่มีได้ 0 รายการ", len(by_tag2.json()["items"]) == 0)

    search = client.get("/api/community/posts", params={"q": "ตัดสินใจ"})
    check("ค้นหากระทู้ได้", len(search.json()["items"]) == 1)

    liked = client.post(f"/api/community/posts/{post['id']}/like")
    check("กดไลก์ได้", liked.status_code == 200 and liked.json()["liked"] is True)
    unliked = client.post(f"/api/community/posts/{post['id']}/like")
    check("กดไลก์ซ้ำ = ยกเลิก", unliked.json()["liked"] is False)

    option_id = post["options"][0]["id"]
    voted = client.post(f"/api/community/posts/{post['id']}/vote", json={"option_id": option_id})
    check("โหวตได้", voted.status_code == 200)
    voted2 = client.post(f"/api/community/posts/{post['id']}/vote", json={"option_id": post['options'][1]['id']})
    check("โหวตทับของเดิมได้", voted2.status_code == 200)
    after = client.get(f"/api/community/posts/{post['id']}").json()
    check("นับโหวตรวมได้ 1 คน", after["post"]["total_votes"] == 1, str(after["post"]["total_votes"]))

    comment = client.post(f"/api/community/posts/{post['id']}/comments", json={"body": "ช่วยด้วย!"})
    check("เพิ่มความคิดเห็นได้", comment.status_code == 201)
    check("นับความคิดเห็นถูกต้อง", client.get(f"/api/community/posts/{post['id']}").json()["post"]["comments_count"] == 1)
    check("ความคิดเห็นเก็บรูปโปรไฟล์", comment.json()["comment"].get("author_avatar") == "/static/assets/avatars/a01.jpg",
          str(comment.json()["comment"].get("author_avatar")))
    check("อ่านความคิดเห็นได้รูปโปรไฟล์",
          client.get(f"/api/community/posts/{post['id']}").json()["comments"][0].get("author_avatar") == "/static/assets/avatars/a01.jpg")

    empty_comment = client.post(f"/api/community/posts/{post['id']}/comments", json={"body": "  "})
    check("ความคิดเห็นว่างถูกปฏิเสธ", empty_comment.status_code == 400)

    no_title = client.post("/api/community/posts", json={"body": "ไม่มีหัวข้อ"})
    check("กระทู้ไม่มีหัวข้อถูกปฏิเสธ", no_title.status_code == 400)

    new_tag = client.post("/api/community/tags", json={"name": "#ทดสอบแท็ก"})
    check("สร้าง tag ใหม่ได้", new_tag.status_code == 200 and new_tag.json()["tag"]["name"] == "ทดสอบแท็ก")

    # tag ที่มีอักขระพิเศษของ PostgREST ต้องไม่ทำให้ query พัง
    weird = client.post("/api/community/posts", json={
        "title": "ทดสอบ tag พิเศษ", "body": "x", "tags": ["a,b(c)"],
    })
    check("tag ที่มีอักขระพิเศษสร้างได้", weird.status_code == 201, weird.text[:150])
    still_lists = client.get("/api/community/posts")
    check("ยังอ่านรายการกระทู้ได้หลังมี tag พิเศษ", still_lists.status_code == 200 and len(still_lists.json()["items"]) == 2)

    print("\n=== ระบบ Ticket ===")
    ticket = client.post("/api/tickets", json={"subject": "ล็อกอินไม่ได้", "body": "ช่วยด้วย", "category": "ปัญหาการใช้งาน"})
    check("เปิด Ticket ได้", ticket.status_code == 201, ticket.text[:200])
    ticket_id = ticket.json()["ticket"]["id"]
    check("ไม่มีแอดมิน -> ตอบ 'ยังไม่มีแอดมินอยู่ในขณะนี้'", ticket.json()["admin_online"] is False)

    messages = client.get(f"/api/tickets/{ticket_id}").json()["messages"]
    check("เก็บข้อความผู้ใช้ + ตอบอัตโนมัติ", len(messages) == 2, str([m["body"] for m in messages]))
    check("ข้อความระบบตอบถูกต้อง", messages[-1]["body"] == "ยังไม่มีแอดมินอยู่ในขณะนี้")

    replied = client.post(f"/api/tickets/{ticket_id}/messages", json={"body": "ยังไม่ได้เข้าใจ"})
    check("ผู้ใช้พิมพ์ต่อได้", replied.status_code == 201)
    check("ระบบตอบอัตโนมัติอีกครั้ง", len(replied.json()["replies"]) == 1)

    # แอดมินออนไลน์
    hb = client.post("/api/tickets/status/admin", headers={"x-test-user": "u-admin"})
    check("แอดมินส่ง heartbeat ได้", hb.status_code == 200, hb.text[:150])

    admin_tickets = client.get("/api/admin/tickets", headers={"x-test-user": "u-admin"})
    check("แอดมินเห็นคิว Ticket ได้", admin_tickets.status_code == 200 and len(admin_tickets.json()["items"]) == 1)

    reply = client.post(f"/api/admin/tickets/{ticket_id}/reply", headers={"x-test-user": "u-admin"}, json={"body": "เดี๋ยวช่วยดูให้นะ"})
    check("แอดมินตอบกลับได้", reply.status_code == 200)

    closed = client.post(f"/api/admin/tickets/{ticket_id}/status", headers={"x-test-user": "u-admin"}, json={"status": "closed"})
    check("แอดมินปิดตั๋วได้", closed.status_code == 200 and closed.json()["status"] == "closed")
    check("แอดมินปิดตั๋วแล้วข้อมูลถูกลบ", closed.json().get("purged") is True)

    print("\n=== ล้างข้อมูลตั๋วที่ปิดแล้ว ===")
    check("ข้อความถูกลบหมด", not repo.tables["ticket_messages"], str(repo.tables["ticket_messages"]))
    check("ตั๋วถูกลบหมด", not repo.tables["tickets"], str(repo.tables["tickets"]))
    gone = client.get(f"/api/tickets/{ticket_id}")
    check("เปิดตั๋วที่ปิดแล้วไม่ได้ (404)", gone.status_code == 404, str(gone.status_code))

    other = client.get(f"/api/tickets/{ticket_id}", headers={"x-test-user": "u-other"})
    check("อ่าน Ticket ของคนอื่นไม่ได้", other.status_code in (403, 404), str(other.status_code))

    print("\n=== สรุป ===")
    if FAILURES:
        print(f"ผ่าน {len(FAILURES)} ข้อที่ไม่ผ่าน:")
        for item in FAILURES:
            print("  -", item)
        return 1
    print("ผ่านทั้งหมด")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
