"""ทดสอบซิงก์ข้อมูล myTCAS (มหาวิทยาลัย/คณะ/รอบรับสมัคร)

ทดสอบการแปลงข้อมูลดิบจาก myTCAS ให้เข้ากับตารางของเรา — ไม่ต้องต่อเน็ต

รัน: python tests/test_tcas_sync.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.tcas_sync import (  # noqa: E402
    _plain,
    _split_note,
    admission_records,
    course_records,
    university_record,
)

FAILURES: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {extra}")
        FAILURES.append(label)


UNIVERSITY_RAW = {
    "_id": "6183b148ee214bbbe863301d",
    "university_id": "001",
    "university_type": "1",
    "university_name": "จุฬาลงกรณ์มหาวิทยาลัย",
    "university_name_en": "Chulalongkorn University",
    "is_accepted_round1": False,
}

COURSE_RAW = {
    "_id": "6a4dbb15ed95040d0cf52e5f",
    "university_type_id": "1",
    "university_type_name_th": "ทปอ.",
    "university_id": "001",
    "university_name_th": "จุฬาลงกรณ์มหาวิทยาลัย",
    "university_name_en": "Chulalongkorn University",
    "campus_id": "01",
    "campus_name_th": "วิทยาเขตหลัก",
    "faculty_id": "21",
    "faculty_name_th": "คณะวิศวกรรมศาสตร์",
    "group_field_id": "30",
    "group_field_th": "วิศวกรรมศาสตร์",
    "field_id": "00",
    "field_name_th": "วิศวกรรมทั่วไป",
    "program_name_th": "หลักสูตรวิศวกรรมศาสตรบัณฑิต สาขาวิชาวิศวกรรมศาสตร์",
    "program_name_en": "Bachelor of Engineering Program",
    "program_type_id": "A",
    "program_type_name_th": "ภาษาไทย ปกติ",
    "program_id": "10010121300001A",
    "cost": "ภาคการศึกษาต้นและภาคการศึกษาปลาย ภาคการศึกษาละ 25,500 บาท",
    "graduate_rate": "ร้อยละ 86.8 ต่อปีการศึกษา",
    "employment_rate": "0",
    "median_salary": "0",
}

ROUND_ADMISSION = {
    "_id": "6a4df552ac2b6b7a8877fa72",
    "university_id": "001",
    "program_id": "10010121300001A",
    "type": "3_2570",
    "receive_student_number": 250,
    "condition": "ต้องมีเกรดเฉลี่ย 12 วิชา ไม่น้อยกว่า 3.00",
    "interview_location": "ไม่มีสอบสัมภาษณ์",
    "interview_date": "ไม่มีสอบสัมภาษณ์",
    "link": "https://admission.chula.ac.th/admission_c1.php",
    "min_gpax": 2,
    "min_total_score": 51,
    "scores": {"tgat": 20, "tpat3": 30, "a_lv_61": 20},
    "score_conditions": {"min_gpax": 2},
    "description": "",
}

ROUND_QUOTA = {
    "_id": "6a4df552ac2b6b7a8877fa73",
    "university_id": "001",
    "program_id": "10010121300001A",
    "project_id": "C2101",
    "project_name_th": "โครงการรับนักเรียนผู้มีความสามารถทางกีฬา",
    "type": "2_2570",
    "receive_student_number": 12,
    "link": None,
    "folio": {"closed_date": "2026-11-12T00:00:00.000Z", "criteria": "เกณฑ์การพิจารณาแฟ้มสะสมผลงาน"},
}


def main() -> int:
    print("\n=== แปลงมหาวิทยาลัย ===")
    record = university_record(UNIVERSITY_RAW)
    check("เก็บ tc_uid", record["tc_uid"] == "001")
    check("เก็บชื่อไทย", record["name"] == "จุฬาลงกรณ์มหาวิทยาลัย")
    check("เก็บชื่ออังกฤษ", record["name_en"] == "Chulalongkorn University")
    check("แปลงประเภทเป็น 'รัฐ'", record["kind"] == "รัฐ", record["kind"])
    check("ใส่ลิงก์ myTCAS", "mytcas.com" in record["website_url"])
    check("ใส่ลิงก์โลโก้", record["logoUrl"].endswith("/001.png"))

    print("\n=== แปลงคณะ/หลักสูตร ===")
    records = course_records([COURSE_RAW])
    check("ได้ 1 รายการ", len(records) == 1)
    row = records[0]
    check("เก็บชื่อคณะ", "คณะวิศวกรรมศาสตร์" in row["name"], row["name"])
    check("เก็บชื่อหลักสูตร", "วิศวกรรมศาสตร์" in row["program"])
    check("เก็บ program_id", row["program_id"] == "10010121300001A")
    check("เก็บ tc_uid ไม่ซ้ำ", row["tc_uid"] == "course:10010121300001A")
    check("เก็บค่าเล่าเรียน", "25,500" in row["cost"])
    check("เก็บอัตราการจบการศึกษา", "86.8" in row["graduate_rate"])
    check("เก็บระดับปริญญา", row["degree"] == "ภาษาไทย ปกติ")

    print("\n=== แปลงรอบรับสมัคร ===")
    admissions = admission_records(COURSE_RAW, [ROUND_ADMISSION])
    check("ได้ 1 รายการ", len(admissions) == 1)
    item = admissions[0]
    check("ตั้งชื่อรอบ", item["round"].startswith("รอบ 3"), item["round"])
    check("เก็บปีการศึกษา", item["academic_year"] == "2570")
    check("เก็บโควตา", item["quota"] == 250)
    check("เก็บเกณฑ์ GPA", item["min_gpax"] == 2)
    check("เก็บเกณฑ์คะแนนรวม", item["min_total_score"] == 51)
    check("เก็บเงื่อนไข", "3.00" in item["condition"])
    check("เก็บลิงก์ประกาศ", item["source_url"] == "https://admission.chula.ac.th/admission_c1.php")
    check("criterion มีเกณฑ์ GPA", "GPA 10 วิชา" in item["criteria"], item["criteria"][:80])
    check("criterion ไม่มีค่า 0 ที่ไร้ความหมาย", "ไม่ต่ำกว่า 0" not in item["criteria"], item["criteria"][:80])
    check("tc_uid กันข้อมูลซ้ำ", item["tc_uid"] == "admission:10010121300001A:default:3_2570", item["tc_uid"])

    print("\n=== รอบโควตา (มีโครงการ + วันปิด) ===")
    quota = admission_records(COURSE_RAW, [ROUND_QUOTA])[0]
    check("ตั้งชื่อรอบพร้อมโครงการ", "รอบ 2" in quota["round"] and "กีฬา" in quota["round"], quota["round"])
    check("เก็บวันปิดรับ", quota["closed_date"] == "2026-11-12", str(quota["closed_date"]))
    check("เก็บเกณฑ์ Portfolio", "แฟ้มสะสมผลงาน" in quota["criteria"])
    check("tc_uid รวม project_id", quota["tc_uid"] == "admission:10010121300001A:C2101:2_2570", quota["tc_uid"])

    print("\n=== ถอด HTML ออกจากเงื่อนไข (ที่คัดลอกมาจาก Word) ===")
    html_text = '<p class="MsoListParagraphCxSpFirst" style="margin-top:0in">เกณฑ์ GPA ไม่ต่ำกว่า 3.00</p><p>อายุไม่เกิน 20 ปี</p>'
    plain = _plain(html_text)
    check("ไม่มีแท็กเหลือ", "<" not in plain and ">" not in plain, repr(plain))
    check("เก็บข้อความครบ", "3.00" in plain and "20 ปี" in plain, repr(plain))
    check("ไม่มี entity", "&nbsp;" not in _plain("a&nbsp;b"))
    check("ตัดแท็กที่ไม่มีจุดปิด", "<" not in _plain("ข้อความ<span style=\"border-c"), repr(_plain("ข้อความ<span style=\"border-c")))

    print("\n=== แยกเงื่อนไขยาวเป็นรายการย่อย ===")
    items = _split_note("1. ประวัติผลงาน สัดส่วน 25.00 2. SOP สัดส่วน 5.00 3. ผลสอบ MCAT")
    check("แยกได้ 3 ข้อ", len(items) == 3, str(items))
    check("ตัดหมายเลขข้อออก", not items[0].startswith("1."), repr(items[0]))
    check("เก็บเนื้อหาครบ", "ประวัติผลงาน" in items[0] and "MCAT" in items[2])
    check("ไม่ตัด '(ตามข้อ 9)' ผิด", len(_split_note("ผลคะแนนภาษาอังกฤษ (ตามข้อ 9) ส่งเกรดเฉลี่ย")) == 1)

    print("\n=== โครงสร้างเกณฑ์สำหรับแสดงผล (score_items) ===")
    admission = admission_records(COURSE_RAW, [ROUND_ADMISSION])[0]
    score_items = admission["score_items"]
    check("มีรายการเกณฑ์", len(score_items) >= 2, str(score_items))
    check("แยก GPA 10 วิชา", any(i["label"] == "GPA 10 วิชา" and i["value"] == 2 for i in score_items), str(score_items))
    check("แยกคะแนนรวม", any("TGAT" in i["label"] and i["value"] == 51 for i in score_items), str(score_items))
    check("แยกเกณฑ์คะแนนส่วน", any(i["label"].startswith("TGAT") for i in score_items), str(score_items))
    check("มีหน่วยกำกับ", any(i["unit"] == "คะแนน" for i in score_items), str(score_items))
    check("เงื่อนไขแยกเป็น notes", isinstance(admission["notes"], list) and admission["notes"], str(admission["notes"])[:80])
    check("notes ไม่มีหมายเลขข้อนำหน้า", not admission["notes"][0].startswith("1."), repr(admission["notes"][0][:50]))

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
