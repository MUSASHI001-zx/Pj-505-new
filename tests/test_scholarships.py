"""ทดสอบระบบค้นหาทุนการศึกษา (กสศ. + Scholarship.in.th)

ทดสอบส่วนที่ไม่ต้องต่อเน็ต (normalize, การค้นหา, ตัวกรอง) และทดสอบ endpoint ด้วยข้อมูลจำลอง

รัน: python tests/test_scholarships.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.scholarships import (  # noqa: E402
    SOURCE_EEF,
    SOURCE_SIT,
    STATUS_CLOSED,
    STATUS_CLOSING,
    STATUS_OPEN,
    STATUS_UNKNOWN,
    build_facets,
    build_router,
    compute_status,
    level_of,
    matches_level,
    matches_query,
    normalize_eef,
    normalize_wp,
    parse_thai_date,
    search_items,
    strip_html,
)

FAILURES: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {extra}")
        FAILURES.append(label)


EEF_RAW = {
    "id": "abc-123",
    "title": "ทุนการศึกษาปริญญาตรี วิศวกรรมศาสตร์",
    "budget": "100,000 บาทต่อปี",
    "budget_source": ["หน่วยงานรัฐ"],
    "channel": "สมัครออนไลน์",
    "close_register_in": None,
    "feature": False,
    "genres": ["ทุนให้เปล่า"],
    "grade": "ปริญญาตรี",
    "granter": ["นักเรียนนักศึกษา"],
    "images": "https://findstudentship.eef.or.th/api/v3/public/bucket/x.jpeg",
    "md_link": None,
    "requirement": ["เรียนดี"],
    "sponsor": "มูลนิธิทดสอบ",
    "start_at": "ภายใน 31 ตุลาคม 2569",
    "viewer": "10",
    "visible": True,
    "source_url": "https://example.org/scholarship",
    "created_at": "2026-10-01T00:00:00.000Z",
}

WP_RAW = {
    "id": 226,
    "date": "2026-06-20T13:57:57",
    "link": "https://scholarship.in.th/post-1/",
    "title": {"rendered": "ทุนเรียนต่อจีน 2026 ที่ Zhejiang Normal University"},
    "excerpt": {"rendered": "<p>รับสมัครนักศึกษา&#8230;</p>"},
    "featured_media": 227,
}

WP_EMBEDDED = {
    "wp:featuredmedia": [{
        "source_url": "https://scholarship.in.th/wp-content/uploads/cover.jpg",
        "media_details": {"sizes": {"medium": {"source_url": "https://scholarship.in.th/wp-content/uploads/cover-300x157.jpg"}}},
    }],
    "wp:term": [[{"id": 59, "name": "ทุนจีน"}, {"id": 21, "name": "ทุนปริญญาตรี"}]],
}


def make_items() -> list[dict]:
    eef = normalize_eef(EEF_RAW)
    sit = normalize_wp(WP_RAW, WP_EMBEDDED)
    return [eef, sit]


def main() -> int:
    print("\n=== แปลงข้อมูลจากกสศ. ===")
    eef = normalize_eef(EEF_RAW)
    check("มี id ที่ไม่ซ้ำกันข้ามแหล่ง", eef["id"].startswith(SOURCE_EEF))
    check("เก็บชื่อทุน", eef["title"] == "ทุนการศึกษาปริญญาตรี วิศวกรรมศาสตร์")
    check("เก็บมูลค่าทุน", eef["amount"] == "100,000 บาทต่อปี")
    check("เก็บผู้ให้ทุน", eef["sponsor"] == "มูลนิธิทดสอบ")
    check("เก็บกำหนดปิดรับ", eef["deadline"] == "ภายใน 31 ตุลาคม 2569")
    check("เก็บระดับชั้น", eef["levels"] == ["ปริญญาตรี"])
    check("เก็บประเภททุน", eef["tags"] == ["ทุนให้เปล่า"])
    check("เก็บรูปภาพ", eef["image_url"].endswith("x.jpeg"))
    check("ลิงก์หลักชี้ไปหน้ารายละเอียดบนเว็บกสศ.", eef["url"] == "https://findstudentship.eef.or.th/scholarship/abc-123", eef["url"])
    check("เก็บลิงก์ใบสมัครต้นทางไว้", eef["apply_url"] == "https://example.org/scholarship")
    check("มีสถานะทุน", eef["status"] in (STATUS_OPEN, STATUS_CLOSING, STATUS_CLOSED), eef["status"])

    print("\n=== ทำความสะอาดข้อมูลที่ไม่มีค่า ===")
    dirty = normalize_eef({
        "id": "dirty-1", "title": "ทุนทดสอบ", "budget": "-", "start_at": "-", "grade": "ปริญญาตรี",
        "channel": "https://example.org/signup", "genres": [], "requirement": [], "images": "",
    })
    check("มูลค่าทุน '-' ไม่แสดงเป็นตัวเลข", dirty["amount"] == "", repr(dirty["amount"]))
    check("วันที่ '-' ไม่แสดง", dirty["deadline"] == "", repr(dirty["deadline"]))
    check("ช่องทางที่เป็น URL ถูกย้ายออกจากข้อความ", dirty["channel"] == "", repr(dirty["channel"]))
    check("ข้อความสรุปไม่มี URL ปน", "http" not in dirty["summary"], dirty["summary"])

    print("\n=== แปลงข้อมูลจาก Scholarship.in.th ===")
    sit = normalize_wp(WP_RAW, WP_EMBEDDED)
    check("มี id ที่ไม่ซ้ำกันข้ามแหล่ง", sit["id"].startswith(SOURCE_SIT))
    check("ถอดแท็ก HTML ออกจากชื่อ", "<" not in sit["title"] and sit["title"].startswith("ทุนเรียนต่อจีน"))
    check("ถอดแท็ก HTML และ entity ออกจากสรุป", "<" not in sit["summary"] and "…" in sit["summary"])
    check("เดาระดับชั้นจากหมวดหมู่", "ปริญญาตรี" in sit["levels"], str(sit["levels"]))
    check("เก็บหมวดหมู่เป็นแท็ก", "ทุนจีน" in sit["tags"])
    check("เลือกรูปขนาดกลาง", sit["image_url"].endswith("cover-300x157.jpg"))
    check("ลิงก์ชี้ไปโพสต์", sit["url"] == "https://scholarship.in.th/post-1/")

    print("\n=== ตัวช่วย strip HTML ===")
    check("ตัดแท็กออก", strip_html("<b>ทุน</b> ดี") == "ทุน ดี")
    check("decode entity", strip_html("a &amp; b") == "a & b")

    print("\n=== แปลงวันที่ไทย ===")
    check("วันที่ พ.ศ. 4 หลัก", parse_thai_date("ภายใน 31 ตุลาคม 2569").isoformat() == "2026-10-31")
    check("วันที่ ค.ศ. แบบ slash", parse_thai_date("2022/2/1").isoformat() == "2022-02-01")
    check("วันที่ ค.ศ. แบบ dash", parse_thai_date("2021-09-01").isoformat() == "2021-09-01")
    check("วันที่ พ.ศ. แบบ slash", parse_thai_date("31/10/2569").isoformat() == "2026-10-31")
    check("ช่วงวันที่เอาวันสิ้นสุด", parse_thai_date("ตั้งแต่ 1 กรกฎาคม 2568 ถึง 28 กุมภาพันธ์ 2569").isoformat() == "2026-02-28")
    check("ไม่มีปี → ไม่มีวันที่", parse_thai_date("ตลอดทั้งปี") is None)
    check("ไม่มีปี (ของทุกปี) → ไม่มีวันที่", parse_thai_date("1-30 พฤศจิกายน ของทุกปี") is None)
    check("ข้อความ '-' → ไม่มีวันที่", parse_thai_date("-") is None)

    print("\n=== คำนวณสถานะทุน ===")
    check("เลยกำหนดแล้ว → ปิดรับแล้ว", compute_status({"deadline": "ภายใน 1 มกราคม 2560", "deadline_date": parse_thai_date("ภายใน 1 มกราคม 2560")}) == STATUS_CLOSED)
    check("ยังไม่ถึงกำหนด → เปิดรับสมัคร", compute_status({"deadline": "ภายใน 31 ธันวาคม 2699", "deadline_date": parse_thai_date("ภายใน 31 ธันวาคม 2699")}) == STATUS_OPEN)
    check("ตลอดทั้งปี → เปิดรับสมัคร", compute_status({"deadline": "ตลอดทั้งปี", "deadline_date": None}) == STATUS_OPEN)
    check("ของทุกปี → เปิดรับสมัคร", compute_status({"deadline": "ภายใน พฤษภาคม ของทุกปี", "deadline_date": None}) == STATUS_OPEN)
    check("ไม่มีวันที่ → ไม่ระบุ", compute_status({"deadline": "", "deadline_date": None}) == STATUS_UNKNOWN)
    check("ติดตามประกาศ → ไม่ระบุ", compute_status({"deadline": "ติดตามในเพจ", "deadline_date": None}) == STATUS_UNKNOWN)

    print("\n=== การค้นหา (ค้นภาษาไทยได้) ===")
    items = make_items()
    check("ค้นคำไทยตรงชื่อ", matches_query(eef, "วิศวกรรม"))
    check("ค้นคำไทยที่ยาวกว่าข้อมูล (prefix)", matches_query(eef, "วิศวกรรมศาสตร์"))
    check("ค้นชื่อมหาวิทยาลัยไทย", matches_query(sit, "Zhejiang"))
    check("ค้นคำที่ไม่มีจริงไม่เจอ", not matches_query(eef, "อวกาศ"))
    check("ค้นหลายคำต้องเจอครบทุกคำ", not matches_query(eef, "วิศวกรรม อวกาศ"))
    check("ค้นว่างเจอทั้งหมด", matches_query(eef, ""))
    check("ทุกคำในคำค้นต้องเจอ", matches_query(eef, "ทุน วิศวกรรม"))

    print("\n=== การจัดอันดับผลค้นหา ===")
    ranked = search_items(items, query="ทุน")
    check("ผลที่ตรงคำค้นอยู่บน", len(ranked) == 2)
    check("ชื่อที่ตรงคำมากกว่าอยู่ก่อน", ranked[0]["title"].startswith("ทุนการศึกษาปริญญาตรี"), ranked[0]["title"])

    print("\n=== ตัวกรองระดับชั้น / แหล่งข้อมูล / ประเภททุน ===")
    check("จัดกลุ่มระดับชั้น ปริญญาตรี", level_of(eef) == "ปวส.-ปริญญาตรี", level_of(eef))
    check("จัดกลุ่มระดับชั้น ปริญญาตรี (จากหมวดหมู่)", level_of(sit) == "ปวส.-ปริญญาตรี", level_of(sit))
    check("กรองตามระดับชั้นผ่าน", matches_level(eef, "ปวส.-ปริญญาตรี"))
    check("กรองตามระดับชั้นไม่ผ่าน", not matches_level(eef, "ประถม-มัธยมต้น"))
    check("กรองตามแหล่งข้อมูลผ่าน", matches_level(sit, "ทั้งหมด"))

    only_sit = search_items(items, source=SOURCE_SIT)
    check("กรองเฉพาะ Scholarship.in.th", len(only_sit) == 1 and only_sit[0]["source"] == SOURCE_SIT)
    only_eef = search_items(items, source=SOURCE_EEF)
    check("กรองเฉพาะกสศ.", len(only_eef) == 1 and only_eef[0]["source"] == SOURCE_EEF)
    by_genre = search_items(items, genre="ทุนให้เปล่า")
    check("กรองตามประเภททุน", len(by_genre) == 1 and by_genre[0]["source"] == SOURCE_EEF)
    check("จำกัดจำนวนผลลัพธ์", len(search_items(items, limit=1)) == 1)

    print("\n=== ตัวนับสำหรับตัวกรอง (facets) ===")
    facets = build_facets(items)
    check("นับตามระดับชั้น", facets["levels"] and facets["levels"][0]["count"] == 2, str(facets["levels"]))
    check("นับตามแหล่งข้อมูล", len(facets["sources"]) == 2)
    check("นับตามประเภททุน", any(g["label"] == "ทุนให้เปล่า" for g in facets["genres"]))
    check("นับตามสถานะทุน", len(facets["statuses"]) == 4, str(facets["statuses"]))

    print("\n=== กรองตามสถานะทุน ===")
    # สร้างรายการที่สถานะชัดเจน เพื่อไม่ให้ผลขึ้นกับวันที่ที่รันเทสต์
    open_item = normalize_eef({**EEF_RAW, "id": "open-1", "start_at": "ภายใน 31 ธันวาคม 2699"})
    closed_item = normalize_eef({**EEF_RAW, "id": "closed-1", "start_at": "ภายใน 31 มกราคม 2560"})
    status_items = [open_item, closed_item, sit]
    check("ทุนอนาคตเป็นเปิดรับสมัคร", open_item["status"] == STATUS_OPEN, open_item["status"])
    check("ทุนที่เลยกำหนดเป็นปิดรับแล้ว", closed_item["status"] == STATUS_CLOSED, closed_item["status"])
    check("กรอง 'เปิดรับสมัคร'", len(search_items(status_items, status=STATUS_OPEN)) == 1)
    check("กรอง 'ปิดรับแล้ว'", len(search_items(status_items, status=STATUS_CLOSED)) == 1)
    check("กรอง 'ไม่ระบุ'", len(search_items(status_items, status=STATUS_UNKNOWN)) == 1)

    print("\n=== API endpoint ===")
    app = FastAPI()
    app.include_router(build_router())
    client = TestClient(app)

    import app.scholarships as scholarships_module

    scholarships_module._cache.clear()
    scholarships_module._cache[SOURCE_EEF] = (9e9, [open_item, closed_item])
    scholarships_module._cache[SOURCE_SIT] = (9e9, [sit])

    response = client.get("/api/scholarships")
    check("ตอบ 200", response.status_code == 200, response.text[:200])
    payload = response.json()
    check("มีรายการทุน", payload["total"] == 3, str(payload["total"]))
    check("มี facets", "levels" in payload["facets"])
    check("มีรายชื่อแหล่งข้อมูล", len(payload["sources"]) == 2)

    response = client.get("/api/scholarships?q=วิศวกรรมศาสตร์")
    check("ค้นภาษาไทยผ่าน API ได้", response.json()["total"] == 2, str(response.json()["total"]))

    response = client.get("/api/scholarships?source=sit")
    check("กรองแหล่งข้อมูลผ่าน API", response.json()["total"] == 1)

    response = client.get("/api/scholarships?level=ไม่มีจริง")
    check("ระดับชั้นผิดถูกปฏิเสธ", response.status_code == 400)

    response = client.get("/api/scholarships?source=ไม่มีจริง")
    check("แหล่งข้อมูลผิดถูกปฏิเสธ", response.status_code == 400)

    response = client.get("/api/scholarships?status=เปิดรับสมัคร")
    check("กรองสถานะผ่าน API", response.status_code == 200 and response.json()["total"] == 1, str(response.json().get("total")))

    response = client.get("/api/scholarships?status=ไม่มีจริง")
    check("สถานะผิดถูกปฏิเสธ", response.status_code == 400)

    response = client.get("/api/scholarships?limit=1")
    check("จำกัด limit ผ่าน API", len(response.json()["items"]) == 1)
    check("total ยังเป็นจำนวนรายการที่ตรงทั้งหมด", response.json()["total"] == 3, str(response.json()["total"]))
    check("คืนจำนวนที่ส่งจริงแยกจาก total", response.json()["returned"] == 1)

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
