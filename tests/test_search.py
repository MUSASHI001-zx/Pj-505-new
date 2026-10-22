"""ทดสอบช่องค้นหากลาง (/api/search) — repository จำลอง ไม่ต้องต่อฐานข้อมูลจริง

รัน: python tests/test_search.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {extra}")
        FAILURES.append(label)


class FakeRepo:
    def __init__(self) -> None:
        self.configured = True
        self.last_database_error: str | None = None
        self.tables: dict[str, list[dict[str, Any]]] = {
            "faculties": [
                {"id": 1, "institution": "มหาวิทยาลัยธรรมศาสตร์", "name": "คณะนิติศาสตร์", "program": "น.บ.", "degree": "นานาชาติ"},
                {"id": 2, "institution": "มหาวิทยาลัยธรรมศาสตร์", "name": "คณะรัฐศาสตร์", "program": "ร.บ.", "degree": "นานาชาติ"},
            ],
            "admissions": [
                {"id": 10, "institution": "มหาวิทยาลัยธรรมศาสตร์", "faculty": "คณะนิติศาสตร์", "program": "น.บ.", "round": "รอบ 1"},
            ],
        }

    async def select(self, table: str, params: dict[str, str], quiet: bool = False) -> list[dict[str, Any]] | None:
        rows = self.tables.get(table)
        if rows is None:
            return None
        needle = ""
        if "or" in params:
            # จำลอง ilike อย่างง่าย — เอาค่าหลัง ilike. ออกมา
            parts = params["or"].split("ilike.*")
            needle = parts[-1].split("*")[0].lower()
        if needle:
            rows = [row for row in rows if any(needle in str(value or "").lower() for value in row.values())]
        limit = int(params.get("limit", 100))
        return rows[:limit]

    async def column_exists(self, table: str, column: str) -> bool:
        return column in ("id", "name", "institution", "program", "degree", "source_url", "faculty", "round")


async def main() -> int:
    repo = FakeRepo()

    import app.main as main_module
    import app.tcas_sync as sync_module

    # จำลองข้อมูล myTCAS — ไม่ต้องยิงเน็ต
    UNIVERSITIES = [
        {"tc_uid": "005", "name": "มหาวิทยาลัยธรรมศาสตร์", "name_en": "Thammasat University",
         "short_name": "มธ", "logoUrl": "https://assets.mytcas.com/i/logo/005.png", "kind": "รัฐ", "kind_label": "รัฐ"},
        {"tc_uid": "001", "name": "จุฬาลงกรณ์มหาวิทยาลัย", "name_en": "Chulalongkorn University",
         "short_name": "จุ", "logoUrl": "https://assets.mytcas.com/i/logo/001.png", "kind": "รัฐ", "kind_label": "รัฐ"},
    ]

    async def fake_live_universities() -> list[dict[str, Any]]:
        return UNIVERSITIES

    async def fake_live_faculty_search(needle: str, take: int = 8) -> list[dict[str, Any]]:
        if "วิศว" not in needle:
            return []
        return [{"name": "คณะวิศวกรรมศาสตร์", "institution": "มหาวิทยาลัยธรรมศาสตร์", "program": "ว.ศบ.", "url": "/quota"}]

    async def fake_news(limit: int = 120):
        return ([{"id": 1, "title": "ประกาศ TCAS รอบ 1", "summary": "ติดตามปฏิทิน", "source_url": "https://mytcas.com/x"}], 1)

    sync_module.live_universities = fake_live_universities
    sync_module.live_faculty_search = fake_live_faculty_search
    main_module.fetch_mytcas_news_with_total = fake_news
    main_module.repo = repo

    app = FastAPI()
    app.include_router(main_module.app.router)
    client = TestClient(app)

    print("\n=== 1. ค้นหาที่มีผลลัพธ์ ===")
    found = client.get("/api/search", params={"q": "ธรรมศาสตร์"})
    check("ตอบ 200", found.status_code == 200, found.text[:200])
    data = found.json()
    groups = data.get("groups") or {}
    check("คืน query", data.get("query") == "ธรรมศาสตร์", str(data.get("query")))
    check("มีกลุ่มมหาวิทยาลัย", "institutions" in groups, str(list(groups.keys())))
    check("มีกลุ่มคณะ", "faculties" in groups, str(list(groups.keys())))
    inst = groups.get("institutions") or []
    check("มหาวิทยาลัยที่เจอถูกต้อง", any(i["name"] == "มหาวิทยาลัยธรรมศาสตร์" for i in inst), str(inst))
    check("ผลลัพธ์มี url ให้กดไป", bool(inst and inst[0].get("url")), str(inst[:1]))
    check("มี logo", bool(inst and inst[0].get("logo_url")), str(inst[:1]))
    check("total ตรงกับจำนวนผลลัพธ์", data.get("total") == sum(len(v) for v in groups.values()), str(data.get("total")))

    print("\n=== 2. ค้นหาที่ไม่มีผลลัพธ์ ===")
    empty = client.get("/api/search", params={"q": "zzzzไม่มีจริง"}).json()
    check("ไม่มีผลลัพธ์", empty.get("total") == 0, str(empty.get("total")))
    check("groups ว่าง", not empty.get("groups"), str(empty.get("groups")))

    print("\n=== 3. คำค้นสั้นเกินไปไม่ต้องค้น ===")
    short = client.get("/api/search", params={"q": "a"}).json()
    check("ไม่ค้นเมื่อสั้นกว่า 2 ตัว", short.get("total") == 0 and not short.get("groups"), str(short))

    print("\n=== 4. คณะจาก myTCAS สด (ตารางว่าง) ===")
    live = client.get("/api/search", params={"q": "วิศวกรรม"}).json()
    fac_groups = (live.get("groups") or {}).get("faculties") or []
    check("เติมคณะจาก myTCAS สดได้", any("วิศวกรรม" in (f.get("name") or "") for f in fac_groups), str(fac_groups))

    print("\n=== 5. ข่าวเข้ากลุ่ม news ===")
    news = client.get("/api/search", params={"q": "TCAS"}).json()
    check("มีกลุ่มข่าว", "news" in (news.get("groups") or {}), str(list((news.get("groups") or {}).keys())))

    print("\n=== สรุป ===")
    if FAILURES:
        print(f"ผ่าน {len(FAILURES)} ข้อที่ไม่ผ่าน:")
        for item in FAILURES:
            print("  -", item)
        return 1
    print("ผ่านทั้งหมด")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
