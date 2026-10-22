"""API สำหรับซิงก์ข้อมูล myTCAS และอ่านข้อมูลแบบละเอียด

- GET  /api/tcas/sync/status   — สถานะข้อมูลในฐานข้อมูล (ต้องล็อกอินและเป็นแอดมิน)
- POST /api/tcas/sync/run      — สั่งซิงก์ข้อมูลจาก myTCAS (แอดมินเท่านั้น)
- GET  /api/tcas/programs      — ค้นหาหลักสูตร + รอบรับสมัครจาก myTCAS (อ่านได้ทุกคน)
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .auth import require_admin
from .tcas_sync import (
    MYTCAS_SITE,
    ROUNDS_BATCH_LIMIT,
    admission_records,
    course_records,
    fetch_courses,
    fetch_rounds,
    fetch_universities,
    university_record,
)

MAX_LIMIT = 200


def build_router(repo: Any) -> APIRouter:
    router = APIRouter(prefix="/api/tcas")

    # ---------- ซิงก์ข้อมูล (แอดมินเท่านั้น) ----------
    @router.get("/sync/status")
    async def sync_status(request: Request) -> dict[str, Any]:
        await require_admin(request, repo)
        if not repo.configured:
            raise HTTPException(status_code=503, detail="Supabase ยังไม่ได้ตั้งค่า")
        counts: dict[str, int] = {}
        for table in ("institutions", "faculties", "admissions"):
            rows = await repo.select(table, {"select": "id", "limit": "10000"})
            counts[table] = len(rows) if rows is not None else 0
        latest = await repo.select("admissions", {"select": "updated_at", "order": "updated_at.desc", "limit": "1"})
        return {
            "counts": counts,
            "last_sync": latest[0]["updated_at"] if latest else None,
            "source": MYTCAS_SITE,
        }

    @router.post("/sync/run")
    async def sync_run(request: Request) -> dict[str, Any]:
        await require_admin(request, repo)
        from .tcas_sync import sync_all

        limit = ROUNDS_BATCH_LIMIT
        summary = await sync_all(repo, program_limit=limit)
        return {"ok": not summary.get("errors"), **summary}

    # ---------- อ่านข้อมูลสดจาก myTCAS (ไม่ต้องรอซิงก์) ----------
    @router.get("/programs")
    async def programs(q: str = "", limit: int = 60) -> dict[str, Any]:
        """ค้นหาหลักสูตรจาก myTCAS พร้อมรอบรับสมัคร — อ่านได้ทุกคน ไม่ต้องล็อกอิน"""
        import httpx

        needle = q.strip().lower()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, connect=10.0),
                headers={"User-Agent": "TCASBuddy/1.0", "Accept": "application/json"},
            ) as client:
                courses = await fetch_courses(client)
                matches = [
                    course for course in courses
                    if not needle or needle in (
                        f"{course.get('university_name_th', '')} {course.get('faculty_name_th', '')} "
                        f"{course.get('program_name_th', '')} {course.get('field_name_th', '')}"
                    ).lower()
                ]
                matches = matches[: max(1, min(limit, MAX_LIMIT))]
                program_ids = sorted({str(c.get("program_id")) for c in matches if c.get("program_id")})
                rounds_map = await fetch_rounds(client, program_ids)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"ดึงข้อมูล myTCAS ไม่สำเร็จ: {exc}") from None

        items: list[dict[str, Any]] = []
        for course in matches:
            pid = str(course.get("program_id") or "")
            rounds = rounds_map.get(pid, [])
            record = course_records([course])[0] if course_records([course]) else {}
            admissions = [
                {
                    "round": admission["round"],
                    "round_type": admission["round_type"],
                    "project_name": admission["project_name"],
                    "quota": admission["quota"],
                    "min_gpax": admission["min_gpax"],
                    "min_total_score": admission["min_total_score"],
                    "criteria": admission["criteria"],
                    "deadline": admission["deadline"],
                    "link": admission["source_url"],
                }
                for admission in admission_records(course, rounds)
            ]
            items.append({
                "program_id": pid,
                "university": course.get("university_name_th"),
                "university_en": course.get("university_name_en"),
                "faculty": course.get("faculty_name_th"),
                "campus": course.get("campus_name_th"),
                "program": course.get("program_name_th"),
                "field": course.get("field_name_th"),
                "degree": course.get("program_type_name_th"),
                "cost": course.get("cost"),
                "graduate_rate": course.get("graduate_rate"),
                "employment_rate": course.get("employment_rate"),
                "median_salary": course.get("median_salary"),
                "url": f"{MYTCAS_SITE}/courses/detail/{pid}",
                "rounds": admissions,
            })
        return {"items": items, "total": len(items), "source": MYTCAS_SITE}

    # ---------- รายชื่อมหาวิทยาลัยสดจาก myTCAS ----------
    @router.get("/universities/live")
    async def universities_live() -> dict[str, Any]:
        import httpx

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, connect=10.0),
                headers={"User-Agent": "TCASBuddy/1.0", "Accept": "application/json"},
            ) as client:
                data = await fetch_universities(client)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"ดึงข้อมูล myTCAS ไม่สำเร็จ: {exc}") from None
        items = [university_record(item) for item in data]
        return {"items": items, "total": len(items), "source": MYTCAS_SITE}

    return router
