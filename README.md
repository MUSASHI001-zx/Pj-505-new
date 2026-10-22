# TCAS Buddy

เว็บแอปช่วยวางแผนเส้นทางเข้ามหาวิทยาลัย สร้างด้วย Python + FastAPI + Jinja2 โดยออกแบบตามภาพอ้างอิง pastel dashboard ที่มี sidebar, topbar, การ์ด และมาสคอตนักเรียน

## รันในเครื่อง

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload
```

## ตรวจว่าระบบตั้งค่าครบแล้วหรือยัง

```bash
curl http://localhost:3000/api/setup/status
```

คืนสถานะว่าตาราง/คอลัมน์ที่จำเป็นพร้อมใช้หรือไม่ พร้อมบอกว่า**ต้องรัน migration ไหนบ้าง** — ถ้ายังไม่ครบ หน้า `/community` จะแสดงวิธีแก้ให้อัตโนมัติ

## รัน migration (สร้างตาราง)

REST API ของ Supabase ทำ DDL ไม่ได้ ต้องใช้ SQL Editor หรือเชื่อม Postgres ตรง

**ทางเลือก 1 — SQL Editor:** คัดลอกไฟล์ใน `supabase/migrations/` ที่ยังไม่ได้รันไปวางแล้วกด Run (ทุกไฟล์ใช้ `if not exists` จึงรันซ้ำได้)
- `007_community.sql` — กระทู้, tag, โพล, ความคิดเห็น, Ticket
- `008_admin.sql` — สิทธิ์แอดมิน, มหาวิทยาลัย, เกณฑ์รับ, audit log
- `009_tcas_ingest.sql` — คณะ/หลักสูตร, `tc_uid` สำหรับ sync จาก myTCAS
- `010_comment_avatar.sql` — รูปโปรไฟล์ของความคิดเห็น

ไฟล์ `007_009_all.sql` คือทั้งสามไฟล์แรกรวมกัน (รันซ้ำได้)

**ทางเลือก 2 — สคริปต์อัตโนมัติ:** ใส่ `DATABASE_URL` ใน `.env` (Supabase → Project Settings → Database → Connection string → URI) แล้วรัน

```bash
pip install "psycopg[binary]"
python scripts/run_migrations.py --list      # ดูตารางและ migration ที่รอรัน
python scripts/run_migrations.py             # รันไฟล์ที่ยังไม่เคยรัน
python scripts/run_migrations.py 007 008 009 # รันเฉพาะไฟล์ที่ระบุ
```

สถานะการรันถูกเก็บในตาราง `public.schema_migrations` — รันซ้ำจะข้ามไฟล์ที่รันแล้ว
`scripts/create_missing_tables.py` เป็นทางลัดที่รันไฟล์รวมทั้งหมดในครั้งเดียว

## เชื่อม Supabase ภายหลัง

สร้าง Supabase project และรันไฟล์ `supabase/migrations/001_tcas_buddy.sql` ใน SQL Editor จากนั้นเปิด Authentication → Providers → Google และเพิ่ม redirect URL เป็น origin ของเว็บ ระบบต้องมี environment variables ต่อไปนี้ โดย `SUPABASE_SERVICE_ROLE_KEY` ใช้เฉพาะ backend และห้ามใส่ใน JavaScript หรือ Git:

```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-publishable-key
SUPABASE_SERVICE_ROLE_KEY=your-server-key
```

หน้า Login จะใช้ Supabase JS ฝั่ง browser เฉพาะเมื่อ `/api/config` รายงานว่าค่าครบ ปัจจุบันถ้าไม่มีค่าจะแสดงโหมดพร้อมเชื่อมต่อและไม่สร้าง session ปลอม

## การตั้งค่า Google Provider

ใช้ callback ของ Supabase Auth ในรูปแบบ `https://<project-ref>.supabase.co/auth/v1/callback` ที่ Google Cloud OAuth Client และใส่ site URL/redirect URL ของเว็บใน Supabase Auth URL Configuration ตามโดเมนที่ deploy จริง

## โครงสร้างสำคัญ

