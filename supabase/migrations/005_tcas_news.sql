-- ตารางข่าว TCAS ที่หน้าเว็บอ่าน (GET /api/news) และที่ Make.com เขียน (POST /api/news)
-- รันใน Supabase SQL Editor — รันซ้ำได้ ถ้ามีตารางอยู่แล้วจะไม่แตะโครงสร้างเดิม
create table if not exists public.tcas_news (
  id bigint generated always as identity primary key,
  title text,
  content text,
  source_url text,
  news_date text,
  image_url text,
  pdf_url text,
  created_at text default now()::text
);

-- ให้ POST /api/news ทำ upsert ด้วย source_url ได้ (ยิงซ้ำไม่เกิดข่าวซ้ำ)
-- ถ้าคำสั่งนี้ error ว่ามีค่าซ้ำ แปลว่ามีข่าว source_url ซ้ำอยู่แล้ว ให้ลบแถวซ้ำก่อน
create unique index if not exists tcas_news_source_url_uidx on public.tcas_news(source_url);

-- backend ใช้ service role key (ข้าม RLS) เปิด RLS เพื่อไม่ให้ anon key อ่าน/เขียนตรง ๆ ได้
-- หากต้องการให้ browser อ่านตรงผ่าน anon key ให้เพิ่ม policy select เอง
alter table public.tcas_news enable row level security;
