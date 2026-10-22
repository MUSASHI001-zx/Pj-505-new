"""ตรวจสอบสิทธิ์ผู้ใช้ด้วย Supabase Auth (Bearer token) และตรวจว่าเป็นแอดมินหรือไม่.

ทุก endpoint ที่แก้ข้อมูลส่วนตัวต้องใช้ require_user/require_db_user เพื่อไม่ให้เขียนทับข้อมูลของคนอื่นได้
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import HTTPException, Request


def admin_emails() -> set[str]:
    """อีเมลที่ให้สิทธิ์แอดมินจาก .env (ADMIN_EMAILS=amin@example.com,team@example.com)"""
    raw = os.getenv("ADMIN_EMAILS", "")
    return {item.strip().lower() for item in raw.replace(";", ",").split(",") if item.strip()}


def _token(request: Request) -> str:
    return request.headers.get("authorization", "").removeprefix("Bearer ").strip()


async def require_user(request: Request, repo: Any) -> dict[str, Any]:
    """ตรวจ Bearer token กับ Supabase Auth แล้วคืนข้อมูลผู้ใช้ (ไม่เชื่อ user id จาก body/query)"""
    token = _token(request)
    if not token or not repo.auth_configured:
        raise HTTPException(status_code=401, detail="กรุณาเข้าสู่ระบบก่อน")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(
                f"{repo.url}/auth/v1/user",
                headers={"apikey": repo.anon_key, "Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            user = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=401, detail="session ไม่ถูกต้องหรือหมดอายุ") from None
    if not user.get("id"):
        raise HTTPException(status_code=401, detail="session ไม่ถูกต้องหรือหมดอายุ")
    return user


async def is_admin(repo: Any, open_id: str, email: str | None = None) -> bool:
    """เป็นแอดมินหรือไม่ — เช็คจาก users.is_admin, คอลัมน์บทบาท, profiles.role และรายชื่อใน .env"""
    if email and email.strip().lower() in admin_emails():
        return True
    if await repo.column_exists("users", "is_admin"):
        rows = await repo.select("users", {"select": "is_admin", "openId": f"eq.{open_id}", "limit": "1"})
        if rows and rows[0].get("is_admin"):
            return True
    role = await repo.user_role(open_id)
    if role and str(role).lower() == "admin":
        return True
    if await repo.column_exists("profiles", "role"):
        profiles = await repo.select("profiles", {"select": "role", "id": f"eq.{open_id}", "limit": "1"})
        if profiles and str(profiles[0].get("role") or "").lower() == "admin":
            return True
    return False


async def require_admin(request: Request, repo: Any) -> dict[str, Any]:
    """ผ่าน require_user แล้วต้องเป็นแอดมินด้วย"""
    user = await require_user(request, repo)
    if not await is_admin(repo, user["id"], user.get("email")):
        raise HTTPException(status_code=403, detail="ต้องเป็นแอดมินเท่านั้น")
    return user


async def is_disabled(repo: Any, open_id: str) -> bool:
    """บัญชีถูกระงับโดยแอดมินหรือไม่"""
    if not await repo.column_exists("users", "is_disabled"):
        return False
    rows = await repo.select("users", {"select": "is_disabled", "openId": f"eq.{open_id}", "limit": "1"})
    return bool(rows and rows[0].get("is_disabled"))


async def log_admin_action(
    repo: Any,
    actor: dict[str, Any],
    action: str,
    target_type: str = "",
    target_id: str = "",
    detail: str = "",
) -> None:
    """บันทึกว่าแอดมินคนไหนทำอะไร (audit trail) — ล้มเหลวก็ไม่ทำให้คำสั่งหลักพัง"""
    try:
        await repo.insert("admin_audit_log", {
            "actor_id": actor.get("id"),
            "actor_name": (actor.get("user_metadata") or {}).get("full_name") or actor.get("email") or "แอดมิน",
            "action": action,
            "target_type": target_type,
            "target_id": str(target_id),
            "detail": detail[:500],
        })
    except Exception:  # noqa: BLE001 — audit เป็นข้อมูลเสริม ไม่ควรทำให้การกระทำหลักล้มเหลว
        pass


def require_database(repo: Any) -> None:
    if not repo.configured:
        raise HTTPException(status_code=503, detail="ยังไม่ได้ตั้งค่า Supabase ฝั่งเซิร์ฟเวอร์")


def database_error(repo: Any, default: str) -> HTTPException:
    """แปลงข้อผิดพลาดจากฐานข้อมูลเป็นข้อความที่บอกว่าต้องรัน migration ไหน"""
    detail = default
    error = repo.last_database_error or ""
    if "does not exist" in error or "PGRST205" in error:
        for table, migration in MIGRATION_HINTS.items():
            if table in error:
                detail = f"ยังไม่ได้สร้างตาราง {table} — รัน supabase/migrations/{migration} ใน Supabase SQL Editor"
                break
        else:
            detail = "ยังไม่ได้สร้างตารางที่จำเป็น — รันไฟล์ใน supabase/migrations/ ใน Supabase SQL Editor"
    return HTTPException(status_code=503, detail=detail)


# ตาราง -> ไฟล์ migration ที่ต้องรัน (ใช้บอกข้อความ error ให้ชัดเจน)
MIGRATION_HINTS = {
    "user_settings": "006_account.sql",
    "invite_links": "006_account.sql",
    "invite_redemptions": "006_account.sql",
    "community_tags": "007_community.sql",
    "community_posts": "007_community.sql",
    "community_post_options": "007_community.sql",
    "community_comments": "007_community.sql",
    "community_post_likes": "007_community.sql",
    "community_post_votes": "007_community.sql",
    "tickets": "007_community.sql",
    "ticket_messages": "007_community.sql",
    "admin_presence": "007_community.sql",
    "admissions": "008_admin.sql",
    "admin_audit_log": "008_admin.sql",
}
