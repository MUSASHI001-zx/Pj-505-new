"""ระบบกระทู้ชุมชน: สร้างกระทู้ขอความคิดเห็น (พร้อมแนบรูป) เลือก tag จากรายการที่มีอยู่ ความคิดเห็น กดไลก์ และโหวต.

กฎสำคัญของระบบ:
- tag: ผู้ใช้เลือกได้เฉพาะ tag ที่มีอยู่แล้ว (ผู้ดูแลระบบเป็นคนเพิ่ม tag เอง) — ไม่มีการสร้าง tag จากผู้ใช้
- ไลก์: 1 คนกดไลก์กระทู้เดียวได้ 1 ครั้ง (บังคับด้วย unique index ในฐานข้อมูล)
- โหวต: 1 คนโหวตกระทู้เดียวได้ 1 เสียง โหวตทับได้ (upsert ไม่ลบแล้วใหม่)

ทุก endpoint ต้องใช้ Bearer token (ผ่าน require_user) — ผู้ใช้เขียนได้เฉพาะกระทู้/ความคิดเห็นของตัวเอง
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from .auth import database_error, require_database, require_user
from .avatars import avatar_urls
from .uploads import MAX_BYTES as MAX_IMAGE_BYTES, upload_image

MAX_TITLE = 200
MAX_BODY = 5000
MAX_TAGS = 5
MAX_OPTIONS = 8
MAX_COMMENT = 2000

# cache tag (เปลี่ยนบ่อยมาก) — ลดจำนวน request ไป Supabase
_tag_cache: dict[str, Any] = {"items": None, "at": 0.0}

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


def invalidate_tag_cache() -> None:
    """ล้าง cache รายการ tag — เรียกเมื่อมีการเพิ่ม/ลบ/เปลี่ยน tag"""
    _tag_cache["items"] = None
    _tag_cache["at"] = 0.0


# cache สถานะ view สรุปยอด (migration 014) — ตรวจครั้งเดียวแล้วจำไว้ 5 นาที
_view_cache: dict[str, Any] = {"ready": None, "at": 0.0}
VIEW_CACHE_TTL = 300.0


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

    async def known_tag_names() -> set[str]:
        """ชื่อ tag ทั้งหมดที่มีอยู่จริงในระบบ — ผู้ใช้เลือกได้เฉพาะในรายการนี้"""
        rows = await repo.select("community_tags", {"select": "name", "limit": "500"})
        if not rows:
            # ตารางยังไม่มีข้อมูล (หรือยังไม่ได้รัน migration) — ใช้รายการเริ่มต้น
            return {name for name, _ in DEFAULT_TAGS}
        return {row.get("name") for row in rows if row.get("name")}

    def clean_tags(raw_tags: Any) -> list[str]:
        """ทำความสะอาดรายการ tag ที่ผู้ใช้ส่งมา (ตัดซ้ำ ตัด # นำหน้า จำกัดจำนวน)"""
        if isinstance(raw_tags, str):
            raw_tags = [part for part in raw_tags.replace(",", " ").split() if part]
        cleaned: list[str] = []
        for item in raw_tags or []:
            tag = _clean(item).lstrip("#").strip()
            if not tag or tag in cleaned:
                continue
            if len(tag) > 40:
                raise HTTPException(status_code=400, detail=f"ชื่อ tag '{tag}' ยาวเกินไป")
            cleaned.append(tag)
        return cleaned[:MAX_TAGS]

    async def attach_details(posts: list[dict[str, Any]], open_id: str) -> list[dict[str, Any]]:
        """เติมตัวเลือกโพล ผลโหวต จำนวนความคิดเห็น และสถานะไลก์/โหวตของผู้ใช้

        ใช้ view สรุปยอด (community_option_tally / community_post_stats) ถ้ามี —
        ได้ยอดแบบ exact ไม่โดนตัดที่ limit และไม่ต้องดึงทุกแถวมานับใน Python
        ถ้ายังไม่ได้รัน migration 014 จะ fallback ไปนับจากแถวดิบเหมือนเดิม
        """
        if not posts:
            return posts
        post_ids = [str(post["id"]) for post in posts]
        id_list = ",".join(post_ids)

        my_vote_rows = await repo.select("community_post_votes", {
            "select": "post_id,option_id", "post_id": f"in.({id_list})",
            "open_id": f"eq.{open_id}", "limit": "500",
        })
        my_votes: dict[str, int] = {}
        for row in my_vote_rows or []:
            my_votes[str(row["post_id"])] = int(row["option_id"])

        if await has_summary_views():
            # --- ทางหลัก: ยอด exact จาก view ---
            tally_rows, stat_rows = await asyncio.gather(
                repo.select("community_option_tally", {
                    "select": "post_id,option_id,label,sort_order,votes",
                    "post_id": f"in.({id_list})", "order": "post_id,sort_order", "limit": "1000",
                }),
                repo.select("community_post_stats", {
                    "select": "post_id,likes,total_votes,comments_count",
                    "post_id": f"in.({id_list})", "limit": "500",
                }),
            )
            if tally_rows is not None and stat_rows is not None:
                options_by_post: dict[str, list[dict[str, Any]]] = {}
                for row in tally_rows:
                    options_by_post.setdefault(str(row["post_id"]), []).append({
                        "id": int(row["option_id"]),
                        "label": row.get("label") or "",
                        "sort_order": row.get("sort_order") or 0,
                        "votes": int(row.get("votes") or 0),
                    })
                stats = {str(row["post_id"]): row for row in stat_rows}
                for post in posts:
                    key = str(post["id"])
                    stat = stats.get(key, {})
                    post["options"] = options_by_post.get(key, [])
                    post["total_votes"] = int(stat.get("total_votes") or 0)
                    post["likes"] = int(stat.get("likes") or 0)
                    post["comments_count"] = int(stat.get("comments_count") or 0)
                    post["my_vote"] = my_votes.get(key)
                    post["liked"] = False
                return await _fill_liked(posts, open_id)

        # --- ทางสำรอง: ยังไม่ได้รัน migration 014 — นับจากแถวดิบ ---
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
        for vote in votes or []:
            key = str(vote["post_id"])
            vote_counts[key] = vote_counts.get(key, 0) + 1
            option_id = int(vote["option_id"])
            option_vote_counts[option_id] = option_vote_counts.get(option_id, 0) + 1

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
            for option in post_options:
                option["votes"] = option_vote_counts.get(int(option["id"]), 0)
            post["options"] = post_options
            post["total_votes"] = vote_counts.get(key, 0)
            post["likes"] = like_counts.get(key, 0)
            post["liked"] = key in my_likes
            post["comments_count"] = comment_counts.get(key, 0)
            post["my_vote"] = my_votes.get(key)
        return posts

    async def has_summary_views() -> bool:
        """มี view สรุปยอด (migration 014) แล้วหรือยัง — ตรวจครั้งเดียวแล้วจำไว้"""
        if _view_cache.get("ready") is not None and (time.monotonic() - _view_cache["at"]) < VIEW_CACHE_TTL:
            return bool(_view_cache["ready"])
        rows = await repo.select("community_post_stats", {"select": "post_id", "limit": "1"}, quiet=True)
        ready = rows is not None
        _view_cache["ready"] = ready
        _view_cache["at"] = time.monotonic()
        return ready

    async def _fill_liked(posts: list[dict[str, Any]], open_id: str) -> list[dict[str, Any]]:
        """เติมสถานะ 'ผู้ใช้กดไลก์แล้วหรือยัง' (ต้องเช็คแยก เพราะ view นับรวมได้แต่ไม่แยกคน)"""
        if not open_id:
            return posts
        rows = await repo.select("community_post_likes", {
            "select": "post_id", "post_id": f"in.({','.join(str(p['id']) for p in posts)})",
            "open_id": f"eq.{open_id}", "limit": "500",
        })
        liked = {str(row["post_id"]) for row in rows or []}
        for post in posts:
            post["liked"] = str(post["id"]) in liked
        return posts

    # ---------- tag (อ่านอย่างเดียว — ผู้ดูแลระบบเป็นคนเพิ่ม tag) ----------
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

    # ---------- อัปโหลดรูปประกอบกระทู้ ----------
    @router.post("/uploads", status_code=201)
    async def upload(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
        """อัปโหลดรูปภาพประกอบกระทู้ — คืน URL สาธารณะไปใส่ในกระทู้"""
        user = await current_user(request)
        # อ่านทีละน้อยกว่าขนาดสูงสุด +1 ไบต์ เพื่อรู้ว่าเกินขนาดหรือไม่โดยไม่ดึงทั้งไฟล์
        data = await file.read(MAX_IMAGE_BYTES + 1)
        # ตรวจไฟล์ก่อน — ถ้าไฟล์ผิดรูปแบบต้องแจ้งผู้ใช้ ไม่ใช่บอกให้รัน migration
        url = await upload_image(repo, data, user["id"])
        return {"ok": True, "url": url}

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
            "select": "id,open_id,author_name,author_avatar,title,body,tags,image_url,created_at,updated_at",
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

        # tag — ผู้ใช้เลือกได้เฉพาะ tag ที่มีอยู่แล้ว (ผู้ดูแลระบบเป็นคนเพิ่ม tag เอง)
        tags = clean_tags(payload.get("tags"))
        if tags:
            allowed = await known_tag_names()
            dropped = [tag for tag in tags if tag not in allowed]
            tags = [tag for tag in tags if tag in allowed]
            if dropped:
                print(f"drop unknown tags for {user['id']}: {dropped}")

        raw_options = payload.get("options") or []
        options = []
        for item in raw_options:
            label = _clean(item.get("label") if isinstance(item, dict) else item)
            if label and len(label) <= 120 and label not in options:
                options.append(label)
        if len(options) > MAX_OPTIONS:
            raise HTTPException(status_code=400, detail=f"ตัวเลือกได้ไม่เกิน {MAX_OPTIONS} รายการ")

        # รูปภาพประกอบ (ถ้ามี) — ต้องมีคอลัมน์ image_url ในฐานข้อมูลก่อน
        image_url = _clean(payload.get("image_url"))
        if image_url and not image_url.startswith("http"):
            raise HTTPException(status_code=400, detail="รูปภาพไม่ถูกต้อง")
        has_image_column = await repo.column_exists("community_posts", "image_url")

        fallback = display_name(user)
        name, avatar = await profile_of(user["id"], fallback)
        record: dict[str, Any] = {
            "open_id": user["id"],
            "author_name": name,
            "author_avatar": avatar,
            "title": title,
            "body": body,
            "tags": tags,
        }
        if image_url and has_image_column:
            record["image_url"] = image_url
        elif image_url:
            raise HTTPException(status_code=503, detail="ยังไม่ได้รัน supabase/migrations/014_community_images_and_votes.sql")

        saved = await repo.insert_returning("community_posts", record)
        if saved is None:
            raise database_error(repo, "บันทึกกระทู้ไม่สำเร็จ")
        for index, label in enumerate(options):
            await repo.insert_returning("community_post_options", {"post_id": saved["id"], "label": label, "sort_order": index})
        await attach_details([saved], user["id"])
        return {"ok": True, "post": saved}

    @router.post("/posts/{post_id}/like")
    async def toggle_like(request: Request, post_id: int) -> dict[str, Any]:
        """กดไลก์/ยกเลิกไลก์ — 1 คนได้ไลก์กระทู้เดียว 1 ครั้ง (unique index กันซ้ำ)"""
        user = await current_user(request)
        existing = await repo.select("community_post_likes", {
            "select": "post_id", "post_id": f"eq.{post_id}", "open_id": f"eq.{user['id']}", "limit": "1",
        })
        if existing:
            await repo.delete("community_post_likes", {"post_id": f"eq.{post_id}", "open_id": f"eq.{user['id']}"})
            liked = False
        else:
            # upsert กัน race condition (กดรัว ๆ / สองแท็บพร้อมกัน) ไม่ให้ได้ error 409
            saved = await repo.upsert(
                "community_post_likes", {"post_id": post_id, "open_id": user["id"]}, "post_id,open_id",
            )
            if saved is None:
                raise database_error(repo, "กดไลก์ไม่สำเร็จ")
            liked = True

        posts = await repo.select("community_posts", {"select": "id", "id": f"eq.{post_id}", "limit": "1"})
        count = 0
        if posts:
            await attach_details(posts, user["id"])
            count = int(posts[0].get("likes") or 0)
        return {"ok": True, "liked": liked, "likes": count}

    @router.post("/posts/{post_id}/vote")
    async def vote(request: Request, post_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """โหวตหนึ่งเสียงต่อคน

        - โหวตตัวเลือกที่เลือกไว้แล้ว = ยกเลิกโหวต
        - โหวตตัวเลือกอื่น = เปลี่ยนคำตอบ (upsert ทับของเดิม ไม่ลบแล้วใหม่ ข้อมูลไม่หายกลางคัน)
        """
        user = await current_user(request)
        try:
            option_id = int(payload.get("option_id"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="ตัวเลือกไม่ถูกต้อง") from None
        options = await repo.select("community_post_options", {
            "select": "id", "id": f"eq.{option_id}", "post_id": f"eq.{post_id}", "limit": "1",
        })
        if not options:
            raise HTTPException(status_code=404, detail="ไม่พบตัวเลือกนี้")

        current = await repo.select("community_post_votes", {
            "select": "option_id", "post_id": f"eq.{post_id}", "open_id": f"eq.{user['id']}", "limit": "1",
        })
        already = bool(current) and int(current[0]["option_id"]) == option_id
        if already:
            await repo.delete("community_post_votes", {"post_id": f"eq.{post_id}", "open_id": f"eq.{user['id']}"})
            my_vote = None
        else:
            saved = await repo.upsert(
                "community_post_votes",
                {"post_id": post_id, "option_id": option_id, "open_id": user["id"]},
                "post_id,open_id",
            )
            if saved is None:
                raise database_error(repo, "บันทึกโหวตไม่สำเร็จ")
            my_vote = option_id

        posts = await repo.select("community_posts", {"select": "id", "id": f"eq.{post_id}", "limit": "1"})
        if not posts:
            raise HTTPException(status_code=404, detail="ไม่พบกระทู้นี้")
        await attach_details(posts, user["id"])
        post = posts[0]
        return {
            "ok": True,
            "option_id": option_id,
            "my_vote": my_vote,
            "total_votes": int(post.get("total_votes") or 0),
            "options": [
                {"id": option.get("id"), "label": option.get("label"), "votes": int(option.get("votes") or 0)}
                for option in post.get("options") or []
            ],
        }

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