`app/main.py` ให้บริการหน้าและ API, `app/repository.py` ติดต่อ Supabase REST, `app/community.py` ระบบกระทู้, `app/tickets.py` ระบบ Ticket, `app/admin.py` ศูนย์จัดการแอดมิน, `app/tcas_ingest.py` ช่องรับข้อมูลจาก myTCAS, `app/tcas_sync.py` + `app/tcas_live.py` ดึงรอบรับสมัครจาก myTCAS, `app/tcas_news.py` ดึงข่าวประกาศจาก myTCAS, `app/scholarships.py` ค้นหาทุนจากกสศ. + Scholarship.in.th, `app/ai_chat.py` AI ที่ปรึกษา, `app/tutor.py` AI Tutor / Notebook, `app/dekd.py` คลังชุดข้อมูลเด็กดี, `templates/app.html` รวมหน้าจอ, `static/` เก็บ CSS/JS, `supabase/migrations/` เก็บ schema + RLS, `docs/` เก็บคู่มือตั้งค่า Make.com, `public/manus-routes.json` ประกาศ routes สำหรับ Preview/SEO

## ข้อมูลและความถูกต้อง

ข้อมูลมหาวิทยาลัย/ข่าว/กำหนดการที่อยู่ใน Preview เป็นข้อมูลตัวอย่างเพื่อสาธิต UI และมีป้ายกำกับชัดเจน สถิติแสดงขีด `—` จนกว่าจะเชื่อม Supabase ไม่ควรนำข้อมูลตัวอย่างไปใช้เป็นเกณฑ์สมัครจริง ต้องตรวจประกาศมหาวิทยาลัยหรือ myTCAS ล่าสุดเสมอ


## ระบบจัดการบัญชี (`/account`)

กดที่ชื่อผู้ใช้มุมขวาบน → **จัดการบัญชี** (หรือไอคอนเฟืองใน sidebar) จะเข้าหน้า `/account` ซึ่งมี 5 ส่วน: ข้อมูลส่วนตัว, คณะที่สนใจ (เลือกได้ไม่เกิน 10), ตั้งค่าการแจ้งเตือน (บันทึกทันทีเมื่อสลับ), ลิงก์คำเชิญ และช่วยเหลือ / ติดต่อเรา นอกจากนี้คลิกรูปโปรไฟล์เพื่อเลือกรูปจากชุดที่เตรียมไว้

**ตั้งค่าครั้งแรก:** รัน `supabase/migrations/006_account.sql` ใน Supabase SQL Editor (สร้างตาราง `user_settings`, `invite_links`, `invite_redemptions` เปิด RLS ไม่มี policy จึงเข้าถึงได้เฉพาะ backend ผ่าน service role)

**เพิ่มรูปโปรไฟล์ให้ผู้ใช้เลือก:** วางไฟล์ `.svg/.png/.webp/.jpg` ลงใน `static/assets/avatars/` (ชื่อไฟล์ใช้ได้เฉพาะ `A-Z a-z 0-9 _ -`) ระบบสแกนโฟลเดอร์เอง ไม่ต้องแก้โค้ด ชุดเริ่มต้น `a01–a12.svg` เป็นรูปตัวอย่างที่แทนที่หรือลบได้ แนะนำรูปสี่เหลี่ยมจัตุรัส ขนาดไม่น้อยกว่า 256×256

**API** (ต้องแนบ `Authorization: Bearer <supabase access token>` ยกเว้น `options`): `GET /api/account/options`, `GET|PUT /api/account`, `GET|POST /api/account/invites`, `DELETE /api/account/invites/{code}`, `POST /api/account/invites/redeem` และหน้า `/invite/{code}` ที่ส่งต่อไป `/login?invite=CODE` เพื่อรับคำเชิญหลังเข้าสู่ระบบ

## ระบบกระทู้ชุมชน (`/community`)

ผู้ใช้สร้างกระทู้เพื่อขอความคิดเห็นจากผู้ใช้คนอื่น เลือก **tag แบบ Discord** (มี tag เริ่มต้น 9 ตัว และสร้าง tag ใหม่ได้เอง สูงสุด 5 tag ต่อกระทู้) ใส่ตัวเลือกเพื่อทำเป็นโพล ผู้ใช้อ่านกระทู้ได้โดยไม่ต้องล็อกอิน แต่กดไลก์ โหวต และคอมเมนต์ต้องเข้าสู่ระบบ (โหวตได้คนละหนึ่งครั้ง โหวตใหม่จะทับของเดิม)

**ตั้งค่าครั้งแรก:** รัน `supabase/migrations/007_community.sql` ใน Supabase SQL Editor (สร้าง `community_tags`, `community_posts`, `community_post_options`, `community_comments`, `community_post_likes`, `community_post_votes`, `tickets`, `ticket_messages`, `admin_presence` และคอลัมน์ `users.is_admin` — เปิด RLS ไม่มี policy จึงเข้าถึงได้เฉพาะ backend ผ่าน service role) ถ้ายังไม่รัน หน้าเว็บจะขึ้นข้อความแนะนำให้รัน migration แทนที่จะพัง

