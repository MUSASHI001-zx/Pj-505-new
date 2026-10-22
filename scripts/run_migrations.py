"""รันไฟล์ migration ใน Supabase ผ่าน Postgres connection string (ต้องมี psycopg)

ใช้ค่า DATABASE_URL จาก .env หรือ argument:
    python scripts/run_migrations.py                 # รันเฉพาะไฟล์ที่ยังไม่เคยรัน
    python scripts/run_migrations.py 007 008        # รันเฉพาะไฟล์ที่ระบุ
    python scripts/run_migrations.py --list         # ดูตารางและสถานะ migration
    python scripts/run_migrations.py --check        # ตรวจ SQL ทุกไฟล์ (ไม่รันจริง)

สถานะการรันถูกเก็บในตาราง public.schema_migrations — ไฟล์ที่รันแล้วจะถูกข้าม
หา connection string: Supabase Dashboard → Project Settings → Database → Connection string
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

# migration ที่ทำงานกับ schema ปัจจุบันของโปรเจกต์นี้ (001-006 ถูกรันไว้ก่อนหน้านี้แล้ว)
PRESEEDED = {"001", "002", "003", "004", "005", "006"}


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


def connection_string() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit(
            "ไม่พบ DATABASE_URL\n"
            "ใส่ connection string ลง .env เช่น:\n"
            "  DATABASE_URL=postgresql://postgres:PASSWORD@db.XXXX.supabase.co:5432/postgres\n"
            "หรือใช้โรงสร้างใน Supabase Dashboard → Project Settings → Database"
        )
    return url


def parse_args() -> list[str]:
    return [arg for arg in sys.argv[1:] if not arg.startswith("-")]


async def ensure_tracking(conn) -> None:
    async with conn.cursor() as cur:
        await cur.execute("""
            create table if not exists public.schema_migrations (
              name text primary key,
              applied_at timestamptz not null default now()
            )
        """)
        # ทำเครื่องหมายว่าไฟล์ที่รันไว้ก่อนหน้านี้ (ก่อนมีตารางบันทึก) ถือว่ารันแล้ว
        for prefix in PRESEEDED:
            await cur.execute(
                "insert into public.schema_migrations (name) values (%s) on conflict (name) do nothing",
                (f"{prefix}_preexisting",),
            )


async def applied_migrations(conn) -> set[str]:
    async with conn.cursor() as cur:
        await cur.execute("select name from public.schema_migrations")
        return {row[0] for row in await cur.fetchall()}


async def list_tables(conn) -> set[str]:
    async with conn.cursor() as cur:
        await cur.execute("""
            select table_name from information_schema.tables
            where table_schema = 'public' order by table_name
        """)
        return {row[0] for row in await cur.fetchall()}


async def run() -> int:
    load_env()
    try:
        import psycopg
    except ImportError:
        raise SystemExit("ไม่พบ psycopg — ติดตั้งด้วย: pip install \"psycopg[binary]\"") from None

    url = connection_string()
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    wanted = parse_args()

    conn = await psycopg.AsyncConnection.connect(url, autocommit=True)
    try:
        await ensure_tracking(conn)
        applied = await applied_migrations(conn)
        tables = await list_tables(conn)

        if "--list" in sys.argv:
            print(f"ตารางที่มีอยู่ ({len(tables)}):")
            for name in sorted(tables):
                print(f"  - {name}")
            print(f"\nmigration ที่รันแล้ว ({len(applied)}):")
            for name in sorted(applied):
                print(f"  - {name}")
            pending = [f for f in files if f.stem.split("_")[0] not in {a.split("_")[0] for a in applied}]
            print(f"\nรอรัน: {', '.join(f.name for f in pending) if pending else 'ไม่มี'}")
            return 0

        if "--check" in sys.argv:
            # ตรวจว่าไฟล์ที่รอรันอ่านได้และไม่ว่าง
            pending = [f for f in files if f.stem.split("_")[0] not in {a.split("_")[0] for a in applied}]
            for path in pending:
                sql = path.read_text(encoding="utf-8")
                print(f"{path.name}: {len(sql)} ตัวอักษร, {sql.count(';')} คำสั่ง — พร้อมรัน")
            return 0

        targets = [f for f in files if not wanted or any(w in f.name for w in wanted)]
        if not targets:
            print("ไม่พบไฟล์ migration ที่ระบุ")
            return 1

        ran = 0
        for path in targets:
            prefix = path.stem.split("_")[0]
            if prefix in {a.split("_")[0] for a in applied} and not wanted:
                print(f">>> {path.name} — ข้าม (รันไปแล้ว)")
                continue
            sql = path.read_text(encoding="utf-8")
            print(f">>> {path.name}")
            try:
                async with conn.cursor() as cur:
                    await cur.execute(sql)
                    await cur.execute(
                        "insert into public.schema_migrations (name) values (%s) on conflict (name) do nothing",
                        (path.stem,),
                    )
                print("    สำเร็จ")
                ran += 1
            except Exception as exc:  # noqa: BLE001
                print(f"    ผิดพลาด: {type(exc).__name__}: {exc}")
                return 1

        tables = await list_tables(conn)
    finally:
        await conn.close()

    print(f"\nรันไป {ran} ไฟล์ — ตารางใน public ตอนนี้ {len(tables)} ตาราง")
    for name in sorted(tables):
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    # psycopg async ต้องใช้ SelectorEventLoop — Windows ค่าเริ่มต้นเป็น Proactor (ไม่รองรับ)
    try:
        loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
        raise SystemExit(asyncio.run(run(), loop_factory=lambda: loop))
    except ImportError:  # pragma: no cover — ทางเลือกสำรอง
        raise SystemExit(asyncio.run(run()))
