"""สร้างตารางที่ยังขาดสำหรับระบบกระทู้ชุมชน / Ticket / หลังบ้านแอดมิน

รัน: python scripts/create_missing_tables.py

ใช้ DATABASE_URL จาก .env — เชื่อมต่อ Postgres ตรงแล้วรัน DDL ที่ REST API ของ Supabase ทำไม่ได้
รันทุกไฟล์ใน supabase/migrations/ ตามลำดับ (ทุกไฟล์ใช้ if not exists จึงรันซ้ำได้)
"""
from __future__ import annotations

import asyncio
import os
import selectors
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MIGRATIONS_DIR = ROOT / "supabase" / "migrations"
# ไฟล์ 001-006 รันไปแล้วกับ schema เดิมของโปรเจกต์ (อาจรันซ้ำไม่ได้) — ข้ามไป
SKIP_PREFIXES = ("001", "002", "003", "004", "005", "006")


def load_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


async def main() -> int:
    load_env()
    import psycopg

    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        print("ไม่พบ DATABASE_URL ใน .env")
        return 1

    files = sorted(
        path for path in MIGRATIONS_DIR.glob("*.sql")
        if not path.stem.startswith(SKIP_PREFIXES) and path.name != "007_009_all.sql"
    )
    if not files:
        print("ไม่พบไฟล์ migration")
        return 1

    conn = await psycopg.AsyncConnection.connect(url, autocommit=True)
    try:
        for path in files:
            sql = path.read_text(encoding="utf-8")
            print(f">>> {path.name} ({len(sql)} ตัวอักษร)")
            try:
                async with conn.cursor() as cur:
                    await cur.execute(sql)
                print("    สำเร็จ")
            except Exception as exc:  # noqa: BLE001
                print(f"    ผิดพลาด: {type(exc).__name__}: {exc}")
                return 1

        async with conn.cursor() as cur:
            await cur.execute("""
                select table_name from information_schema.tables
                where table_schema = 'public' order by table_name
            """)
            tables = [row[0] for row in await cur.fetchall()]
    finally:
        await conn.close()

    print(f"\nตารางใน public ตอนนี้ {len(tables)} ตาราง:")
    for name in tables:
        print(f"  - {name}")

    required = {
        "community_tags", "community_posts", "community_post_options", "community_comments",
        "community_post_likes", "community_post_votes", "tickets", "ticket_messages",
        "admin_presence", "faculties", "admissions", "admin_audit_log",
    }
    missing = required - set(tables)
    if missing:
        print(f"\nยังขาด: {', '.join(sorted(missing))}")
        return 1
    print("\nตารางที่จำเป็นครบทั้งหมดแล้ว")
    return 0


if __name__ == "__main__":
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    raise SystemExit(asyncio.run(main(), loop_factory=lambda: loop))
