"""ทดสอบช่องรับข้อมูลจาก myTCAS (POST /api/tcas/*) — รวมถึงการป้องกันด้วย webhook secret

รัน: python tests/test_tcas_ingest.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from tests.test_community_tickets import FakeRepo  # noqa: E402

SECRET = "test-secret-123"
FAILURES: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {extra}")
        FAILURES.append(label)


def main() -> int:
    os.environ["MAKE_WEBHOOK_SECRET"] = SECRET
    repo = FakeRepo()
    repo.tables["institutions"] = [
        {"id": 1, "name": "จุฬาลงกรณ์มหาวิทยาลัย", "logoUrl": "https://assets.mytcas.com/i/logo/001.png"},
    ]
    repo.tables["faculties"] = []
    repo.tables["admissions"] = []

    from app.tcas_ingest import build_router

    app = FastAPI()
    app.include_router(build_router(repo))
    client = TestClient(app)
    auth = {"X-Webhook-Secret": SECRET}

    print("\n=== ป้องกันด้วย webhook secret ===")
    no_secret = client.post("/api/tcas/institutions", json={"name": "x"})
    check("ไม่ส่ง secret -> 401", no_secret.status_code == 401, str(no_secret.status_code))

    wrong = client.post("/api/tcas/institutions", json={"name": "x"}, headers={"X-Webhook-Secret": "wrong-secret"})
    check("secret ผิด -> 401", wrong.status_code == 401)

    ok = client.post("/api/tcas/institutions", json={"name": "ตรวจสอบ-secret"}, headers=auth)
    check("secret ถูก -> 200", ok.status_code == 200, ok.text[:150])
    # ลบแถวทดสอบออก เพื่อให้นับแถวได้ตรง
    repo.tables["institutions"] = [row for row in repo.tables["institutions"] if row.get("name") != "ตรวจสอบ-secret"]

    print("\n=== มหาวิทยาลัย/สถาบัน ===")
    # นับจากจุดเริ่ม เพราะเทสต์ตรวจ secret ข้างบนได้สร้างแถวไว้แล้ว
    base = len(repo.tables["institutions"])
    created = client.post("/api/tcas/institutions", headers=auth, json={
        "tc_uid": "001", "name": "จุฬาลงกรณ์มหาวิทยาลัย", "short_name": "CU",
        "city": "กรุงเทพฯ", "kind": "รัฐ", "logo_url": "https://assets.mytcas.com/i/logo/001.png",
    })
    check("เพิ่มมหาวิทยาลัยได้", created.status_code == 200, created.text[:150])
    # แถว seed เดิมมีชื่อเดียวกัน -> ต้องถูกเติมข้อมูล ไม่ใช่สร้างแถวซ้ำ
    check("ไม่เกิดแถวซ้ำ (เติมข้อมูลแถว seed เดิม)", len(repo.tables["institutions"]) == base, f"{len(repo.tables['institutions'])} != {base}")
    row = repo.tables["institutions"][0]
    check("บันทึก tc_uid", row.get("tc_uid") == "001")
    check("บันทึก short_name/city/kind", row.get("short_name") == "CU" and row.get("city") == "กรุงเทพฯ" and row.get("kind") == "รัฐ")
    check("บันทึก logoUrl", row.get("logoUrl") == "https://assets.mytcas.com/i/logo/001.png")

    # ยิงซ้ำด้วย tc_uid เดิม -> ต้องอัปเดตแถวเดิม ไม่ใช่สร้างใหม่
    again = client.post("/api/tcas/institutions", headers=auth, json={
        "tc_uid": "001", "name": "จุฬาลงกรณ์มหาวิทยาลัย", "short_name": "CU", "city": "กรุงเทพมหานคร",
    })
    check("ยิงซ้ำไม่เกิดข้อมูลซ้ำ", len(repo.tables["institutions"]) == base, f"{len(repo.tables['institutions'])} != {base}")
    check("อัปเดตค่าใหม่แทน", repo.tables["institutions"][0].get("city") == "กรุงเทพมหานคร", str(repo.tables["institutions"][0].get("city")))

    # ไม่มี tc_uid -> จับคู่ด้วยชื่อ
    by_name = client.post("/api/tcas/institutions", headers=auth, json={"name": "จุฬาลงกรณ์มหาวิทยาลัย", "kind": "รัฐ"})
    check("จับคู่ด้วยชื่อได้", len(repo.tables["institutions"]) == base, f"{len(repo.tables['institutions'])} != {base}")

    no_name = client.post("/api/tcas/institutions", headers=auth, json={"short_name": "X"})
    check("ไม่มี name -> 422", no_name.status_code == 422, str(no_name.status_code))

    bad_kind = client.post("/api/tcas/institutions", headers=auth, json={"name": "สถาบันใหม่", "kind": "แปลก"})
    check("kind แปลกถูกบันทึกเป็น 'อื่น ๆ'", repo.tables["institutions"][-1].get("kind") == "อื่น ๆ", str(repo.tables["institutions"][-1].get("kind")))

    print("\n=== ส่งหลายรายการ ===")
    before_bulk = len(repo.tables["institutions"])
    bulk = client.post("/api/tcas/institutions", headers=auth, json={"items": [
        {"tc_uid": "002", "name": "มหาวิทยาลัยเกษตรศาสตร์"},
        {"tc_uid": "003", "name": "มหาวิทยาลัยกาฬสินธุ์"},
    ]})
    check("ส่งแบบ items ได้", bulk.status_code == 200 and bulk.json()["count"] == 2, bulk.text[:150])
    check("เพิ่มครบ 2 รายการ", len(repo.tables["institutions"]) == before_bulk + 2, f"{len(repo.tables['institutions'])} != {before_bulk + 2}")

    print("\n=== คณะและหลักสูตร ===")
    fac = client.post("/api/tcas/faculties", headers=auth, json={
        "tc_uid": "001", "institution": "จุฬาลงกรณ์มหาวิทยาลัย", "name": "วิศวกรรมศาสตร์",
        "program": "วิศวกรรมศาสตร์ (วศ.บ.)", "degree": "ปริญญาตรี",
        "tc_faculty_uid": "001-ENG", "source_url": "https://www.chula.ac.th/engineering/",
    })
    check("เพิ่มคณะได้", fac.status_code == 200, fac.text[:200])
    check("ผูกกับมหาวิทยาลัย", repo.tables["faculties"][0].get("institution_id") == 1, str(repo.tables["faculties"][0]))
    check("บันทึก program/degree", repo.tables["faculties"][0].get("program") == "วิศวกรรมศาสตร์ (วศ.บ.)")
    check("บันทึก source_url", repo.tables["faculties"][0].get("source_url") == "https://www.chula.ac.th/engineering/")

    fac_again = client.post("/api/tcas/faculties", headers=auth, json={
        "tc_uid": "001", "institution": "จุฬาลงกรณ์มหาวิทยาลัย", "name": "วิศวกรรมศาสตร์",
        "tc_faculty_uid": "001-ENG", "degree": "ปริญญาตรี",
    })
    check("ยิงซ้ำคณะไม่เกิดซ้ำ", len(repo.tables["faculties"]) == 1, str(len(repo.tables["faculties"])))

    no_fac_name = client.post("/api/tcas/faculties", headers=auth, json={"institution": "x"})
    check("คณะไม่มี name -> 422", no_fac_name.status_code == 422)

    print("\n=== เกณฑ์รับ/รอบสมัคร ===")
    adm = client.post("/api/tcas/admissions", headers=auth, json={
        "tc_uid": "001-ENG-1", "tc_uid_inst": "001",
        "institution": "จุฬาลงกรณ์มหาวิทยาลัย", "faculty": "วิศวกรรมศาสตร์",
        "round": "รอบ 1", "criteria": "ตามประกาศทางการ",
        "source_url": "https://www.chula.ac.th/engineering/admission/",
        "deadline": "2027-01-15",
    })
    check("เพิ่มเกณฑ์รับได้", adm.status_code == 200, adm.text[:200])
    check("บันทึกรอบ/เกณฑ์", repo.tables["admissions"][0].get("round") == "รอบ 1")
    check("บันทึก deadline", repo.tables["admissions"][0].get("deadline") == "2027-01-15")
    check("ผูกกับมหาวิทยาลัย", repo.tables["admissions"][0].get("institution_id") == 1)

    adm_again = client.post("/api/tcas/admissions", headers=auth, json={
        "tc_uid": "001-ENG-1", "institution": "จุฬาลงกรณ์มหาวิทยาลัย",
        "faculty": "วิศวกรรมศาสตร์", "round": "รอบ 1", "criteria": "เกณฑ์ใหม่",
    })
    check("ยิงซ้ำเกณฑ์รับไม่เกิดซ้ำ", len(repo.tables["admissions"]) == 1, str(len(repo.tables["admissions"])))
    check("อัปเดตเกณฑ์ใหม่", repo.tables["admissions"][0].get("criteria") == "เกณฑ์ใหม่")

    missing = client.post("/api/tcas/admissions", headers=auth, json={"institution": "x", "faculty": "y"})
    check("เกณฑ์รับข้อมูลไม่ครบ -> 422", missing.status_code == 422)

    print("\n=== จำกัดจำนวนรายการ ===")
    too_many = client.post("/api/tcas/institutions", headers=auth, json={"items": [{"name": f"x{i}"} for i in range(501)]})
    check("ส่งเกิน 500 รายการ -> 422", too_many.status_code == 422, str(too_many.status_code))

    print("\n=== ปิดเมื่อไม่ได้ตั้ง secret ===")
    os.environ["MAKE_WEBHOOK_SECRET"] = ""
    closed = client.post("/api/tcas/institutions", json={"name": "x"}, headers=auth)
    check("ไม่ได้ตั้ง secret -> 503 (fail closed)", closed.status_code == 503, str(closed.status_code))
    os.environ["MAKE_WEBHOOK_SECRET"] = SECRET

    print("\n=== สรุป ===")
    if FAILURES:
        print(f"ไม่ผ่าน {len(FAILURES)} ข้อ:")
        for item in FAILURES:
            print("  -", item)
        return 1
    print("ผ่านทั้งหมด")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
