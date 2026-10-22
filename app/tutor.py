"""AI Tutor / Notebook — สมุดโน้ตเรียนรายวิชา คุยกับ AI ในบริบทของสมุด

ผู้ใช้แต่ละคนมีสมุดโน้ตแยกตามวิชา (TCAS / A-Level / TPAT / TOEIC)
ในแต่ละสมุดเก็บบทเรียนที่เขียนเองหรือให้ AI สรุป รวมถึงประวัติคุยกับ AI

ทุก endpoint ต้องมี Bearer token — ตรวจผู้ใช้จาก Supabase Auth ก่อนเข้าถึงข้อมูล
"""
from __future__ import annotations

import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request

from .ai_chat import (
    DEFAULT_MODELS,
    SYSTEM_PROMPT,
    _clean_messages,
    _env,
    detect_provider,
    main_model,
)
from .auth import require_user

SUBJECTS = ("TCAS", "A-Level", "TPAT", "TOEIC")
MAX_SOURCE_LENGTH = 20000
MAX_MESSAGE_LENGTH = 4000
MAX_CONTEXT_SOURCES = 6  # จำนวนบทเรียนที่ส่งเป็นบริบทให้ AI
MAX_HISTORY = 12

# คำถามตัวอย่างสำหรับหน้าแรกของแต่ละวิชา
STARTER_QUESTIONS = {
    "TCAS": [
        "สรุปเกณฑ์การคัดเลือกรอบ 1 ให้สั้น ๆ หน่อย",
        "ผมควรเตรียมเอกสารอะไรบ้างก่อนสมัคร",
        "อธิบายเกณฑ์ GPA 10 วิชาใช้ยังไง",
    ],
    "A-Level": [
        "สรุปวิชาที่ต้องเน้นสำหรับสายวิทยาศาสตร์",
        "ช่วยอธิบายแนวคิดที่มักสับสนใน A-Level",
        "วางแผนอ่าน A-Level 3 เดือนก่อนสอบ",
    ],
    "TPAT": [
        "TPAT ประกอบด้วยอะไรบ้าง",
        "ช่วยฝึกทำข้อความแนะนำตัวเอง",
        "วิธีเตรียมตัวสอบ TPAT 1 อาทิตย์",
    ],
    "TOEIC": [
        "สรุปโครงสร้างข้อสอบ TOEIC",
        "ช่วยฝึกคำศัพท์ที่ออกบ่อย",
        "แนะนำแผนอ่าน TOEIC 2 เดือน",
    ],
}


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _subject(value: str) -> str:
    """ตรวจว่าวิชาถูกต้องไหม — คืนค่าเริ่มต้นถ้าไม่รู้จัก"""
    text = _text(value)
    for subject in SUBJECTS:
        if text.lower() == subject.lower():
            return subject
    return "TCAS"


