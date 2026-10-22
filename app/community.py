"""ระบบกระทู้ชุมชน: สร้างกระทู้ขอความคิดเห็น เลือก tag แบบ Discord ความคิดเห็น กดไลก์ และโหวต.

ทุก endpoint ต้องใช้ Bearer token (ผ่าน require_user) — ผู้ใช้เขียนได้เฉพาะกระทู้/ความคิดเห็นของตัวเอง
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .auth import database_error, require_database, require_user
from .avatars import avatar_urls

MAX_TITLE = 200
MAX_BODY = 5000
MAX_TAGS = 5
MAX_OPTIONS = 8
MAX_COMMENT = 2000

# cache tag (เปลี่ยนบ่อยมาก) — ลดจำนวน request ไป Supabase
_tag_cache: dict[str, Any] = {"items": None, "at": 0.0}

# cache ผลรวมโหวต/ไลก์/คอมเมนต์ ต่อกระทู้ (โหวตกับไลก์เปลี่ยนบ่อยแต่ไม่ถี่เท่าโพสต์ใหม่)
_count_cache: dict[str, tuple[float, dict[str, Any]]] = {}
COUNT_CACHE_TTL = 10.0  # วินาที


def invalidate_counts(post_id: Any) -> None:
    """ล้าง cache ของกระทู้ เมื่อมีการโหวต/ไลก์/คอมเมนต์"""
    key = str(post_id)
    for cached_key in list(_count_cache):
        if key in cached_key:
            _count_cache.pop(cached_key, None)
DEFAULT_TAGS = [
    ("TCAS", "purple"),
    ("คณะในฝัน", "blue"),
    ("เตรียมสอบ", "pink"),
    ("A-Level", "teal"),
    ("ทุนการศึกษา", "gold"),
    ("สายสุขภาพ", "rose"),
    ("สายวิศวกรรม", "violet"),
    ("ประชับสังคม", "indigo"),
    ("ช่วยกันตัดสินใจ", "green"),
]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def build_router(repo: Any) -> APIRouter:
    router = APIRouter(prefix="/api/community")

    # ---------- helpers ----------
    async def current_user(request: Request) -> dict[str, Any]:
        user = await require_user(request, repo)
        require_database(repo)
        return user

    def display_name(user: dict[str, Any]) -> str:
        meta = user.get("user_metadata") or {}
        return _clean(meta.get("full_name") or meta.get("name")) or (user.get("email") or "ผู้ใช้").split("@")[0]

    async def profile_of(open_id: str, fallback: str) -> tuple[str, str | None]:
        """ชื่อที่แสดง + url รูปโปรไฟล์ (ค้นจาก user_settings ก่อน แล้วค่อย users)"""
        rows = await repo.select("user_settings", {"select": "display_name,avatar_key", "open_id": f"eq.{open_id}", "limit": "1"})
        if rows:
            row = rows[0]
            urls = avatar_urls()
            return _clean(row.get("display_name")) or fallback, urls.get(row.get("avatar_key") or "")
        users = await repo.select("users", {"select": "name", "openId": f"eq.{open_id}", "limit": "1"})
        if users and _clean(users[0].get("name")):
            return _clean(users[0]["name"]), None
        return fallback, None

    async def fill_missing_avatars(comments: list[dict[str, Any]]) -> None:
        """เติมรูปโปรไฟล์ให้ความคิดเห็นเก่าที่ยังไม่ได้บันทึกไว้ (อ่านจาก user_settings)"""
        pending = [c for c in comments if not c.get("author_avatar") and c.get("open_id")]
        if not pending:
            return
        open_ids = list({c["open_id"] for c in pending})
        rows = await repo.select("user_settings", {
            "select": "open_id,avatar_key", "open_id": f"in.({','.join(open_ids)})", "limit": "300",
        })
        if not rows:
            return
        urls = avatar_urls()
        by_id = {row["open_id"]: urls.get(row.get("avatar_key") or "") for row in rows}
        for comment in pending:
            url = by_id.get(comment["open_id"])
            if url:
                comment["author_avatar"] = url

    async def ensure_tags(names: list[str], open_id: str) -> list[str]:
        """คืนชื่อ tag ที่สะอาดแล้ว และสร้าง tag ใหม่ในตารางถ้ายังไม่มี"""
        cleaned: list[str] = []
        for name in names:
            tag = _clean(name).lstrip("#").strip()
            if not tag or tag in cleaned:
                continue
            if len(tag) > 40:
                raise HTTPException(status_code=400, detail=f"ชื่อ tag '{tag}' ยาวเกินไป")
            cleaned.append(tag)
        if not cleaned:
            return []
        # ชื่อ tag อาจมีอักขระที่ PostgREST ใช้เป็นตัวคั่น filter (,) และอื่น ๆ — ตัดทิ้งเพื่อไม่ให้ query พัง
        safe = [re.sub(r"[,(){}%*\\]", " ", tag).strip() for tag in cleaned]
        safe = [tag for tag in safe if tag]
        known: set[str] = set()
        if safe:
            existing = await repo.select("community_tags", {"select": "name", "name": f"in.({','.join(safe)})", "limit": "100"})
            known = {row.get("name") for row in (existing or [])}
        for tag in cleaned:
            if tag in known:
                continue
            await repo.insert("community_tags", {"name": tag, "color": "purple", "created_by": open_id})
        return cleaned[:MAX_TAGS]

    async def attach_details(posts: list[dict[str, Any]], open_id: str) -> list[dict[str, Any]]:
        """เติมตัวเลือกโพล ผลโหวต จำนวนความคิดเห็น และสถานะไลก์/โหวตของผู้ใช้"""
        if not posts:
            return posts
        post_ids = [str(post["id"]) for post in posts]
        id_list = ",".join(post_ids)

        # ยิง 4 ตารางพร้อมกัน — แต่ละ request ไป Supabase ใช้เวลาหลายร้อย ms
        options, votes, likes, comments = await asyncio.gather(
            repo.select("community_post_options", {
                "select": "id,post_id,label,sort_order", "post_id": f"in.({id_list})",
                "order": "post_id,sort_order", "limit": "500",
            }),
            repo.select("community_post_votes", {"select": "post_id,option_id,open_id", "post_id": f"in.({id_list})", "limit": "5000"}),
            repo.select("community_post_likes", {"select": "post_id,open_id", "post_id": f"in.({id_list})", "limit": "5000"}),
            repo.select("community_comments", {"select": "post_id", "post_id": f"in.({id_list})", "limit": "5000"}),
        )

        options_by_post: dict[str, list[dict[str, Any]]] = {}
        for option in options or []:
            options_by_post.setdefault(str(option["post_id"]), []).append(option)

        vote_counts: dict[str, int] = {}
        option_vote_counts: dict[int, int] = {}
        my_votes: dict[str, int] = {}
        for vote in votes or []:
            key = str(vote["post_id"])
            vote_counts[key] = vote_counts.get(key, 0) + 1
            option_id = int(vote["option_id"])
            option_vote_counts[option_id] = option_vote_counts.get(option_id, 0) + 1
            if vote.get("open_id") == open_id:
                my_votes[key] = option_id

        like_counts: dict[str, int] = {}
        my_likes: set[str] = set()
        for like in likes or []:
            key = str(like["post_id"])
            like_counts[key] = like_counts.get(key, 0) + 1
            if like.get("open_id") == open_id:
                my_likes.add(key)

        comment_counts: dict[str, int] = {}
        for comment in comments or []:
            key = str(comment["post_id"])
            comment_counts[key] = comment_counts.get(key, 0) + 1

        for post in posts:
            key = str(post["id"])
            post_options = options_by_post.get(key, [])
            total = vote_counts.get(key, 0)
            for option in post_options:
                option["votes"] = option_vote_counts.get(int(option["id"]), 0)
            post["options"] = post_options
            post["total_votes"] = total
            post["likes"] = like_counts.get(key, 0)
            post["liked"] = key in my_likes
            post["comments_count"] = comment_counts.get(key, 0)
            post["my_vote"] = my_votes.get(key)
        return posts

    # ---------- tag ----------
    @router.get("/tags")
    async def list_tags() -> dict[str, Any]:
        # tag เปลี่ยนบ่อยมาก — cache 60 วินาที ลดจำนวน request ลง Supabase
        cached = _tag_cache.get("items")
        if cached and (time.monotonic() - _tag_cache["at"]) < 60:
            return {"items": cached, "source": "cache"}
        rows = await repo.select("community_tags", {"select": "name,color", "order": "name", "limit": "200"})
        items = list(rows or [])
        known = {item.get("name") for item in items}
        # เติม tag เริ่มต้นที่ยังไม่มีในฐานข้อมูล (เผื่อยังไม่ได้รัน migration)
        for name, color in DEFAULT_TAGS:
            if name not in known:
                items.append({"name": name, "color": color})
        items.sort(key=lambda item: item.get("name") or "")
        _tag_cache["items"] = items
        _tag_cache["at"] = time.monotonic()
        return {"items": items, "source": "database" if rows is not None else "default"}

    @router.post("/tags")
    async def create_tag(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        user = await current_user(request)
        name = _clean(payload.get("name")).lstrip("#").strip()
        if not name:
            raise HTTPException(status_code=400, detail="กรุณากรอกชื่อ tag")
        if len(name) > 40:
            raise HTTPException(status_code=400, detail="ชื่อ tag ยาวเกินไป")
        existing = await repo.select("community_tags", {"select": "id,name", "name": f"eq.{name}", "limit": "1"})
        if existing:
            return {"ok": True, "tag": {"name": name, "color": existing[0].get("color") or "purple"}, "already": True}
        saved = await repo.insert_returning("community_tags", {"name": name, "color": "purple", "created_by": user["id"]})
        if saved is None:
            raise database_error(repo, "สร้าง tag ไม่สำเร็จ")
        _tag_cache["items"] = None  # ล้าง cache เพราะมี tag ใหม่
        return {"ok": True, "tag": {"name": name, "color": "purple"}, "already": False}

    # ---------- กระทู้ ----------
    @router.get("/posts")
    async def list_posts(request: Request, tag: str = "", q: str = "", limit: int = 50) -> dict[str, Any]:
        """รายการกระทู้ทั้งหมด (อ่านได้โดยไม่ต้องล็อกอิน แต่ถ้าล็อกอินจะได้สถานะไลก์/โหวตของตัวเอง)"""
        open_id = ""
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if token and repo.auth_configured:
            try:
                user = await require_user(request, repo)
                open_id = user["id"]
            except HTTPException:
                open_id = ""
        if not repo.configured:
            return {"items": [], "configured": False}

        params: dict[str, str] = {
            "select": "id,open_id,author_name,author_avatar,title,body,tags,created_at,updated_at",
            "order": "id.desc",
            "limit": str(max(1, min(limit, 100))),
        }
        needle = q.strip()
        if needle:
            # ตัดอักขระที่ PostgREST ใช้เป็นตัวคั่น filter ออกก่อนค้นหา
            escaped = re.sub(r"[,(){}%*\\]", " ", needle).strip()
            if escaped:
                params["or"] = f"(title.ilike.*{escaped}*,body.ilike.*{escaped}*)"
        wanted_tag = tag.strip()
        if wanted_tag:
            # ตัดอักขระที่ PostgREST ใช้เป็นตัวคั่นของ cs filter ออก
            safe_tag = re.sub(r"[,(){}%*\\]", " ", wanted_tag).strip()
            if safe_tag:
                params["tags"] = f"cs.{{{safe_tag}}}"
        rows = await repo.select("community_posts", params)
        if rows is None:
            # ยังไม่ได้รัน migration 007 -> บอกหน้าเว็บให้แสดงคำแนะนำแทนที่จะพัง
            return {"items": [], "configured": False, "error": "ยังไม่ได้รัน supabase/migrations/007_community.sql"}
        await attach_details(rows, open_id)
        return {"items": rows, "configured": True}

    @router.get("/posts/{post_id}")
    async def get_post(request: Request, post_id: int) -> dict[str, Any]:
        open_id = ""
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if token and repo.auth_configured:
            try:
                user = await require_user(request, repo)
                open_id = user["id"]
            except HTTPException:
                open_id = ""
        rows = await repo.select("community_posts", {"select": "*", "id": f"eq.{post_id}", "limit": "1"})
        if rows is None:
            raise database_error(repo, "อ่านกระทู้ไม่สำเร็จ")
        if not rows:
            raise HTTPException(status_code=404, detail="ไม่พบกระทู้นี้")
        post = rows[0]
        # ดึงความคิดเห็นไปพร้อมกับรายละเอียดกระทู้ (แทนที่จะรอทีละอย่าง)
        comments_task = repo.select("community_comments", {
            "select": "id,open_id,author_name,author_avatar,body,created_at", "post_id": f"eq.{post_id}",
            "order": "created_at", "limit": "300",
        })
        await attach_details([post], open_id)
        comments = await comments_task
        await fill_missing_avatars(comments or [])
        return {"post": post, "comments": comments or []}

    @router.post("/posts", status_code=201)
    async def create_post(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
        user = await current_user(request)
        title = _clean(payload.get("title"))
        body = _clean(payload.get("body"))
        if not title:
            raise HTTPException(status_code=400, detail="กรุณาเขียนหัวข้อคำถาม")
        if len(title) > MAX_TITLE:
            raise HTTPException(status_code=400, detail=f"หัวข้อยาวเกิน {MAX_TITLE} ตัวอักษร")
        if len(body) > MAX_BODY:
            raise HTTPException(status_code=400, detail=f"เนื้อหายาวเกิน {MAX_BODY} ตัวอักษร")

        raw_tags = payload.get("tags") or []
        if isinstance(raw_tags, str):
            raw_tags = [part for part in raw_tags.replace(",", " ").split() if part]
        tags = await ensure_tags([_clean(tag) for tag in raw_tags][:MAX_TAGS], user["id"])

        raw_options = payload.get("options") or []
        options = []
        for item in raw_options:
            label = _clean(item.get("label") if isinstance(item, dict) else item)
            if label and len(label) <= 120 and label not in options:
                options.append(label)
        if len(options) > MAX_OPTIONS:
            raise HTTPException(status_code=400, detail=f"ตัวเลือกได้ไม่เกิน {MAX_OPTIONS} รายการ")

        fallback = display_name(user)
        name, avatar = await profile_of(user["id"], fallback)
        record = {
            "open_id": user["id"],
            "author_name": name,
            "author_avatar": avatar,
            "title": title,
            "body": body,
            "tags": tags,
        }
        saved = await repo.insert_returning("community_posts", record)
        if saved is None:
            raise database_error(repo, "บันทึกกระทู้ไม่สำเร็จ")
        for index, label in enumerate(options):
            await repo.insert_returning("community_post_options", {"post_id": saved["id"], "label": label, "sort_order": index})
        await attach_details([saved], user["id"])
        return {"ok": True, "post": saved}

    @router.post("/posts/{post_id}/like")
    async def toggle_like(request: Request, post_id: int) -> dict[str, Any]:
        user = await current_user(request)
        existing = await repo.select("community_post_likes", {"select": "post_id", "post_id": f"eq.{post_id}", "open_id": f"eq.{user['id']}", "limit": "1"})
        if existing:
            await repo.delete("community_post_likes", {"post_id": f"eq.{post_id}", "open_id": f"eq.{user['id']}"})
            return {"ok": True, "liked": False}
        await repo.insert("community_post_likes", {"post_id": post_id, "open_id": user["id"]})
        return {"ok": True, "liked": True}

    @router.post("/posts/{post_id}/vote")
    async def vote(request: Request, post_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """โหวตหนึ่งครั้งต่อคน — โหวตใหม่จะทับของเดิม"""
        user = await current_user(request)
        try:
            option_id = int(payload.get("option_id"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="ตัวเลือกไม่ถูกต้อง") from None
        options = await repo.select("community_post_options", {"select": "id", "id": f"eq.{option_id}", "post_id": f"eq.{post_id}", "limit": "1"})
        if not options:
            raise HTTPException(status_code=404, detail="ไม่พบตัวเลือกนี้")
        await repo.delete("community_post_votes", {"post_id": f"eq.{post_id}", "open_id": f"eq.{user['id']}"})
        await repo.insert("community_post_votes", {"post_id": post_id, "option_id": option_id, "open_id": user["id"]})
        return {"ok": True, "option_id": option_id}

    @router.post("/posts/{post_id}/comments", status_code=201)
    async def add_comment(request: Request, post_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        user = await current_user(request)
        body = _clean(payload.get("body"))
        if not body:
            raise HTTPException(status_code=400, detail="กรุณาเขียนความคิดเห็น")
        if len(body) > MAX_COMMENT:
            raise HTTPException(status_code=400, detail=f"ความคิดเห็นยาวเกิน {MAX_COMMENT} ตัวอักษร")
        posts = await repo.select("community_posts", {"select": "id,open_id,author_name", "id": f"eq.{post_id}", "limit": "1"})
        if not posts:
            raise HTTPException(status_code=404, detail="ไม่พบกระทู้นี้")
        fallback = display_name(user)
        name, avatar = await profile_of(user["id"], fallback)
        record: dict[str, Any] = {
            "post_id": post_id, "open_id": user["id"], "author_name": name, "body": body,
        }
        if avatar:
            record["author_avatar"] = avatar
        saved = await repo.insert_returning("community_comments", record)
        if saved is None:
            raise database_error(repo, "บันทึกความคิดเห็นไม่สำเร็จ")
        return {"ok": True, "comment": saved}

    @router.delete("/posts/{post_id}")
    async def delete_post(request: Request, post_id: int) -> dict[str, Any]:
        """ลบกระทู้ของตัวเองได้ (ผู้ดูแลระบบลบได้ทุกกระทู้)"""
        from .auth import is_admin

        user = await current_user(request)
        rows = await repo.select("community_posts", {"select": "id,open_id", "id": f"eq.{post_id}", "limit": "1"})
        if not rows:
            raise HTTPException(status_code=404, detail="ไม่พบกระทู้นี้")
        if rows[0].get("open_id") != user["id"] and not await is_admin(repo, user["id"], user.get("email")):
            raise HTTPException(status_code=403, detail="ลบได้เฉพาะกระทู้ของตัวเอง")
        if not await repo.delete("community_posts", {"id": f"eq.{post_id}"}):
            raise database_error(repo, "ลบกระทู้ไม่สำเร็จ")
        return {"ok": True}

    return router
