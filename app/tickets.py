"""ระบบ Ticket: ห้องแชทส่วนตัวระหว่างผู้ใช้กับแอดมิน (Amin).

กติกา:
- ผู้ใช้เปิด Ticket แล้วพิมพ์คุยได้ทันที (ผู้ใช้ที่ยังไม่มี Ticket จะเปิดให้อัตโนมัติเมื่อพิมพ์ครั้งแรก)
- ถ้าไม่มีแอดมินออนไลน์ ระบบจะตอบกลับอัตโนมัติว่า "ยังไม่มีแอดมินอยู่ในขณะนี้" และเก็บข้อความไว้ให้แอดมินตอบทีหลัง
- แอดมินปิดตั๋วได้ (สถานะ open -> answered -> closed) และผู้ใช้เปิดตั๋วใหม่ได้หลังจากนั้น
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .auth import database_error, is_admin, require_database, require_user
from .ticket_cleanup import build_helpers as build_ticket_helpers
from .uploads import upload_ticket_image

NO_ADMIN_REPLY = "ยังไม่มีแอดมินอยู่ในขณะนี้"
ADMIN_OFFLINE_REPLY = "ขณะนี้แอดมินออฟไลน์อยู่ ข้อความของคุณถูกบันทึกไว้แล้ว และจะได้รับการตอบกลับโดยเร็วที่สุด"
MAX_MESSAGE = 3000
MAX_SUBJECT = 150
ADMIN_ONLINE_WINDOW = timedelta(minutes=2)  # ถือว่าออนไลน์ถ้า heartbeat ใหม่ภายใน 2 นาที
TICKET_CATEGORIES = ["ทั่วไป", "ปัญหาการใช้งาน", "บัญชีและข้อมูลส่วนตัว", "เกี่ยวกับคณะ/การสมัคร", "ข้อเสนอแนะ"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def build_router(repo: Any) -> APIRouter:
    router = APIRouter(prefix="/api/tickets")

    # ล้างข้อมูลตั๋วที่ปิดแล้ว (ใช้ร่วมกับ admin.py)
    _cleanup = build_ticket_helpers(repo)
    purge_ticket = _cleanup["purge_ticket"]
    purge_closed_tickets = _cleanup["purge_closed_tickets"]

    # ---------- helpers ----------
    async def current_user(request: Request) -> dict[str, Any]:
        user = await require_user(request, repo)
        require_database(repo)
        return user

    async def online_admin() -> dict[str, Any] | None:
        """แอดมินที่ออนไลน์อยู่ตอนนี้ (ไม่มี = None)"""
        since = (_now() - ADMIN_ONLINE_WINDOW).isoformat()
        rows = await repo.select("admin_presence", {
            "select": "admin_id,display_name,is_online,updated_at",
            "is_online": "eq.true", "updated_at": f"gt.{since}", "limit": "10",
        })
        if not rows:
            return None
        return rows[0]

    async def admin_names() -> list[str]:
        rows = await repo.select("users", {"select": "openId,name,is_admin", "is_admin": "eq.true", "limit": "50"})
        return [_clean(row.get("name")) for row in (rows or []) if row.get("name")]

    async def touch_presence(admin_id: str, name: str, online: bool = True) -> None:
        await repo.upsert("admin_presence", {
            "admin_id": admin_id, "display_name": name, "is_online": online,
            "updated_at": _now().isoformat(),
        }, "admin_id")

    async def serialize_ticket(row: dict[str, Any], open_id: str) -> dict[str, Any]:
        messages = await repo.select("ticket_messages", {
            "select": "id,sender_type,sender_name,body,image_url,created_at",
            "ticket_id": f"eq.{row['id']}", "order": "created_at", "limit": "500",
        })
        preview = ""
        for message in messages or []:
            preview = _clean(message.get("body"))
            if preview:
                break
        return {
            "id": row["id"],
            "subject": row.get("subject"),
            "category": row.get("category"),
            "status": row.get("status"),
            "image_url": row.get("image_url"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "message_count": len(messages or []),
            "last_message": preview,
            "mine": row.get("open_id") == open_id,
        }

    # ---------- สถานะแอดมิน (ลงทะเบียนก่อน /{ticket_id} เพื่อไม่ให้ถูกบัง) ----------
    @router.get("/status/admin")
    async def admin_status() -> dict[str, Any]:
        admin = await online_admin()
        return {"admin_online": bool(admin), "admin_name": _clean((admin or {}).get("display_name")) if admin else ""}

    @router.post("/status/admin")
    async def admin_heartbeat(request: Request) -> dict[str, Any]:
        """แอดมินเรียก heartbeat เพื่อบอกว่าออนไลน์อยู่ (ถ้าหยุดเรียกเกิน 2 นาที ถือว่าออฟไลน์)"""
        user = await require_user(request, repo)
        require_database(repo)
        if not await is_admin(repo, user["id"], user.get("email")):
            raise HTTPException(status_code=403, detail="ต้องเป็นแอดมินเท่านั้น")
        name = _clean((user.get("user_metadata") or {}).get("full_name")) or "แอดมิน"
        await touch_presence(user["id"], name)
        return {"ok": True, "admin_online": True}

    @router.post("/upload", status_code=201)
    async def upload_ticket_image_endpoint(request: Request) -> dict[str, Any]:
        """อัปโหลดรูปสำหรับ Ticket — รับ multipart/form-data"""
        user = await current_user(request)
        form = await request.form()
        file = form.get("file")
        if not file:
            raise HTTPException(status_code=400, detail="ไม่พบไฟล์รูป")
        data = await file.read()
        url = await upload_ticket_image(repo, data, user["id"])
        return {"url": url}

    # ---------- ผู้ใช้ ----------
    @router.get("")
    async def list_tickets(request: Request) -> dict[str, Any]:
        user = await current_user(request)
        rows = await repo.select("tickets", {
            "select": "id,open_id,subject,category,status,created_at,updated_at",
            "open_id": f"eq.{user['id']}", "order": "updated_at.desc", "limit": "50",
        })
        if rows is None:
            raise database_error(repo, "อ่าน Ticket ไม่สำเร็จ")
        items = [await serialize_ticket(row, user["id"]) for row in rows]
        admin = await online_admin()
        return {"items": items, "admin_online": bool(admin), "categories": TICKET_CATEGORIES}

    @router.get("/{ticket_id}")
    async def get_ticket(request: Request, ticket_id: int) -> dict[str, Any]:
        user = await current_user(request)
        rows = await repo.select("tickets", {"select": "*", "id": f"eq.{ticket_id}", "limit": "1"})
        if rows is None:
            raise database_error(repo, "อ่าน Ticket ไม่สำเร็จ")
        if not rows:
            raise HTTPException(status_code=404, detail="ไม่พบ Ticket นี้")
        row = rows[0]
        admin = await is_admin(repo, user["id"], user.get("email"))
        if row.get("open_id") != user["id"] and not admin:
            raise HTTPException(status_code=403, detail="ดู Ticket ของคนอื่นไม่ได้")
        messages = await repo.select("ticket_messages", {
            "select": "id,sender_type,sender_name,body,image_url,created_at",
            "ticket_id": f"eq.{ticket_id}", "order": "created_at", "limit": "500",
        })
        return {"ticket": {k: row.get(k) for k in ("id", "subject", "category", "status", "image_url", "created_at", "updated_at")},
                "messages": messages or [],
                "admin_online": bool(await online_admin())}

    @router.post("", status_code=201)
    async def create_ticket(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        user = await current_user(request)
        subject = _clean(payload.get("subject"))
        if not subject:
            raise HTTPException(status_code=400, detail="กรุณากรอกหัวข้อที่จะปรึกษา")
        if len(subject) > MAX_SUBJECT:
            raise HTTPException(status_code=400, detail=f"หัวข้อยาวเกิน {MAX_SUBJECT} ตัวอักษร")
        category = _clean(payload.get("category")) or "ทั่วไป"
        if category not in TICKET_CATEGORIES:
            category = "ทั่วไป"
        body = _clean(payload.get("body"))
        if not body:
            raise HTTPException(status_code=400, detail="กรุณาเขียนรายละเอียดที่ต้องการปรึกษา")
        if len(body) > MAX_MESSAGE:
            raise HTTPException(status_code=400, detail=f"ข้อความยาวเกิน {MAX_MESSAGE} ตัวอักษร")

        image_url = _clean(payload.get("image_url"))

        saved = await repo.insert_returning("tickets", {
            "open_id": user["id"], "subject": subject, "category": category, "status": "open",
            "image_url": image_url or None,
        })
        if saved is None:
            raise database_error(repo, "สร้าง Ticket ไม่สำเร็จ")
        await repo.insert("ticket_messages", {
            "ticket_id": saved["id"], "sender_type": "user", "sender_id": user["id"],
            "sender_name": _clean((user.get("user_metadata") or {}).get("full_name")) or "ผู้ใช้",
            "body": body, "image_url": image_url or None,
        })
        admin = await online_admin()
        if not admin:
            await repo.insert("ticket_messages", {
                "ticket_id": saved["id"], "sender_type": "system", "sender_id": None,
                "sender_name": "ระบบ", "body": NO_ADMIN_REPLY,
            })
        return {"ok": True, "ticket": {k: saved.get(k) for k in ("id", "subject", "category", "status", "image_url", "created_at", "updated_at")},
                "admin_online": bool(admin)}

    @router.post("/{ticket_id}/messages", status_code=201)
    async def send_message(request: Request, ticket_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        user = await current_user(request)
        body = _clean(payload.get("body"))
        if not body:
            raise HTTPException(status_code=400, detail="กรุณาพิมพ์ข้อความ")
        if len(body) > MAX_MESSAGE:
            raise HTTPException(status_code=400, detail=f"ข้อความยาวเกิน {MAX_MESSAGE} ตัวอักษร")

        image_url = _clean(payload.get("image_url"))
        rows = await repo.select("tickets", {"select": "*", "id": f"eq.{ticket_id}", "limit": "1"})
        if not rows:
            raise HTTPException(status_code=404, detail="ไม่พบ Ticket นี้")
        ticket = rows[0]
        admin = await is_admin(repo, user["id"], user.get("email"))
        if ticket.get("open_id") != user["id"] and not admin:
            raise HTTPException(status_code=403, detail="ส่งข้อความใน Ticket ของคนอื่นไม่ได้")
        if ticket.get("status") == "closed" and not admin:
            raise HTTPException(status_code=409, detail="Ticket นี้ถูกปิดแล้ว กรุณาเปิด Ticket ใหม่")

        sender_name = _clean((user.get("user_metadata") or {}).get("full_name")) or "ผู้ใช้"
        await repo.insert("ticket_messages", {
            "ticket_id": ticket_id, "sender_type": "admin" if admin else "user",
            "sender_id": user["id"], "sender_name": sender_name, "body": body,
            "image_url": image_url or None,
        })
        await repo.update("tickets", {"id": f"eq.{ticket_id}"}, {"updated_at": _now().isoformat()})

        replies: list[dict[str, Any]] = []
        if not admin:
            online = await online_admin()
            if not online:
                # ไม่มีแอดมินออนไลน์ -> ตอบกลับอัตโนมัติ แต่ยังเก็บข้อความไว้ให้แอดมินตอบทีหลัง
                saved = await repo.insert_returning("ticket_messages", {
                    "ticket_id": ticket_id, "sender_type": "system", "sender_id": None,
                    "sender_name": "ระบบ", "body": NO_ADMIN_REPLY,
                })
                if saved:
                    replies.append(saved)
        return {"ok": True, "replies": replies, "admin_online": bool(await online_admin())}

    @router.post("/{ticket_id}/close")
    async def close_ticket(request: Request, ticket_id: int) -> dict[str, Any]:
        """ผู้ใช้ปิด Ticket ตัวเองได้ — ปิดแล้วข้อมูลจะถูกลบทิ้งถาวร"""
        user = await current_user(request)
        rows = await repo.select("tickets", {"select": "id,open_id,status", "id": f"eq.{ticket_id}", "limit": "1"})
        if not rows:
            raise HTTPException(status_code=404, detail="ไม่พบ Ticket นี้")
        if rows[0].get("open_id") != user["id"] and not await is_admin(repo, user["id"], user.get("email")):
            raise HTTPException(status_code=403, detail="ปิด Ticket ของคนอื่นไม่ได้")
        # ลบข้อมูลทิ้งถาวรเลย (ข้อความในตาราง ticket_messages ถูก cascade ลบตาม)
        result = await purge_ticket(ticket_id)
        if not result["ok"]:
            raise database_error(repo, "ปิด Ticket ไม่สำเร็จ")
        return {"ok": True, "status": "closed", "purged": True}

    # ---------- สถานะแอดมิน ----------
    return router
