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
        # True = มี view สรุปยอด (migration 014 แล้ว) / False = ยังไม่รัน (โค้ดสำรอง)
        self.use_views = True
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

    async def select(self, table: str, params: dict[str, str], quiet: bool = False) -> list[dict[str, Any]] | None:
        # เลียนแบบ PostgREST: อ่านตาราง/view ที่ไม่มีอยู่ = error (None) ไม่ใช่รายการว่าง
        if table not in self.tables:
            return None
        rows = [row for row in self._table(table) if self._match(row, params)]
        if "tags" in params and params["tags"].startswith("cs."):
            wanted = params["tags"][3:].strip("{}")
            rows = [row for row in rows if wanted in (row.get("tags") or [])]
        limit = int(params.get("limit", 1000))
        return rows[:limit]

    async def insert(self, table: str, payload: dict[str, Any]) -> bool:
        self._table(table).append(dict(payload))
        self._refresh_views()
        return True

    async def insert_returning(self, table: str, payload: dict[str, Any], on_conflict: str | None = None) -> dict[str, Any] | None:
        rows = self._table(table)
        if on_conflict and on_conflict in payload:
            for existing in rows:
                if existing.get(on_conflict) == payload[on_conflict]:
                    existing.update(payload)
                    self._refresh_views()
                    return existing
        self.next_id[table] = self.next_id.get(table, 0) + 1
        record = {"id": self.next_id[table], **payload}
        rows.append(record)
        self._refresh_views()
        return record

    async def upsert(self, table: str, record: dict[str, Any], on_conflict: str) -> dict[str, Any] | None:
        """upsert ตามคอลัมน์ประกอบ (รองรับ on_conflict หลายคอลัมน์คั่นด้วยจุลภาค)"""
        rows = self._table(table)
        keys = [part.strip() for part in on_conflict.split(",") if part.strip()]
        for existing in rows:
            if all(existing.get(key) == record.get(key) for key in keys):
                existing.update(record)
                self._refresh_views()
                return existing
        rows.append(dict(record))
        self._refresh_views()
        return record

    async def update(self, table: str, params: dict[str, str], record: dict[str, Any]) -> bool:
        for row in self._table(table):
            if self._match(row, params):
                row.update(record)
                self._refresh_views()
                return True
        return False

    async def delete(self, table: str, params: dict[str, str]) -> bool:
        rows = self._table(table)
        keep = [row for row in rows if not self._match(row, params)]
        self.tables[table] = keep
        self._refresh_views()
        return True

    def _refresh_views(self) -> None:
        """อัปเดต view สรุปยอดให้ตรงกับข้อมูล (ถ้าเปิดใช้ view ไว้)"""
        if self.use_views:
            rebuild_views(self)

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
    # ตาราง community ที่ระบบใช้ (ถ้าไม่มีจะถูกมองว่า "ยังไม่ได้รัน migration")
    for name in ("community_tags", "community_posts", "community_post_options",
                 "community_comments", "community_post_likes", "community_post_votes"):
        repo.tables[name] = []
    # tag เริ่มต้น (ตามที่ migration 007 seed ไว้)
    repo.tables["community_tags"] = [
        {"id": 1, "name": "TCAS", "color": "purple"},
        {"id": 2, "name": "คณะในฝัน", "color": "blue"},
    ]
    return repo


