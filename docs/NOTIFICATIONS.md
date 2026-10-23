# ระบบแจ้งเตือนและ Web Push — TCAS Buddy

## สิ่งที่เพิ่ม
- `/api/notifications` อ่านการแจ้งเตือนของบัญชีที่ผ่านการยืนยัน Supabase Auth พร้อมจำนวนยังไม่อ่าน
- `PATCH /api/notifications/{id}/read` และ `POST /api/notifications/read-all`
- `POST /api/notifications/follows` / `GET .../follows` / `DELETE .../follows/{entity_type}/{entity_id}` สำหรับข่าว ทุน มหาวิทยาลัย รอบรับสมัคร กิจกรรม และกำหนดการ
- `POST /api/notifications/push-subscription` บันทึก subscription ของเบราว์เซอร์
- `POST /api/notifications/publish` ให้ระบบ sync/แหล่งข้อมูลที่เชื่อถือได้กระจาย event ไปยังผู้ติดตาม และส่ง Web Push หากตั้งค่า VAPID
- หน้าเว็บกระดิ่งแจ้งเตือนพร้อม polling ทุก 30 วินาที; service worker แสดง Push Notification และเปิดลิงก์เมื่อคลิก

## ติดตั้ง
1. รัน migration `supabase/migrations/017_notifications_push.sql` หลัง migration เดิมทั้งหมด
2. ติดตั้ง dependencies: `pip install -r requirements.txt`
3. ตั้งค่า `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` ตามเดิม
4. สำหรับ Push Notification สร้างคู่กุญแจ VAPID เช่น `npx web-push generate-vapid-keys` แล้วตั้ง `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` ใน environment ของ backend
5. ตั้ง `MAKE_WEBHOOK_SECRET` เป็น secret แบบสุ่มยาว (จำเป็นสำหรับ endpoint publish) และส่งค่าเดียวกันใน header `X-Webhook-Secret`
6. Deploy ผ่าน HTTPS (localhost ใช้พัฒนาได้) แล้วล็อกอิน กดกระดิ่ง และเลือก “เปิดแจ้งเตือนบนอุปกรณ์” พร้อมอนุญาต notification

## ส่ง event เมื่อรายการที่ติดตามมีอัปเดต
ระบบ event publisher ต้องส่ง `POST /api/notifications/publish` พร้อม `Content-Type: application/json` และ `X-Webhook-Secret` ตัวอย่าง payload:

```json
{
  "entity_type": "news",
  "entity_id": "news-id-or-source-url",
  "title": "ประกาศข่าวใหม่",
  "body": "มีข่าวใหม่ในรายการที่คุณติดตาม",
  "url": "/news",
  "event_key": "news-published-2026-10-23"
}
```

`entity_type` รองรับ `news`, `scholarship`, `institution`, `admission`, `event`, `schedule` และ `entity_id` ต้องตรงกับรหัสที่บันทึกในรายการติดตาม ผู้ใช้จะได้รับ notification เฉพาะเมื่อมี follow ที่ตรงกัน ระบบสร้าง `dedupe_key` เพื่อป้องกัน event ซ้ำ หากไม่มีผู้ติดตามตรงรายการจะไม่สร้าง notification

> หมายเหตุ: การติดตามรายการและการแจ้งเตือนในหน้าเว็บทำงานผ่าน API/ฐานข้อมูลหลังรัน migration และตั้งค่า Supabase แล้ว ส่วน Push Notification ต้องตั้งค่า VAPID และผู้ใช้ต้องอนุญาตในแต่ละอุปกรณ์ด้วย การมีระบบ publish ไม่ได้ทำให้แหล่งข้อมูลภายนอกส่ง event อัตโนมัติเอง ต้องเชื่อมงาน sync/ผู้ดูแล/Make webhook ให้เรียก endpoint นี้เมื่อมีการเผยแพร่หรือเปลี่ยนแปลงข้อมูล
