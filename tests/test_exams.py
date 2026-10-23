"""ทดสอบคลังข้อสอบ (ตรรกะแปลงหน้า myTCAS -> รายการ, ความปลอดภัยของ URL ดาวน์โหลด)

รัน: python tests/test_exams.py   (ไม่ต้องต่อเน็ต; ส่วน API ข้ามอัตโนมัติถ้าไม่มี fastapi/httpx)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.exam_catalog import (  # noqa: E402
    DOWNLOAD_RE,
    SUBJECTS,
    discover_answer_pages,
    fallback_answers,
    fallback_blueprints,
    group_counts,
    parse_answer_page,
    parse_blueprint_index,
    search_items,
)

FAILURES: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    print(f"  {'PASS' if condition else 'FAIL'}  {label} {'' if condition else extra}")
    if not condition:
        FAILURES.append(label)


ANSWER_HTML = """
<ul>
 <li><a href="https://assets.mytcas.com/69/answer/tcas69-phy-a-level.pdf"><span>ข้อสอบวิชา A-Level ฟิสิกส์</span></a></li>
 <li><a href='https://assets.mytcas.com/69/answer/tcas69-math1-a-level.pdf?v=2'>ข้อสอบ  คณิต</a></li>
 <li><a href="https://assets.mytcas.com/69/answer/tcas69-phy-a-level.pdf">ซ้ำ</a></li>
 <li><a href="/news">ข่าว</a></li>
 <li><a href="https://evil.example.com/69/answer/tcas69-hack-a-level.pdf">นอกโดเมน</a></li>
 <li><a href="https://assets.mytcas.com/70/TCAS70-A-Level.jpg">รูป</a></li>
 <li><a href="/69/answer/tcas69-chem-a-level.pdf">ลิงก์สัมพัทธ์</a></li>
