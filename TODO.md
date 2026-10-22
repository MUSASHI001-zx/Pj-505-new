# TCAS Buddy — งานพัฒนา

- [ ] **ระบบ Login และ onboarding** — ผู้ใช้ล็อกอินด้วย Google ผ่าน Supabase Auth; โปรไฟล์เก็บ `id`, `name`, `email`, `role` โดย role ต้องรองรับ `student`, `parents`, `teacher`; หลังล็อกอินครั้งแรกให้เลือกบทบาท/ตอบคำถาม; บันทึกคำตอบและเวลา; หลังบ้านรวมยอดคำตอบแยกตามตัวเลือก
- [ ] **หน้า Home และสถิติ** — มี loading screen, sidebar, top search; แสดงจำนวนผู้ใช้, จำนวนเข้าชมหน้าแรก และจำนวนผู้สมัครจากข้อมูล backend; ไม่แสดงตัวเลขสมมติเป็นยอดจริงเมื่อฐานข้อมูลยังไม่พร้อม
- [ ] **หน้า News** — รวบรวมข่าว, หมวดหมู่, ค้นหา, รายละเอียด, bookmark และกดกระดิ่งติดตาม; ผู้ติดตามได้รับ in-app notification ตามหมวด; admin ส่งแจ้งเตือนเฉพาะผู้ใช้/บทบาทได้
- [x] **หน้า Institutes** — แสดงรายชื่อมหาวิทยาลัย/สถาบันพร้อมโลโก้และชื่อ; ค้นหาและกรองตามประเภทได้; อ่านจากตาราง `institutions` (ข้อมูลจริง 92 แห่งจาก myTCAS) และซิงก์เพิ่มผ่าน Make.com ได้
- [x] **หน้า Quota Search** — ค้นหาชื่อมหาวิทยาลัย/โรงเรียน/คณะ/รอบ TCAS/เกณฑ์รับ; แสดง source และลิงก์ประกาศทางการ; อ่านจากตาราง `admissions` และซิงก์เพิ่มผ่าน Make.com ได้
- [x] **ช่องรับข้อมูล myTCAS** — `POST /api/tcas/institutions|faculties|admissions` (ป้องกันด้วย X-Webhook-Secret, upsert ไม่เกิดข้อมูลซ้ำ) + คู่มือ `docs/MYTCAS_SETUP.md`; migration 009
- [ ] **หน้า Identity Discovery** — จำลองสถานการณ์ ตอบคำถาม และสรุปผลแนวทางคณะ/สาขา; บันทึกผลและระบุว่าเป็นเครื่องมือสำรวจตนเอง
- [x] **หน้า Help & Community** — สร้างโพลพร้อมตัวเลือกและ tag แบบ Discord; โหวตได้หนึ่งครั้งต่อคน; AI ปรึกษาเลือกโมเดลที่ใช้งานได้; Ticket มีแชตส่วนตัวกับ admin และสายด่วน; หากไม่มี admin ให้ตอบ “ยังไม่มีแอดมินอยู่ในขณะนี้”
- [x] **ระบบกระทู้ชุมชน** — ผู้ใช้สร้างกระทู้ขอความคิดเห็น เลือก tag แบบ Discord (สร้าง tag ใหม่ได้), ใส่ตัวเลือกโพล, กดไลก์ คอมเมนต์ และโหวตหนึ่งครั้งต่อคน; ค้นหา/กรองตาม tag; เจ้าของกระทู้หรือแอดมินลบกระทู้ได้ (`/api/community/*`, migration 007)
- [x] **ระบบ Ticket แชทส่วนตัว** — ผู้ใช้เปิด Ticket พิมพ์คุยกับแอดมินแบบส่วนตัว; ไม่มีแอดมินออนไลน์จะตอบ “ยังไม่มีแอดมินอยู่ในขณะนี้” แต่ยังเก็บข้อความไว้; แอดมินตอบกลับและปิดตั๋วได้ (`/api/tickets/*`, `/api/admin/tickets/*`)
- [x] **หลังบ้าน Admin (คิว Ticket)** — แสดงยอดผู้ใช้/กระทู้/Ticket รอจัดการ, อ่าน-ตอบ-ปิดตั๋วจากคิว, heartbeat สถานะออนไลน์ของแอดมิน
- [x] **ระบบหลังบ้าน (แอดมินเท่านั้น)** — ประตูสิทธิ์หน้า `/admin` + ตรวจสิทธิ์ซ้ำทุก API; แท็บภาพรวม (ผู้ใช้/ออนไลน์/ยอดชม/แยกตามบทบาท/สถานะ Ticket), ผู้ใช้ & สิทธิ์ (เปลี่ยนบทบาท แต่งตั้ง-ถอดสิทธิ์แอดมิน ตั้งชื่อ ระงับบัญชี), กระทู้ชุมชน (ลบกระทู้/คอมเมนต์ จัดการ tag), มหาวิทยาลัย & เกณฑ์รับ (เพิ่ม/แก้ไข/ซ่อน), Ticket, และบันทึกการทำงาน (audit log) — `supabase/migrations/008_admin.sql`
- [ ] **หน้า How to / FAQ** — สอนใช้งาน Login, ข่าว/กระดิ่ง, โควตา, ตัวตน, โพล, Ticket และ AI ที่ปรึกษา
- [ ] **หลังบ้าน Admin** — แยกสิทธิ์ admin; dashboard สรุปผู้ใช้/role/onboarding/ผู้สมัคร/เข้าชม; จัดการข่าว/สถาบัน/เกณฑ์รับ/แจ้งเตือน/Ticket/admin presence
- [ ] **Supabase schema และ RLS** — migrations สำหรับ profiles, onboarding_answers, page_views, registrations, news, follows, bookmarks, notifications, institutions, admissions, identity_results, polls, poll_options, poll_votes, tickets, ticket_messages, admin_presence และ ai_messages; service key ต้องอยู่ backend เท่านั้น
- [ ] **การส่งมอบ** — มี `manus-routes.json`, health endpoint, README ตั้งค่า Supabase/Google, Dockerfile สำหรับ Python, ตรวจ diagnostics และเปิด Preview; checkpoint แยกจากการ publish สาธารณะ
