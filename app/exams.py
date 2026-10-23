"""คลังข้อสอบ: รวมข้อสอบจาก myTCAS ให้ค้นหาและดาวน์โหลด

- GET /api/exams?q=&kind=&group=     รายการ (ดึงสดจาก myTCAS แล้วแคช 6 ชม.; ดึงไม่ได้ใช้รายการสำรอง)
- GET /api/exams/{id}/download       ส่งไฟล์ PDF เฉลยให้ดาวน์โหลด (สตรีมจาก assets.mytcas.com เท่านั้น)

ไฟล์ทั้งหมดเป็นของ myTCAS/CUPT เราแค่รวมลิงก์และส่งต่อให้โหลดสะดวก พร้อมแสดงแหล่งที่มา
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .exam_catalog import (
    DOWNLOAD_RE,
    MYTCAS_SITE,
    discover_answer_pages,
    fallback_answers,
    fallback_blueprints,
    group_counts,
    parse_answer_page,
    parse_blueprint_index,
    search_items,
)

UA = "TCASBuddy/1.0 (+https://www.mytcas.com)"
CACHE_TTL = 6 * 3600.0
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,80}$")
_cache: dict[str, Any] = {"at": 0.0, "items": None, "live": False}


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        response = await client.get(url)
        response.raise_for_status()
        return response.text
    except httpx.HTTPError:
        return None


async def load_catalog(force: bool = False) -> tuple[list[dict[str, Any]], bool]:
    """คืน (รายการข้อสอบ, ดึงสดสำเร็จหรือไม่) — ถ้าดึงสดไม่ได้จะใช้แคชเก่าก่อน แล้วค่อยใช้รายการสำรอง"""
    fresh = _cache["items"] is not None and time.monotonic() - _cache["at"] < CACHE_TTL
    if fresh and not force:
        return _cache["items"], _cache["live"]

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=10.0),
        headers={"User-Agent": UA, "Accept": "text/html"},
        follow_redirects=True,
    ) as client:
        home = await _fetch_text(client, MYTCAS_SITE + "/")
        pages = discover_answer_pages(home or "")
        answer_pages, blueprint_page = await asyncio.gather(
            asyncio.gather(*(_fetch_text(client, page) for page in pages)),
            _fetch_text(client, MYTCAS_SITE + "/blueprint"),
        )

    answers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page, body in zip(pages, answer_pages):
        for item in parse_answer_page(body or "", page):
            if item["id"] not in seen:
                seen.add(item["id"])
                answers.append(item)
    blueprints = parse_blueprint_index(blueprint_page or "")

    live = bool(answers)
    if not live:
        if _cache["items"] is not None:  # ดึงสดพลาดรอบนี้ — ใช้ของเดิมที่เคยดึงสำเร็จไปก่อน
            return _cache["items"], _cache["live"]
        answers = fallback_answers()
    if not blueprints:
        blueprints = fallback_blueprints()

    items = answers + blueprints
    _cache.update(at=time.monotonic(), items=items, live=live)
    return items, live


def build_router(repo: Any = None) -> APIRouter:
    router = APIRouter(prefix="/api/exams")

    @router.get("")
    async def list_exams(q: str = "", kind: str = "", group: str = "") -> dict[str, Any]:
        items, live = await load_catalog()
        shown = search_items(items, q[:80], kind if kind in ("answer", "blueprint") else "", group[:40])
        return {
            "items": shown,
            "total": len(items),
            "groups": group_counts(search_items(items, q[:80], kind if kind in ("answer", "blueprint") else "")),
            "live": live,
            "source": MYTCAS_SITE,
        }

    @router.get("/{exam_id}/download")
    async def download(exam_id: str) -> StreamingResponse:
        if not ID_RE.match(exam_id):
            raise HTTPException(status_code=404, detail="ไม่พบไฟล์ข้อสอบ")
        items, _ = await load_catalog()
        item = next((i for i in items if i["id"] == exam_id and i["download"]), None)
        # ดาวน์โหลดได้เฉพาะ URL ที่อยู่ในรายการของเรา และต้องผ่านรูปแบบ assets.mytcas.com/..../answer/*.pdf
        if item is None or not DOWNLOAD_RE.match(item["url"]):
            raise HTTPException(status_code=404, detail="ไม่พบไฟล์ข้อสอบ")

        client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0), headers={"User-Agent": UA}, follow_redirects=False)
        try:
            upstream = await client.send(client.build_request("GET", item["url"]), stream=True)
        except httpx.HTTPError:
            await client.aclose()
            raise HTTPException(status_code=502, detail="เชื่อมต่อ myTCAS ไม่สำเร็จ ลองใหม่อีกครั้ง") from None
        if upstream.status_code != 200 or "pdf" not in upstream.headers.get("content-type", "").lower():
            status = upstream.status_code
            await upstream.aclose()
            await client.aclose()
            raise HTTPException(status_code=404 if status == 404 else 502, detail="myTCAS ยังไม่มีไฟล์นี้หรือเข้าถึงไม่ได้ในขณะนี้")

        async def body():
            try:
                async for chunk in upstream.aiter_bytes(65536):
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        headers = {
            "Content-Disposition": f'attachment; filename="{exam_id}.pdf"',
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        }
        if upstream.headers.get("content-length"):
            headers["Content-Length"] = upstream.headers["content-length"]
        return StreamingResponse(body(), media_type="application/pdf", headers=headers)

    return router
