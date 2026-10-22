"""ตั้งค่าอีเมลแอดมินลงใน .env — ใช้เมื่อต้องการเป็นแอดมินโดยไม่ต้องแตะฐานข้อมูล

รัน: python scripts/set_admin_email.py อีเมลของคุณ
  (ไม่ใส่อีเมล = แสดงค่าปัจจุบัน)

ตัวอย่าง: python scripts/set_admin_email.py parameskhamel@gmail.com
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
KEY = "ADMIN_EMAILS"


def main() -> int:
    current = ""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith(f"{KEY}="):
                current = line.split("=", 1)[1].strip()

    if len(sys.argv) < 2:
        print(f"ADMIN_EMAILS ปัจจุบัน: {current or '(ยังไม่ได้ตั้ง)'}")
        print("\nใช้: python scripts/set_admin_email.py อีเมล1,อีเมล2")
        return 0

    emails = [item.strip() for item in sys.argv[1].replace(";", ",").split(",") if item.strip()]
    if not emails:
        print("ไม่พบอีเมลที่ระบุ")
        return 1
    value = ",".join(emails)

    lines = ENV_FILE.read_text(encoding="utf-8-sig").splitlines() if ENV_FILE.exists() else []
    out: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith(f"{KEY}="):
            out.append(f"{KEY}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append("# อีเมลที่ได้สิทธิ์แอดมิน (คั่นด้วย , หรือ ;) — ใช้ตอบ Ticket และปิดตั๋วได้")
        out.append(f"{KEY}={value}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")

    print(f"ตั้ง {KEY} = {value} แล้ว")
    print("\nอย่าลืมรีสตาร์ทเซิร์ฟเวอร์ แล้วลองเข้า /admin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