**API:** `GET /api/community/tags` (อ่านได้ทุกคน), `POST /api/community/tags`, `GET /api/community/posts?tag=&q=`, `GET /api/community/posts/{id}`, `POST /api/community/posts`, `POST /api/community/posts/{id}/like`, `POST /api/community/posts/{id}/vote`, `POST /api/community/posts/{id}/comments`, `DELETE /api/community/posts/{id}` (เฉพาะเจ้าของกระทู้หรือแอดมิน)

**หมายเหตุเรื่องความเร็ว:** โปรเจกต์ Supabase อยู่ในโตเกียว จึงมี latency ราว 150–280 ms ต่อ request — `app/repository.py` จึงใช้ HTTP client เดียวร่วมกันทั้งแอป (keep-alive + pool) ยิง query ที่ไม่ขึ้นกันกันพร้อมกัน (`asyncio.gather`) และมี retry อัตโนมัติเมื่อ connection หลุด นอกจากนี้ tag ถูก cache 60 วินาที ถ้ายิงจากต่างประเทศควรพิจารณา Supabase region ใกล้ผู้ใช้

## AI ที่ปรึกษา (`/community` แท็บ AI ที่ปรึกษา)

แชทกับ AI ได้จริงในแท็บ **"AI ที่ปรึกษา"** ของหน้า `/community` — หน้าตาเหมือนเว็บคุยกับ AI ทั่วไป (แถบหัวเรื่อง + กล่องข้อความ + ช่องพิมพ์)

- **โมเดลหลัก** — ใช้ตัวเดียวต่อเจ้า ผู้ใช้ไม่ต้องเลือก (Claude / GPT / Gemini ตามที่ตั้ง key ไว้) แสดงชื่อโมเดลไว้ใต้ชื่อ AI
- **ประวัติสนทนา** — ส่งรอบก่อนหน้าให้ AI จำบริบทได้ (สูงสุด 20 ข้อความ)
- **ล้างแชท** — เริ่มใหม่ได้
- **กด Enter ส่ง / Shift+Enter ขึ้นบรรทัดใหม่**
- **เรนเดอร์ Markdown** — ตัวหนาตัวเอียง รายการย่อย และลิงก์
- **สลับโมเดลอัตโนมัติ** — ถ้าโมเดลที่เลือกตอบว่า "คนเยอะชั่วคราว" (503/429) ระบบจะลองโมเดลอื่นของเจ้าเดียวกันเอง แล้วแจ้งชื่อโมเดลที่ตอบจริงไว้ใต้คำตอบ

**ไม่เก็บข้อมูลการคุยไว้เลย** — ประวัติสนทนาอยู่แค่ในหน่วยความจำของหน้า (ไม่เขียนลง localStorage, sessionStorage, cookie หรือฐานข้อมูล) เมื่อออกจากหน้า ปิดแท็บ หรือสลับไปแท็บอื่น ข้อมูลจะหายทันที

**รองรับผู้ให้บริการหลายเจ้า** — ใส่ key ของเจ้าใดเจ้าหนึ่งใน `.env` ระบบจะเลือกใช้อัตโนมัติ (เรียงตามลำดับ):

| ตัวแปรใน `.env` | ผู้ให้บริการ |
|---|---|
| `BUILT_IN_FORGE_API_URL` + `BUILT_IN_FORGE_API_KEY` | Manus WebDev runtime |
| `ANTHROPIC_API_KEY` | Claude (Anthropic) |
| `OPENAI_API_KEY` | GPT (OpenAI) |
| `GEMINI_API_KEY` | Gemini (Google) |

**API:** `GET /api/ai/config` (สถานะการเชื่อมต่อ + โมเดลที่ใช้ได้), `POST /api/ai/chat` (`{message, model, history}` → `{answer, model, provider, error}`)

> ถ้ายังไม่ได้ตั้ง key ระบบจะแจ้งว่า "ยังไม่ได้เชื่อมต่อบริการ AI" ในหน้าแชท (ไม่พังหน้าเว็บ) — เจ้าหน้าที่ต้องใส่ key ใน `.env` แล้วรีสตาร์ทเซิร์ฟเวอร์

