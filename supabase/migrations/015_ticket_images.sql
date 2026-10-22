-- 015: รูปภาพในระบบ Ticket — แนบรูปตอนเปิดตั๋ว และส่งรูปในแชทกับแอดมิน
-- รันซ้ำได้ ไม่พัง

-- รูปประกอบตั๋ว (แนบตอนเปิด Ticket)
alter table public.tickets add column if not exists image_url text;

-- รูปประกอบข้อความในแชท (ผู้ใช้หรือแอดมินส่งได้)
alter table public.ticket_messages add column if not exists image_url text;

-- bucket สำหรับรูปในระบบ Ticket (แยกจากรูปกระทู้ เพื่อจัดการ/ลบแยกกันได้)
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('ticket-uploads', 'ticket-uploads', true, 5242880,
        array['image/jpeg', 'image/png', 'image/webp', 'image/gif'])
on conflict (id) do update
   set public = excluded.public,
       file_size_limit = excluded.file_size_limit,
       allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "Public read ticket uploads" on storage.objects;
create policy "Public read ticket uploads"
  on storage.objects for select
  to anon, authenticated
  using (bucket_id = 'ticket-uploads');