def rebuild_views(repo: FakeRepo) -> None:
    """สร้าง view สรุปยอดเหมือน migration 014 — ให้ทดสอบเส้นทางหลัก (อ่านยอด exact)"""
    options = repo.tables.get("community_post_options") or []
    votes = repo.tables.get("community_post_votes") or []
    likes = repo.tables.get("community_post_likes") or []
    comments = repo.tables.get("community_comments") or []

    tally = []
    for option in options:
        tally.append({
            "post_id": option["post_id"],
            "option_id": option["id"],
            "label": option.get("label") or "",
            "sort_order": option.get("sort_order") or 0,
            "votes": sum(1 for vote in votes if vote["option_id"] == option["id"]),
        })
    repo.tables["community_option_tally"] = tally

    stats = []
    for post_id in {row["post_id"] for row in votes} | {row["post_id"] for row in likes} | {row["post_id"] for row in comments}:
        stats.append({
            "post_id": post_id,
            "likes": sum(1 for row in likes if row["post_id"] == post_id),
            "total_votes": sum(1 for row in votes if row["post_id"] == post_id),
            "comments_count": sum(1 for row in comments if row["post_id"] == post_id),
        })
    repo.tables["community_post_stats"] = stats


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
    check("tag ที่ไม่มีอยู่จริงถูกตัดออก (ผู้ใช้สร้าง tag เองไม่ได้)", post["tags"] == ["TCAS", "คณะในฝัน"], str(post.get("tags")))
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
    check("ไลก์แล้วส่งคืนจำนวนไลก์", liked.json().get("likes") == 1, str(liked.json().get("likes")))
    unliked = client.post(f"/api/community/posts/{post['id']}/like")
    check("กดไลก์ซ้ำ = ยกเลิก", unliked.json()["liked"] is False)
    check("ยกเลิกไลก์แล้วจำนวนกลับเป็น 0", unliked.json().get("likes") == 0, str(unliked.json().get("likes")))

    option_id = post["options"][0]["id"]
    voted = client.post(f"/api/community/posts/{post['id']}/vote", json={"option_id": option_id})
    check("โหวตได้", voted.status_code == 200)
    check("โหวตแล้ว my_vote ตรงกับตัวเลือก", voted.json().get("my_vote") == option_id, str(voted.json().get("my_vote")))
    voted2 = client.post(f"/api/community/posts/{post['id']}/vote", json={"option_id": post['options'][1]['id']})
    check("โหวตทับของเดิมได้", voted2.status_code == 200)
    check("โหวตทับแล้ว my_vote เปลี่ยนตาม", voted2.json().get("my_vote") == post['options'][1]['id'])
    after = client.get(f"/api/community/posts/{post['id']}").json()
    check("นับโหวตรวมได้ 1 คน (1 คน = 1 เสียง)", after["post"]["total_votes"] == 1, str(after["post"]["total_votes"]))

    # กดตัวเลือกเดิมซ้ำ = ยกเลิกโหวต
    cancelled = client.post(f"/api/community/posts/{post['id']}/vote", json={"option_id": post['options'][1]['id']})
    check("กดตัวเลือกเดิมซ้ำ = ยกเลิกโหวต", cancelled.json().get("my_vote") is None, str(cancelled.json().get("my_vote")))
    check("ยกเลิกโหวตแล้วยอดรวมเป็น 0", cancelled.json().get("total_votes") == 0, str(cancelled.json().get("total_votes")))

    # โหวตใหม่หลังยกเลิก
    client.post(f"/api/community/posts/{post['id']}/vote", json={"option_id": option_id})
    after2 = client.get(f"/api/community/posts/{post['id']}").json()
    check("โหวตใหม่ได้ และนับเป็น 1 คน", after2["post"]["total_votes"] == 1, str(after2["post"]["total_votes"]))
    check("ยอดโหวตถูกตัวเลือก", after2["post"]["options"][0]["votes"] == 1, str(after2["post"]["options"][0]["votes"]))

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
    check("ผู้ใช้สร้าง tag เองไม่ได้ (ปิดปลายทางแล้ว)", new_tag.status_code in (404, 405), str(new_tag.status_code))

    admin_tag = client.post("/api/admin/tags", headers={"x-test-user": "u-admin"}, json={"name": "#ทดสอบแท็ก", "color": "teal"})
    check("แอดมินสร้าง tag ใหม่ได้", admin_tag.status_code == 200, admin_tag.text[:150])
    check("tag ที่แอดมินสร้างอยู่ในรายการ", any(
        item["name"] == "ทดสอบแท็ก" for item in client.get("/api/community/tags").json()["items"]
    ))
    # tag ที่แอดมินสร้าง ผู้ใช้เลือกใช้ได้
    allowed_tag = client.post("/api/community/posts", json={"title": "ใช้ tag ที่แอดมินสร้าง", "tags": ["ทดสอบแท็ก"]})
    check("ผู้ใช้เลือกใช้ tag ที่มีอยู่จริงได้", allowed_tag.json()["post"]["tags"] == ["ทดสอบแท็ก"], str(allowed_tag.json()["post"]["tags"]))

    # tag ที่มีอักขระพิเศษของ PostgREST ต้องไม่ทำให้ query พัง
    weird = client.post("/api/community/posts", json={
        "title": "ทดสอบ tag พิเศษ", "body": "x", "tags": ["a,b(c)"],
    })
    check("tag ที่มีอักขระพิเศษถูกตัดทิ้ง (ไม่มีในระบบ)", weird.status_code == 201 and weird.json()["post"]["tags"] == [], weird.text[:150])
    still_lists = client.get("/api/community/posts")
    check("ยังอ่านรายการกระทู้ได้หลังมี tag พิเศษ", still_lists.status_code == 200 and len(still_lists.json()["items"]) == 3)

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
