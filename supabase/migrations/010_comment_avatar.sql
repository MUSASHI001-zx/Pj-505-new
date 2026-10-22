-- 010: เพิ่มรูปโปรไฟล์ให้ความคิดเห็น (ให้แสดงตามรูปที่ผู้ใช้ตั้งไว้)
-- รันใน Supabase SQL Editor หรือ: python scripts/create_missing_tables.py
alter table public.community_comments add column if not exists author_avatar text;

-- เติมรูปให้ความคิดเห็นเดิมที่ยังไม่มี
-- ใช้รูปจากกระทู้ของคนเดียวกัน (เก็บ URL ไว้แล้ว จึงไม่ต้องเดาส่วนขยายไฟล์)
update public.community_comments c
set author_avatar = p.author_avatar
from public.community_posts p
where p.open_id = c.open_id
  and c.author_avatar is null
  and p.author_avatar is not null
  and p.author_avatar <> '';