## AI Tutor / Notebook (`/tutor`)

สมุดโน้ตเรียนรายวิชา (TCAS / A-Level / TPAT / TOEIC) — ผู้ใช้แต่ละคนมีสมุดของตัวเอง เก็บบทเรียนที่เขียนเองหรือให้ AI สรุป แล้วคุยกับ AI ในบริบทของสมุดนั้น

- **3 โหมดการ์ด** (เรียนรู้แบบรวม / ฝึกทำข้อสอบ / วางแผนอ่านหนังสือ) — กดแล้วเปิดหน้าต่างแชทกับ AI
- **สมุดโน้ตแยกตามวิชา** — สลับแท็บได้ แต่ละวิชาแยกบทเรียนและประวัติคุยกัน
- **AI อ้างอิงบทเรียนของคุณ** — ส่งบทเรียนล่าสุด 6 ชิ้นไปเป็นบริบทให้ AI พร้อมระบุว่าอ้างอิงจากสมุดโน้ต
- **เพิ่มบทเรียนได้ 2 ทาง** — เขียนเอง หรือวางเนื้อหาแล้วให้ AI สรุปเป็นบทเรียน
- **ประวัติคุย** — เก็บไว้ในสมุด ทำให้ AI จำบริบทได้ต่อเนื่อง

**ตารางที่ใช้:** `notebooks`, `notebook_sources`, `tutor_messages` (สร้างจาก `supabase/migrations/012_tutor_notebooks.sql`)

**API** (ต้อง Bearer token): `GET /api/tutor/notebooks`, `GET /api/tutor/notebooks/{subject}`, `POST /api/tutor/notebooks/{subject}/sources`, `DELETE /api/tutor/sources/{id}`, `GET /api/tutor/notebooks/{subject}/messages`, `POST /api/tutor/notebooks/{subject}/chat`, `POST /api/tutor/notebooks/{subject}/summarize`

### คลังชุดข้อมูลเด็กดี (ในหน้า AI Tutor)

