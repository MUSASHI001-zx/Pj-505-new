"""ระบบข้อสอบจำลองอาชีพ (หน้า Identity Discovery)

- GET    /api/identity/careers         รายการอาชีพ + หมวด + สถานการณ์จำลอง (ไม่ต้องล็อกอิน)
- GET    /api/identity/discover        คำถามแบบสำรวจภาพรวม 18 ข้อ (ไม่ผูกกับอาชีพ)
- POST   /api/identity/discover/evaluate  สรุปผลแบบสำรวจภาพรวม ไม่บันทึก
- POST   /api/identity/discover/results   สรุปผลแบบสำรวจภาพรวมแล้วบันทึก (ต้องล็อกอิน; เก็บเป็น career_id = "discover")
- POST   /api/identity/profile         สรุปรวมจากคำตอบดิบที่ส่งมา (ผู้เยี่ยมชมใช้ — ไม่บันทึก)
- GET    /api/identity/profile         สรุปรวมจากผลที่บันทึกไว้ของผู้ใช้ที่ล็อกอิน
- POST   /api/identity/evaluate        คำนวณผลสรุป ไม่บันทึก (ไม่ต้องล็อกอิน — ผู้เยี่ยมชมก็เล่นได้)
- POST   /api/identity/results         คำนวณผลแล้วบันทึกให้ผู้ใช้ที่ล็อกอิน
- GET    /api/identity/results         ประวัติผลของตัวเอง (หน้าเว็บสรุปรวมหลายอาชีพเอง)
- DELETE /api/identity/results/{id}    ลบผลของตัวเอง

คะแนนคำนวณฝั่งเซิร์ฟเวอร์จาก "คำตอบดิบ" เท่านั้น ไม่เชื่อคะแนนที่ client ส่งมา
เก็บในตาราง public.identity_simulation_results (migration 016) แยกตาม open_id ของผู้ใช้
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .auth import database_error, require_database, require_user
from .identity_data import (
    IdentityInputError,
    build_profile,
    evaluate,
    evaluate_discover,
    public_careers,
    public_discover,
)
from .identity_extra import GROUPS

TABLE = "identity_simulation_results"
HISTORY_LIMIT = 50
ID_RE = re.compile(r"^[0-9a-fA-F-]{8,40}$")


def _body_fields(body: Any) -> tuple[Any, Any, Any]:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="รูปแบบข้อมูลไม่ถูกต้อง")
    return body.get("career_id"), body.get("answers"), body.get("enjoyment")


def _run(body: Any) -> tuple[dict[str, Any], list[int]]:
    career_id, answers, enjoyment = _body_fields(body)
    try:
        result = evaluate(career_id, answers, enjoyment)
    except IdentityInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return result, list(answers)


def _json_body_error() -> HTTPException:
    return HTTPException(status_code=400, detail="รูปแบบข้อมูลไม่ถูกต้อง")


def _profile_or_422(entries: Any, discover: Any) -> dict[str, Any]:
    try:
        return build_profile(entries, discover)
    except IdentityInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def _entries_from_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Any]:
    """แปลงแถวที่บันทึกไว้เป็นคำตอบดิบ (ใหม่สุดก่อน) — ข้ามแถวที่ใช้ไม่ได้ เช่น ข้อมูลอาชีพเปลี่ยนไปแล้ว"""
    entries: list[dict[str, Any]] = []
    discover: Any = None
    for row in rows:
        if row.get("career_id") == "discover":
            if discover is None:
                try:
                    evaluate_discover(row.get("answers"))
                    discover = row.get("answers")
                except IdentityInputError:
                    pass
            continue
        entry = {"career_id": row.get("career_id"), "answers": row.get("answers"), "enjoyment": (row.get("result") or {}).get("enjoyment")}
        try:
            evaluate(entry["career_id"], entry["answers"], entry["enjoyment"])
        except IdentityInputError:
            continue
        entries.append(entry)
    return entries, discover


def _row_to_result(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row.get("result") or {})
    result["id"] = row.get("id")
    result["created_at"] = row.get("created_at")
    return result


def build_router(repo: Any) -> APIRouter:
    router = APIRouter(prefix="/api/identity")

    @router.get("/careers")
    async def careers() -> dict[str, Any]:
        return {
            "careers": public_careers(),
            "groups": [{"id": key, "label": label} for key, label in GROUPS.items()],
        }

    @router.get("/discover")
    async def discover_questions() -> dict[str, Any]:
        return {"questions": public_discover()}

    @router.post("/discover/evaluate")
    async def discover_evaluate(request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError:
            raise _json_body_error() from None
        if not isinstance(body, dict):
            raise _json_body_error()
        try:
            result = evaluate_discover(body.get("answers"))
        except IdentityInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return {"result": result, "saved": False}

    @router.post("/discover/results", status_code=201)
    async def discover_save(request: Request) -> dict[str, Any]:
        user = await require_user(request, repo)
        require_database(repo)
        try:
            body = await request.json()
        except ValueError:
            raise _json_body_error() from None
        if not isinstance(body, dict):
            raise _json_body_error()
        try:
            result = evaluate_discover(body.get("answers"))
        except IdentityInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        row = await repo.insert_returning(TABLE, {
            "open_id": user["id"],
            "career_id": "discover",
            "answers": result["answers"],
            "result": result,
        })
        if row is None:
            raise database_error(repo, "บันทึกผลไม่สำเร็จ")
        result["id"] = row.get("id")
        result["created_at"] = row.get("created_at")
        return {"result": result, "saved": True}

    @router.post("/profile")
    async def profile_from_answers(request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError:
            raise _json_body_error() from None
        if not isinstance(body, dict):
            raise _json_body_error()
        return {"profile": _profile_or_422(body.get("entries"), body.get("discover"))}

    @router.get("/profile")
    async def my_profile(request: Request) -> dict[str, Any]:
        user = await require_user(request, repo)
        require_database(repo)
        rows = await repo.select(TABLE, {
            "select": "id,career_id,answers,result,created_at",
            "open_id": f"eq.{user['id']}",
            "order": "created_at.desc",
            "limit": str(HISTORY_LIMIT),
        })
        if rows is None:
            raise database_error(repo, "โหลดประวัติไม่สำเร็จ")
        entries, discover = _entries_from_rows(rows)
        return {"profile": _profile_or_422(entries[:30], discover)}

    @router.post("/evaluate")
    async def evaluate_only(request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(status_code=400, detail="รูปแบบข้อมูลไม่ถูกต้อง") from None
        result, _ = _run(body)
        return {"result": result, "saved": False}

    @router.post("/results", status_code=201)
    async def save_result(request: Request) -> dict[str, Any]:
        user = await require_user(request, repo)
        require_database(repo)
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(status_code=400, detail="รูปแบบข้อมูลไม่ถูกต้อง") from None
        result, answers = _run(body)
        row = await repo.insert_returning(TABLE, {
            "open_id": user["id"],
            "career_id": result["career_id"],
            "answers": answers,
            "result": result,
        })
        if row is None:
            raise database_error(repo, "บันทึกผลไม่สำเร็จ")
        result["id"] = row.get("id")
        result["created_at"] = row.get("created_at")
        return {"result": result, "saved": True}

    @router.get("/results")
    async def my_results(request: Request) -> dict[str, Any]:
        user = await require_user(request, repo)
        require_database(repo)
        rows = await repo.select(TABLE, {
            "select": "id,career_id,result,created_at",
            "open_id": f"eq.{user['id']}",
            "order": "created_at.desc",
            "limit": str(HISTORY_LIMIT),
        })
        if rows is None:
            raise database_error(repo, "โหลดประวัติไม่สำเร็จ")
        results = [_row_to_result(row) for row in rows]
        return {"results": results}

    @router.delete("/results/{result_id}")
    async def delete_result(result_id: str, request: Request) -> dict[str, Any]:
        user = await require_user(request, repo)
        require_database(repo)
        if not ID_RE.match(result_id):
            raise HTTPException(status_code=404, detail="ไม่พบผลที่ต้องการลบ")
        # ต้องกรอง open_id ด้วยเสมอ เพื่อไม่ให้ลบผลของคนอื่นได้
        ok = await repo.delete(TABLE, {"id": f"eq.{result_id}", "open_id": f"eq.{user['id']}"})
        if not ok:
            raise database_error(repo, "ลบผลไม่สำเร็จ")
        return {"ok": True}

    return router