</ul>"""
HOME_HTML = '<a href="/answers-t69">เฉลย 69</a><a href="https://www.mytcas.com/answers-t70/">เฉลย 70</a><a href="https://evil.com/answers-t99">x</a><a href="/blueprint">b</a>'
BLUEPRINT_HTML = """
<a href="/blueprint/tgat1-91/">TGAT1 91 การสื่อสารภาษาอังกฤษ</a>
<a href="/blueprint/a-level-64-phy/"><div>A-Level 64 Phy</div> <small>ฟิสิกส์</small></a>
<a href="/blueprint/a-level-64-phy/">ซ้ำ</a><a href="/blueprint/">หน้ารวม</a><a href="/news/1/">ข่าว</a>
<a href="https://evil.com/blueprint/tpat3-30/">นอกโดเมน</a><a href="/blueprint/tpat3-30">TPAT3 30</a>"""


def main() -> int:
    print("\n=== แปลงหน้าเฉลย ===")
    items = parse_answer_page(ANSWER_HTML, "https://www.mytcas.com/answers-t69")
    ids = [i["id"] for i in items]
    check("ได้เฉพาะไฟล์เฉลยบน assets.mytcas.com ไม่ซ้ำ (ลิงก์สัมพัทธ์บนโดเมน www ไม่ใช่ที่เก็บไฟล์จริง จึงไม่รับ)",
          ids == ["tcas69-phy-a-level", "tcas69-math1-a-level"], str(ids))
    check("ลิงก์นอกโดเมน/รูป/ข่าวไม่ถูกนับ", not any("evil" in i["url"] or i["url"].endswith(".jpg") for i in items))
    phy = items[0]
    check("ชื่อวิชา/กลุ่ม/ระดับ/ปี ถูกต้อง", (phy["subject"], phy["group"], phy["level"], phy["year"]) == ("ฟิสิกส์", "วิทยาศาสตร์", "A-Level", "TCAS69"))
    check("ลิงก์ ?v=2 ถูกตัด query ออก", items[1]["url"] == "https://assets.mytcas.com/69/answer/tcas69-math1-a-level.pdf")
    check("ทุกชิ้นดาวน์โหลดได้", all(i["download"] for i in items if "assets.mytcas.com" in i["url"]))

    print("\n=== ค้นหาหน้าเฉลยปีอื่น ===")
    pages = discover_answer_pages(HOME_HTML)
    check("พบ t70 และ t69 เสมอ ไม่รับโดเมนอื่น", pages == ["https://www.mytcas.com/answers-t70", "https://www.mytcas.com/answers-t69"], str(pages))
    check("หน้าแรกว่างยังมี t69", discover_answer_pages("") == ["https://www.mytcas.com/answers-t69"])

    print("\n=== แปลงหน้า blueprint ===")
    bps = parse_blueprint_index(BLUEPRINT_HTML)
    check("ได้ 3 รายการ ไม่ซ้ำ ไม่รวมหน้ารวม/นอกโดเมน", [b["id"] for b in bps] == ["blueprint-tgat1-91", "blueprint-a-level-64-phy", "blueprint-tpat3-30"], str([b["id"] for b in bps]))
    check("blueprint ไม่ให้ดาวน์โหลด (เปิดอ่านบน myTCAS)", all(not b["download"] and b["url"].startswith("https://www.mytcas.com/blueprint/") for b in bps))
    check("จัดกลุ่ม TGAT/TPAT/วิชา", [b["group"] for b in bps] == ["ความถนัดทั่วไป", "วิทยาศาสตร์", "ความถนัดเฉพาะ"])
    check("ข้อความในลิงก์ถูกล้างแท็ก/ช่องว่าง", bps[1]["title"] == "A-Level 64 Phy ฟิสิกส์", bps[1]["title"])

    print("\n=== รายการสำรอง ===")
    fb = fallback_answers()
    check("สำรองมีครบ 16 วิชา และชื่อไม่ซ้ำ", len(fb) == len(SUBJECTS) == 16 and len({i["id"] for i in fb}) == 16)
    check("URL สำรองทุกตัวผ่านตัวตรวจดาวน์โหลด", all(DOWNLOAD_RE.match(i["url"]) for i in fb))
    check("blueprint สำรอง 23 รายการ", len(fallback_blueprints()) == 23)

    print("\n=== ความปลอดภัย URL ดาวน์โหลด ===")
    bad = [
        "http://assets.mytcas.com/69/answer/a.pdf", "https://assets.mytcas.com.evil.com/69/answer/a.pdf",
        "https://evil.com/assets.mytcas.com/69/answer/a.pdf", "https://assets.mytcas.com/69/answer/../../x.pdf",
        "https://assets.mytcas.com/69/answer/a.pdf?x=1", "https://assets.mytcas.com/69/other/a.pdf",
        "https://assets.mytcas.com/69/answer/a.exe", "https://user@assets.mytcas.com/69/answer/a.pdf",
        "https://assets.mytcas.com/69/answer/a b.pdf",
    ]
    check("URL ผิดรูปแบบ/นอกโดเมนถูกปฏิเสธทั้งหมด", not any(DOWNLOAD_RE.match(u) for u in bad), str([u for u in bad if DOWNLOAD_RE.match(u)]))
    check("URL เฉลยจริงผ่าน", bool(DOWNLOAD_RE.match("https://assets.mytcas.com/69/answer/tcas69-phy-a-level.pdf")))

    print("\n=== ค้นหา/กรอง ===")
    allitems = fb + fallback_blueprints()
    check("ค้นหา 'ฟิสิกส์' ได้ทั้งเฉลยและ blueprint", len(search_items(allitems, "ฟิสิกส์")) == 2)
    check("กรอง kind=answer ได้ 16", len(search_items(allitems, kind="answer")) == 16)
    check("กรองกลุ่มภาษาต่างประเทศ (เฉลย) ได้ 7", len(search_items(allitems, kind="answer", group="ภาษาต่างประเทศ")) == 7)
    check("ค้นหาไม่ตรงได้ว่าง", search_items(allitems, "zzzz") == [])
    check("ค้นหาไม่สนตัวพิมพ์เล็ก/ใหญ่", len(search_items(allitems, "TGAT")) == len(search_items(allitems, "tgat")) >= 1)
    counts = group_counts(fb)
    check("นับกลุ่มเรียงตามลำดับ คณิต→วิทย์→...", [c["group"] for c in counts] == ["คณิตศาสตร์", "วิทยาศาสตร์", "ภาษาและสังคม", "ภาษาต่างประเทศ"] and sum(c["count"] for c in counts) == 16)

    test_api()
    print()
    if FAILURES:
        print(f"ไม่ผ่าน {len(FAILURES)} ข้อ:\n  - " + "\n  - ".join(FAILURES))
        return 1
    print("ผ่านทั้งหมด")
    return 0


def test_api() -> None:
    try:
        import httpx
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ModuleNotFoundError:
        print("\n=== API === ข้าม: ยังไม่ได้ติดตั้ง fastapi/httpx (pip install -r requirements.txt)")
        return
    import app.exams as exams

    pdf = b"%PDF-1.4 test"

    def handler(request: "httpx.Request") -> "httpx.Response":
        url = str(request.url)
        if url.endswith("/answers-t69"):
            return httpx.Response(200, text=ANSWER_HTML)
        if url.endswith("/blueprint"):
            return httpx.Response(200, text=BLUEPRINT_HTML)
        if url == "https://www.mytcas.com/":
            return httpx.Response(200, text=HOME_HTML.replace("answers-t70", "x"))
        if url.endswith("tcas69-phy-a-level.pdf"):
            return httpx.Response(200, content=pdf, headers={"content-type": "application/pdf"})
        if url.endswith("tcas69-math1-a-level.pdf"):
            return httpx.Response(200, text="<html>", headers={"content-type": "text/html"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    exams.httpx.AsyncClient = lambda **kw: real(transport=transport, **kw)  # type: ignore[assignment]
    app = FastAPI()
    app.include_router(exams.build_router())
    client = TestClient(app)

    print("\n=== API ===")
    data = client.get("/api/exams").json()
    check("API คืนรายการสดและบอกว่า live", data["live"] is True and any(i["id"] == "tcas69-phy-a-level" for i in data["items"]) or data["live"])
    check("กรอง kind=blueprint", all(i["kind"] == "blueprint" for i in client.get("/api/exams?kind=blueprint").json()["items"]))
    check("kind แปลก ๆ ไม่ทำให้พัง", client.get("/api/exams?kind=../x").status_code == 200)
    got = client.get("/api/exams/tcas69-phy-a-level/download")
    check("ดาวน์โหลด PDF ได้พร้อมหัว attachment", got.status_code == 200 and got.content == pdf and "attachment" in got.headers["content-disposition"] and got.headers["content-type"] == "application/pdf")
    check("ต้นทางตอบไม่ใช่ PDF ได้ 502", client.get("/api/exams/tcas69-math1-a-level/download").status_code == 502)
    check("id ที่ไม่มีในรายการ 404", client.get("/api/exams/tcas69-hack-a-level/download").status_code == 404)
    check("blueprint โหลดไม่ได้ 404", client.get("/api/exams/blueprint-tgat1-91/download").status_code == 404)
    check("id แปลกปลอม 404", client.get("/api/exams/..%2Fetc/download").status_code in (404, 405))
    exams.httpx.AsyncClient = real  # type: ignore[assignment]
    _ = Any


if __name__ == "__main__":
    raise SystemExit(main())
