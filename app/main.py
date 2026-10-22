from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .repository import SupabaseRepository
from .schemas import AccountUpdate, InviteCreate, InviteRedeem

BASE_DIR = Path(__file__).resolve().parent.parent
repo = SupabaseRepository()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """เปิด/ปิด HTTP client กลางตอนแอปเริ่มและหยุด"""
    yield
    await repo.aclose()


app = FastAPI(title="TCAS Buddy", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# โมดูลระบบชุมชน / Ticket / แอดมิน (ประกอบ router เพราะต้องใช้ repo ที่สร้างไว้ข้างบน)
from .admin import build_router as build_admin_router  # noqa: E402
from .ai_chat import build_router as build_ai_chat_router  # noqa: E402
from .community import build_router as build_community_router  # noqa: E402
from .scholarships import build_router as build_scholarships_router  # noqa: E402
from .tickets import build_router as build_tickets_router  # noqa: E402
from .tcas_ingest import build_router as build_tcas_ingest_router  # noqa: E402
from .tcas_live import build_router as build_tcas_live_router  # noqa: E402
from .tcas_news import build_router as build_tcas_news_router  # noqa: E402
from .tcas_news import fetch_news_with_total as fetch_mytcas_news_with_total  # noqa: E402
from .tcas_sync_api import build_router as build_tcas_sync_router  # noqa: E402
from .setup_check import build_router as build_setup_check_router  # noqa: E402

app.include_router(build_community_router(repo))
app.include_router(build_tickets_router(repo))
app.include_router(build_admin_router(repo))
app.include_router(build_tcas_ingest_router(repo))
app.include_router(build_setup_check_router(repo))
app.include_router(build_scholarships_router(repo))
app.include_router(build_tcas_sync_router(repo))
app.include_router(build_tcas_live_router(repo))
app.include_router(build_tcas_news_router(repo))
app.include_router(build_ai_chat_router(repo))

PAGE_META = {
    "login": ("เข้าสู่ระบบ", "เริ่มต้นใช้งาน TCAS Buddy"),
    "home": ("หน้าหลัก", "พื้นที่วางแผนเส้นทางเข้ามหาวิทยาลัยของเธอ"),
    "news": ("ข่าวสาร & อัปเดต", "รวมข่าว TCAS และการสมัครที่ควรรู้"),
    "institutes": ("ข้อมูลมหาวิทยาลัย", "สำรวจสถาบันและคณะที่น่าสนใจ"),
    "quota": ("ค้นหาโควตา / TCAS", "ค้นหารอบรับสมัครและเกณฑ์ที่เหมาะกับเธอ"),
    "scholarships": ("ค้นหาทุน", "ค้นหาทุนการศึกษาจากกสศ. และ Scholarship.in.th ในที่เดียว"),
    "identity": ("ค้นหาตัวตนของคุณ", "ลองตอบคำถาม แล้วค่อย ๆ รู้จักตัวเองมากขึ้น"),
    "community": ("ช่วยเหลือ & สร้างโพล", "คุย ขอความเห็น และรับคำปรึกษาเมื่อไหร่ก็ได้"),
    "faq": ("คู่มือใช้งาน & คำถามที่พบบ่อย", "เริ่มต้นใช้งาน TCAS Buddy ได้ง่าย ๆ"),
    "account": ("จัดการบัญชี", "โปรไฟล์ ข้อมูลส่วนตัว การแจ้งเตือน และลิงก์คำเชิญ"),
    "admin": ("ศูนย์จัดการแอดมิน", "ดูภาพรวมและจัดการข้อมูลของระบบ"),
}

SAMPLE_NEWS = [
    {"tag": "TCAS68", "title": "อัปเดตปฏิทิน TCAS และกำหนดการสำคัญ", "summary": "ติดตามรอบสมัครและสิ่งที่ต้องเตรียมก่อนยื่นจริง", "tone": "purple", "time": "ตัวอย่างเนื้อหา"},
    {"tag": "เตรียมตัว", "title": "เช็กลิสต์เอกสารก่อนสมัครมหาวิทยาลัย", "summary": "รวมเอกสารที่ควรจัดเตรียมให้พร้อมในที่เดียว", "tone": "blue", "time": "ตัวอย่างเนื้อหา"},
    {"tag": "A-Level", "title": "วางแผนอ่านหนังสือแบบไม่กดดันตัวเอง", "summary": "แบ่งเวลาให้พอดี แล้วค่อย ๆ สร้างความมั่นใจ", "tone": "pink", "time": "ตัวอย่างเนื้อหา"},
]

SAMPLE_INSTITUTES = [
    {"short": "CU", "name": "จุฬาลงกรณ์มหาวิทยาลัย", "city": "กรุงเทพฯ", "tone": "rose"},
    {"short": "MU", "name": "มหาวิทยาลัยมหิดล", "city": "นครปฐม", "tone": "teal"},
    {"short": "CMU", "name": "มหาวิทยาลัยเชียงใหม่", "city": "เชียงใหม่", "tone": "violet"},
    {"short": "KKU", "name": "มหาวิทยาลัยขอนแก่น", "city": "ขอนแก่น", "tone": "gold"},
    {"short": "TU", "name": "มหาวิทยาลัยธรรมศาสตร์", "city": "ปทุมธานี", "tone": "indigo"},
    {"short": "PSU", "name": "มหาวิทยาลัยสงขลานครินทร์", "city": "สงขลา", "tone": "green"},
]

SAMPLE_ADMISSIONS = [
    {"name": "มหาวิทยาลัยศิลปากร", "faculty": "อักษรศาสตร์", "round": "รอบ 1 Portfolio", "criteria": "ตรวจสอบเกณฑ์จากประกาศทางการ", "status": "เปิดดูรายละเอียด"},
    {"name": "มหาวิทยาลัยเกษตรศาสตร์", "faculty": "วิทยาศาสตร์", "round": "รอบ 2 Quota", "criteria": "ใช้ผลคะแนนตามประกาศคณะ", "status": "ดูแหล่งอ้างอิง"},
    {"name": "มหาวิทยาลัยธรรมศาสตร์", "faculty": "วารสารศาสตร์", "round": "รอบ 3 Admission", "criteria": "ดูรายละเอียดใน myTCAS", "status": "ตรวจสอบ"},
]

FAQS = [
    ("เริ่มใช้งาน TCAS Buddy อย่างไร?", "เริ่มจากเข้าสู่ระบบด้วย Google เลือกบทบาท และเลือกสิ่งที่อยากให้เราช่วยดูแล จากนั้นใช้เมนูด้านซ้ายเพื่อไปยังแต่ละฟีเจอร์"),
    ("ข้อมูลโควตาอ้างอิงจากที่ใด?", "ระบบจะแสดงแหล่งอ้างอิงและลิงก์ไปยัง myTCAS หรือประกาศทางการของมหาวิทยาลัยเสมอ โปรดตรวจสอบประกาศล่าสุดก่อนสมัครจริง"),
    ("กระดิ่งติดตามข่าวทำงานอย่างไร?", "กดติดตามบนหมวดข่าวที่สนใจ ระบบจะเตรียมแจ้งเตือนในบัญชีของคุณเมื่อมีข่าวใหม่ในหมวดนั้น"),
    ("AI ที่ปรึกษาในหน้าชุมชนใช้ทำอะไรได้บ้าง?", "ถามเรื่องเกณฑ์รับ โควตา ทุนการศึกษา หรือการเตรียมตัว TCAS ได้ โดย AI จะไปค้นข้อมูลจริงจาก myTCAS กสศ. และเด็กดีมาตอบ ไม่ตอบจากความจำล้วน ๆ"),
]


def context_for(page: str, request: Request) -> dict[str, Any]:
    title, subtitle = PAGE_META.get(page, PAGE_META["home"])
    return {
        "page": page,
        "title": title,
        "subtitle": subtitle,
        "page_meta": PAGE_META,
        "sample_news": SAMPLE_NEWS,
        "institutes": SAMPLE_INSTITUTES,
        "admissions": SAMPLE_ADMISSIONS,
        "faqs": FAQS,
        "supabase_ready": repo.configured,
        "supabase_url": repo.url,
        "request": request,
        "now": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health", response_class=JSONResponse)
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "tcasbuddy", "supabase_configured": repo.configured}


@app.get("/manus-routes.json", response_class=JSONResponse)
async def route_manifest() -> FileResponse:
    return FileResponse(BASE_DIR / "public" / "manus-routes.json", media_type="application/json")


@app.get("/api/config", response_class=JSONResponse)
async def public_config() -> dict[str, Any]:
    return {
        "supabase_url": repo.url,
        "supabase_anon_key": repo.anon_key,
        "configured": repo.auth_configured,
        "database_configured": repo.configured,
    }


@app.post("/api/auth/sync", response_class=JSONResponse)
async def sync_authenticated_user(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    authorization = request.headers.get("authorization", "")
    access_token = authorization.removeprefix("Bearer ").strip()
    if not access_token or not repo.auth_configured:
        raise HTTPException(status_code=401, detail="ไม่พบ session ของผู้ใช้")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(
                f"{repo.url}/auth/v1/user",
                headers={"apikey": repo.anon_key, "Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            auth_user = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=401, detail="session ไม่ถูกต้องหรือหมดอายุ") from None
    
    metadata = auth_user.get("user_metadata") or {}
    
    role = payload.get("role")
    if role is not None and role not in {"student", "parents", "teacher"}:
        raise HTTPException(status_code=400, detail="role ไม่ถูกต้อง")

    name = metadata.get("full_name") or metadata.get("name") or auth_user.get("email", "ผู้ใช้").split("@")[0]
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()  # คอลัมน์เป็น timestamp without time zone
    record: dict[str, Any] = {
        "openId": auth_user.get("id"),
        "name": name,
        "email": auth_user.get("email", ""),
        "loginMethod": (auth_user.get("app_metadata") or {}).get("provider", "google"),
        "lastSignedIn": now,
        "updatedAt": now,
    }
    if role:
        record["accountRole"] = role  # บทบาทที่ผู้ใช้เลือก (ไม่แตะคอลัมน์ role เดิม)

    if not record["openId"] or not await repo.sync_user(record):
        raise HTTPException(status_code=503, detail=repo.last_database_error or "บันทึกข้อมูลผู้ใช้ไม่สำเร็จ")

    return {"ok": True, "user": {"name": name, "email": record["email"], "role": role or "student"}}


@app.get("/api/stats", response_class=JSONResponse, response_model=None)
async def stats() -> dict[str, Any] | JSONResponse:
    if not repo.configured:
        return {"configured": False, "users": None, "views": None, "online": None}
    counts = await repo.stats()
    return {"configured": True, "database_ready": repo.last_database_error is None, **counts}


@app.post("/api/page-view", response_class=JSONResponse)
async def page_view(payload: dict[str, Any]) -> dict[str, Any]:
    stored = False
    if repo.configured:
        stored = await repo.insert("page_views", {"path": payload.get("path", "/"), "viewed_at": datetime.now(timezone.utc).isoformat()})
    return {"ok": stored}


@app.post("/api/presence", response_class=JSONResponse)
async def presence(payload: dict[str, Any]) -> dict[str, Any]:
    visitor_id = str(payload.get("visitor_id", "")).strip()
    if not visitor_id or len(visitor_id) > 120:
        raise HTTPException(status_code=400, detail="visitor_id ไม่ถูกต้อง")
    if repo.configured:
        await repo.touch_presence(visitor_id)
    return {"ok": True}


@app.get("/api/institutes", response_class=JSONResponse)
async def institutes(q: str = "", limit: int = 100) -> dict[str, Any]:
    """รายชื่อมหาวิทยาลัยจากตาราง institutions (หลังบ้านแอดมินจัดการได้)"""
    if not repo.configured:
        return {"items": [], "configured": False}
    # ขอเฉพาะคอลัมน์ที่มีจริง (คอลัมน์ใหม่มาจาก migration 008)
    optional = ["logoUrl", "short_name", "city", "kind", "tc_uid", "website_url"]
    columns = ["id", "name"] + [name for name in optional if await repo.column_exists("institutions", name)]
    params: dict[str, str] = {
        "select": ",".join(columns),
        "order": "name", "limit": str(max(1, min(limit, 200))),
    }
    if await repo.column_exists("institutions", "is_published"):
        params["is_published"] = "eq.true"
    needle = q.strip()
    if needle:
        safe = re.sub(r"[,(){}%*\\]", " ", needle).strip()
        if safe:
            params["name"] = f"ilike.*{safe}*"
    rows = await repo.select("institutions", params)
    if rows is None:
        return {"items": [], "configured": False}
    # เติมข้อมูลที่ตารางยังไม่มี (ชื่ออังกฤษ/ประเภท/โลโก้) จาก myTCAS
    tc_index: dict[str, dict[str, Any]] = {}
    try:
        from .tcas_sync import university_index
        tc_index = await university_index()
    except Exception:  # noqa: BLE001 — ข้อมูล myTCAS ใช้ไม่ได้ก็ยังแสดงข้อมูลจากฐานข้อมูลได้
        tc_index = {}
    by_name = {record["name"]: record for record in tc_index.values() if record.get("name")}

    items = []
    for row in rows or []:
        logo = row.get("logoUrl")
        if not logo and row.get("tc_uid"):
            logo = f"https://assets.mytcas.com/i/logo/{row['tc_uid']}.png"
        live = by_name.get(row.get("name") or "")
        if live and not logo:
            logo = live.get("logoUrl")
        items.append({
            "id": row.get("id"),
            "name": row.get("name"),
            "short_name": row.get("short_name"),
            "city": row.get("city"),
            "kind": row.get("kind") or (live or {}).get("kind"),
            "name_en": (live or {}).get("name_en"),
            "logo_url": logo,
            "website_url": row.get("website_url") or (live or {}).get("website_url"),
        })
    return {"items": items, "configured": True}


@app.get("/api/admissions", response_class=JSONResponse)
async def admissions(q: str = "", limit: int = 100) -> dict[str, Any]:
    """รายการเกณฑ์รับ/รอบสมัคร (หลังบ้านแอดมินจัดการได้)"""
    if not repo.configured:
        return {"items": [], "configured": False}
    params: dict[str, str] = {
        "select": "id,institution,faculty,program,round,criteria,source_url,source_label,deadline",
        "order": "id.desc", "limit": str(max(1, min(limit, 200))),
    }
    if await repo.column_exists("admissions", "is_published"):
        params["is_published"] = "eq.true"
    needle = q.strip()
    if needle:
        safe = re.sub(r"[,(){}%*\\]", " ", needle).strip()
        if safe:
            params["or"] = f"(institution.ilike.*{safe}*,faculty.ilike.*{safe}*)"
    rows = await repo.select("admissions", params)
    if rows is None:
        return {"items": [], "configured": False}
    return {"items": rows, "configured": True}


@app.get("/api/faculties", response_class=JSONResponse)
async def faculties(q: str = "", institution: str = "", limit: int = 100) -> dict[str, Any]:
    """รายชื่อคณะ/หลักสูตรจากตาราง faculties (ข้อมูลที่ sync มาจาก myTCAS)"""
    if not repo.configured:
        return {"items": [], "configured": False}
    params: dict[str, str] = {
        "select": "id,institution,name,program,degree,source_url",
        "order": "name", "limit": str(max(1, min(limit, 300))),
    }
    if await repo.column_exists("faculties", "is_published"):
        params["is_published"] = "eq.true"
    needle = q.strip()
    if needle:
        safe = re.sub(r"[,(){}%*\\]", " ", needle).strip()
        if safe:
            params["or"] = f"(name.ilike.*{safe}*,program.ilike.*{safe}*)"
    if institution.strip():
        params["institution"] = f"eq.{institution.strip()}"
    rows = await repo.select("faculties", params)
    if rows is None:
        return {"items": [], "configured": False}
    return {"items": rows, "configured": True}


@app.get("/api/news", response_class=JSONResponse)
async def news(q: str = "", limit: int = 50) -> dict[str, Any]:
    """รายการข่าวประกาศจาก myTCAS (สด) — ไม่ต้องใช้ Make.com

    คืน {id,title,summary,news_date,image_url,pdf_url,source_url,content}
    """
    try:
        items, total = await fetch_mytcas_news_with_total(limit=min(max(limit, 1), 120))
    except Exception as exc:  # noqa: BLE001 — ถ้า myTCAS มีปัญหา ให้แสดงข้อมูลตัวอย่างแทน
        needle = q.strip().lower()
        samples = [item for item in SAMPLE_NEWS if not needle or needle in (item["title"] + item["summary"] + item["tag"]).lower()]
        return {
            "items": samples,
            "configured": repo.auth_configured,
            "database_ready": False,
            "sample_mode": True,
            "error": str(exc)[:200],
        }

    needle = q.strip().lower()
    if needle:
        items = [
            item for item in items
            if needle in f"{item.get('title', '')} {item.get('summary', '')} {item.get('content', '')}".lower()
        ]
        total = len(items)
    return {
        "items": items,
        "total": total,
        "returned": len(items),
        "configured": True,
        "database_ready": True,
        "source": "mytcas",
        "source_label": "myTCAS",
    }


# ---------------------------------------------------------------------------
# ระบบจัดการบัญชี (โปรไฟล์, คณะที่สนใจ, การแจ้งเตือน, ลิงก์คำเชิญ)
# ---------------------------------------------------------------------------
AVATAR_DIR = BASE_DIR / "static" / "assets" / "avatars"
AVATAR_EXTS = {".svg", ".png", ".webp", ".jpg", ".jpeg"}
GRADE_LEVELS = ["ม.4", "ม.5", "ม.6", "ปวช.", "ปวส.", "จบการศึกษาแล้ว", "อื่น ๆ"]
FACULTY_OPTIONS = [
    "แพทยศาสตร์", "ทันตแพทยศาสตร์", "เภสัชศาสตร์", "พยาบาลศาสตร์", "สัตวแพทยศาสตร์", "สาธารณสุขศาสตร์",
    "วิศวกรรมศาสตร์", "วิทยาศาสตร์", "วิทยาการคอมพิวเตอร์ / IT", "สถาปัตยกรรมศาสตร์", "เกษตรศาสตร์",
    "บริหารธุรกิจ / พาณิชยศาสตร์", "เศรษฐศาสตร์", "นิติศาสตร์", "รัฐศาสตร์",
    "นิเทศศาสตร์ / วารสารศาสตร์", "อักษรศาสตร์ / มนุษยศาสตร์", "ครุศาสตร์ / ศึกษาศาสตร์", "จิตวิทยา", "ศิลปกรรมศาสตร์ / ดุริยางคศาสตร์",
]
MAX_FACULTIES = 10
NOTIFY_KEYS = ("news", "deadlines", "community", "ticket")
DEFAULT_NOTIFY = {key: True for key in NOTIFY_KEYS}
MAX_ACTIVE_INVITES = 10
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{4,40}$")
HOTLINE = {"name": "สายด่วน TCAS", "phone": "02-126-5111", "tel": "tel:021265111"}


def list_avatars() -> list[dict[str, str]]:
    """รูปโปรไฟล์ที่ให้ผู้ใช้เลือก = ไฟล์ทั้งหมดใน static/assets/avatars (เพิ่มไฟล์ใหม่แล้วโผล่เอง)"""
    found: dict[str, str] = {}
    if AVATAR_DIR.is_dir():
        for path in sorted(AVATAR_DIR.iterdir()):
            if path.is_file() and path.suffix.lower() in AVATAR_EXTS and re.fullmatch(r"[A-Za-z0-9_-]+", path.stem):
                found.setdefault(path.stem, f"/static/assets/avatars/{path.name}")
    return [{"key": key, "url": url} for key, url in found.items()]


async def require_user(request: Request) -> dict[str, Any]:
    """ตรวจ Bearer token กับ Supabase Auth แล้วคืนข้อมูลผู้ใช้ (ไม่เชื่อ user id จาก body/query)"""
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
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


def require_database() -> None:
    if not repo.configured:
        raise HTTPException(status_code=503, detail="ยังไม่ได้ตั้งค่า Supabase ฝั่งเซิร์ฟเวอร์")


def database_error(default: str) -> HTTPException:
    detail = default
    if repo.last_database_error and "does not exist" in repo.last_database_error:
        detail = "ยังไม่ได้สร้างตารางบัญชี — รัน supabase/migrations/006_account.sql ก่อน"
    return HTTPException(status_code=503, detail=detail)


def _clean(value: str | None) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def build_profile(
    auth_user: dict[str, Any],
    settings: dict[str, Any] | None,
    user_row: dict[str, Any] | None,
    role: str | None = None,
) -> dict[str, Any]:
    settings = settings or {}
    metadata = auth_user.get("user_metadata") or {}
    email = auth_user.get("email", "")
    google_name = metadata.get("full_name") or metadata.get("name") or email.split("@")[0] or "ผู้ใช้"
    avatars = {item["key"]: item["url"] for item in list_avatars()}
    avatar_key = settings.get("avatar_key") if settings.get("avatar_key") in avatars else None
    resolved_role = role or (user_row or {}).get("accountRole") or "student"
    return {
        "display_name": settings.get("display_name") or (user_row or {}).get("name") or google_name,
        "has_custom_name": bool(settings.get("display_name")),
        "email": email,
        "role": resolved_role,
        "avatar_key": avatar_key,
        "avatar_url": avatars.get(avatar_key) if avatar_key else None,
        "school": settings.get("school") or "",
        "grade_level": settings.get("grade_level") or "",
        "classroom": settings.get("classroom") or "",
        "interested_faculties": settings.get("interested_faculties") or [],
        "notify_prefs": {**DEFAULT_NOTIFY, **(settings.get("notify_prefs") or {})},
    }


@app.get("/api/account/options", response_class=JSONResponse)
async def account_options() -> dict[str, Any]:
    return {
        "avatars": list_avatars(),
        "faculties": FACULTY_OPTIONS,
        "max_faculties": MAX_FACULTIES,
        "grade_levels": GRADE_LEVELS,
        "hotline": HOTLINE,
    }


@app.get("/api/account", response_class=JSONResponse)
async def get_account(request: Request) -> dict[str, Any]:
    auth_user = await require_user(request)
    require_database()
    open_id = auth_user["id"]
    rows = await repo.select("user_settings", {"select": "*", "open_id": f"eq.{open_id}", "limit": "1"})
    if rows is None:
        raise database_error("อ่านข้อมูลบัญชีไม่สำเร็จ")
    user_rows = await repo.select("users", {"select": "name", "openId": f"eq.{open_id}", "limit": "1"})
    return {"profile": build_profile(auth_user, rows[0] if rows else None, (user_rows or [None])[0], await repo.user_role(open_id))}


@app.put("/api/account", response_class=JSONResponse)
async def update_account(request: Request, payload: AccountUpdate) -> dict[str, Any]:
    auth_user = await require_user(request)
    require_database()
    open_id = auth_user["id"]
    data = payload.model_dump(exclude_unset=True)
    record: dict[str, Any] = {}

    if "display_name" in data:
        record["display_name"] = _clean(data["display_name"])
    if "school" in data:
        record["school"] = _clean(data["school"])
    if "classroom" in data:
        record["classroom"] = _clean(data["classroom"])
    if "grade_level" in data:
        grade = _clean(data["grade_level"])
        if grade is not None and grade not in GRADE_LEVELS:
            raise HTTPException(status_code=400, detail="ระดับชั้นไม่ถูกต้อง")
        record["grade_level"] = grade
    if "avatar_key" in data:
        key = data["avatar_key"]
        if key is not None and key not in {item["key"] for item in list_avatars()}:
            raise HTTPException(status_code=400, detail="ไม่พบรูปโปรไฟล์นี้")
        record["avatar_key"] = key
    if "interested_faculties" in data:
        picked = list(dict.fromkeys(data["interested_faculties"] or []))
        if len(picked) > MAX_FACULTIES:
            raise HTTPException(status_code=400, detail=f"เลือกคณะได้ไม่เกิน {MAX_FACULTIES} รายการ")
        if any(item not in FACULTY_OPTIONS for item in picked):
            raise HTTPException(status_code=400, detail="มีคณะที่ไม่อยู่ในรายการ")
        record["interested_faculties"] = picked
    if "notify_prefs" in data:
        incoming = data["notify_prefs"] or {}
        if any(key not in NOTIFY_KEYS for key in incoming):
            raise HTTPException(status_code=400, detail="ประเภทการแจ้งเตือนไม่ถูกต้อง")
        existing = await repo.select("user_settings", {"select": "notify_prefs", "open_id": f"eq.{open_id}", "limit": "1"})
        if existing is None:
            raise database_error("บันทึกการตั้งค่าไม่สำเร็จ")
        current = {**DEFAULT_NOTIFY, **((existing[0].get("notify_prefs") if existing else None) or {})}
        record["notify_prefs"] = {**current, **incoming}

    if not record:
        raise HTTPException(status_code=400, detail="ไม่มีข้อมูลที่ต้องบันทึก")
    record["open_id"] = open_id
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    saved = await repo.upsert("user_settings", record, "open_id")
    if saved is None:
        raise database_error("บันทึกข้อมูลบัญชีไม่สำเร็จ")
    user_rows = await repo.select("users", {"select": "name", "openId": f"eq.{open_id}", "limit": "1"})
    return {"ok": True, "profile": build_profile(auth_user, saved, (user_rows or [None])[0], await repo.user_role(open_id))}


def _invite_state(row: dict[str, Any], uses: int, now: datetime) -> str:
    if row.get("revoked_at"):
        return "revoked"
    expires = row.get("expires_at")
    if expires:
        try:
            if datetime.fromisoformat(expires.replace("Z", "+00:00")) <= now:
                return "expired"
        except ValueError:
            pass
    if row.get("max_uses") and uses >= row["max_uses"]:
        return "full"
    return "active"


@app.get("/api/account/invites", response_class=JSONResponse)
async def list_invites(request: Request) -> dict[str, Any]:
    auth_user = await require_user(request)
    require_database()
    rows = await repo.select("invite_links", {
        "select": "code,label,max_uses,expires_at,revoked_at,created_at",
        "created_by": f"eq.{auth_user['id']}", "order": "created_at.desc", "limit": "50",
    })
    if rows is None:
        raise database_error("อ่านลิงก์คำเชิญไม่สำเร็จ")
    uses: dict[str, int] = {}
    if rows:
        codes = ",".join(row["code"] for row in rows)
        redemptions = await repo.select("invite_redemptions", {"select": "code", "code": f"in.({codes})", "limit": "5000"})
        for item in redemptions or []:
            uses[item["code"]] = uses.get(item["code"], 0) + 1
    now = datetime.now(timezone.utc)
    items = [{**row, "uses": uses.get(row["code"], 0), "status": _invite_state(row, uses.get(row["code"], 0), now)} for row in rows]
    return {"items": items, "max_active": MAX_ACTIVE_INVITES}


@app.post("/api/account/invites", response_class=JSONResponse, status_code=201)
async def create_invite(request: Request, payload: InviteCreate) -> dict[str, Any]:
    auth_user = await require_user(request)
    require_database()
    current = await list_invites(request)
    if sum(1 for item in current["items"] if item["status"] == "active") >= MAX_ACTIVE_INVITES:
        raise HTTPException(status_code=400, detail=f"มีลิงก์ที่ใช้งานได้ครบ {MAX_ACTIVE_INVITES} ลิงก์แล้ว ยกเลิกลิงก์เดิมก่อนสร้างใหม่")
    now = datetime.now(timezone.utc)
    record: dict[str, Any] = {
        "code": secrets.token_urlsafe(6),
        "created_by": auth_user["id"],
        "label": _clean(payload.label),
        "max_uses": payload.max_uses,
        "expires_at": (now + timedelta(days=payload.expires_in_days)).isoformat() if payload.expires_in_days else None,
    }
    if not await repo.insert("invite_links", record):
        raise database_error("สร้างลิงก์คำเชิญไม่สำเร็จ")
    return {"ok": True, "invite": {**record, "uses": 0, "status": "active", "created_at": now.isoformat(), "revoked_at": None}}


@app.delete("/api/account/invites/{code}", response_class=JSONResponse)
async def revoke_invite(request: Request, code: str) -> dict[str, Any]:
    auth_user = await require_user(request)
    require_database()
    if not CODE_RE.match(code):
        raise HTTPException(status_code=400, detail="รหัสลิงก์ไม่ถูกต้อง")
    ok = await repo.update(
        "invite_links",
        {"code": f"eq.{code}", "created_by": f"eq.{auth_user['id']}", "revoked_at": "is.null"},
        {"revoked_at": datetime.now(timezone.utc).isoformat()},
    )
    if not ok:
        raise database_error("ยกเลิกลิงก์ไม่สำเร็จ")
    return {"ok": True}


@app.post("/api/account/invites/redeem", response_class=JSONResponse)
async def redeem_invite(request: Request, payload: InviteRedeem) -> dict[str, Any]:
    auth_user = await require_user(request)
    require_database()
    rows = await repo.select("invite_links", {"select": "code,created_by,max_uses,expires_at,revoked_at,created_at", "code": f"eq.{payload.code}", "limit": "1"})
    if rows is None:
        raise database_error("ตรวจสอบลิงก์คำเชิญไม่สำเร็จ")
    if not rows:
        raise HTTPException(status_code=404, detail="ไม่พบลิงก์คำเชิญนี้")
    invite = rows[0]
    if invite["created_by"] == auth_user["id"]:
        raise HTTPException(status_code=400, detail="ใช้ลิงก์คำเชิญของตัวเองไม่ได้")
    taken = await repo.select("invite_redemptions", {"select": "open_id", "code": f"eq.{payload.code}", "limit": "5000"})
    if taken is None:
        raise database_error("ตรวจสอบลิงก์คำเชิญไม่สำเร็จ")
    if any(item["open_id"] == auth_user["id"] for item in taken):
        return {"ok": True, "already": True}
    state = _invite_state(invite, len(taken), datetime.now(timezone.utc))
    if state != "active":
        messages = {"revoked": "ลิงก์นี้ถูกยกเลิกแล้ว", "expired": "ลิงก์นี้หมดอายุแล้ว", "full": "ลิงก์นี้ถูกใช้ครบจำนวนแล้ว"}
        raise HTTPException(status_code=410, detail=messages[state])
    if not await repo.insert("invite_redemptions", {"code": payload.code, "open_id": auth_user["id"]}):
        raise database_error("รับคำเชิญไม่สำเร็จ")
    return {"ok": True, "already": False}


@app.get("/invite/{code}")
async def invite_landing(code: str) -> RedirectResponse:
    if not CODE_RE.match(code):
        raise HTTPException(status_code=404, detail="Page not found")
    return RedirectResponse(f"/login?invite={code}", status_code=302)


@app.get("/{page:path}", response_class=HTMLResponse)
async def pages(request: Request, page: str = "") -> HTMLResponse:
    normalized = page.strip("/") or "home"
    if normalized not in PAGE_META:
        raise HTTPException(status_code=404, detail="Page not found")
    return templates.TemplateResponse(request=request, name="app.html", context=context_for(normalized, request))