-- รองรับข่าวที่ส่งมาจาก Make.com (POST /api/news)
-- รันใน Supabase SQL Editor (รันซ้ำได้ ไม่พัง)

-- ลิงก์ไฟล์ PDF แนบข่าว (รูปภาพใช้คอลัมน์ cover_url เดิม)
alter table public.news add column if not exists pdf_url text;

-- กันข่าวซ้ำ: source_url (ลิงก์ myTCAS) ต้องไม่ซ้ำกัน
-- ถ้า Make ยิงซ้ำ/retry ระบบจะอัปเดตแถวเดิมแทนการสร้างใหม่
-- (แถวที่ source_url เป็น NULL ซ้ำได้ตามปกติของ Postgres)
create unique index if not exists news_source_url_uidx on public.news(source_url);
