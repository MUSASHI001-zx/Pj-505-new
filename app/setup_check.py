"""ตรวจว่าตารางที่ระบบต้องใช้พร้อมใช้งานหรือยัง — ใช้ในหน้าตั้งค่าและหน้าแอดมิน

เช็คผ่าน PostgREST จริง (อ่าน schema cache) ไม่ใช่เดาจากชื่อไฟล์
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request

from .auth import database_error, require_database

# ตาราง -> migration ที่ต้องรันเพื่อให้ได้
# (ไม่มี tcas_news แล้ว — ข่าวดึงสดจาก myTCAS ผ่าน app/tcas_news.py ไม่ต้องใช้ตาราง)
REQUIRED_TABLES: dict[str, str] = {
    "user_settings": "006_account.sql",
    "invite_links": "006_account.sql",
    "community_tags": "007_community.sql",
    "community_posts": "007_community.sql",
    "community_post_options": "007_community.sql",
    "community_comments": "007_community.sql",
    "community_post_likes": "007_community.sql",
    "community_post_votes": "007_community.sql",
    "tickets": "007_community.sql",
    "ticket_messages": "007_community.sql",
    "admin_presence": "007_community.sql",
    "faculties": "009_tcas_ingest.sql",
    "admissions": "008_admin.sql",
    "admin_audit_log": "008_admin.sql",
    "notebooks": "012_tutor_notebooks.sql",
    "notebook_sources": "012_tutor_notebooks.sql",
    "tutor_messages": "012_tutor_notebooks.sql",
}

# คอลัมน์ที่ต้องมีในตาราง users เพื่อให้ระบบหลังบ้านทำงานได้
REQUIRED_USER_COLUMNS = ("is_admin", "is_disabled")

# คอลัมน์อื่นที่ต้องมี — ตาราง -> (คอลัมน์, migration)
REQUIRED_OTHER_COLUMNS: dict[str, tuple[tuple[str, ...], str]] = {
    "community_comments": (("author_avatar",), "010_comment_avatar.sql"),
}


def build_router(repo: Any) -> APIRouter:
    router = APIRouter(prefix="/api/setup")

    @router.get("/status")
    async def setup_status(request: Request) -> dict[str, Any]:
        """รายงานว่าตาราง/คอลัมน์ที่จำเป็นพร้อมใช้งานหรือยัง"""
        if not repo.configured:
            return {
                "ok": False,
                "reason": "ยังไม่ได้ตั้งค่า Supabase ฝั่งเซิร์ฟเวอร์",
                "missing_tables": list(REQUIRED_TABLES),
                "missing_columns": [],
            }

        missing_tables: dict[str, str] = {}
        # เช็คทีเดียวเป็น parallel — ตาราง 15 ตัวถ้าไล่ทีละอันจะช้ามาก
        names = list(REQUIRED_TABLES)
        results = await asyncio.gather(
            *(repo.select(table, {"select": "*", "limit": "1"}) for table in names),
            return_exceptions=True,
        )
        for table, result in zip(names, results):
            if result is None or isinstance(result, Exception):
                missing_tables[table] = REQUIRED_TABLES[table]

        missing_columns: dict[str, str] = {}
        column_results = await asyncio.gather(
            *(repo.column_exists("users", column) for column in REQUIRED_USER_COLUMNS)
        )
        for column, exists in zip(REQUIRED_USER_COLUMNS, column_results):
            if not exists:
                missing_columns[f"users.{column}"] = "008_admin.sql"

        # คอลัมน์ของตารางอื่น (เช่น รูปโปรไฟล์ของความคิดเห็น)
        other_checks = [
            (table, column, migration)
            for table, (columns, migration) in REQUIRED_OTHER_COLUMNS.items()
            for column in columns
        ]
        if other_checks:
            results = await asyncio.gather(
                *(repo.column_exists(table, column) for table, column, _ in other_checks)
            )
            for (table, column, migration), exists in zip(other_checks, results):
                if not exists:
                    missing_columns[f"{table}.{column}"] = migration

        # migration ที่ต้องรัน (เรียงตามลำดับเลขไฟล์)
        migrations = sorted({*missing_tables.values(), *missing_columns.values()})
        ready = not missing_tables and not missing_columns
        return {
            "ok": ready,
            "ready": ready,
            "missing_tables": missing_tables,
            "missing_columns": missing_columns,
            "migrations_to_run": migrations,
            "message": (
                "ระบบพร้อมใช้งานครบแล้ว"
                if ready
                else "ยังไม่ได้รัน migration: " + ", ".join(migrations)
            ),
        }

    return router
