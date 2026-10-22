-- 014: รูปภาพในกระทู้ + ยืนยันกฎ 1 คนต่อ 1 ไลก์ / 1 โหวต
-- รันซ้ำได้ ไม่พัง

alter table public.community_posts add column if not exists image_url text;

delete from public.community_post_likes a
  using public.community_post_likes b
 where a.ctid > b.ctid and a.post_id = b.post_id and a.open_id = b.open_id;

delete from public.community_post_votes a
  using public.community_post_votes b
 where a.ctid > b.ctid and a.post_id = b.post_id and a.open_id = b.open_id;

create unique index if not exists community_post_likes_pkey
  on public.community_post_likes(post_id, open_id);

create unique index if not exists community_post_votes_pkey
  on public.community_post_votes(post_id, open_id);

-- เผื่อตารางเดิมสร้างมาโดยไม่มี primary key/unique (เช่น ตารางที่ import มาจากที่อื่น)
-- ให้เพิ่ม unique index ให้แน่นอน โดยไม่ชนกับ index ที่มีอยู่แล้ว
do $$
begin
  if not exists (
    select 1 from pg_index i
     join pg_class c on c.oid = i.indexrelid
     join pg_attribute a1 on a1.attrelid = i.indrelid and a1.attnum = any(i.indkey)
     join pg_attribute a2 on a2.attrelid = i.indrelid and a2.attnum = any(i.indkey)
    where c.relname = 'community_post_likes'
      and i.indisunique
      and a1.attname = 'post_id' and a2.attname = 'open_id'
      and array_length(i.indkey, 1) = 2
  ) then
    create unique index community_post_likes_unique_idx
      on public.community_post_likes(post_id, open_id);
  end if;

  if not exists (
    select 1 from pg_index i
     join pg_class c on c.oid = i.indexrelid
     join pg_attribute a1 on a1.attrelid = i.indrelid and a1.attnum = any(i.indkey)
     join pg_attribute a2 on a2.attrelid = i.indrelid and a2.attnum = any(i.indkey)
    where c.relname = 'community_post_votes'
      and i.indisunique
      and a1.attname = 'post_id' and a2.attname = 'open_id'
      and array_length(i.indkey, 1) = 2
  ) then
    create unique index community_post_votes_unique_idx
      on public.community_post_votes(post_id, open_id);
  end if;
end $$;

-- bucket สำหรับเก็บรูปที่ผู้ใช้แนบตอนตั้งกระทู้ (backend เขียนผ่าน service role)
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('community-uploads', 'community-uploads', true, 5242880,
        array['image/jpeg', 'image/png', 'image/webp', 'image/gif'])
on conflict (id) do update
   set public = excluded.public,
       file_size_limit = excluded.file_size_limit,
       allowed_mime_types = excluded.allowed_mime_types;

-- ---------------------------------------------------------------------------
-- view สรุปยอดโหวต/ไลก์/คอมเมนต์ ให้ backend อ่านยอดแบบ exact
-- (เดิม backend ดึงทุกแถวมานับใน Python ซึ่งโดนตัดที่ limit 5000)
-- ---------------------------------------------------------------------------
create or replace view public.community_option_tally as
select o.post_id,
       o.id   as option_id,
       o.label,
       o.sort_order,
       coalesce(v.votes, 0) as votes
  from public.community_post_options o
  left join (
        select option_id, count(*)::int as votes
          from public.community_post_votes
         group by option_id
       ) v on v.option_id = o.id;

create or replace view public.community_post_stats as
select p.id as post_id,
       coalesce(l.cnt, 0) as likes,
       coalesce(v.cnt, 0) as total_votes,
       coalesce(c.cnt, 0) as comments_count
  from public.community_posts p
  left join (
        select post_id, count(*)::int as cnt from public.community_post_likes group by post_id
       ) l on l.post_id = p.id
  left join (
        select post_id, count(*)::int as cnt from public.community_post_votes group by post_id
       ) v on v.post_id = p.id
  left join (
        select post_id, count(*)::int as cnt from public.community_comments group by post_id
       ) c on c.post_id = p.id;