def build_router(repo: Any) -> APIRouter:
    router = APIRouter(prefix="/api/tutor")

    # ---------- ตรวจสิทธิ์ผู้ใช้ ----------
    async def current_user(request: Request) -> dict[str, Any]:
        if not repo.configured:
            raise HTTPException(status_code=503, detail="Supabase ยังไม่ได้ตั้งค่า")
        user = await require_user(request, repo)
        if not repo.column_exists("users", "openId"):
            raise HTTPException(status_code=503, detail="ระบบบัญชียังไม่พร้อมใช้งาน")
        return user

    # ---------- สมุดโน้ต ----------
    async def get_notebook(open_id: str, subject: str) -> dict[str, Any] | None:
        rows = await repo.select(
            "notebooks",
            {"select": "*", "open_id": f"eq.{open_id}", "subject": f"eq.{subject}", "limit": "1"},
        )
        return rows[0] if rows else None

    async def ensure_notebook(open_id: str, subject: str) -> dict[str, Any]:
        """คืนสมุดของวิชานั้น — สร้างใหม่ถ้ายังไม่มี"""
        notebook = await get_notebook(open_id, subject)
        if notebook:
            return notebook
        record = {
            "open_id": open_id,
            "title": f"สมุดโน้ต {subject}",
            "subject": subject,
            "description": "",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        saved = await repo.insert_returning("notebooks", record)
        if saved is None:
            raise HTTPException(status_code=503, detail=repo.last_database_error or "สร้างสมุดโน้ตไม่สำเร็จ")
        return saved

    # ---------- API ----------
    @router.get("/notebooks")
    async def list_notebooks(request: Request) -> dict[str, Any]:
        """สมุดโน้ตทั้งหมดของผู้ใช้ พร้อมจำนวนบทเรียนในแต่ละสมุด"""
        user = await current_user(request)
        open_id = user["id"]
        notebooks = await repo.select(
            "notebooks",
            {"select": "*", "open_id": f"eq.{open_id}", "order": "subject", "limit": "20"},
        )
        if notebooks is None:
            raise HTTPException(status_code=503, detail=repo.last_database_error or "อ่านสมุดโน้ตไม่สำเร็จ")

        counts: dict[int, int] = {}
        if notebooks:
            ids = [str(item["id"]) for item in notebooks]
            rows = await repo.select(
                "notebook_sources", {"select": "notebook_id", "notebook_id": f"in.({','.join(ids)})", "limit": "2000"}
            )
            for row in rows or []:
                key = int(row["notebook_id"])
                counts[key] = counts.get(key, 0) + 1

        items = []
        for notebook in notebooks:
            items.append({
                "id": notebook["id"],
                "title": notebook.get("title") or f"สมุดโน้ต {notebook.get('subject')}",
                "subject": notebook.get("subject") or "TCAS",
                "description": notebook.get("description") or "",
                "source_count": counts.get(int(notebook["id"]), 0),
                "updated_at": notebook.get("updated_at"),
            })

        # สร้างสมุดให้ครบทุกวิชาให้อัตโนมัติ (ผู้ใช้ยังไม่ต้องทำอะไร)
        existing = {item["subject"] for item in items}
        for subject in SUBJECTS:
            if subject not in existing:
                notebook = await ensure_notebook(open_id, subject)
                items.append({
                    "id": notebook["id"],
                    "title": notebook.get("title"),
                    "subject": subject,
                    "description": "",
                    "source_count": 0,
                    "updated_at": notebook.get("updated_at"),
                })
        items.sort(key=lambda item: SUBJECTS.index(item["subject"]) if item["subject"] in SUBJECTS else 99)
        return {
            "items": items,
            "subjects": list(SUBJECTS),
            "starter_questions": STARTER_QUESTIONS,
        }

    @router.get("/notebooks/{subject}")
    async def get_notebook_detail(subject: str, request: Request) -> dict[str, Any]:
        """สมุดโน้ต + บทเรียนทั้งหมดในสมุดนั้น"""
        user = await current_user(request)
        open_id = user["id"]
        subject_key = _subject(subject)
        notebook = await ensure_notebook(open_id, subject_key)
        sources = await repo.select(
            "notebook_sources",
            {"select": "*", "notebook_id": f"eq.{notebook['id']}", "order": "created_at.desc", "limit": "100"},
        )
        return {
            "notebook": {
                "id": notebook["id"],
                "title": notebook.get("title"),
                "subject": subject_key,
                "description": notebook.get("description") or "",
                "updated_at": notebook.get("updated_at"),
            },
            "sources": [
                {
                    "id": item["id"],
                    "title": item.get("title") or "",
                    "content": item.get("content") or "",
                    "source_url": item.get("source_url"),
                    "kind": item.get("kind") or "note",
                    "is_ai_generated": bool(item.get("is_ai_generated")),
                    "created_at": item.get("created_at"),
                }
                for item in (sources or [])
            ],
            "starter_questions": STARTER_QUESTIONS.get(subject_key, []),
        }

    @router.post("/notebooks/{subject}/sources")
    async def create_source(subject: str, request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        """เพิ่มบทเรียน/เนื้อหาลงสมุด (เขียนเอง หรือให้ AI สรุปก็ได้)"""
        user = await current_user(request)
        open_id = user["id"]
        subject_key = _subject(subject)
        notebook = await ensure_notebook(open_id, subject_key)

        title = _text(payload.get("title"))
        content = _text(payload.get("content"))
        if not title:
            raise HTTPException(status_code=400, detail="กรุณาใส่หัวข้อ")
        if not content:
            raise HTTPException(status_code=400, detail="กรุณาใส่เนื้อหา")

        record = {
            "notebook_id": notebook["id"],
            "title": title[:300],
            "content": content[:MAX_SOURCE_LENGTH],
            "source_url": _text(payload.get("source_url")) or None,
            "kind": _text(payload.get("kind")) or "note",
            "is_ai_generated": bool(payload.get("is_ai_generated")),
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        saved = await repo.insert_returning("notebook_sources", record)
        if saved is None:
            raise HTTPException(status_code=503, detail=repo.last_database_error or "บันทึกบทเรียนไม่สำเร็จ")
        return {"ok": True, "source": {"id": saved["id"], **record}}

    @router.delete("/sources/{source_id}")
    async def delete_source(source_id: int, request: Request) -> dict[str, Any]:
        """ลบบทเรียน (เฉพาะของตัวเอง)"""
        user = await current_user(request)
        open_id = user["id"]
        rows = await repo.select(
            "notebook_sources",
            {"select": "id,notebook_id", "id": f"eq.{source_id}", "limit": "1"},
        )
        if not rows:
            raise HTTPException(status_code=404, detail="ไม่พบบทเรียนนี้")
        notebook_id = rows[0]["notebook_id"]
        owned = await repo.select(
            "notebooks", {"select": "id", "id": f"eq.{notebook_id}", "open_id": f"eq.{open_id}", "limit": "1"}
        )
        if not owned:
            raise HTTPException(status_code=403, detail="ลบไม่ได้ เพราะไม่ใช่สมุดของคุณ")
        ok = await repo.delete("notebook_sources", {"id": f"eq.{source_id}"})
        if not ok:
            raise HTTPException(status_code=503, detail=repo.last_database_error or "ลบบทเรียนไม่สำเร็จ")
        return {"ok": True}

    @router.get("/notebooks/{subject}/messages")
    async def list_messages(subject: str, request: Request) -> dict[str, Any]:
        """ประวัติคุยกับ AI ในสมุดนั้น"""
        user = await current_user(request)
        open_id = user["id"]
        subject_key = _subject(subject)
        notebook = await get_notebook(open_id, subject_key)
        if not notebook:
            return {"items": []}
        rows = await repo.select(
            "tutor_messages",
            {"select": "*", "notebook_id": f"eq.{notebook['id']}", "order": "created_at.desc", "limit": str(MAX_HISTORY)},
        )
        items = [
            {
                "id": row["id"],
                "role": row.get("role"),
                "content": row.get("content") or "",
                "model": row.get("model") or "",
                "created_at": row.get("created_at"),
            }
            for row in reversed(rows or [])
        ]
        return {"items": items}

    @router.post("/notebooks/{subject}/chat")
    async def chat(subject: str, request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        """คุยกับ AI ในบริบทของสมุด — AI จะเห็นบทเรียนในสมุดนั้นด้วย"""
        user = await current_user(request)
        open_id = user["id"]
        subject_key = _subject(subject)
        message = _text(payload.get("message"))
        if not message:
            raise HTTPException(status_code=400, detail="กรุณาพิมพ์คำถามก่อนนะ")
        message = message[:MAX_MESSAGE_LENGTH]

        provider = detect_provider()
        if not provider:
            return {
                "configured": False,
                "answer": "",
                "error": "ยังไม่ได้เชื่อมต่อบริการ AI — เจ้าหน้าที่ต้องตั้งค่า API key",
            }

        notebook = await ensure_notebook(open_id, subject_key)
        model = main_model(provider)

        # บริบทจากบทเรียนในสมุด
        sources = await repo.select(
            "notebook_sources",
            {"select": "title,content", "notebook_id": f"eq.{notebook['id']}", "order": "created_at.desc", "limit": str(MAX_CONTEXT_SOURCES)},
        )
        context_blocks = []
        for item in sources or []:
            title = _text(item.get("title"))
            content = _text(item.get("content"))
            if content:
                context_blocks.append(f"### {title}\n{content[:4000]}")

        # ประวัติคุยก่อนหน้า
        history_rows = await repo.select(
            "tutor_messages",
            {"select": "role,content", "notebook_id": f"eq.{notebook['id']}", "order": "created_at.desc", "limit": str(MAX_HISTORY)},
        )
        history = [
            {"role": row.get("role"), "content": row.get("content")}
            for row in reversed(history_rows or [])
            if row.get("role") in ("user", "assistant") and row.get("content")
        ]
        history = _clean_messages(history)

        system = SYSTEM_PROMPT
        if context_blocks:
            system += (
                "\n\n---\n"
                "นี่คือบทเรียน/เนื้อหาที่ผู้เรียนเก็บไว้ในสมุดโน้ตวิชา "
                f"{subject_key} (เรียกว่า 'สมุดโน้ต') ให้ยึดเป็นหลักในการตอบ "
                "และอ้างอิงเนื้อหาในสมุดเมื่อเกี่ยวข้อง\n\n"
                + "\n\n".join(context_blocks)
            )

        messages = [*history, {"role": "user", "content": message}]
        answer = ""
        error = ""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                from .ai_chat import CALLERS
                answer = await CALLERS[provider](client, model["key"], [{"role": "system", "content": system}, *messages])
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                detail = exc.response.text[:250]
            except Exception:  # noqa: BLE001
                pass
            error = f"บริการ AI ตอบกลับผิดพลาด ({exc.response.status_code}): {detail}"
        except (httpx.HTTPError, ValueError) as exc:
            error = f"ติดต่อบริการ AI ไม่สำเร็จ: {str(exc).strip() or type(exc).__name__}"

        # บันทึกประวัติ (บันทึกข้อความผู้ใช้เสมอ แม้ AI จะตอบไม่ได้ เพื่อไม่ให้หลุดคำถาม)
        stamp = _now_iso()
        await repo.insert("tutor_messages", {
            "open_id": open_id, "notebook_id": notebook["id"], "role": "user",
            "content": message, "model": model["key"], "created_at": stamp,
        })
        if answer:
            await repo.insert("tutor_messages", {
                "open_id": open_id, "notebook_id": notebook["id"], "role": "assistant",
                "content": answer, "model": model["key"], "created_at": _now_iso(),
            })

        return {
            "configured": True,
            "answer": answer,
            "error": error,
            "model": model["key"],
            "model_label": model["label"],
            "context_count": len(context_blocks),
        }

    @router.post("/notebooks/{subject}/summarize")
    async def summarize(subject: str, request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        """ให้ AI สรุปเนื้อหาที่ผู้ใช้วางไว้ แล้วบันทึกเป็นบทเรียนในสมุด"""
        user = await current_user(request)
        open_id = user["id"]
        subject_key = _subject(subject)
        notebook = await ensure_notebook(open_id, subject_key)

        source_text = _text(payload.get("content"))
        title = _text(payload.get("title")) or f"สรุป {subject_key}"
        if not source_text:
            raise HTTPException(status_code=400, detail="กรุณาใส่เนื้อหาที่ต้องการให้สรุป")

        provider = detect_provider()
        if not provider:
            raise HTTPException(status_code=503, detail="ยังไม่ได้เชื่อมต่อบริการ AI")

        model = main_model(provider)
        prompt = (
            f"สรุปเนื้อหาด้านล่างให้เป็นบทเรียนสำหรับวิชา {subject_key} "
            "ให้เข้าใจง่าย เน้นประเด็นสำคัญ ใช้รายการย่อย และปิดท้ายด้วยสิ่งที่ควรจำ\n\n"
            f"---\n{source_text[:MAX_SOURCE_LENGTH]}"
        )
        answer = ""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                from .ai_chat import CALLERS
                answer = await CALLERS[provider](client, model["key"], [{"role": "user", "content": prompt}])
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=502, detail=f"บริการ AI ตอบกลับผิดพลาด ({exc.response.status_code})") from None
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"ติดต่อบริการ AI ไม่สำเร็จ: {exc}") from None

        if not answer:
            raise HTTPException(status_code=502, detail="บริการ AI ไม่ได้ส่งคำตอบกลับมา")

        record = {
            "notebook_id": notebook["id"],
            "title": title[:300],
            "content": answer[:MAX_SOURCE_LENGTH],
            "source_url": _text(payload.get("source_url")) or None,
            "kind": "summary",
            "is_ai_generated": True,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        saved = await repo.insert_returning("notebook_sources", record)
        if saved is None:
            raise HTTPException(status_code=503, detail=repo.last_database_error or "บันทึกบทเรียนไม่สำเร็จ")
        return {"ok": True, "source": {"id": saved["id"], **record}}

    return router
