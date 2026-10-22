"""ซิงก์ข้อมูล myTCAS ทั้งหมดลงฐานข้อมูล (มหาวิทยาลัย/คณะ/รอบรับสมัคร)

รัน: python scripts/sync_mytcas.py              # ดึงครั้งแรก 600 program
     python scripts/sync_mytcas.py --all        # ดึงครบทั้งหมด (ช้า ~5 นาที)
     python scripts/sync_mytcas.py --limit 200  # กำหนดจำนวน program ต่อรอบ
     python scripts/sync_mytcas.py --institutions  # ซิงก์เฉพาะรายชื่อมหาวิทยาลัย (เร็ว)
     python scripts/sync_mytcas.py --dry-run    # ดึงและนับอย่างเดียว ไม่เขียนฐานข้อมูล

หมายเหตุ: ต้องรัน supabase/migrations/011_tcas_mytcas_sync.sql ก่อน (เพิ่มคอลัมน์เกณฑ์คะแนน)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.repository import SupabaseRepository  # noqa: E402
from app.tcas_sync import ROUNDS_BATCH_LIMIT, sync_all, sync_institutions  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=ROUNDS_BATCH_LIMIT, help="จำนวน program ที่ดึงรอบรับต่อรอบ")
    parser.add_argument("--all", action="store_true", help="ดึงครบทุก program (ช้า)")
    parser.add_argument("--dry-run", action="store_true", help="ไม่เขียนฐานข้อมูล")
    parser.add_argument("--institutions", action="store_true", help="ซิงก์เฉพาะรายชื่อมหาวิทยาลัย/สถาบัน (เร็ว)")
    args = parser.parse_args()

    repo = SupabaseRepository()
    if not repo.configured:
        print("Supabase ยังไม่ได้ตั้งค่า — ตรวจค่าใน .env")
        return 1

    # โหมดซิงก์เฉพาะมหาวิทยาลัย — เร็ว ใช้เติมข้อมูลที่ตารางยังขาด
    if args.institutions:
        started = time.monotonic()
        print("กำลังซิงก์รายชื่อมหาวิทยาลัย/สถาบันจาก myTCAS...")
        result = await sync_institutions(repo)
        elapsed = time.monotonic() - started
        print(f"\nเสร็จใน {elapsed:.1f} วินาที")
        print(f"  จาก myTCAS   : {result['total']} แห่ง")
        print(f"  อัปเดตแถวเดิม: {result['updated']}")
        print(f"  เพิ่มแถวใหม่ : {result['inserted']}")
        for message in result.get("errors", []):
            print(f"  ข้อผิดพลาด: {message}")
        return 0

    limit = 999_999 if args.all else args.limit
    started = time.monotonic()
    print(f"กำลังซิงก์ข้อมูล myTCAS (สูงสุด {limit} program)...")
    summary = await sync_all(repo, program_limit=limit)
    elapsed = time.monotonic() - started

    print(f"\nเสร็จใน {elapsed:.1f} วินาที")
    print(f"  มหาวิทยาลัย : {summary['institutions']} แห่ง")
    print(f"  คณะ/หลักสูตร: {summary['faculties']} รายการ")
    print(f"  รอบรับสมัคร : {summary['admissions']} รายการ")
    if summary.get("program_total"):
        print(f"  program ทั้งหมด: {summary['program_total']}")
    if summary.get("has_more"):
        print("  ยังเหลือ — รันซ้ำอีกครั้งเพื่อดึงส่วนที่เหลือ")
    if summary.get("errors"):
        print(f"  ข้อผิดพลาด {len(summary['errors'])} รายการ:")
        for message in summary["errors"][:5]:
            print(f"    - {message}")
    if repo.last_database_error:
        print(f"  error ล่าสุด: {repo.last_database_error[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
