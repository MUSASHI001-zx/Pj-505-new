"""โมดูลนี้เป็นโค้ดเก่า — ระบบจัดการบัญชีจริงอยู่ใน app/main.py แล้ว

เหลือไว้เฉพาะเพื่อไม่ให้ import ของไฟล์เก่าพัง ไม่มี router ที่ถูก register แล้ว
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from .account_data import (
    CONTACT_CATEGORIES, FACULTY_CATALOG, GRADE_LEVELS, MAX_FACULTIES,
    NOTIFICATION_KEYS, NOTIFICATION_TOPICS, PROVINCES,
)
from .schemas import AccountUpdate as ProfileUpdate
from .schemas import InviteRedeem

# schema ที่ถูกลบไปแล้ว (ระบบใหม่ใช้ AccountUpdate แทน) — ทำ placeholder ไว้ให้ import ไม่พัง
class _RemovedSchema:
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

class AvatarUpdate(_RemovedSchema): ...
class ContactCreate(_RemovedSchema): ...
class FacultiesUpdate(_RemovedSchema): ...
class NotificationsUpdate(_RemovedSchema): ...

INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # ตัดตัวที่สับสน (0/O, 1/I/L)
INVITE_CODE_LENGTH = 8
INVITE_WINDOW = timedelta(days=2)  # ใช้โค้ดเชิญได้เฉพาะบัญชีที่เพิ่งสร้าง
CONTACT_LIMIT_PER_HOUR = 5
AVATAR_EXTENSIONS = {".svg", ".png", ".webp", ".jpg", ".jpeg", ".gif"}
ROLE_LABELS = {"student": "นักเรียน", "parents": "ผู้ปกครอง", "teacher": "คุณครู"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def build_router(repo: Any, static_dir: Path) -> APIRouter:
    router = APIRouter(prefix="/api")
    avatar_dir = static_dir / "avatars"

    # ---------- helpers ----------
    def list_avatars() -> list[dict[str, str]]:
        if not avatar_dir.is_dir():
            return []
        names = sorted(
            p.name for p in avatar_dir.iterdir()
            if p.is_file() and p.suffix.lower() in AVATAR_EXTENSIONS and not p.name.startswith(".")
        )
        return [
            {"key": name, "url": f"/static/avatars/{quote(name)}", "label": Path(name).stem.replace("-", " ").replace("_", " ")}
            for name in names
        ]

    def db_failure(response: "httpx.Response | None") -> HTTPException:
        text = response.text if response is not None else ""
        if response is not None and response.status_code == 404 and ("PGRST205" in text or "does not exist" in text):
            return HTTPException(status_code=503, detail="ยังไม่ได้รัน migration 006_account.sql ใน Supabase")
        return HTTPException(status_code=503, detail="ระบบฐานข้อมูลขัดข้อง โปรดลองใหม่อีกครั้ง")

    async def require_user(request: Request) -> dict[str, Any]:
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not token or not repo.auth_configured:
            raise HTTPException(status_code=401, detail="กรุณาเข้าสู่ระบบก่อน")
        if not repo.configured:
            raise HTTPException(status_code=503, detail="Supabase ยังไม่ได้ตั้งค่า")
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(
                    f"{repo.url}/auth/v1/user",
                    headers={"apikey": repo.anon_key, "Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                auth_user = response.json()
        except (httpx.HTTPError, ValueError):
            raise HTTPException(status_code=401, detail="session ไม่ถูกต้องหรือหมดอายุ") from None
        user_id = auth_user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="session ไม่ถูกต้อง")
        meta = auth_user.get("user_metadata") or {}
        email = auth_user.get("email", "")
        return {"id": str(user_id), "email": email, "name": meta.get("full_name") or meta.get("name") or email.split("@")[0] or "ผู้ใช้"}

    async def load_profile(user_id: str) -> dict[str, Any] | None:
        response = await repo.request("GET", "account_profiles", params={"select": "*", "user_id": f"eq.{user_id}", "limit": "1"})
        if response is None or response.is_error:
            raise db_failure(response)
        rows = response.json()
        return rows[0] if rows else None

    async def ensure_profile(user: dict[str, Any]) -> dict[str, Any]:
        """คืนโปรไฟล์ของผู้ใช้ ถ้ายังไม่มีให้สร้างพร้อมโค้ดเชิญ (เรียกซ้ำ/พร้อมกันได้)"""
        row = await load_profile(user["id"])
        if row:
            return row
        for _ in range(6):  # โค้ดชนกันได้ยากมาก แต่ลองใหม่ถ้าชน
            record = {
                "user_id": user["id"],
                "display_name": user["name"][:60],
                "invite_code": "".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_CODE_LENGTH)),
            }
            response = await repo.request(
                "POST", "account_profiles", params={"on_conflict": "user_id"},
                json=record, prefer="resolution=ignore-duplicates,return=representation",
            )
            if response is None:
                raise db_failure(None)
            if response.status_code == 409:  # invite_code ซ้ำ -> สุ่มใหม่
                continue
            if response.is_error:
                raise db_failure(response)
            rows = response.json()
            if rows:
                return rows[0]
            row = await load_profile(user["id"])  # มีคนสร้างไปก่อนในจังหวะเดียวกัน
            if row:
                return row
        raise HTTPException(status_code=503, detail="สร้างโปรไฟล์ไม่สำเร็จ โปรดลองใหม่")

    async def patch_profile(user: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
        await ensure_profile(user)
        response = await repo.request(
            "PATCH", "account_profiles", params={"user_id": f"eq.{user['id']}"},
            json={**changes, "updated_at": _now().isoformat()}, prefer="return=representation",
        )
        if response is None or response.is_error:
            raise db_failure(response)
        rows = response.json()
        if not rows:
            raise HTTPException(status_code=404, detail="ไม่พบโปรไฟล์")
        return rows[0]

    async def load_role(user_id: str) -> str | None:
        response = await repo.request("GET", "users", params={"select": "role", "openId": f"eq.{user_id}", "limit": "1"})
        if response is None or response.is_error:
            return None  # บทบาทเป็นข้อมูลเสริม ไม่ให้ทำให้ทั้งหน้าล่ม
        rows = response.json()
        return (rows[0].get("role") if rows else None) or None

    def serialize(row: dict[str, Any], user: dict[str, Any], role: str | None, avatars: list[dict[str, str]]) -> dict[str, Any]:
        avatar_urls = {a["key"]: a["url"] for a in avatars}
        stored = row.get("notification_prefs") or {}
        prefs = {t["key"]: bool(stored.get(t["key"], t["default"])) for t in NOTIFICATION_TOPICS}
        return {
            "display_name": row.get("display_name") or user["name"],
            "email": user["email"],
            "role": role if role in ROLE_LABELS else None,
            "avatar_key": row.get("avatar_key") if row.get("avatar_key") in avatar_urls else None,
            "avatar_url": avatar_urls.get(row.get("avatar_key") or ""),
            "school": row.get("school"),
            "grade_level": row.get("grade_level"),
            "province": row.get("province"),
            "phone": row.get("phone"),
            "faculties": row.get("faculties") or [],
            "notification_prefs": prefs,
            "invite_code": row.get("invite_code"),
            "was_invited": bool(row.get("invited_by")),
            "created_at": row.get("created_at"),
        }

    async def invite_summary(user_id: str, avatars: list[dict[str, str]]) -> dict[str, Any]:
        count = await repo._count("account_profiles", {"invited_by": f"eq.{user_id}"})
        response = await repo.request("GET", "account_profiles", params={
            "select": "display_name,avatar_key,invited_at", "invited_by": f"eq.{user_id}",
            "order": "invited_at.desc", "limit": "5",
        })
        avatar_urls = {a["key"]: a["url"] for a in avatars}
        recent = []
        if response is not None and not response.is_error:
            for row in response.json():
                first_name = (row.get("display_name") or "เพื่อน").split()[0][:30]  # แสดงแค่ชื่อแรก ไม่เปิดข้อมูลเกินจำเป็น
                recent.append({"name": first_name, "avatar_url": avatar_urls.get(row.get("avatar_key") or ""), "invited_at": row.get("invited_at")})
        return {"count": count or 0, "recent": recent}

    async def contact_recent(user_id: str) -> list[dict[str, Any]]:
        response = await repo.request("GET", "contact_messages", params={
            "select": "id,category,subject,status,created_at", "user_id": f"eq.{user_id}",
            "order": "created_at.desc", "limit": "5",
        })
        return response.json() if response is not None and not response.is_error else []

    # ---------- public ----------
    @router.get("/avatars")
    async def avatars() -> dict[str, Any]:
        return {"items": list_avatars()}

    @router.get("/account/options")
    async def options() -> dict[str, Any]:
        return {
            "avatars": list_avatars(),
            "grade_levels": GRADE_LEVELS,
            "provinces": PROVINCES,
            "faculty_catalog": FACULTY_CATALOG,
            "max_faculties": MAX_FACULTIES,
            "notification_topics": NOTIFICATION_TOPICS,
            "contact_categories": CONTACT_CATEGORIES,
            "roles": ROLE_LABELS,
        }

    # ---------- account ----------
    @router.get("/account")
    async def get_account(user: dict = Depends(require_user)) -> dict[str, Any]:
        row = await ensure_profile(user)
        avs = list_avatars()
        return {
            "profile": serialize(row, user, await load_role(user["id"]), avs),
            "invite": await invite_summary(user["id"], avs),
            "contact": {"recent": await contact_recent(user["id"])},
        }

    @router.put("/account/profile")
    async def update_profile(payload: ProfileUpdate, user: dict = Depends(require_user)) -> dict[str, Any]:
        row = await patch_profile(user, payload.model_dump())
        return {"profile": serialize(row, user, await load_role(user["id"]), list_avatars())}

    @router.put("/account/avatar")
    async def update_avatar(payload: AvatarUpdate, user: dict = Depends(require_user)) -> dict[str, Any]:
        avs = list_avatars()
        if payload.avatar_key is not None and payload.avatar_key not in {a["key"] for a in avs}:
            raise HTTPException(status_code=400, detail="ไม่พบรูปโปรไฟล์นี้")
        row = await patch_profile(user, {"avatar_key": payload.avatar_key})
        return {"profile": serialize(row, user, await load_role(user["id"]), avs)}

    @router.put("/account/faculties")
    async def update_faculties(payload: FacultiesUpdate, user: dict = Depends(require_user)) -> dict[str, Any]:
        row = await patch_profile(user, {"faculties": payload.faculties})
        return {"profile": serialize(row, user, await load_role(user["id"]), list_avatars())}

    @router.put("/account/notifications")
    async def update_notifications(payload: NotificationsUpdate, user: dict = Depends(require_user)) -> dict[str, Any]:
        current = await ensure_profile(user)
        merged = {**(current.get("notification_prefs") or {}), **payload.prefs}
        merged = {k: v for k, v in merged.items() if k in NOTIFICATION_KEYS}
        row = await patch_profile(user, {"notification_prefs": merged})
        return {"profile": serialize(row, user, await load_role(user["id"]), list_avatars())}

    @router.post("/account/contact", status_code=201)
    async def send_contact(payload: ContactCreate, user: dict = Depends(require_user)) -> dict[str, Any]:
        since = (_now() - timedelta(hours=1)).isoformat()
        recent = await repo._count("contact_messages", {"user_id": f"eq.{user['id']}", "created_at": f"gt.{since}"})
        if recent is not None and recent >= CONTACT_LIMIT_PER_HOUR:
            raise HTTPException(status_code=429, detail="ส่งข้อความบ่อยเกินไป โปรดรอสักครู่แล้วลองใหม่")
        response = await repo.request("POST", "contact_messages", json={
            "user_id": user["id"], "email": user["email"], "category": payload.category,
            "subject": payload.subject, "message": payload.message,
        }, prefer="return=representation")
        if response is None or response.is_error:
            raise db_failure(response)
        rows = response.json()
        item = rows[0] if rows else {}
        return {"ok": True, "item": {k: item.get(k) for k in ("id", "category", "subject", "status", "created_at")}}

    # ---------- invite ----------
    @router.post("/invite/redeem")
    async def redeem_invite(payload: InviteRedeem, user: dict = Depends(require_user)) -> dict[str, Any]:
        me = await ensure_profile(user)
        if me.get("invited_by"):
            raise HTTPException(status_code=409, detail="บัญชีนี้ใช้โค้ดเชิญไปแล้ว")
        created = _parse_time(me.get("created_at"))
        if created is None or _now() - created > INVITE_WINDOW:
            raise HTTPException(status_code=409, detail="ใช้โค้ดเชิญได้เฉพาะบัญชีที่เพิ่งสมัครใหม่")
        lookup = await repo.request("GET", "account_profiles", params={
            "select": "user_id,display_name", "invite_code": f"eq.{payload.code}", "limit": "1",
        })
        if lookup is None or lookup.is_error:
            raise db_failure(lookup)
        rows = lookup.json()
        if not rows:
            raise HTTPException(status_code=404, detail="ไม่พบโค้ดเชิญนี้")
        inviter = rows[0]
        if inviter["user_id"] == user["id"]:
            raise HTTPException(status_code=400, detail="ใช้โค้ดเชิญของตัวเองไม่ได้")
        # เงื่อนไข invited_by is null อยู่ในคำสั่งเดียว กันการใช้ซ้ำแม้ยิงพร้อมกัน
        response = await repo.request(
            "PATCH", "account_profiles",
            params={"user_id": f"eq.{user['id']}", "invited_by": "is.null"},
            json={"invited_by": inviter["user_id"], "invited_at": _now().isoformat()},
            prefer="return=representation",
        )
        if response is None or response.is_error:
            raise db_failure(response)
        if not response.json():
            raise HTTPException(status_code=409, detail="บัญชีนี้ใช้โค้ดเชิญไปแล้ว")
        first_name = (inviter.get("display_name") or "เพื่อน").split()[0][:30]
        return {"ok": True, "inviter_name": first_name}

    return router
