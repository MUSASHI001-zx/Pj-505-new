# ดึงข้อมูลมหาวิทยาลัย / คณะ / เกณฑ์รับ จาก myTCAS ด้วย Make.com

ระบบรับข้อมูลเข้าผ่าน API แบบเดียวกับข่าว (`POST /api/news`) — Make.com เป็นฝ่ายยิงเข้ามา
ระบบจะ **upsert** ให้อัตโนมัติ ยิงซ้ำได้โดยไม่เกิดข้อมูลซ้ำ

---

## 0. เตรียมฝั่งเซิร์ฟเวอร์ (ครั้งเดียว)

1. รัน `supabase/migrations/009_tcas_ingest.sql` ใน Supabase SQL Editor
   (เพิ่มคอลัมน์ `institutions.tc_uid/short_name/city/kind/website_url` และสร้างตาราง `faculties`)
2. ตั้ง `.env` (หรือ environment ของที่ deploy):

   ```bash
   MAKE_WEBHOOK_SECRET=<สตริงสุ่มยาว ๆ>   # เช่น openssl rand -hex 32
   ```

   ใช้ค่าเดียวกับนี้ใน header `X-Webhook-Secret` ของ Make
3. FastAPI ต้องเข้าถึงได้จากอินเทอร์เน็ตผ่าน **HTTPS** (Make อยู่บนคลาวด์ เรียก `localhost` ไม่ได้)
   ตอนทดสอบในเครื่องใช้ ngrok / cloudflared ได้

> **หมายเหตุ:** ถ้ายังไม่ได้ตั้ง `MAKE_WEBHOOK_SECRET` ระบบจะปฏิเสธทุกคำขอ (fail closed)
> และจะใช้ค่าเดียวกันกับข่าวได้

ทดสอบก่อนต่อ Make:

```bash
curl -i -X POST https://YOUR-DOMAIN/api/tcas/institutions \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: $MAKE_WEBHOOK_SECRET" \
  -d '{"name":"มหาวิทยาลัยตัวอย่าง","tc_uid":"001","short_name":"CU","city":"กรุงเทพฯ","kind":"รัฐ"}'
# ควรได้ 200 {"ok":true,...}
```

| Status | ความหมาย |
|---|---|
| 200 | บันทึกสำเร็จ (ยิงซ้ำ = อัปเดตแถวเดิม) |
| 401 | `X-Webhook-Secret` ไม่ตรง |
| 422 | payload ไม่ครบ (เช่น ไม่มี `name`) |
| 502 | Supabase บันทึกไม่สำเร็จ |
| 503 | ยังไม่ได้ตั้ง `MAKE_WEBHOOK_SECRET` หรือ Supabase |

---

## 1. Scenario บน Make.com

ทำ **3 scenario แยกกัน** (เพราะความถี่และต้นทางข้อมูลต่างกัน) หรือรวมเป็น 1 ก็ได้ถ้าไล่ส่งทีละชนิด

### 1A. มหาวิทยาลัย/สถาบัน — `POST /api/tcas/institutions`

```
[1 Schedule ทุก 1 สัปดาห์] → [2 HTTP: ดึงหน้ารายชื่อสถาบัน] → [3 Iterator/Text parser]
                                                          → [4 HTTP: POST /api/tcas/institutions]
```

### 1B. คณะและหลักสูตร — `POST /api/tcas/faculties`

```
[1 Schedule ทุก 1 สัปดาห์] → [2 HTTP: ดึงหน้าสถาบันรายแห่ง (ทีละแห่ง)] → [3 Text parser]
                                                          → [4 HTTP: POST /api/tcas/faculties]
```

### 1C. เกณฑ์รับ/รอบสมัคร — `POST /api/tcas/admissions`

```
[1 Schedule ทุก 1–3 วัน (ช่วงเปิดรับ) / ทุกเดือน] → [2 HTTP: ดึงประกาศรับสมัคร]
                                                          → [3 Text parser]
                                                          → [4 HTTP: POST /api/tcas/admissions]
```

> เกณฑ์รับเปลี่ยนทุกปีและต้องอ้างอิงประกาศทางการ — **ควรตั้งความถี่ถี่กว่าข่าว**
> แต่ไม่เกิน 1 ครั้งต่อวันต่อรายการ เพื่อไม่รบกวน myTCAS

### โครงสร้าง HTTP ตัวส่ง (เหมือนกันทั้ง 3 scenario)

- **URL:** `https://YOUR-DOMAIN/api/tcas/institutions` (หรือ `/faculties`, `/admissions`)
- **Method:** `POST`
- **Headers:** `Content-Type: application/json` และ `X-Webhook-Secret: <ค่าเดียวกับ MAKE_WEBHOOK_SECRET>`
- **Body type:** `Raw`, Content type `JSON (application/json)`

#### มหาวิทยาลัย/สถาบัน — ส่งทีละรายการ

```json
{
  "tc_uid": "001",
  "name": "จุฬาลงกรณ์มหาวิทยาลัย",
  "short_name": "CU",
  "city": "กรุงเทพฯ",
  "kind": "รัฐ",
  "website_url": "https://www.chula.ac.th/",
  "logo_url": "https://assets.mytcas.com/i/logo/001.png"
}
```