ดึงข้อมูลเรื่องสอบ/ข่าว TCAS จาก [Dek-D](https://www.dek-d.com/) มารวมไว้ในหน้า Notebook ML — เป็นเว็บ PHP ไม่มี API สาธารณะ จึงต้อง parse HTML (ดู `app/dekd.py`)

**9 หมวด** — TCAS Alert (ข่าวแจ้งเตือนเร่งด่วน), TCAS Daily, TCAS Review, TCAS Coach, TCAS School Tour, TCAS Event, Dream Campus, TCAS Idol, ติว TCAS

**รายการแต่ละอันมี** — หัวข้อ ข้อความย่อ วันเวลา รูปปก ลิงก์ต้นทาง และแท็กที่เดาจากเนื้อหา (portfolio, quota, tgat, tpat, a-level, admission, dekd, scholarship, exam)

**API:** `GET /api/dekd/library?cat=&q=&pages=` — `cat` เป็น key ของหมวด, `pages` คือจำนวนหน้าที่ดึงต่อหมวด (15 รายการต่อหน้า) cache 15 นาที

## ระบบ Ticket (`/community` แท็บ Ticket / ติดต่อแอดมิน)

ผู้ใช้เปิด Ticket แล้วพิมพ์คุยกับแอดมิน (Amin) แบบส่วนตัวในห้องแชทของตัวเอง **ถ้าไม่มีแอดมินออนไลน์อยู่ ระบบจะตอบกลับอัตโนมัติว่า "ยังไม่มีแอดมินอยู่ในขณะนี้"** แต่ยังเก็บข้อความไว้ให้แอดมินตอบทีหลัง แอดมินเป็นคนปิดตั๋ว (สถานะ `open` → `answered` → `closed`) ผู้ใช้ปิด Ticket ตัวเองได้ และเปิด Ticket ใหม่ได้หลังจากนั้น ข้อความของผู้ใช้อ่านได้เฉพาะเจ้าของ Ticket กับแอดมินเท่านั้น

**การล้างข้อมูล:** เมื่อปิดตั๋ว (ทั้งโดยผู้ใช้และโดยแอดมิน) **ข้อมูลทั้งหมดจะถูกลบออกจากฐานข้อมูลทันที** — ตั๋วและข้อความทั้งหมดหายไป (ข้อความถูกลบด้วย `on delete cascade`) เพื่อไม่ให้ตารางโตไม่จำกัด เท่านี้ตั๋วที่ปิดแล้วจะเปิดดูไม่ได้อีก ผู้ใช้ต้องเปิด Ticket ใหม่

นอกจากนี้มีงานล้างอัตโนมัติสำหรับตั๋วที่ปิดค้างไว้ (เช่น ถ้ามีการปิดผ่านทางอื่นที่ไม่ได้ลบข้อมูล) — เรียกด้วย cron:
```
POST /api/admin/tickets/purge-closed   (body: {"keep_days": 30})
```

แอดมินถูกระบุจาก `public.users.is_admin = true` (หรือ `role = 'admin'`) และต้องเรียก `POST /api/tickets/status/admin` (heartbeat) เป็นระยะ ๆ เพื่อให้ระบบรู้ว่าออนไลน์อยู่ — ถ้าหยุดเรียกเกิน 2 นาที ถือว่าออฟไลน์

**API:** `GET /api/tickets`, `GET /api/tickets/{id}`, `POST /api/tickets`, `POST /api/tickets/{id}/messages`, `POST /api/tickets/{id}/close`, `GET|POST /api/tickets/status/admin` และฝั่งแอดมิน `GET /api/admin/tickets`, `GET /api/admin/tickets/{id}`, `POST /api/admin/tickets/{id}/reply`, `POST /api/admin/tickets/{id}/status`, `GET /api/admin/stats`

## ข่าวประกาศจาก myTCAS (`/news`)

ข่าวดึงจาก myTCAS **โดยตรง ไม่ต้องใช้ Make.com แล้ว**

myTCAS เป็นเว็บ static (Astro) — หน้า `/news/` มีรายการข่าว**ทั้งหมด 105 ข่าว** ในหน้าเดียว (ไม่มี pagination) และแต่ละข่าวอยู่ที่ `/news/{id}/`
ระบบจึงไล่ดึงทีละหน้าแบบขนาน (12 ตัวพร้อมกัน) แล้ว cache ไว้ 15 นาที — **ครั้งแรก ~3 วินาที ครั้งต่อไป ~0.3 วินาที**

**ข้อมูลที่ได้ต่อข่าว:** หัวข้อ วันที่ประกาศ (แปลงเป็น พ.ศ. ได้ รวมปี 2 หลักแบบ "ต.ค. 69") เนื้อหา รูปประกอบ ลิงก์เอกสาร PDF และลิงก์ภายนอก

**การแสดงผล:** หน้า `/news` แสดงครั้งละ 24 ข่าว พร้อมปุ่ม "ดูข่าวเพิ่มเติม" (กดได้จนครบ 105 ข่าว) ค้นหาได้จากช่องค้นหาด้านบน

**API:** `GET /api/news?q=&limit=` — คืน `{items, total, returned, source: "mytcas"}` (`total` = จำนวนข่าวทั้งหมดที่ myTCAS มี, `returned` = จำนวนที่ส่งจริง) และ `GET /api/tcas/news?limit=` (endpoint เดียวกัน)

> **ไม่ต้องมีตาราง `tcas_news` แล้ว** — ระบบไม่เขียนข่าวลงฐานข้อมูล ดึงสดจาก myTCAS แล้วแสดงผลทันที (ถ้าเคยรัน migration 005 ไว้ ลบตารางทิ้งได้)
ถ้า myTCAS โหลดไม่สำเร็จ ระบบจะส่งข้อมูลตัวอย่างกลับไปพร้อม `sample_mode: true` แทนที่จะหน้าเว็บพัง

> หมายเหตุ: ข่าวประกาศส่วนใหญ่ของ myTCAS เป็น PDF จึงไม่มีเนื้อหาในหน้าเว็บ — ระบบจะใช้ชื่อไฟล์ PDF เป็นคำอธิบายแทน และลิงก์ไฟล์ให้ดาวน์โหลด

## ช่องรับข้อมูล myTCAS (ทางเลือก — ไม่จำเป็นแล้ว)

ระบบมี **ช่องรับข้อมูล** เปิดไว้ให้ยิงข้อมูลเข้ามาเอง (เช่น ถ้าต้องการเก็บลงฐานข้อมูลถาวร) แต่ **ไม่ต้องใช้แล้ว** เพราะอ่านข้อมูลจาก myTCAS ได้โดยตรง (ดูหัวข้อข้างบน)

- `POST /api/tcas/institutions` — มหาวิทยาลัย/สถาบัน (ชื่อ ชื่อย่อ โลโก้ ประเภท เมือง เว็บไซต์)
- `POST /api/tcas/faculties` — คณะและหลักสูตรของแต่ละมหาวิทยาลัย
- `POST /api/tcas/admissions` — เกณฑ์รับ/รอบสมัคร (พร้อมลิงก์ประกาศทางการ)

ทุกตัวต้องส่ง header `X-Webhook-Secret` ที่ตรงกับ `MAKE_WEBHOOK_SECRET` (ถ้ายังไม่ตั้งค่า ระบบจะปฏิเสธทุกคำขอ — fail closed) และ **upsert** ให้อัตโนมัติ โดยจับคู่แถวเดิมจาก `tc_uid` ของ myTCAS (ถ้าไม่มีจะใช้ชื่อ) ยิงซ้ำได้โดยไม่เกิดข้อมูลซ้ำ ส่งทีเดียวหลายรายการได้ด้วย `items: [...]` (สูงสุด 500 รายการ)

**ตั้งค่าครั้งแรก:** รัน `supabase/migrations/009_tcas_ingest.sql` ใน Supabase SQL Editor แล้วทำตามคู่มือ `docs/MYTCAS_SETUP.md`

ข้อมูลที่ sync เข้ามาจะแสดงบนหน้า **"ข้อมูลมหาวิทยาลัย"** (`/institutes` — ค้นหาและกรองตามประเภทได้) และแก้ไข/ซ่อนรายการได้ที่หลังบ้าน `/admin`

## ระบบค้นหาทุน (`/scholarships`)

หน้า **"ค้นหาทุน"** รวมข้อมูลทุนการศึกษาจาก 2 แหล่งมาไว้ในที่เดียว และค้นหาได้ทั้งภาษาไทยและอังกฤษ

- **กสศ. (findstudentship.eef.or.th)** — ดึงจาก API สาธารณะ `GET /api/v3/scholar` (ปัจจุบัน ~910 รายการ) มีข้อมูลผู้ให้ทุน มูลค่าทุน กำหนดปิดรับ ช่องทางสมัคร เงื่อนไข และระดับชั้น
- **Scholarship.in.th** — ดึงจาก WordPress REST API `GET /wp-json/wp/v2/posts` (มีหมวดหมู่แยกตามประเภททุนและประเทศ)

**ทำไมต้องค้นฝั่งเซิร์ฟเวอร์:** API ของทั้งสองเว็บค้นคำภาษาไทยไม่ได้ (โทเคนไนเซอร์ของเว็บทำงานกับคำอังกฤษเท่านั้น — ค้น "Future" เจอ แต่ค้น "ทุน" ไม่เจอ) ระบบจึงดึงรายการทั้งหมดมา cache ไว้ 10 นาที แล้วค้นแบบ substring พร้อมให้คะแนนความเกี่ยวข้อง — คำที่เจอในชื่อทุนได้คะแนนสูงกว่า และรองรับการพิมพ์คำที่ยาวกว่าที่เว็บต้นทางบันทึกไว้ (เช่นค้น "วิศวกรรมศาสตร์" เจอทุนที่มีแค่ "วิศวกรรม")

**ตัวกรอง:** สถานะ, ระดับชั้น, แหล่งข้อมูล และประเภททุน — แสดงเป็น **dropdown** สี่ปุ่มบรรทัดเดียว (กดออกมาเลือก) ไม่กินพื้นที่แนวตั้ง ตัวกรองและจำนวนข้อมูลถูกนับมาจากข้อมูลจริงทุกครั้งที่โหลดหน้า เลือกแล้วปุ่มจะแสดงค่าที่เลือกพร้อมจำนวน พร้อมลิงก์ "ล้างตัวกรอง" เมื่อมีตัวกรองตั้งไว้

**สถานะทุน (คำนวณเอง):** เว็บกสศ. มีตัวกรองสถานะใน UI แต่ API ไม่รับค่านั้น (ค่าที่ใช้ได้ว่างเปล่า) ระบบจึงคำนวณเองจากวันที่ปิดรับ โดยแปลงวันที่ไทยให้เป็น ค.ศ. ก่อน (`parse_thai_date` รองรับทั้ง "31 ตุลาคม 2569", "31/10/2569", "2022/2/1" และช่วงวันที่) ได้ 4 สถานะ:
- **เปิดรับสมัคร** — ยังไม่ถึงวันปิด (รวมทุนที่เปิดต่อเนื่อง เช่น "ตลอดทั้งปี" / "ของทุกปี")
- **ใกล้ปิดรับ** — เหลือไม่ถึง 30 วัน
- **ปิดรับแล้ว** — เลยวันปิดมาแล้ว
- **ไม่ระบุ** — ไม่มีวันที่ที่ระบุได้ (เช่น "ติดตามในเพจ")

ผลลัพธ์จะเรียงทุนที่ยังเปิดอยู่ขึ้นก่อนทุนที่ปิดแล้ว และแต่ละการ์ดมีป้ายสถานะกำกับ

**การทำความสะอาดข้อมูล:** ข้อมูลดิบจากกสศ. มีค่าที่ไม่มีความหมายปนอยู่ ระบบจึงกรองออก — มูลค่าทุนที่เป็น `-` / `ไม่ระบุ` ไม่แสดงเป็นตัวเลข, ช่องทางสมัครที่เป็น URL ย้ายไปไว้เป็นลิงก์แทนข้อความ, และโพสต์หมวด "บทความ" ของ scholarship.in.th (ซึ่งเป็นบทความ/เคล็ดลับ ไม่ใช่ทุนที่สมัครได้) ถูกตัดออก

**API:** `GET /api/scholarships?q=&status=&level=&source=&genre=&limit=` (ค่า `status` คือ `เปิดรับสมัคร` / `ใกล้ปิดรับ` / `ปิดรับแล้ว` / `ไม่ระบุ`, `source` คือ `eef` หรือ `sit`, `limit` ไม่เกิน 120) คืนค่า `{items, total, returned, facets, errors, sources}` — `total` คือจำนวนที่ตรงทั้งหมด ส่วน `returned` คือจำนวนที่ส่งจริง (ใช้กับปุ่ม "ดูเพิ่มเติม") ถ้าแหล่งข้อมูลใดโหลดไม่สำเร็จ ระบบจะยังแสดงข้อมูลของอีกแหล่งที่ใช้ได้ พร้อมข้อความแจ้งเตือนใน `errors`

## ค้นหาโควตา / รอบรับสมัคร (`/quota`) — ข้อมูลสดจาก myTCAS

myTCAS เปิดข้อมูลเป็น **JSON สาธารณะบน S3** ระบบจึงอ่านข้อมูลตรง ไม่ต้องใช้ Make.com และไม่ต้องรอซิงก์:

| ไฟล์ | เนื้อหา |
|---|---|
| `universities.json` | มหาวิทยาลัย/สถาบัน 92 แห่ง (พร้อมชื่อไทย-อังกฤษ ประเภท) |
| `courses.json` | คณะ/หลักสูตร/สาขา 4,619 รายการ (พร้อมค่าเล่าเรียน อัตราการจบการศึกษา อัตราการจ้างงาน เงินเดือน) |
| `rounds/{programId}.json` | รอบรับสมัคร 19,548 รายการ (พร้อมโครงการ โควตา เกณฑ์คะแนน วันปิดรับ วันสัมภาษณ์ ลิงก์ประกาศ) |

**API:** `GET /api/tcas/quota?q=&limit=` — คืนรายการรอบรับสมัครที่รวมแล้ว เรียงตามวันปิดที่ใกล้ที่สุด พร้อมเกณฑ์ GPA 10 วิชา เกณฑ์ GPA 22/23/24 เกรดเฉลี่ย เกณฑ์คะแนนรวม TGAT/TPAT อายุสูงสุด และเงื่อนไขเฉพาะของแต่ละโครงการ

**ข้อมูลถูก cache ในหน่วยความจำ 1 ชั่วโมง** — ครั้งแรกที่เปิดหน้าจะยิง myTCAS หลายร้อย request (ข้อมูลรอบรับต้องโหลดทีละ program) ครั้งต่อไปจะเร็วทันที

**API อื่น:** `GET /api/tcas/programs?q=&limit=` (ค้นหาหลักสูตรพร้อมรอบรับ), `GET /api/tcas/universities/live` (รายชื่อมหาวิทยาลัยสด), `GET /api/tcas/sync/status` + `POST /api/tcas/sync/run` (ซิงก์ลงฐานข้อมูล — แอดมินเท่านั้น)

**ซิงก์ลงฐานข้อมูล (ทางเลือก):** ถ้าต้องการเก็บข้อมูลไว้ใน Supabase ให้รัน `supabase/migrations/011_tcas_mytcas_sync.sql` แล้ว `python scripts/sync_mytcas.py --all` (ระบบกรองคีย์ที่ตารางยังไม่มีให้อัตโนมัติ จึงรันได้แม้ยังไม่ได้รัน migration)

## หน้าแอดมิน (`/admin`)

หลังบ้านสำหรับผู้ดูแลระบบ **เข้าถึงได้เฉพาะแอดมินเท่านั้น** — ผู้ที่ไม่มีสิทธิ์จะเจอหน้า "ไม่มีสิทธิ์เข้าหลังบ้าน" และทุก API ตรวจสิทธิ์ซ้ำฝั่ง server (คืน 401/403) แม้จะเรียกผ่าน JavaScript โดยตรง

มี 6 แท็บ:
- **ภาพรวม** — ยอดผู้ใช้ ผู้ออนไลน์ ยอดเข้าชม แยกผู้ใช้ตามบทบาท และสถานะ Ticket
- **ผู้ใช้ & สิทธิ์** — ดูรายชื่อผู้ใช้ (พร้อมชื่อที่ผู้ใช้ตั้งเอง โรงเรียน คณะที่สนใจ จำนวนกระทู้/Ticket) เปลี่ยนบทบาท แต่งตั้ง/ถอดสิทธิ์แอดมิน ตั้งชื่อที่แสดง และระงับบัญชี
- **กระทู้ชุมชน** — ดู/ลบกระทู้ ดูและลบความคิดเห็น และจัดการ tag (เปลี่ยนสี หรือลบ tag ซึ่งจะถูกถอดออกจากทุกกระทู้ที่ใช้)
- **มหาวิทยาลัย & เกณฑ์รับ** — เพิ่ม/แก้ไข/ซ่อนมหาวิทยาลัย (ตาราง `institutions` มีข้อมูลจริง 92 แห่งจาก myTCAS) และจัดการรายการเกณฑ์รับ/รอบสมัคร
- **Ticket** — คิว Ticket แบบฝั่งซ้าย–ขวา: เลือก Ticket เพื่ออ่านข้อความ ตอบกลับ และเปลี่ยนสถานะ (ปิดตั๋ว)
- **บันทึกการทำงาน** — audit trail ว่าแอดมินคนไหนแก้อะไรไว้

**ตั้งค่าครั้งแรก:** รัน `supabase/migrations/008_admin.sql` ใน Supabase SQL Editor (เพิ่มคอลัมน์ `users.is_admin`, `users.is_disabled`, `users.display_name`, `users.notes`; คอลัมน์มหาวิทยาลัย; สร้างตาราง `admissions` และ `admin_audit_log` — เปิด RLS ไม่มี policy)

**กำหนดสิทธิ์แอดมิน:** เลือกวิธีใดวิธีหนึ่ง
1. ใส่อีเมลใน `.env` → `ADMIN_EMAILS=amin@example.com` (คั่นด้วย `,` ได้หลายคน) — ใช้ได้ทันทีไม่ต้องแตะฐานข้อมูล
2. รันใน Supabase SQL Editor → `update public.users set is_admin = true where email = 'amin@example.com';`

แอดมินต้องเปิดหน้าเว็บค้างไว้เพื่อให้ระบบรู้ว่าออนไลน์อยู่ (ระบบส่ง heartbeat ทุก 60 วินาที ถ้าหยุดเกิน 2 นาทีถือว่าออฟไลน์ และระบบจะตอบผู้ใช้ว่า "ยังไม่มีแอดมินอยู่ในขณะนี้")

**API** (ทุกตัวต้องมีสิทธิ์แอดมิน): `GET /api/admin/stats`, `GET /api/admin/audit`, `GET /api/admin/users`, `POST /api/admin/users/{open_id}/role`, `POST /api/admin/users/{open_id}/admin`, `POST /api/admin/users/{open_id}/disabled`, `POST /api/admin/users/{open_id}/display-name`, `GET /api/admin/posts`, `DELETE /api/admin/posts/{id}`, `GET /api/admin/posts/{id}/comments`, `DELETE /api/admin/comments/{id}`, `GET /api/admin/tags`, `POST /api/admin/tags`, `DELETE /api/admin/tags/{name}`, `GET|POST /api/admin/institutions`, `PUT|DELETE /api/admin/institutions/{id}`, `GET|POST /api/admin/admissions`, `PUT|DELETE /api/admin/admissions/{id}`, `GET /api/admin/tickets`, `GET /api/admin/tickets/{id}`, `POST /api/admin/tickets/{id}/reply`, `POST /api/admin/tickets/{id}/status`
