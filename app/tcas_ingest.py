"""ช่องรับข้อมูลจาก myTCAS ผ่าน Make.com — มหาวิทยาลัย/สถาบัน, คณะและหลักสูตร, เกณฑ์รับ/รอบสมัคร

รูปแบบเดียวกับ POST /api/news:
- ต้องส่ง header X-Webhook-Secret ที่ตรงกับ MAKE_WEBHOOK_SECRET (fail closed ถ้ายังไม่ตั้งค่า)
- upsert ด้วย tc_uid ของ myTCAS เพื่อไม่ให้ข้อมูลซ้ำ — ยิงซ้ำได้ไม่ต้องกลัว
- ถ้าส่งรายการใหญ่ (เช่น คณะทั้งหมดของหลายมหาวิทยาลัย) ให้แบ่งเป็นหลายคำขอ หรือใช้ payload แบบ items: [...]
"""
from __future__ import annotations

import hmac
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from .repository import SupabaseRepository

MAX_NAME = 200
MAX_TEXT = 2000
MAX_ITEMS = 500
KINDS = ("รัฐ", "เอกชน", "ราชมงคล", "นานาชาติ", "อื่น ๆ")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _check_webhook(provided: str | None) -> None:
    """ตรวจ secret แบบ fail closed — ถ้ายังไม่ตั้งค่า MAKE_WEBHOOK_SECRET ให้ปฏิเสธทั้งหมด"""
    expected = os.getenv("MAKE_WEBHOOK_SECRET", "")
    if not expected:
        raise HTTPException(status_code=503, detail="ยังไม่ได้ตั้งค่า MAKE_WEBHOOK_SECRET")
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid webhook secret")


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """รับได้ทั้งแบบรายการเดียว และแบบ items: [...]"""
    raw = payload.get("items")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return [payload]


