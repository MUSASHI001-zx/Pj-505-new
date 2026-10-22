-- 013: ลบระบบ AI Tutor / Notebook — ระบบสมุดโน้ตถูกเอาออกจากเว็บแล้ว
-- รันใน Supabase SQL Editor (รันซ้ำได้ ไม่พัง — ใช้ if exists)
-- ลบเรียงจากตารางลูกไปตารางแม่ เพราะ notebook_sources/tutor_messages อ้างอิง notebooks

-- 1) ai_messages (จาก migration 001) มี FK ชี้ไปที่ notebooks — ต้องตัด FK ก่อน
--    ไม่งั้น drop notebooks จะติด foreign key constraint
do $$
declare
  constraint_name text;
begin
  -- ข้ามถ้าไม่มีตาราง ai_messages หรือ notebooks อยู่จริง
  if to_regclass('public.ai_messages') is null or to_regclass('public.notebooks') is null then
    return;
  end if;

  for constraint_name in
    select con.conname
    from pg_constraint con
    where con.conrelid = 'public.ai_messages'::regclass
      and con.contype = 'f'
      and con.confrelid = 'public.notebooks'::regclass
  loop
    execute format('alter table public.ai_messages drop constraint if exists %I', constraint_name);
  end loop;
end $$;

-- 2) ลบตารางของระบบ Notebook (เรียงจากลูกไปแม่)
drop table if exists public.tutor_messages;
drop table if exists public.notebook_sources;
drop table if exists public.notebooks;
