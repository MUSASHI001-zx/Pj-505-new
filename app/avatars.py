"""รายการรูปโปรไฟล์ที่ผู้ใช้เลือกได้ (สแกนโฟลเดอร์ static/assets/avatars อัตโนมัติ)."""
from __future__ import annotations

import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
AVATAR_DIR = BASE_DIR / "static" / "assets" / "avatars"
AVATAR_EXTS = {".svg", ".png", ".webp", ".jpg", ".jpeg"}


def list_avatars() -> list[dict[str, str]]:
    """คืน [{key, url}] ของไฟล์รูปทั้งหมดในโฟลเดอร์ (เพิ่มไฟล์ใหม่แล้วโผล่เอง)"""
    found: dict[str, str] = {}
    if AVATAR_DIR.is_dir():
        for path in sorted(AVATAR_DIR.iterdir()):
            if path.is_file() and path.suffix.lower() in AVATAR_EXTS and re.fullmatch(r"[A-Za-z0-9_-]+", path.stem):
                found.setdefault(path.stem, f"/static/assets/avatars/{path.name}")
    return [{"key": key, "url": url} for key, url in found.items()]


def avatar_urls() -> dict[str, str]:
    return {item["key"]: item["url"] for item in list_avatars()}
