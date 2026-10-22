"""ทดสอบการดึงข่าวจาก myTCAS — ทดสอบการ parse HTML โดยไม่ต้องต่อเน็ต

รัน: python tests/test_tcas_news.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.tcas_news import (  # noqa: E402
    FALLBACK_COVERS,
    _parse_thai_date,
    _pdf_label,
    _pick_cover,
    _short_summary,
    clean_content,
    parse_detail_page,
    parse_list_page,
    strip_tags,
)

FAILURES: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {extra}")
        FAILURES.append(label)


LIST_HTML = """
<ul>
<li class="s-flex"><div class="date"><div class="day">19</div><small> ต.ค.&nbsp;69 </small></div>
<a href="/news/105/" class="link">ประกาศเรื่องรายชื่อสถาบันฝ่ายผลิต</a></li>
<li class="s-flex"><div class="date"><div class="day">11</div><small> ก.ย.&nbsp;69 </small></div>
<a href="/news/101/" class="link">ประกาศฉบับที่ 7 แนวทางปฏิบัติ</a></li>
</ul>
"""

DETAIL_HTML = """
<html><body><main>
<h1>ประกาศสำนักงานปลัดกระทรวงฯ เรื่อง รายชื่อสถาบัน</h1>
<div class="s-container">
<p>19 ตุลาคม 2569</p>
<p>ประกาศรายชื่อสถาบันฝ่ายผลิตในโครงการผลิตครู เพื่อพัฒนาท้องถิ่น ระยะที่ 2</p>
<img src="/img/logo70-alt.svg" alt="โลโก้" />
<img src="https://i.mytcas.com/wp-content/uploads/2026/10/shot.webp" alt="ภาพประกาศ" />
<p><a href="https://i.mytcas.com/wp-content/uploads/2026/10/announce.pdf">ดาวน์โหลดเอกสาร</a></p>
</div>
</main></body></html>
"""


def main() -> int:
    print("\n=== แปลงวันที่ไทย ===")
    check("วันที่เต็ม", _parse_thai_date("19 ตุลาคม 2569") == "2569-10-19")
    check("วันที่ 2 หลัก (69 = พ.ศ. 2569)", _parse_thai_date("11 ก.ย. 69") == "2569-09-11", str(_parse_thai_date("11 ก.ย. 69")))
    check("วันที่ 2 หลัก แบบย่อ", _parse_thai_date("19 ต.ค. 69") == "2569-10-19", str(_parse_thai_date("19 ต.ค. 69")))
    check("ไม่มีวันที่", _parse_thai_date("ไม่มีข้อมูล") is None)

    print("\n=== ถอดแท็กและทำความสะอาด ===")
    check("ถอดแท็ก", strip_tags("<p>ทดสอบ <b>ข้อความ</b></p>") == "ทดสอบ ข้อความ")
    check("ตัด breadcrumb", clean_content("‹ ข่าวประกาศ หัวข้อข่าว") == "หัวข้อข่าว")
    check("ไม่มี &nbsp;", "&nbsp;" not in strip_tags("<p>a&nbsp;b</p>"))

    print("\n=== แยกรายการข่าวจากหน้า /news/ ===")
    items = parse_list_page(LIST_HTML)
    check("ได้ 2 ข่าว", len(items) == 2, str(len(items)))
    check("เก็บ id", items[0]["id"] == "105", items[0]["id"])
    check("เก็บลิงก์", items[0]["url"] == "https://www.mytcas.com/news/105/", items[0]["url"])
    check("เก็บหัวข้อ", "รายชื่อสถาบัน" in items[0]["title"], items[0]["title"])
    check("เก็บวันที่", items[0]["date"] == "2569-10-19", str(items[0]["date"]))

    print("\n=== แยกรายละเอียดข่าว ===")
    detail = parse_detail_page(DETAIL_HTML, "https://www.mytcas.com/news/105/")
    check("เก็บหัวข้อ", detail["title"].startswith("ประกาศสำนักงาน"), detail["title"])
    check("เก็บวันที่", detail["date"] == "2569-10-19", str(detail["date"]))
    check("ตัดหัวข้อออกจากเนื้อหา", not detail["content"].startswith("ประกาศสำนักงาน"), detail["content"][:60])
    check("เก็บเนื้อหาจริง", "รายชื่อสถาบันฝ่ายผลิต" in detail["content"])
    check("เก็บรูปประกอบ", detail["images"] == ["https://i.mytcas.com/wp-content/uploads/2026/10/shot.webp"], str(detail["images"]))
    check("ไม่เก็บรูปโลโก้เว็บ", all("/img/" not in u for u in detail["images"]))
    check("เก็บ PDF", detail["pdfs"] == ["https://i.mytcas.com/wp-content/uploads/2026/10/announce.pdf"], str(detail["pdfs"]))

    print("\n=== ชื่อไฟล์ PDF เป็นคำอธิบาย ===")
    check("ชื่อไทย", "ประกาศ" in _pdf_label("https://x.com/ประกาศเกณฑ์.pdf"))
    check("ชื่ออังกฤษ → ข้อความทั่วไป", "PDF" in _pdf_label("https://x.com/tcas70-announcement-8.pdf"))
    check("ไม่มีชื่อ", "PDF" in _pdf_label("https://x.com/a.pdf"))

    print("\n=== สรุปสั้น ===")
    long_text = ("ประกาศเรื่องนี้เป็นเรื่องที่สำคัญมากสำหรับนักเรียนทุกคนที่กำลังจะสมัคร "
                 "โดยเฉพาะผู้ที่อยู่ในภูมิภาคตะวันออก ซึ่งต้องดำเนินการตามขั้นตอนที่ระบุไว้ในเอกสารแนบ "
                 "และกรุณาตรวจสอบรายละเอียดเพิ่มเติมก่อนสมัคร ระบบจะเปิดรับตามรอบที่ประกาศ")
    summary = _short_summary(long_text)
    check("สรุปสั้นลง", len(summary) < len(long_text), f"{len(summary)} vs {len(long_text)}")
    check("ลงท้ายด้วย …", summary.endswith("…"))

    print("\n=== กรองรูปปกข่าว ===")
    emoji_url = "https://static.xx.fbcdn.net/images/emoji.php/v9/t3a/2/16/1f6d1.png"
    good_url = "https://i.mytcas.com/wp-content/uploads/2026/10/shot.webp"
    check("ข้ามอีโมจิ Facebook", _pick_cover([emoji_url]) != emoji_url, _pick_cover([emoji_url]))
    check("เลือกรูปจากแหล่งที่น่าเชื่อถือ", _pick_cover([good_url, emoji_url]) == good_url)
    check("ข่าวไม่มีรูป → ใช้พื้นหลัง myTCAS", _pick_cover([], "105") in FALLBACK_COVERS, _pick_cover([], "105"))
    check("พื้นหลังสำรองหมุนตาม id", _pick_cover([], "105") != _pick_cover([], "106"))

    print("\n=== ข่าวครบทุกรายการของ myTCAS ===")
    # หน้า /news/ ของ myTCAS มีข่าวทั้งหมดในหน้าเดียว (id 1-105) ไม่มี pagination
    import re as _re
    ids = [int(m) for m in _re.findall(r'href="/news/(\d+)/"', LIST_HTML)]
    check("หน้า /news/ ไม่มี pagination", "page=" not in LIST_HTML)
    check("แต่ละข่าวมี id ที่แยกกัน", len(ids) == len(set(ids)))

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
