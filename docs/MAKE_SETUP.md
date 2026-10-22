# ตั้งค่า Make.com ให้ส่งข่าวเข้า TCAS Buddy

## 0. เตรียมฝั่งเซิร์ฟเวอร์ (ครั้งเดียว)

1. รัน `supabase/migrations/004_news_webhook.sql` ใน Supabase SQL Editor
2. ตั้งค่า `.env` (หรือ environment ของที่ deploy):
   - `MAKE_WEBHOOK_SECRET` = สตริงสุ่มยาว ๆ เช่น `openssl rand -hex 32`
   - `NEWS_AUTO_PUBLISH` = `true` (แสดงข่าวทันที) หรือ `false` (เก็บเป็นฉบับร่างให้แอดมินตรวจก่อน)
3. FastAPI ต้องเข้าถึงได้จากอินเทอร์เน็ตผ่าน **HTTPS** (Make อยู่บนคลาวด์ เรียก `localhost` ไม่ได้)
   ตอนทดสอบในเครื่องใช้ ngrok / cloudflared ได้

ทดสอบ endpoint ก่อนต่อ Make:

```bash
curl -i -X POST https://YOUR-DOMAIN/api/news \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: $MAKE_WEBHOOK_SECRET" \
  -d '{"title":"ทดสอบ","content":"เนื้อหาข่าว","image_url":null,"pdf_url":"","source_url":"https://www.mytcas.com/test-1"}'
# ควรได้ 201  ส่งซ้ำอีกรอบ = อัปเดตแถวเดิม ไม่เกิดข่าวซ้ำ
```

| Status | ความหมาย |
|---|---|
| 201 | บันทึกสำเร็จ |
| 401 | `X-Webhook-Secret` ไม่ตรง |
| 422 | payload ผิด (ไม่มี title/content/source_url หรือ URL ไม่ขึ้นต้น http/https) |
| 502 | Supabase บันทึกไม่สำเร็จ (ดู log ของ FastAPI) |
| 503 | ยังไม่ได้ตั้ง `MAKE_WEBHOOK_SECRET` หรือ Supabase |

## 1. Scenario บน Make.com

ทิศทางข้อมูลคือ **Make เป็นฝ่ายยิงออก** จึงใช้โมดูล *HTTP → Make a request*
(โมดูล "Webhooks → Custom webhook" ของ Make ใช้ *รับ* ข้อมูล ไม่ใช่ส่งไปหา FastAPI)

```
[1 Schedule] → [2 HTTP: ดึงหน้าข่าว] → [3 Iterator/Parser] → [4 (ถ้าต้องมี) HTTP: ดึงหน้ารายละเอียด + Text parser]
             → [5 Filter / Data store: กันซ้ำ (ไม่บังคับ)] → [6 HTTP: POST ไป FastAPI]
```

1. **Tools/Scheduler → Every X hours** — ตั้งความถี่ เช่นทุก 1–3 ชั่วโมง
2. **HTTP → Make a request** (GET) — ดึงหน้า/ฟีดข่าวของ myTCAS (หรือใช้ **RSS → Watch RSS feed items** แทน
   ถ้ามีฟีด ซึ่งง่ายที่สุด) ตั้ง *Parse response = Yes*
3. **แยกรายการข่าว** — ถ้าได้ JSON ใช้ **Iterator**; ถ้าได้ HTML ใช้ **Text parser → Match pattern / Get Elements from HTML (CSS selector)**
   เพื่อดึง `title`, `content`, `image`, `pdf`, ลิงก์ข่าว
4. (ถ้าหน้า list ไม่มีเนื้อหาเต็ม) **HTTP → Make a request** ไปที่ลิงก์ข่าวแต่ละข่าว แล้วดึงเนื้อหา/รูป/PDF จากหน้านั้น
5. (ไม่บังคับ) **Data store → Search records** ด้วย `source_url` + Filter เพื่อลดการยิงซ้ำ —
   ไม่จำเป็นเพื่อความถูกต้อง เพราะ API upsert ด้วย `source_url` อยู่แล้ว
6. **HTTP → Make a request** (ตัวส่ง):
   - URL: `https://YOUR-DOMAIN/api/news`, Method: `POST`
   - Headers: `Content-Type: application/json` และ `X-Webhook-Secret: <ค่าเดียวกับ MAKE_WEBHOOK_SECRET>`
   - Body type: `Raw`, Content type: `JSON (application/json)`, Request content:
     ```json
     {
       "title": "{{3.title}}",
       "content": "{{3.content}}",
       "image_url": "{{3.image_url}}",
       "pdf_url": "{{3.pdf_url}}",
       "source_url": "{{3.source_url}}"
     }
     ```
   - ติ๊ก *Parse response*; ปล่อยให้ "Evaluate all states as errors" เป็นค่าเริ่มต้น เพื่อให้ 4xx/5xx ขึ้น error ใน Make

## 2. ข้อควรระวัง

- **ช่องที่ไม่มีค่า**: ปล่อยว่าง (`""`) ได้เลย — API แปลง `""`, `"null"` เป็น NULL ให้
  ไม่ต้องทำ if ใน Make (ถ้าอยากส่ง `null` จริง ๆ ให้ใช้โมดูล *Tools → Create JSON*)
- **ตัวอักษรพิเศษ**: เนื้อหาข่าวมักมีเครื่องหมายคำพูด/ขึ้นบรรทัดใหม่ ซึ่งทำให้ JSON ที่เขียนมือใน Raw body พัง
  (จะได้ 422 หรือ error ใน Make) แนะนำให้สร้าง body ด้วยโมดูล *Tools → Create JSON* (กำหนด data structure
  ตามฟิลด์ทั้ง 5) แล้วส่งผลลัพธ์ไปใส่ใน Request content แทน — โมดูลนี้ escape ให้เอง
- **URL แบบ relative** (เช่น `/files/a.pdf`) ต้องต่อโดเมนให้เป็น `https://...` ก่อนส่ง ไม่งั้นได้ 422
- **PDF/รูป**: ระบบเก็บ *ลิงก์* ไม่ได้ดาวน์โหลดไฟล์มาเก็บเอง ถ้าต้นทางลบไฟล์ ลิงก์จะเสีย
- **Error handler**: คลิกขวาที่โมดูลส่ง → *Add error handler → Break* ตั้ง retry อัตโนมัติ (เช่น 3 ครั้ง ห่างกัน 15 นาที)
  สำหรับ 502/503
- **สิทธิ์ดึงข้อมูลจาก myTCAS**: ตรวจเงื่อนไขการใช้งาน/robots ของ myTCAS ก่อนดึงอัตโนมัติ และไม่ควรตั้งความถี่ถี่เกินจำเป็น
