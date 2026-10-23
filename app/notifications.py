from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Request

from .repository import SupabaseRepository

ENTITY_TYPES = {"news", "scholarship", "institution", "admission", "event", "schedule"}
BASE_COLUMNS = "id,user_id,entity_type,entity_id,title,body,url,read_at,created_at"


async def authenticated_user(request: Request, repo: SupabaseRepository) -> dict[str, Any]:
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not token or not repo.auth_configured:
        raise HTTPException(status_code=401, detail="กรุณาเข้าสู่ระบบก่อน")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(
                f"{repo.url}/auth/v1/user",
                headers={"apikey": repo.anon_key, "Authorization": f"Bearer {token}"},
            )
        if response.status_code != 200:
            raise HTTPException(status_code=401, detail="session หมดอายุ กรุณาเข้าสู่ระบบใหม่")
        return response.json()
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="ตรวจสอบ session ไม่สำเร็จ") from None


async def send_push(repo: SupabaseRepository, user_id: str, payload: dict[str, Any]) -> None:
    rows = await repo.select("push_subscriptions", {
        "select": "endpoint,p256dh,auth", "user_id": f"eq.{user_id}"
    }, quiet=True)
    if not rows:
        return
    public_key, private_key = os.getenv("VAPID_PUBLIC_KEY", ""), os.getenv("VAPID_PRIVATE_KEY", "")
    if not public_key or not private_key:
        return
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return
    for row in rows:
        try:
            webpush(
                subscription_info={"endpoint": row["endpoint"], "keys": {"p256dh": row["p256dh"], "auth": row["auth"]}},
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=private_key,
                vapid_claims={"sub": os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")},
            )
        except Exception as exc:  # noqa: BLE001
            # Subscription ที่หมดอายุถูกลบ เพื่อไม่ให้ส่งซ้ำทุกครั้ง
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                await repo.delete("push_subscriptions", {"endpoint": f"eq.{row['endpoint']}"})


async def create_notification(repo: SupabaseRepository, user_id: str, event: dict[str, Any]) -> bool:
    record = {
        "user_id": user_id,
        "title": str(event.get("title") or "มีอัปเดตใหม่")[:180],
        "body": str(event.get("body") or "")[:1000],
        "url": str(event.get("url") or "/")[:1000],
        "entity_type": event.get("entity_type"),
        "entity_id": str(event.get("entity_id") or "")[:200] or None,
        "dedupe_key": str(event.get("dedupe_key") or "")[:250] or None,
    }
    # unique(user_id,dedupe_key) ป้องกันแจ้งซ้ำ; ถ้ามี key ใช้ upsert แบบ ignore duplicate
    if record["dedupe_key"]:
        existing = await repo.select("notifications", {
            "select": "id", "user_id": f"eq.{user_id}",
            "dedupe_key": f"eq.{record['dedupe_key']}", "limit": "1"
        }, quiet=True)
        if existing:
            return False
        ok = await repo.insert("notifications", record)
        if ok:
            await send_push(repo, user_id, record)
        return ok
    ok = await repo.insert("notifications", record)
    if ok:
        await send_push(repo, user_id, record)
    return ok


def build_router(repo: SupabaseRepository) -> APIRouter:
    router = APIRouter(prefix="/api/notifications", tags=["notifications"])

    @router.get("")
    async def list_notifications(request: Request, limit: int = 30) -> dict[str, Any]:
        user = await authenticated_user(request, repo)
        rows = await repo.select("notifications", {
            "select": BASE_COLUMNS, "user_id": f"eq.{user['id']}",
            "order": "created_at.desc", "limit": str(max(1, min(limit, 100))),
        })
        if rows is None:
            raise HTTPException(status_code=503, detail="อ่านการแจ้งเตือนไม่สำเร็จ กรุณาตรวจสอบ migration")
        unread = await repo.select("notifications", {
            "select": "id", "user_id": f"eq.{user['id']}", "read_at": "is.null", "limit": "500"
        })
        return {"items": rows, "unread_count": len(unread or []), "configured": True}

    @router.patch("/{notification_id}/read")
    async def mark_read(notification_id: str, request: Request) -> dict[str, bool]:
        user = await authenticated_user(request, repo)
        ok = await repo.update("notifications", {
            "id": f"eq.{notification_id}", "user_id": f"eq.{user['id']}", "read_at": "is.null"
        }, {"read_at": datetime.now(timezone.utc).isoformat()})
        if not ok:
            raise HTTPException(status_code=503, detail="บันทึกสถานะอ่านไม่สำเร็จ")
        return {"ok": True}

    @router.post("/read-all")
    async def mark_all_read(request: Request) -> dict[str, bool]:
        user = await authenticated_user(request, repo)
        ok = await repo.update("notifications", {
            "user_id": f"eq.{user['id']}", "read_at": "is.null"
        }, {"read_at": datetime.now(timezone.utc).isoformat()})
        if not ok:
            raise HTTPException(status_code=503, detail="บันทึกสถานะอ่านไม่สำเร็จ")
        return {"ok": True}

    @router.get("/follows")
    async def list_follows(request: Request) -> dict[str, Any]:
        user = await authenticated_user(request, repo)
        rows = await repo.select("notification_follows", {
            "select": "id,entity_type,entity_id,title,url,created_at",
            "user_id": f"eq.{user['id']}", "order": "created_at.desc", "limit": "500"
        })
        if rows is None:
            raise HTTPException(status_code=503, detail="อ่านรายการติดตามไม่สำเร็จ กรุณารัน migration")
        return {"items": rows}

    @router.post("/follows")
    async def follow(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        user = await authenticated_user(request, repo)
        entity_type = str(payload.get("entity_type") or "")
        entity_id = str(payload.get("entity_id") or "").strip()
        title = str(payload.get("title") or "").strip()
        if entity_type not in ENTITY_TYPES or not entity_id or len(entity_id) > 200 or not title:
            raise HTTPException(status_code=400, detail="ประเภทหรือข้อมูลรายการติดตามไม่ถูกต้อง")
        row = {
            "user_id": user["id"], "entity_type": entity_type, "entity_id": entity_id,
            "title": title[:250], "url": str(payload.get("url") or "/")[:1000]
        }
        saved = await repo.upsert("notification_follows", row, "user_id,entity_type,entity_id")
        if saved is None:
            raise HTTPException(status_code=503, detail="บันทึกรายการติดตามไม่สำเร็จ")
        return {"ok": True, "item": saved}

    @router.delete("/follows/{entity_type}/{entity_id}")
    async def unfollow(entity_type: str, entity_id: str, request: Request) -> dict[str, bool]:
        user = await authenticated_user(request, repo)
        if entity_type not in ENTITY_TYPES:
            raise HTTPException(status_code=400, detail="ประเภทไม่ถูกต้อง")
        ok = await repo.delete("notification_follows", {
            "user_id": f"eq.{user['id']}", "entity_type": f"eq.{entity_type}",
            "entity_id": f"eq.{entity_id}"
        })
        if not ok:
            raise HTTPException(status_code=503, detail="ยกเลิกติดตามไม่สำเร็จ")
        return {"ok": True}

    @router.post("/push-subscription")
    async def save_push(request: Request, payload: dict[str, Any]) -> dict[str, bool]:
        user = await authenticated_user(request, repo)
        endpoint = str(payload.get("endpoint") or "")
        keys = payload.get("keys") or {}
        if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
            raise HTTPException(status_code=400, detail="ข้อมูล Push subscription ไม่ถูกต้อง")
        ok = await repo.upsert("push_subscriptions", {
            "user_id": user["id"], "endpoint": endpoint,
            "p256dh": keys["p256dh"], "auth": keys["auth"],
        }, "endpoint")
        if ok is None:
            raise HTTPException(status_code=503, detail="บันทึก Push subscription ไม่สำเร็จ")
        return {"ok": True}

    @router.delete("/push-subscription")
    async def delete_push(request: Request, payload: dict[str, Any]) -> dict[str, bool]:
        user = await authenticated_user(request, repo)
        endpoint = str(payload.get("endpoint") or "")
        if not endpoint:
            raise HTTPException(status_code=400, detail="ไม่พบ endpoint")
        ok = await repo.delete("push_subscriptions", {"user_id": f"eq.{user['id']}", "endpoint": f"eq.{endpoint}"})
        if not ok:
            raise HTTPException(status_code=503, detail="ยกเลิก Push subscription ไม่สำเร็จ")
        return {"ok": True}

    # สำหรับแหล่งข้อมูล/งาน sync ที่เชื่อถือได้ ใช้ webhook secret ไม่เปิดให้ผู้ใช้ทั่วไปยิงสร้างแจ้งเตือน
    @router.post("/publish")
    async def publish_event(request: Request, payload: dict[str, Any], x_webhook_secret: str | None = Header(default=None)) -> dict[str, Any]:
        expected = os.getenv("MAKE_WEBHOOK_SECRET", "")
        if not expected or x_webhook_secret != expected:
            raise HTTPException(status_code=401, detail="webhook secret ไม่ถูกต้อง")
        entity_type = str(payload.get("entity_type") or "")
        entity_id = str(payload.get("entity_id") or "").strip()
        if entity_type not in ENTITY_TYPES or not entity_id:
            raise HTTPException(status_code=400, detail="entity_type หรือ entity_id ไม่ถูกต้อง")
        follows = await repo.select("notification_follows", {
            "select": "user_id", "entity_type": f"eq.{entity_type}", "entity_id": f"eq.{entity_id}", "limit": "5000"
        })
        if follows is None:
            raise HTTPException(status_code=503, detail="อ่านรายการติดตามไม่สำเร็จ")
        count = 0
        for row in follows:
            ok = await create_notification(repo, row["user_id"], {
                **payload, "dedupe_key": payload.get("dedupe_key") or f"{entity_type}:{entity_id}:{payload.get('version') or payload.get('event_key') or payload.get('title')}"
            })
            count += int(ok)
        return {"ok": True, "matched": len(follows), "created": count}

    return router
