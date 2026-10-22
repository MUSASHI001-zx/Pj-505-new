"""ศูนย์จัดการแอดมิน: ผู้ใช้และสิทธิ์, กระทู้ชุมชน (moderation), มหาวิทยาลัยและเกณฑ์รับ, และคิว Ticket.

ทุก endpoint ต้องผ่าน require_admin — เข้าถึงได้เฉพาะแอดมินเท่านั้น (service role อยู่ฝั่ง backend เท่านั้น)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import database_error, is_admin, log_admin_action, require_database, require_user
from .ticket_cleanup import build_helpers as build_ticket_helpers

TICKET_STATUSES = ("open", "answered", "closed")
STATUS_LABELS = {"open": "รอแอดมินตอบ", "answered": "ตอบแล้ว", "closed": "ปิดแล้ว"}
USER_ROLES = ("student", "parents", "teacher", "admin")
ROLE_LABELS = {"student": "นักเรียน", "parents": "ผู้ปกครอง", "teacher": "คุณครู", "admin": "แอดมิน"}
INSTITUTION_KINDS = ("รัฐ", "เอกชน", "ราชมงคล", "นานาชาติ", "อื่น ๆ")
MAX_NAME = 120
MAX_LIMIT = 200


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def build_router(repo: Any) -> APIRouter:
    router = APIRouter(prefix="/api/admin")

    # ล้างข้อมูลตั๋วที่ปิดแล้ว (ใช้ร่วมกับ tickets.py)
    _cleanup = build_ticket_helpers(repo)
    purge_ticket = _cleanup["purge_ticket"]
    purge_closed_tickets = _cleanup["purge_closed_tickets"]

    # ---------- helpers ----------
    async def admin_user(request: Request) -> dict[str, Any]:
        user = await require_user(request, repo)
        require_database(repo)
        if not await is_admin(repo, user["id"], user.get("email")):
            raise HTTPException(status_code=403, detail="ต้องเป็นแอดมินเท่านั้น")
        return user

    async def role_column() -> str:
        return await repo.user_role_column()

    async def user_columns(extra: list[str] | None = None) -> str:
        """สร้างรายการคอลัมน์ที่ใช้ได้จริง — ข้ามคอลัมน์ที่ยังไม่ได้ migration มา"""
        column = await role_column()
        columns = ["id", "openId", "name", "email", column, "lastSignedIn"]
        for name in extra or []:
            if name not in columns and await repo.column_exists("users", name):
                columns.append(name)
        # บทบาทอาจอยู่คอลัมน์ role หรือ accountRole — เอาค่าที่มีจริงเข้ามาให้ครบ
        if column not in columns:
            columns.append(column)
        return ",".join(dict.fromkeys(columns))

    # =====================================================================
    # ภาพรวม
    # =====================================================================
    @router.get("/stats")
    async def stats(request: Request) -> dict[str, Any]:
        await admin_user(request)
        column = await role_column()
        users = await repo.select("users", {"select": f"openId,{column}", "limit": "5000"})
        posts = await repo.select("community_posts", {"select": "id", "limit": "5000"})
        tickets = await repo.select("tickets", {"select": "status", "limit": "5000"})
        by_role: dict[str, int] = {}
        for row in users or []:
            key = row.get(column) or "student"
            by_role[key] = by_role.get(key, 0) + 1
        ticket_counts: dict[str, int] = {key: 0 for key in TICKET_STATUSES}
        for row in tickets or []:
            key = row.get("status")
            if key in ticket_counts:
                ticket_counts[key] += 1
        views = await repo._count("page_views")
        online = await repo._count("online_visitors", {"last_seen": f"gt.{(_now() - timedelta(minutes=2)).isoformat()}"})
        return {
            "users": len(users or []),
            "users_by_role": by_role,
            "posts": len(posts or []),
            "tickets": ticket_counts,
            "views": views,
            "online": online,
        }

    @router.get("/audit")
    async def audit_log(request: Request, limit: int = 50) -> dict[str, Any]:
        await admin_user(request)
        rows = await repo.select("admin_audit_log", {
            "select": "id,actor_name,action,target_type,target_id,detail,created_at",
            "order": "id.desc", "limit": str(max(1, min(limit, MAX_LIMIT))),
        })
        return {"items": rows or []}

    # =====================================================================
    # ผู้ใช้ + สิทธิ์
    # =====================================================================
    @router.get("/users")
    async def list_users(request: Request, q: str = "", limit: int = 100) -> dict[str, Any]:
        await admin_user(request)
        column = await role_column()
        select = await user_columns(["is_admin", "is_disabled"])
        params: dict[str, str] = {
            "select": select,
            "order": "lastSignedIn.desc", "limit": str(max(1, min(limit, MAX_LIMIT))),
        }
        needle = q.strip()
        if needle:
            safe = needle.replace(",", " ").replace("(", " ").replace(")", " ").replace("*", " ").strip()
            if safe:
                params["or"] = f"(name.ilike.*{safe}*,email.ilike.*{safe}*)"
        rows = await repo.select("users", params)
        if rows is None:
            raise database_error(repo, "อ่านรายชื่อผู้ใช้ไม่สำเร็จ")

        # รวมข้อมูลจาก user_settings (ชื่อที่ผู้ใช้ตั้งเอง, คณะที่สนใจ) และจำนวนกระทู้/Ticket
        open_ids = [row.get("openId") for row in rows if row.get("openId")]
        settings: dict[str, dict[str, Any]] = {}
        if open_ids:
            found = await repo.select("user_settings", {
                "select": "open_id,display_name,school,grade_level,interested_faculties",
                "open_id": f"in.({','.join(open_ids)})", "limit": str(MAX_LIMIT),
            })
            for row in found or []:
                settings[row["open_id"]] = row
        post_counts: dict[str, int] = {}
        if open_ids:
            posts = await repo.select("community_posts", {
                "select": "open_id", "open_id": f"in.({','.join(open_ids)})", "limit": "5000",
            })
            for row in posts or []:
                key = row.get("open_id")
                post_counts[key] = post_counts.get(key, 0) + 1
        ticket_counts: dict[str, int] = {}
        if open_ids:
            tickets = await repo.select("tickets", {
                "select": "open_id,status", "open_id": f"in.({','.join(open_ids)})", "limit": "5000",
            })
            for row in tickets or []:
                key = row.get("open_id")
                ticket_counts[key] = ticket_counts.get(key, 0) + 1

        items = []
        for row in rows:
            open_id = row.get("openId")
            setting = settings.get(open_id, {})
            role = row.get(column) or "student"
            items.append({
                "open_id": open_id,
                "name": setting.get("display_name") or row.get("name") or "(ไม่มีชื่อ)",
                "account_name": row.get("name"),
                "email": row.get("email") or "",
                "role": role,
                "role_label": ROLE_LABELS.get(role, role),
                "is_admin": bool(row.get("is_admin")),
                "is_disabled": bool(row.get("is_disabled")),
                "school": setting.get("school") or "",
                "grade_level": setting.get("grade_level") or "",
                "faculties": setting.get("interested_faculties") or [],
                "posts": post_counts.get(open_id, 0),
                "tickets": ticket_counts.get(open_id, 0),
                "last_signed_in": row.get("lastSignedIn"),
            })
        return {"items": items, "roles": ROLE_LABELS, "total": len(items)}

    @router.post("/users/{open_id}/role")
    async def set_user_role(request: Request, open_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        actor = await admin_user(request)
        role = _clean(payload.get("role"))
        if role not in USER_ROLES:
            raise HTTPException(status_code=400, detail="บทบาทไม่ถูกต้อง")
        column = await role_column()
        if not await repo.update("users", {"openId": f"eq.{open_id}"}, {column: role}):
            raise database_error(repo, "อัปเดตบทบาทไม่สำเร็จ")
        await log_admin_action(repo, actor, "เปลี่ยนบทบาท", "user", open_id, f"เปลี่ยนเป็น {ROLE_LABELS.get(role, role)}")
        return {"ok": True, "role": role}

    @router.post("/users/{open_id}/admin")
    async def set_admin_flag(request: Request, open_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """แต่งตั้ง/ถอดสิทธิ์แอดมิน — ต้องมีคอลัมน์ users.is_admin (migration 008)"""
        actor = await admin_user(request)
        if not await repo.column_exists("users", "is_admin"):
            raise HTTPException(status_code=503, detail="ยังไม่ได้รัน supabase/migrations/008_admin.sql")
        grant = bool(payload.get("is_admin"))
        if not grant:
            # กันไม่ให้ถอดสิทธิ์ตัวเองจนติดล็อกระบบ
            if open_id == actor["id"]:
                raise HTTPException(status_code=400, detail="ถอดสิทธิ์แอดมินของตัวเองไม่ได้")
        if not await repo.update("users", {"openId": f"eq.{open_id}"}, {"is_admin": grant}):
            raise database_error(repo, "อัปเดตสิทธิ์แอดมินไม่สำเร็จ")
        await log_admin_action(repo, actor, "เปลี่ยนสิทธิ์แอดมิน", "user", open_id, "ให้สิทธิ์" if grant else "ถอดสิทธิ์")
        return {"ok": True, "is_admin": grant}

    @router.post("/users/{open_id}/disabled")
    async def set_disabled(request: Request, open_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """ระงับ/ปลดบัญชี (ใช้ตอนแอดมินต้องการหยุดใช้งานบัญชี)"""
        actor = await admin_user(request)
        if not await repo.column_exists("users", "is_disabled"):
            raise HTTPException(status_code=503, detail="ยังไม่ได้รัน supabase/migrations/008_admin.sql")
        disabled = bool(payload.get("is_disabled"))
        if disabled and open_id == actor["id"]:
            raise HTTPException(status_code=400, detail="ระงับบัญชีของตัวเองไม่ได้")
        if not await repo.update("users", {"openId": f"eq.{open_id}"}, {"is_disabled": disabled}):
            raise database_error(repo, "อัปเดตสถานะบัญชีไม่สำเร็จ")
        await log_admin_action(repo, actor, "ระงับบัญชี" if disabled else "ปลดระงับบัญชี", "user", open_id)
        return {"ok": True, "is_disabled": disabled}

    @router.post("/users/{open_id}/display-name")
    async def set_display_name(request: Request, open_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """ตั้งชื่อที่แสดงให้ผู้ใช้ (เขียนทับค่าที่ผู้ใช้ตั้งเองได้)"""
        actor = await admin_user(request)
        name = _clean(payload.get("display_name"))[:MAX_NAME] or None
        existing = await repo.select("user_settings", {"select": "open_id", "open_id": f"eq.{open_id}", "limit": "1"})
        if existing is None:
            raise database_error(repo, "อ่านข้อมูลผู้ใช้ไม่สำเร็จ")
        if existing:
            if not await repo.update("user_settings", {"open_id": f"eq.{open_id}"}, {"display_name": name}):
                raise database_error(repo, "อัปเดตชื่อไม่สำเร็จ")
        else:
            await repo.insert("user_settings", {"open_id": open_id, "display_name": name})
        await log_admin_action(repo, actor, "ตั้งชื่อที่แสดง", "user", open_id, name or "")
        return {"ok": True, "display_name": name}

    # =====================================================================
    # กระทู้ชุมชน (moderation)
    # =====================================================================
    @router.get("/posts")
    async def list_posts(request: Request, q: str = "", tag: str = "", limit: int = 100) -> dict[str, Any]:
        await admin_user(request)
        params: dict[str, str] = {
            "select": "id,open_id,author_name,title,body,tags,created_at",
            "order": "id.desc", "limit": str(max(1, min(limit, MAX_LIMIT))),
        }
        needle = q.strip()
        if needle:
            safe = needle.replace(",", " ").replace("(", " ").replace(")", " ").replace("*", " ").strip()
            if safe:
                params["or"] = f"(title.ilike.*{safe}*,body.ilike.*{safe}*)"
        rows = await repo.select("community_posts", params)
        if rows is None:
            raise database_error(repo, "อ่านกระทู้ไม่สำเร็จ")
        post_ids = [str(row["id"]) for row in rows] or ["0"]
        comment_counts: dict[str, int] = {}
        comments = await repo.select("community_comments", {
            "select": "post_id", "post_id": f"in.({','.join(post_ids)})", "limit": "5000",
        })
        for row in comments or []:
            key = str(row["post_id"])
            comment_counts[key] = comment_counts.get(key, 0) + 1
        items = [{
            "id": row["id"],
            "title": row.get("title"),
            "body": row.get("body"),
            "author_name": row.get("author_name"),
            "open_id": row.get("open_id"),
            "tags": row.get("tags") or [],
            "comments": comment_counts.get(str(row["id"]), 0),
            "created_at": row.get("created_at"),
        } for row in rows]
        return {"items": items}

    @router.get("/posts/{post_id}/comments")
    async def list_comments(request: Request, post_id: int) -> dict[str, Any]:
        await admin_user(request)
        rows = await repo.select("community_comments", {
            "select": "id,open_id,author_name,body,created_at", "post_id": f"eq.{post_id}",
            "order": "created_at", "limit": str(MAX_LIMIT),
        })
        return {"items": rows or []}

    @router.delete("/posts/{post_id}")
    async def delete_post(request: Request, post_id: int) -> dict[str, Any]:
        actor = await admin_user(request)
        rows = await repo.select("community_posts", {"select": "id,title,open_id", "id": f"eq.{post_id}", "limit": "1"})
        if not rows:
            raise HTTPException(status_code=404, detail="ไม่พบกระทู้นี้")
        if not await repo.delete("community_posts", {"id": f"eq.{post_id}"}):
            raise database_error(repo, "ลบกระทู้ไม่สำเร็จ")
        await log_admin_action(repo, actor, "ลบกระทู้", "post", post_id, rows[0].get("title") or "")
        return {"ok": True}

    @router.delete("/comments/{comment_id}")
    async def delete_comment(request: Request, comment_id: int) -> dict[str, Any]:
        actor = await admin_user(request)
        rows = await repo.select("community_comments", {"select": "id,body,post_id", "id": f"eq.{comment_id}", "limit": "1"})
        if not rows:
            raise HTTPException(status_code=404, detail="ไม่พบความคิดเห็นนี้")
        if not await repo.delete("community_comments", {"id": f"eq.{comment_id}"}):
            raise database_error(repo, "ลบความคิดเห็นไม่สำเร็จ")
        await log_admin_action(repo, actor, "ลบความคิดเห็น", "comment", comment_id)
        return {"ok": True}

    @router.get("/tags")
    async def list_tags(request: Request) -> dict[str, Any]:
        await admin_user(request)
        rows = await repo.select("community_tags", {"select": "id,name,color,created_at", "order": "name", "limit": str(MAX_LIMIT)})
        usage: dict[str, int] = {}
        posts = await repo.select("community_posts", {"select": "tags", "limit": "5000"})
        for row in posts or []:
            for tag in row.get("tags") or []:
                usage[tag] = usage.get(tag, 0) + 1
        items = [{
            "id": row.get("id"),
            "name": row.get("name"),
            "color": row.get("color") or "purple",
            "posts": usage.get(row.get("name") or "", 0),
        } for row in rows or []]
        return {"items": items}

    @router.post("/tags")
    async def update_tag(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        actor = await admin_user(request)
        name = _clean(payload.get("name"))
        color = _clean(payload.get("color")) or "purple"
        if not name:
            raise HTTPException(status_code=400, detail="กรุณากรอกชื่อ tag")
        if not await repo.upsert("community_tags", {"name": name, "color": color}, "name"):
            raise database_error(repo, "บันทึก tag ไม่สำเร็จ")
        await log_admin_action(repo, actor, "แก้ไข tag", "tag", name, color)
        return {"ok": True, "name": name, "color": color}

    @router.delete("/tags/{name}")
    async def delete_tag(request: Request, name: str) -> dict[str, Any]:
        """ลบ tag และเอาออกจากกระทู้ที่ใช้อยู่"""
        actor = await admin_user(request)
        if not await repo.delete("community_tags", {"name": f"eq.{name}"}):
            raise database_error(repo, "ลบ tag ไม่สำเร็จ")
        posts = await repo.select("community_posts", {"select": "id,tags", "tags": f"cs.{{{name}}}", "limit": "5000"})
        for row in posts or []:
            remaining = [tag for tag in (row.get("tags") or []) if tag != name]
            await repo.update("community_posts", {"id": f"eq.{row['id']}"}, {"tags": remaining})
        await log_admin_action(repo, actor, "ลบ tag", "tag", name)
        return {"ok": True}

    # =====================================================================
    # มหาวิทยาลัย + เกณฑ์รับ
    # =====================================================================
    @router.get("/institutions")
    async def list_institutions(request: Request, q: str = "", limit: int = 200) -> dict[str, Any]:
        await admin_user(request)
        # คอลัมน์ใหม่ (short_name, city, ...) มาจาก migration 008 — ขอเฉพาะที่มีจริง
        optional = ["short_name", "city", "kind", "website_url", "is_published"]
        available = [name for name in optional if await repo.column_exists("institutions", name)]
        base = ["id", "name"]
        if await repo.column_exists("institutions", "logoUrl"):
            base.append("logoUrl")
        params: dict[str, str] = {
            "select": ",".join(base + available),
            "order": "name", "limit": str(max(1, min(limit, 500))),
        }
        needle = q.strip()
        if needle:
            safe = needle.replace(",", " ").replace("(", " ").replace(")", " ").replace("*", " ").strip()
            if safe:
                params["name"] = f"ilike.*{safe}*"
        rows = await repo.select("institutions", params)
        if rows is None:
            raise database_error(repo, "อ่านรายชื่อมหาวิทยาลัยไม่สำเร็จ")
        items = [{
            "id": row.get("id"),
            "name": row.get("name"),
            "logoUrl": row.get("logoUrl"),
            "short_name": row.get("short_name"),
            "city": row.get("city"),
            "kind": row.get("kind"),
            "website_url": row.get("website_url"),
            "is_published": row.get("is_published", True),
        } for row in rows or []]
        return {"items": items, "kinds": INSTITUTION_KINDS, "columns_available": available}

    @router.post("/institutions")
    async def create_institution(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        actor = await admin_user(request)
        name = _clean(payload.get("name"))
        if not name:
            raise HTTPException(status_code=400, detail="กรุณากรอกชื่อมหาวิทยาลัย")
        record: dict[str, Any] = {"name": name[:MAX_NAME]}
        logo = _clean(payload.get("logo_url"))
        if logo:
            record["logoUrl"] = logo
        for key, column in (("short_name", "short_name"), ("city", "city"), ("kind", "kind"), ("website_url", "website_url")):
            value = _clean(payload.get(key))
            if value:
                record[column] = value[:MAX_NAME]
        saved = await repo.insert_returning("institutions", record)
        if saved is None:
            raise database_error(repo, "เพิ่มมหาวิทยาลัยไม่สำเร็จ")
        await log_admin_action(repo, actor, "เพิ่มมหาวิทยาลัย", "institution", saved.get("id"), name)
        return {"ok": True, "item": saved}

    @router.put("/institutions/{institution_id}")
    async def update_institution(request: Request, institution_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        actor = await admin_user(request)
        record: dict[str, Any] = {}
        name = _clean(payload.get("name"))
        if name:
            record["name"] = name[:MAX_NAME]
        if "logo_url" in payload:
            record["logoUrl"] = _clean(payload.get("logo_url")) or None
        for key, column in (("short_name", "short_name"), ("city", "city"), ("kind", "kind"), ("website_url", "website_url")):
            if key in payload:
                record[column] = _clean(payload.get(key)) or None
        if "is_published" in payload:
            record["is_published"] = bool(payload.get("is_published"))
        if not record:
            raise HTTPException(status_code=400, detail="ไม่มีข้อมูลที่ต้องบันทึก")
        if not await repo.update("institutions", {"id": f"eq.{institution_id}"}, record):
            raise database_error(repo, "อัปเดตมหาวิทยาลัยไม่สำเร็จ")
        await log_admin_action(repo, actor, "แก้ไขมหาวิทยาลัย", "institution", institution_id, name)
        return {"ok": True}

    @router.delete("/institutions/{institution_id}")
    async def delete_institution(request: Request, institution_id: int) -> dict[str, Any]:
        actor = await admin_user(request)
        rows = await repo.select("institutions", {"select": "id,name", "id": f"eq.{institution_id}", "limit": "1"})
        if not rows:
            raise HTTPException(status_code=404, detail="ไม่พบมหาวิทยาลัยนี้")
        if not await repo.delete("institutions", {"id": f"eq.{institution_id}"}):
            raise database_error(repo, "ลบมหาวิทยาลัยไม่สำเร็จ")
        await log_admin_action(repo, actor, "ลบมหาวิทยาลัย", "institution", institution_id, rows[0].get("name") or "")
        return {"ok": True}

    @router.get("/admissions")
    async def list_admissions(request: Request, institution: str = "", limit: int = 200) -> dict[str, Any]:
        await admin_user(request)
        params: dict[str, str] = {
            "select": "id,institution,faculty,program,round,criteria,source_url,source_label,deadline,is_published",
            "order": "id.desc", "limit": str(max(1, min(limit, MAX_LIMIT))),
        }
        if institution.strip():
            params["institution"] = f"ilike.*{institution.strip()}*"
        rows = await repo.select("admissions", params)
        if rows is None:
            raise database_error(repo, "อ่านรายการรับสมัครไม่สำเร็จ — รัน supabase/migrations/008_admin.sql")
        return {"items": rows or []}

    @router.post("/admissions")
    async def create_admission(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        actor = await admin_user(request)
        institution = _clean(payload.get("institution"))
        faculty = _clean(payload.get("faculty"))
        round_name = _clean(payload.get("round"))
        if not institution or not faculty or not round_name:
            raise HTTPException(status_code=400, detail="กรุณากรอกมหาวิทยาลัย คณะ และรอบการรับ")
        record: dict[str, Any] = {
            "institution": institution[:MAX_NAME],
            "faculty": faculty[:MAX_NAME],
            "round": round_name[:MAX_NAME],
            "criteria": _clean(payload.get("criteria"))[:1000],
        }
        for key in ("program", "source_url", "source_label"):
            value = _clean(payload.get(key))
            if value:
                record[key] = value[:MAX_NAME]
        deadline = _clean(payload.get("deadline"))
        if deadline:
            record["deadline"] = deadline
        saved = await repo.insert_returning("admissions", record)
        if saved is None:
            raise database_error(repo, "เพิ่มรายการรับสมัครไม่สำเร็จ")
        await log_admin_action(repo, actor, "เพิ่มรายการรับสมัคร", "admission", saved.get("id"), institution)
        return {"ok": True, "item": saved}

    @router.put("/admissions/{admission_id}")
    async def update_admission(request: Request, admission_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        actor = await admin_user(request)
        record: dict[str, Any] = {}
        for key in ("institution", "faculty", "program", "round", "criteria", "source_url", "source_label"):
            if key in payload:
                record[key] = _clean(payload.get(key))[:MAX_NAME]
        if "deadline" in payload:
            record["deadline"] = _clean(payload.get("deadline")) or None
        if "is_published" in payload:
            record["is_published"] = bool(payload.get("is_published"))
        if not record:
            raise HTTPException(status_code=400, detail="ไม่มีข้อมูลที่ต้องบันทึก")
        if not await repo.update("admissions", {"id": f"eq.{admission_id}"}, record):
            raise database_error(repo, "อัปเดตรายการรับสมัครไม่สำเร็จ")
        await log_admin_action(repo, actor, "แก้ไขรายการรับสมัคร", "admission", admission_id)
        return {"ok": True}

    @router.delete("/admissions/{admission_id}")
    async def delete_admission(request: Request, admission_id: int) -> dict[str, Any]:
        actor = await admin_user(request)
        if not await repo.delete("admissions", {"id": f"eq.{admission_id}"}):
            raise database_error(repo, "ลบรายการรับสมัครไม่สำเร็จ")
        await log_admin_action(repo, actor, "ลบรายการรับสมัคร", "admission", admission_id)
        return {"ok": True}

    # =====================================================================
    # คิว Ticket
    # =====================================================================
    @router.get("/tickets")
    async def list_tickets(request: Request, status: str = "") -> dict[str, Any]:
        await admin_user(request)
        params: dict[str, str] = {
            "select": "id,open_id,subject,category,status,created_at,updated_at",
            "order": "updated_at.desc", "limit": str(MAX_LIMIT),
        }
        if status in TICKET_STATUSES:
            params["status"] = f"eq.{status}"
        rows = await repo.select("tickets", params)
        if rows is None:
            raise database_error(repo, "อ่าน Ticket ไม่สำเร็จ")
        counts: dict[str, int] = {key: 0 for key in TICKET_STATUSES}
        all_rows = await repo.select("tickets", {"select": "status", "limit": "5000"})
        for row in all_rows or []:
            key = row.get("status")
            if key in counts:
                counts[key] += 1
        items = [{
            "id": row["id"], "subject": row.get("subject"), "category": row.get("category"),
            "status": row.get("status"), "status_label": STATUS_LABELS.get(row.get("status") or "", row.get("status")),
            "created_at": row.get("created_at"), "updated_at": row.get("updated_at"),
        } for row in rows]
        return {"items": items, "counts": counts}

    @router.get("/tickets/{ticket_id}")
    async def get_ticket(request: Request, ticket_id: int) -> dict[str, Any]:
        user = await admin_user(request)
        rows = await repo.select("tickets", {"select": "*", "id": f"eq.{ticket_id}", "limit": "1"})
        if not rows:
            raise HTTPException(status_code=404, detail="ไม่พบ Ticket นี้")
        messages = await repo.select("ticket_messages", {
            "select": "id,sender_type,sender_name,body,created_at",
            "ticket_id": f"eq.{ticket_id}", "order": "created_at", "limit": str(MAX_LIMIT),
        })
        owner = await repo.select("users", {"select": "name,email", "openId": f"eq.{rows[0].get('open_id')}", "limit": "1"})
        return {
            "ticket": {k: rows[0].get(k) for k in ("id", "open_id", "subject", "category", "status", "created_at", "updated_at")},
            "messages": messages or [],
            "user": (owner[0] if owner else {}),
            "my_id": user["id"],
        }

    @router.post("/tickets/{ticket_id}/reply")
    async def reply_ticket(request: Request, ticket_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        user = await admin_user(request)
        body = _clean(payload.get("body"))
        if not body:
            raise HTTPException(status_code=400, detail="กรุณาเขียนข้อความตอบกลับ")
        rows = await repo.select("tickets", {"select": "id,status", "id": f"eq.{ticket_id}", "limit": "1"})
        if not rows:
            raise HTTPException(status_code=404, detail="ไม่พบ Ticket นี้")
        name = _clean((user.get("user_metadata") or {}).get("full_name")) or "แอดมิน"
        saved = await repo.insert_returning("ticket_messages", {
            "ticket_id": ticket_id, "sender_type": "admin", "sender_id": user["id"],
            "sender_name": name, "body": body,
        })
        if saved is None:
            raise database_error(repo, "ส่งข้อความไม่สำเร็จ")
        await repo.update("tickets", {"id": f"eq.{ticket_id}"}, {
            "status": "answered" if rows[0].get("status") == "open" else rows[0].get("status"),
            "updated_at": _now().isoformat(),
        })
        return {"ok": True, "message": saved}

    @router.post("/tickets/{ticket_id}/status")
    async def set_status(request: Request, ticket_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """เปลี่ยนสถานะ Ticket — เมื่อเป็น 'closed' ข้อมูลจะถูกลบทิ้งถาวร"""
        actor = await admin_user(request)
        status = _clean(payload.get("status"))
        if status not in TICKET_STATUSES:
            raise HTTPException(status_code=400, detail="สถานะไม่ถูกต้อง")
        if status == "closed":
            result = await purge_ticket(ticket_id)
            if not result["ok"]:
                raise database_error(repo, "ปิด Ticket ไม่สำเร็จ")
            await log_admin_action(repo, actor, "ปิดและลบ Ticket", "ticket", ticket_id)
            return {"ok": True, "status": "closed", "purged": True}
        if not await repo.update("tickets", {"id": f"eq.{ticket_id}"}, {"status": status, "updated_at": _now().isoformat()}):
            raise database_error(repo, "อัปเดตสถานะไม่สำเร็จ")
        await log_admin_action(repo, actor, "เปลี่ยนสถานะ Ticket", "ticket", ticket_id, STATUS_LABELS.get(status, status))
        return {"ok": True, "status": status, "purged": False}

    @router.post("/tickets/purge-closed")
    async def purge_closed(request: Request, keep_days: int = 30) -> dict[str, Any]:
        """ล้างตั๋วที่ปิดไว้เกินกำหนด (งานประจำวัน — เรียกด้วย cron)"""
        await admin_user(request)
        result = await purge_closed_tickets(keep_days=max(1, min(keep_days, 365)))
        return result

    return router
