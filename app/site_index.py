"""ดัชนีเนื้อหาคงที่ของเว็บ TCAS Buddy สำหรับช่องค้นหากลาง (/api/search)

ครอบคลุมสิ่งที่ไม่ได้อยู่ในฐานข้อมูล: หน้าต่าง ๆ ในเมนู ฟีเจอร์ในแต่ละหน้า ช่องทางโซเชียล
คำถามที่พบบ่อย (FAQ) และอาชีพจากแบบทดสอบค้นหาตัวตน — ไม่พึ่งเน็ตหรือฐานข้อมูล จึงค้นได้ทันที
"""
from __future__ import annotations

from typing import Any, Iterable

# (ชื่อ, url, คำอธิบายสั้น, คีย์เวิร์ดเพิ่มเติม — รวมคำพ้อง/คำสะกดอังกฤษที่คนมักพิมพ์)
PAGES: list[tuple[str, str, str, str]] = [
    ("หน้าหลัก", "/", "ภาพรวมข้อมูลและทางลัดไปยังทุกเมนู", "home dashboard สถิติ เข้าชม ออนไลน์ ข่าวเด่น"),
    ("ข่าวสาร & อัปเดต", "/news", "ข่าว TCAS ประกาศ และกำหนดการสำคัญ", "news ข่าว ประกาศ ปฏิทิน กำหนดการ ติดตามข่าว กระดิ่ง แจ้งเตือน tcas69"),
    ("ข้อมูลมหาวิทยาลัย", "/institutes", "สำรวจมหาวิทยาลัยและสถาบันทั่วประเทศ", "มหาวิทยาลัย มหาลัย มหาลัย university institute สถาบัน รัฐ เอกชน ราชภัฏ ราชมงคล"),
    ("ค้นหาโควตา / TCAS", "/quota", "ค้นหารอบรับสมัครและเกณฑ์รับของแต่ละคณะ", "quota โควตา รอบ 1 รอบ 2 รอบ 3 รอบ 4 portfolio admission เกณฑ์ คณะ สาขา หลักสูตร สมัคร คะแนน"),
    ("ค้นหาทุน", "/scholarships", "ทุนการศึกษาจาก กสศ. และ Scholarship.in.th", "scholarship ทุน ทุนเรียน ทุนการศึกษา กสศ. ทุนเรียนดี ทุนขาดแคลน"),
    ("ค้นหาตัวตนของคุณ", "/identity", "ตอบสถานการณ์จำลอง แล้วดูอาชีพและคณะที่เหมาะ", "identity ตัวตน แบบทดสอบ แบบประเมิน อาชีพ ถนัด บุคลิก ค้นหาตัวเอง quiz ไม่รู้จะเรียนอะไร"),
    ("คลังข้อสอบ", "/exams", "ข้อสอบพร้อมเฉลยและตัวอย่างข้อสอบจาก myTCAS", "exam ข้อสอบ เฉลย a-level tgat tpat pdf ดาวน์โหลด blueprint"),
    ("ช่วยเหลือ & สร้างโพล", "/community", "ถามตอบ ขอความเห็น สร้างโพล และคุยกับแอดมิน", "community ชุมชน กระทู้ โพล poll ถาม ตอบ ช่วยเหลือ ติดต่อแอดมิน ticket แชท ai ที่ปรึกษา"),
    ("คู่มือใช้งาน & FAQ", "/faq", "คำถามที่พบบ่อยและวิธีใช้งาน TCAS Buddy", "faq คู่มือ วิธีใช้ ช่วยเหลือ help คำถาม supabase ตั้งค่า"),
    ("ข้อมูลเพิ่มเติม", "/additional", "ช่องทางติดตาม TCAS Buddy บนโซเชียลมีเดีย", "ติดต่อ โซเชียล social qr facebook instagram tiktok เฟซบุ๊ก อินสตาแกรม ติ๊กต๊อก"),
    ("จัดการบัญชี", "/account", "โปรไฟล์ ข้อมูลส่วนตัว การแจ้งเตือน และลิงก์คำเชิญ", "account บัญชี โปรไฟล์ profile แก้ไขข้อมูล รูปโปรไฟล์ อวตาร์ avatar ชื่อ บทบาท ลิงก์คำเชิญ invite เชิญเพื่อน แจ้งเตือน notification ออกจากระบบ logout"),
    ("เข้าสู่ระบบ", "/login", "เข้าสู่ระบบด้วย Google", "login signin เข้าสู่ระบบ ล็อกอิน google สมัครสมาชิก"),
]

SOCIALS: list[tuple[str, str, str, str]] = [
    ("Facebook — TCAS Buddy", "https://www.facebook.com/share/1KcA1ZB8uh/", "ติดตามข่าวสารและกิจกรรมที่ Facebook", "facebook เฟซบุ๊ก เฟส fb"),
    ("Instagram — @tcas_buddy", "https://www.instagram.com/tcas_buddy/", "ติดตามไลฟ์สไตล์ รีวิว และคอนเทนต์ที่ Instagram", "instagram อินสตาแกรม ig ไอจี"),
    ("TikTok — @tcasbuddy", "https://www.tiktok.com/@tcasbuddy?is_from_webapp=1&sender_device=pc", "ชมคลิปสั้นและเทคนิคเตรียมตัวที่ TikTok", "tiktok ติ๊กต๊อก ติ๊กตอก คลิป"),
]


def _norm(text: Any) -> str:
    return " ".join(str(text or "").casefold().split())


def matches(needle: str, *fields: Any) -> bool:
    """ทุกคำในคำค้น (แยกด้วยช่องว่าง) ต้องอยู่ในข้อความรวมของฟิลด์ใดฟิลด์หนึ่งรวมกัน"""
    tokens = _norm(needle).split()
    if not tokens:
        return False
    haystack = _norm(" ".join(str(f or "") for f in fields))
    return all(token in haystack for token in tokens)


def _rank(needle: str, title: str) -> int:
    n, t = _norm(needle), _norm(title)
    return 0 if t == n else 1 if t.startswith(n) else 2 if n in t else 3


def search_pages(needle: str, take: int) -> list[dict[str, Any]]:
    hits = [(name, url, summary) for name, url, summary, kw in PAGES if matches(needle, name, summary, kw, url)]
    hits.sort(key=lambda item: _rank(needle, item[0]))
    return [{"name": name, "summary": summary, "url": url} for name, url, summary in hits[:take]]


def search_socials(needle: str, take: int) -> list[dict[str, Any]]:
    return [
        {"name": name, "summary": summary, "url": url}
        for name, url, summary, kw in SOCIALS
        if matches(needle, name, summary, kw)
    ][:take]


def search_faqs(needle: str, faqs: Iterable[dict[str, Any]], take: int) -> list[dict[str, Any]]:
    out = []
    for item in faqs:
        question, answer = item["question"], item["answer"]
        if matches(needle, question, answer, item.get("category_label")):
            out.append({
                "name": question,
                "summary": answer[:120] + ("…" if len(answer) > 120 else ""),
                "url": f"/faq#faq-{item['id']}",
            })
        if len(out) >= take:
            break
    return out


def search_careers(needle: str, careers: Iterable[dict[str, Any]], take: int) -> list[dict[str, Any]]:
    out = []
    for career in careers:
        faculties = career.get("faculties") or []
        if matches(needle, career.get("name"), career.get("tagline"), " ".join(faculties)):
            out.append({
                "name": f"{career.get('icon') or ''} {career.get('name') or ''}".strip(),
                "summary": career.get("tagline"),
                "url": "/identity",
            })
        if len(out) >= take:
            break
    return out
