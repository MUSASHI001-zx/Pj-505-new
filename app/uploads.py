"""อัปโหลดรูปภาพประกอบกระทู้ชุมชน — เก็บไฟล์ใน Supabase Storage (bucket community-uploads)

ข้อกำหนด:
- รับเฉพาะรูปภาพ (jpeg/png/webp/gif) ขนาดไม่เกิน 5 MB
- ตรวจ magic bytes จริง ไม่เชื่อ content-type ที่ client ส่งมา
- ชื่อไฟล์สุ่ม ไม่ใช้ชื่อจาก client เพื่อกัน path traversal
- คืน URL สาธารณะให้ฝั่งหน้าใช้แสดงผล
"""
from __future__ import annotations

import secrets
from typing import Any

from fastapi import HTTPException

BUCKET = "community-uploads"
MAX_BYTES = 5 * 1024 * 1024  # 5 MB

# magic bytes ของแต่ละชนิดไฟล์ — ใช้ตรวจว่าเป็นรูปจริง ไม่เชื่อ content-type จาก client
SIGNATURES: dict[bytes, str] = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
}
EXTENSIONS: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


def sniff_image_type(data: bytes) -> str | None:
    """เดา content type จาก bytes จริง — None ถ้าไม่ใช่รูปที่รองรับ"""
    for signature, mime in SIGNATURES.items():
        if data.startswith(signature):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def public_url(repo: Any, path: str) -> str:
    return f"{repo.url}/storage/v1/object/public/{BUCKET}/{path}"


async def upload_image(repo: Any, data: bytes, open_id: str) -> str:
    """อัปโหลดรูปหนึ่งใบ คืน URL สาธารณะ"""
    if not data:
        raise HTTPException(status_code=400, detail="ไม่พบไฟล์รูป")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="รูปใหญ่เกิน 5 MB")

    mime = sniff_image_type(data)
    if mime is None:
        raise HTTPException(status_code=400, detail="รองรับเฉพาะไฟล์รูป (JPG, PNG, WEBP, GIF)")

    if not await repo.storage_bucket_exists(BUCKET):
        raise HTTPException(
            status_code=503,
            detail="ยังไม่ได้สร้างช่องเก็บรูป — รัน supabase/migrations/014_community_images_and_votes.sql ก่อน",
        )

    # ชื่อไฟล์สุ่ม — ไม่ใช้ชื่อจาก client ป้องกัน path traversal
    path = f"posts/{open_id[:8]}-{secrets.token_hex(8)}.{EXTENSIONS.get(mime, 'jpg')}"

    if not await repo.storage_upload(BUCKET, path, data, mime):
        raise HTTPException(status_code=503, detail="อัปโหลดรูปไม่สำเร็จ — ลองใหม่อีกครั้ง")
    return public_url(repo, path)


async def remove_image(repo: Any, image_url: str) -> None:
    """ลบรูปที่อัปโหลดไว้ (ใช้ตอนสร้างกระทู้ไม่สำเร็จ) — ล้มเหลวก็ไม่ทำให้อะไรพัง"""
    marker = f"/object/public/{BUCKET}/"
    if marker not in image_url:
        return
    path = image_url.split(marker, 1)[1].split("?", 1)[0]
    await repo.storage_delete(BUCKET, path)
