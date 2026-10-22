"""ทดสอบการซิงก์รายชื่อมหาวิทยาลัยจาก myTCAS (repository จำลอง — ไม่ต้องต่อฐานข้อมูลจริง)

รัน: python tests/test_tcas_sync.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.tcas_sync import (  # noqa: E402
    TYPE_ABBREVIATIONS,
    TYPE_LABELS,
    live_universities,
    sync_institutions,
    university_record,
)

FAILURES: list[str] = []

# ข้อมูล myTCAS จริง (ตัวอย่างครบทุกประเภท)
SAMPLE = [
    {"university_id": "001", "university_type": "1", "university_name": "จุฬาลงกรณ์มหาวิทยาลัย", "university_name_en": "Chulalongkorn University"},
    {"university_id": "142", "university_type": "2", "university_name": "มหาวิทยาลัยราชภัฏชัยภูมิ", "university_name_en": "Chaiyaphum Rajabhat University"},
    {"university_id": "191", "university_type": "3", "university_name": "มหาวิทยาลัยเทคโนโลยีราชมงคลธัญบุรี", "university_name_en": "Rajamangala University of Technology Thanyaburi"},
    {"university_id": "054", "university_type": "4", "university_name": "มหาวิทยาลัยศรีปทุม", "university_name_en": "Siam University"},
    {"university_id": "221", "university_type": "5", "university_name": "สถาบันพระบรมราชชนก", "university_name_en": "Praboromarajchanok Institute"},
]


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {extra}")
        FAILURES.append(label)


class FakeRepo:
    """repository จำลอง — เก็บ institutions ใน memory"""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.configured = True
        self.rows: list[dict[str, Any]] = rows or []
        self.last_database_error: str | None = None
        self.next_id = 1

    async def select(self, table: str, params: dict[str, str], quiet: bool = False) -> list[dict[str, Any]] | None:
        if table != "institutions":
            return None
        return [dict(row) for row in self.rows]

    async def column_exists(self, table: str, column: str) -> bool:
        return column in {
            "id", "name", "tc_uid", "name_en", "kind", "tc_type", "tc_type_name",
            "website_url", "logoUrl", "short_name", "city", "is_published", "updated_at",
        }

    async def update(self, table: str, params: dict[str, str], record: dict[str, Any]) -> bool:
        target = params.get("id", "")
        wanted = target.removeprefix("eq.")
        for row in self.rows:
            if str(row.get("id")) == wanted:
                row.update(record)
                return True
        return False

    async def upsert(self, table: str, record: dict[str, Any], on_conflict: str) -> dict[str, Any] | None:
        for row in self.rows:
            if row.get(on_conflict) == record.get(on_conflict):
                row.update(record)
                return row
        self.next_id += 1
        new = {"id": self.next_id, **record}
        self.rows.append(new)
        return new


async def main() -> int:
    print("\n=== 1. การแมปประเภทสถาบันตรงกับ myTCAS ===")
    # courses.json ยืนยันว่า 1=ทปอ. 2=มรภ. 3=มทร. 4=เอกชน
    check("type 1 (ทปอ.) = รัฐ", TYPE_LABELS["1"] == "รัฐ", TYPE_LABELS["1"])
    check("type 2 (มรภ./ราชภัฏ) = รัฐ ไม่ใช่เอกชน", TYPE_LABELS["2"] == "รัฐ", TYPE_LABELS["2"])
    check("type 3 (มทร.) = ราชมงคล", TYPE_LABELS["3"] == "ราชมงคล", TYPE_LABELS["3"])
    check("type 4 = เอกชน", TYPE_LABELS["4"] == "เอกชน", TYPE_LABELS["4"])
    check("type 5 = อื่น ๆ", TYPE_LABELS["5"] == "อื่น ๆ", TYPE_LABELS["5"])
    check("มีป้ายย่อครบทุกประเภท", set(TYPE_ABBREVIATIONS) == set(TYPE_LABELS))

    print("\n=== 2. university_record แปลงข้อมูลถูกต้อง ===")
    rec = university_record(SAMPLE[1])
    check("tc_uid ถูกต้อง", rec["tc_uid"] == "142", str(rec["tc_uid"]))
    check("name_en ถูกต้อง", rec["name_en"] == "Chaiyaphum Rajabhat University", str(rec["name_en"]))
    check("kind = รัฐ (มรภ.)", rec["kind"] == "รัฐ", str(rec["kind"]))
    check("tc_type เก็บรหัสเดิม", rec["tc_type"] == "2", str(rec["tc_type"]))
    check("โลโก้ชี้ไป assets.mytcas.com", rec["logoUrl"] == "https://assets.mytcas.com/i/logo/142.png", str(rec["logoUrl"]))
    check("ลิงก์หน้า myTCAS ถูกต้อง", rec["website_url"] == "https://www.mytcas.com/university/142", str(rec["website_url"]))
    check("short_name มีค่า", bool(rec["short_name"]), str(rec["short_name"]))

    print("\n=== 3. live_universities คืน kind_label ===")
    import app.tcas_sync as sync_module

    async def fake_fetch_universities(client, force=False):
        return SAMPLE

    sync_module.fetch_universities = fake_fetch_universities
    sync_module._cache.clear()
    live = await live_universities()
    check("คืนครบทุกแห่ง", len(live) == len(SAMPLE), str(len(live)))
    check("มี kind_label", all(item.get("kind_label") for item in live))
    rajabhat = next((i for i in live if i["tc_uid"] == "142"), None)
    check("ราชภัฏได้ kind_label = รัฐ", bool(rajabhat) and rajabhat["kind_label"] == "รัฐ", str(rajabhat))
    check("tc_type_name = มรภ.", bool(rajabhat) and rajabhat["tc_type_name"] == "มรภ.", str(rajabhat))
    sync_module._cache.clear()

    print("\n=== 4. sync_institutions เติมข้อมูลแถวเดิมที่ tc_uid ว่าง ===")
    # จำลองสถานะเดิมในฐานข้อมูล: มี 2 แถวที่ tc_uid = NULL
    repo = FakeRepo([
        {"id": 1, "name": "จุฬาลงกรณ์มหาวิทยาลัย", "tc_uid": None, "kind": None, "city": None},
        {"id": 2, "name": "มหาวิทยาลัยราชภัฏชัยภูมิ", "tc_uid": None, "kind": None, "city": None},
    ])
    sync_module.fetch_universities = fake_fetch_universities
    sync_module._cache.clear()
    result = await sync_institutions(repo)
    check("อัปเดตแถวเดิม 2 แถว", result["updated"] == 2, str(result))
    check("เพิ่มแถวใหม่ 3 แถว", result["inserted"] == 3, str(result))
    chula = next((r for r in repo.rows if r["name"] == "จุฬาลงกรณ์มหาวิทยาลัย"), None)
    check("เติม tc_uid ให้แถวเดิม", bool(chula) and chula["tc_uid"] == "001", str(chula))
    check("เติม kind ให้แถวเดิม", bool(chula) and chula["kind"] == "รัฐ", str(chula))
    check("เติม name_en ให้แถวเดิม", bool(chula) and chula["name_en"] == "Chulalongkorn University", str(chula))
    rajabhat_row = next((r for r in repo.rows if r["name"] == "มหาวิทยาลัยราชภัฏชัยภูมิ"), None)
    check("แถวราชภัฏได้ kind = รัฐ", bool(rajabhat_row) and rajabhat_row["kind"] == "รัฐ", str(rajabhat_row))
    check("ไม่มี tc_uid ว่างเหลือ", all(r.get("tc_uid") for r in repo.rows), str([r.get("tc_uid") for r in repo.rows]))
    check("ไม่มีชื่อซ้ำ", len({r["name"] for r in repo.rows}) == len(repo.rows), str(len(repo.rows)))

    print("\n=== 5. sync_institutions รันซ้ำได้ (idempotent) ===")
    result2 = await sync_institutions(repo)
    check("ไม่เพิ่มแถวซ้ำ", result2["inserted"] == 0, str(result2))
    check("จำนวนแถวเท่าเดิม", len(repo.rows) == 5, str(len(repo.rows)))

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