def build_router(repo: SupabaseRepository) -> APIRouter:
    router = APIRouter(prefix="/api/tcas")

    def require_db() -> None:
        if not repo.configured:
            raise HTTPException(status_code=503, detail="Supabase ยังไม่ได้ตั้งค่า")

    async def upsert_institution(item: dict[str, Any]) -> tuple[str, str]:
        """คืน (id, ชื่อ) — ใช้ tc_uid หรือชื่อเป็นกุญแจกันข้อมูลซ้ำ"""
        name = _clean(item.get("name"))[:MAX_NAME]
        if not name:
            raise HTTPException(status_code=422, detail="ข้อมูลมหาวิทยาลัยต้องมี name")
        tc_uid = _clean(item.get("tc_uid")) or None
        record: dict[str, Any] = {"name": name, "updated_at": _now()}
        for key, column in (
            ("short_name", "short_name"),
            ("city", "city"),
            ("kind", "kind"),
            ("website_url", "website_url"),
            ("logo_url", "logoUrl"),
        ):
            value = _clean(item.get(key))
            if value:
                record[column] = value[:MAX_NAME]
        kind = record.get("kind")
        if kind and kind not in KINDS:
            record["kind"] = "อื่น ๆ"
        if "is_published" in item:
            record["is_published"] = bool(item.get("is_published"))
        if tc_uid:
            record["tc_uid"] = tc_uid

        # หาแถวเดิมก่อน: ด้วย tc_uid ถ้ามี ไม่งั้นด้วยชื่อ
        rows: list[dict[str, Any]] | None = None
        if tc_uid:
            rows = await repo.select("institutions", {"select": "id,name", "tc_uid": f"eq.{tc_uid}", "limit": "1"})
        if not rows:
            rows = await repo.select("institutions", {"select": "id,name", "name": f"eq.{name}", "limit": "1"})
        if rows:
            if not await repo.update("institutions", {"id": f"eq.{rows[0]['id']}"}, record):
                raise HTTPException(status_code=502, detail=repo.last_database_error or "อัปเดตมหาวิทยาลัยไม่สำเร็จ")
            return str(rows[0]["id"]), name
        saved = await repo.insert_returning("institutions", record)
        if saved is None:
            raise HTTPException(status_code=502, detail=repo.last_database_error or "เพิ่มมหาวิทยาลัยไม่สำเร็จ")
        return str(saved["id"]), name

    # -----------------------------------------------------------------------
    # มหาวิทยาลัย/สถาบัน
    # -----------------------------------------------------------------------
    @router.post("/institutions")
    async def ingest_institutions(
        request: Request,
        payload: dict[str, Any],
        x_webhook_secret: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _check_webhook(x_webhook_secret)
        require_db()
        items = _items(payload)
        if not items:
            raise HTTPException(status_code=422, detail="ไม่มีข้อมูลมหาวิทยาลัย")
        if len(items) > MAX_ITEMS:
            raise HTTPException(status_code=422, detail=f"ส่งได้ครั้งละไม่เกิน {MAX_ITEMS} รายการ")
        results = []
        for item in items:
            inst_id, name = await upsert_institution(item)
            results.append({"id": inst_id, "name": name})
        return {"ok": True, "count": len(results), "items": results}

    # -----------------------------------------------------------------------
    # คณะและหลักสูตร
    # -----------------------------------------------------------------------
    @router.post("/faculties")
    async def ingest_faculties(
        request: Request,
        payload: dict[str, Any],
        x_webhook_secret: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _check_webhook(x_webhook_secret)
        require_db()
        items = _items(payload)
        if not items:
            raise HTTPException(status_code=422, detail="ไม่มีข้อมูลคณะ")
        if len(items) > MAX_ITEMS:
            raise HTTPException(status_code=422, detail=f"ส่งได้ครั้งละไม่เกิน {MAX_ITEMS} รายการ")
        results = []
        for item in items:
            name = _clean(item.get("name"))[:MAX_NAME]
            if not name:
                raise HTTPException(status_code=422, detail="ข้อมูลคณะต้องมี name")
            institution = _clean(item.get("institution"))[:MAX_NAME]
            inst_id: str | None = None
            if institution:
                inst_id, _name = await upsert_institution({"name": institution, "tc_uid": _clean(item.get("tc_uid")) or None})
            record: dict[str, Any] = {
                "institution": institution,
                "name": name,
                "updated_at": _now(),
            }
            if inst_id:
                record["institution_id"] = int(inst_id)
            for key, column in (("program", "program"), ("degree", "degree"), ("source_url", "source_url")):
                value = _clean(item.get(key))
                if value:
                    record[column] = value[:MAX_TEXT]
            tc_faculty_uid = _clean(item.get("tc_faculty_uid")) or None
            if tc_faculty_uid:
                record["tc_faculty_uid"] = tc_faculty_uid
            if "is_published" in item:
                record["is_published"] = bool(item.get("is_published"))

            rows = None
            if tc_faculty_uid:
                rows = await repo.select("faculties", {"select": "id", "tc_faculty_uid": f"eq.{tc_faculty_uid}", "limit": "1"})
            if not rows:
                rows = await repo.select("faculties", {
                    "select": "id", "institution": f"eq.{institution}", "name": f"eq.{name}", "limit": "1",
                })
            if rows:
                await repo.update("faculties", {"id": f"eq.{rows[0]['id']}"}, record)
                results.append({"id": str(rows[0]["id"]), "name": name})
            else:
                saved = await repo.insert_returning("faculties", record)
                if saved is None:
                    raise HTTPException(status_code=502, detail=repo.last_database_error or "เพิ่มคณะไม่สำเร็จ")
                results.append({"id": str(saved["id"]), "name": name})
        return {"ok": True, "count": len(results), "items": results}

    # -----------------------------------------------------------------------
    # เกณฑ์รับ / รอบสมัคร
    # -----------------------------------------------------------------------
    @router.post("/admissions")
    async def ingest_admissions(
        request: Request,
        payload: dict[str, Any],
        x_webhook_secret: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _check_webhook(x_webhook_secret)
        require_db()
        items = _items(payload)
        if not items:
            raise HTTPException(status_code=422, detail="ไม่มีข้อมูลเกณฑ์รับ")
        if len(items) > MAX_ITEMS:
            raise HTTPException(status_code=422, detail=f"ส่งได้ครั้งละไม่เกิน {MAX_ITEMS} รายการ")
        results = []
        for item in items:
            institution = _clean(item.get("institution"))[:MAX_NAME]
            faculty = _clean(item.get("faculty"))[:MAX_NAME]
            round_name = _clean(item.get("round"))[:MAX_NAME]
            if not institution or not faculty or not round_name:
                raise HTTPException(status_code=422, detail="เกณฑ์รับต้องมี institution, faculty และ round")
            inst_id, _name = await upsert_institution({"name": institution, "tc_uid": _clean(item.get("tc_uid")) or None})
            record: dict[str, Any] = {
                "institution": institution,
                "faculty": faculty,
                "round": round_name,
                "criteria": _clean(item.get("criteria"))[:MAX_TEXT],
                "institution_id": int(inst_id),
                "updated_at": _now(),
            }
            for key, column in (("program", "program"), ("source_url", "source_url"), ("source_label", "source_label")):
                value = _clean(item.get(key))
                if value:
                    record[column] = value[:MAX_TEXT]
            deadline = _clean(item.get("deadline"))
            if deadline:
                record["deadline"] = deadline[:10]
            tc_uid = _clean(item.get("tc_uid")) or None
            if tc_uid:
                record["tc_uid"] = tc_uid
            if "is_published" in item:
                record["is_published"] = bool(item.get("is_published"))

            rows = None
            if tc_uid:
                rows = await repo.select("admissions", {"select": "id", "tc_uid": f"eq.{tc_uid}", "limit": "1"})
            if not rows:
                rows = await repo.select("admissions", {
                    "select": "id", "institution": f"eq.{institution}", "faculty": f"eq.{faculty}",
                    "round": f"eq.{round_name}", "limit": "1",
                })
            if rows:
                await repo.update("admissions", {"id": f"eq.{rows[0]['id']}"}, record)
                results.append({"id": str(rows[0]["id"]), "round": round_name})
            else:
                saved = await repo.insert_returning("admissions", record)
                if saved is None:
                    raise HTTPException(status_code=502, detail=repo.last_database_error or "เพิ่มเกณฑ์รับไม่สำเร็จ")
                results.append({"id": str(saved["id"]), "round": round_name})
        return {"ok": True, "count": len(results), "items": results}

    return router