#### คณะและหลักสูตร

```json
{
  "tc_uid": "001",
  "institution": "จุฬาลงกรณ์มหาวิทยาลัย",
  "name": "วิศวกรรมศาสตร์",
  "program": "วิศวกรรมศาสตร์ (วศ.บ.)",
  "degree": "ปริญญาตรี",
  "tc_faculty_uid": "001-ENG",
  "source_url": "https://www.chula.ac.th/engineering/"
}
```

#### เกณฑ์รับ/รอบสมัคร

```json
{
  "tc_uid": "001-ENG-1",
  "tc_uid_inst": "001",
  "institution": "จุฬาลงกรณ์มหาวิทยาลัย",
  "faculty": "วิศวกรรมศาสตร์",
  "program": "วิศวกรรมศาสตร์ (วศ.บ.)",
  "round": "รอบ 1",
  "criteria": "ตรวจสอบเกณฑ์จากประกาศทางการของคณะ",
  "source_url": "https://www.chula.ac.th/engineering/admission/",
  "source_label": "ประกาศรับสมัคร คณะวิศวกรรมศาสตร์",
  "deadline": "2027-01-15"
}
```

### ส่งทีเดียวหลายรายการ (เร็วกว่า)

ใส่ `items` เป็นอาร์เรย์ได้ ส่งได้ครั้งละไม่เกิน **500 รายการ**

```json
{
  "items": [
    { "tc_uid": "001", "name": "จุฬาลงกรณ์มหาวิทยาลัย", "short_name": "CU" },
    { "tc_uid": "002", "name": "มหาวิทยาลัยเกษตรศาสตร์", "short_name": "KU" }
  ]
}
```

---

## 2. การกันข้อมูลซ้ำ (upsert)

ระบบจับคู่แถวเดิมตามลำดับนี้:

1. `tc_uid` ของ myTCAS (แนะนำ — เสถียรที่สุด)
2. ถ้าไม่มี `tc_uid` จะใช้ **ชื่อ** เป็นกุญแจ (สำหรับคณะ/เกณฑ์รับ จะใช้ ชื่อสถาบัน + ชื่อคณะ + รอบ)

ดังนั้นยิงซ้ำแล้วข้อมูลจะ **อัปเดตทับ** ไม่สร้างซ้ำ
ถ้าอยากกันแน่นอน ให้ใส่ `tc_uid` ทุกรายการ

---

## 3. ข้อควรระวัง

- **ช่องที่ไม่มีค่า** ปล่อยว่างได้ (`""`) — API จะไม่เขียนทับค่าเดิมด้วย
- **ตัวอักษรพิเศษ** (เครื่องหมายคำพูด ขึ้นบรรทัดใหม่) ทำให้ JSON ที่เขียนมือพัง
  แนะนำให้สร้าง body ด้วยโมดูล *Tools → Create JSON* แล้วใส่ผลลัพธ์ใน Request content (escape ให้เอง)
- **`kind` (ประเภทสถาบัน)** ต้องเป็นหนึ่งใน: `รัฐ`, `เอกชน`, `ราชมงคล`, `นานาชาติ`, `อื่น ๆ`
  ค่าอื่นจะถูกบันทึกเป็น `อื่น ๆ`
- **`deadline`** ใช้รูปแบบ `YYYY-MM-DD` เท่านั้น
- **`source_url`** ควรใส่เสมอสำหรับเกณฑ์รับ — ผู้ใช้ต้องตรวจสอบกับประกาศทางการ
- **Error handler:** คลิกขวาที่โมดูลส่ง → *Add error handler → Break* ตั้ง retry อัตโนมัติ (3 ครั้ง ห่างกัน 15 นาที)
- **สิทธิ์ดึงข้อมูล:** `https://www.mytcas.com/robots.txt` ปัจจุบันเปิด `Allow: /` ทั้งหมด
  แต่ควรตั้งความถี่ไม่เกินจำเป็น และตรวจเงื่อนไขการใช้งานของ myTCAS เป็นระยะ

---

## 4. ตรวจว่าข้อมูลเข้าแล้ว

```bash
curl https://YOUR-DOMAIN/api/institutes?limit=5
curl https://YOUR-DOMAIN/api/faculties?limit=5
curl https://YOUR-DOMAIN/api/admissions?limit=5
```

หน้า **"ข้อมูลมหาวิทยาลัย"** (`/institutes`) และ **"ค้นหาโควตา / TCAS"** (`/quota`)
จะดึงจากตารางเหล่านี้อัตโนมัติ — ถ้ายังไม่มีข้อมูล ระบบจะแสดงข้อมูลตัวอย่างที่มีอยู่

หลังบ้านที่ `/admin` → แท็บ **"มหาวิทยาลัย & เกณฑ์รับ"** ดูและแก้ไขข้อมูลที่ sync เข้ามาได้ (ซ่อนรายการที่ไม่อยากให้แสดง)
