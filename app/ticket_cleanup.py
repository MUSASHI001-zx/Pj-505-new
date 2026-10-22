"""ล้างข้อมูล Ticket ที่ปิดแล้ว — ใช้ร่วมกันทั้งฝั่งผู้ใช้และฝั่งแอดมิน

เหตุผล: เมื่อปิดตั๋วแล้ว ไม่มีใครต้องการอ่านมันอีก การเก็บไว้ทำให้ตารางโตไม่จำกัด
วิธีนี้จึงลบตั๋วและข้อความทั้งหมดออกจากฐานข้อมูลทันที (cascade ลบข้อความให้อัตโนมัติ)

หมายเหตุเรื่องสิทธิ์: การลบข้อมูลถาวรควรยืนยันกับผู้ใช้ก่อนเสมอ
"""
from __future__ import annotations

from typing import Any


def build_helpers(repo: Any) -> dict[str, Any]:
    """คืนฟังก์ชันสำหรับล้างข้อมูล ticket — แยกเป็นโมดูลเพื่อให้ทั้ง tickets.py และ admin.py ใช้ร่วมกัน"""

    async def purge_ticket(ticket_id: int | str) -> dict[str, Any]:
        """ลบตั๋วและข้อความทั้งหมดออกจากฐานข้อมูล

        ข้อความในตาราง ticket_messages มี on delete cascade จึงหายไปพร้อมตั๋ว
        """
        # ลบข้อความก่อน (กรณี cascade ไม่ได้ทำงาน เช่น ตารางถูกสร้างมาโดยไม่มี FK)
        await repo.delete("ticket_messages", {"ticket_id": f"eq.{ticket_id}"})
        # ลบตั๋ว
        deleted = await repo.delete("tickets", {"id": f"eq.{ticket_id}"})
        return {"ok": deleted, "ticket_id": ticket_id}

    async def purge_closed_tickets(keep_days: int = 30) -> dict[str, Any]:
        """ล้างตั๋วที่ปิดไปนานเกินกำหนด (ใช้เรียกจากงานประจำวัน/สัปดาห์)"""
        from datetime import datetime, timedelta, timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
        rows = await repo.select("tickets", {
            "select": "id", "status": "eq.closed", "updated_at": f"lt.{cutoff}", "limit": "500",
        })
        if not rows:
            return {"ok": True, "count": 0}
        count = 0
        for row in rows:
            result = await purge_ticket(row["id"])
            if result["ok"]:
                count += 1
        return {"ok": True, "count": count}

    return {"purge_ticket": purge_ticket, "purge_closed_tickets": purge_closed_tickets}
