"""ทดสอบคลังชุดข้อมูลเด็กดี (dek-d.com) — ทดสอบ parse HTML โดยไม่ต้องต่อเน็ต

รัน: python tests/test_dekd.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.dekd import (  # noqa: E402
    CATEGORIES,
    _guess_tags,
    _strip_html,
    _timestamp_to_date,
    parse_alert_page,
    parse_article_page,
)

FAILURES: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label} {extra}")
        FAILURES.append(label)


ALERT_HTML = """
<div class="tcas-alert-item  -card" data-timestamp="1792579941">
    <div class="sticker-wrapper">
        <div class="sticker " style="background-image: url(https://www0.dek-d.com/assets/admcal/images/2024/34.png)"></div>
    </div>
    <div class="right-inner">
        <div class="datetime">
            <span class="badge-new">ข่าวใหม่</span>
            21 ต.ค. 2569 17:52 น.</div>
        <div class="message">มาแล้ว! รอบ Portfolio70 พยาบาลฯ สภากาชาดไทย หากผ่านคัดเลือกจะได้ทุนเรียนฟรี</div>
        <a class="link-more" href="https://www.dek-d.com/tcas/69297/" target="_blank">อ่านต่อ</a>
    </div>
</div>
<div class="tcas-alert-item  -card" data-timestamp="1792484249">
    <div class="right-inner">
        <div class="datetime"><span class="badge-new">ข่าวใหม่</span> 20 ต.ค. 2569 15:17 น.</div>
        <div class="message">มารู้จัก "โควตาผลิตครูพัฒนาท้องถิ่น ระยะ 2" รับ DEK70 มีเกรดไม่ต่ำ 3.0</div>
        <a class="link-more" href="https://www.dek-d.com/tcas/69298/" target="_blank">อ่านต่อ</a>
    </div>
</div>
"""

ARTICLE_HTML = """
<article class="article-box -flex-m ">
    <a href="/tcas/51187/" class="thumbnail lazy-background" title="ตามติด 1 วันชีวิตทำงาน"
        target="_blank" data-background-url="https://image.dek-d.com/1/content/2018/51187_230x120.jpg"></a>
    <div class="card-description">
        <div class="text-box">
            <a href="/tcas/51187/" class="title" title="ตามติด 1 วันชีวิตทำงาน" target="_blank">
                <span>ตามติด 1 วันชีวิตทำงาน เสกกลิ่นหวาน</span>
            </a>
            <span class="subtext">
                <a href="/tcas/dreamcareer/" class="categorylink" title="A day in life" target="_blank">A day in life</a>
            </span>
        </div>
    </div>
</article>
"""


def main() -> int:
    print("\n=== แปลงรายการข่าว TCAS Alert ===")
    items = parse_alert_page(ALERT_HTML)
    check("ได้ 2 ข่าว", len(items) == 2, str(len(items)))
    check("เก็บ id", items[0]["id"] == "1792579941", items[0]["id"])
    check("เก็บหัวข้อ", "Portfolio70" in items[0]["title"], items[0]["title"][:60])
    check("เก็บลิงก์", items[0]["url"] == "https://www.dek-d.com/tcas/69297/", items[0]["url"])
    check("เก็บวันที่", "21 ต.ค. 2569" in items[0]["date_text"], items[0]["date_text"])
    check("แปลงวันที่เป็น ISO", items[0]["date"] == "2026-10-21", items[0]["date"])
    check("เดาแท็กได้", "portfolio" in items[0]["tags"], str(items[0]["tags"]))
    check("เดาแท็กโควตา", "quota" in items[1]["tags"], str(items[1]["tags"]))

    print("\n=== แปลงรายการบทความ ===")
    articles = parse_article_page(ARTICLE_HTML)
    check("ได้ 1 บทความ", len(articles) == 1, str(len(articles)))
    check("เก็บหัวข้อ", "ชีวิตทำงาน" in articles[0]["title"], articles[0]["title"])
    check("เก็บลิงก์เต็ม", articles[0]["url"] == "https://www.dek-d.com/tcas/51187/", articles[0]["url"])
    check("เก็บหมวดย่อย", articles[0]["article_category"] == "A day in life", articles[0]["article_category"])
    check("เก็บรูปปก", articles[0]["image_url"].endswith("51187_230x120.jpg"), articles[0]["image_url"])

    print("\n=== ตัวช่วย ===")
    check("ถอดแท็ก", _strip_html("<p>ทดสอบ <b>ข้อความ</b></p>") == "ทดสอบ ข้อความ")
    check("decode entity", "&" in _strip_html("A &amp; B"))
    check("เดาแท็ก TGAT", "tgat" in _guess_tags("เตรียมสอบ TGAT ปี 2569"))
    check("เดาแท็ก A-Level", "a-level" in _guess_tags("เตรียม A-Level"))
    check("แปลง timestamp", _timestamp_to_date(1792579941) == "2026-10-21", _timestamp_to_date(1792579941))

    print("\n=== หมวดที่รองรับ ===")
    check("มีหมวด alert", "alert" in CATEGORIES)
    check("ทุกหมวดมี label", all(item["label"] for item in CATEGORIES.values()))
    check("ทุกหมวดมี url", all(item["url"].startswith("https://") for item in CATEGORIES.values()))

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
