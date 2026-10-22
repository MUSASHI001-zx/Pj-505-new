-- 007: ระบบกระทู้ชุมชน (โพสต์/โพล + tag + ความคิดเห็น) และระบบ Ticket แชทส่วนตัวกับแอดมิน
-- รันใน Supabase SQL Editor (รันซ้ำได้ ไม่พัง)
-- ทุกตารางเปิด RLS และไม่มี policy: เข้าถึงได้เฉพาะ backend ผ่าน service role เท่านั้น

-- ---------------------------------------------------------------------------
-- ผู้ใช้ & สิทธิ์แอดมิน
-- ตาราง public.users มีอยู่แล้ว (คอลัมน์ role) — เพิ่มเฉพาะคอลัมน์ is_admin
-- ถ้ายังไม่มีตาราง users จะสร้างให้ (schema เดียวกับที่ deploy)
-- ---------------------------------------------------------------------------
do $$
begin
  if to_regclass('public.users') is null then
    create table if not exists public.users (
      id            uuid primary key default gen_random_uuid(),
      "openId"      text unique,
      name          text,
      email         text,
      "loginMethod" text,
      role          text,
      "createdAt"   text,
      "updatedAt"   text,
      "lastSignedIn" text,
      created_at    timestamptz not null default now()
    );
  end if;
  alter table public.users add column if not exists is_admin boolean not null default false;
  -- รองรับ schema ที่ใช้ accountRole (ถ้ามีอยู่แล้วคงไว้ ไม่ต้องแตะ)
  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'users' and column_name = 'accountRole'
  ) then
    alter table public.users add column if not exists "accountRole" text;
  end if;
end $$;

create index if not exists users_is_admin_idx on public.users(is_admin);

-- ---------------------------------------------------------------------------
-- Tag ของกระทู้ (Discord style) — ผู้ใช้สร้าง tag ใหม่ได้เอง
-- ---------------------------------------------------------------------------
create table if not exists public.community_tags (
  id         bigint generated always as identity primary key,
  name       text not null unique,
  color      text not null default 'purple',
  created_by text,
  created_at timestamptz not null default now()
);

insert into public.community_tags (name, color) values
  ('TCAS', 'purple'),
  ('คณะในฝัน', 'blue'),
  ('เตรียมสอบ', 'pink'),
  ('A-Level', 'teal'),
  ('ทุนการศึกษา', 'gold'),
  ('สายสุขภาพ', 'rose'),
  ('สายวิศวกรรม', 'violet'),
  ('ประชับสังคม', 'indigo'),
  ('ช่วยกันตัดสินใจ', 'green')
on conflict (name) do nothing;

-- ---------------------------------------------------------------------------
-- กระทู้ (โพสต์) + ตัวเลือกโพล + ความคิดเห็น + กดไลก์ + โหวต
-- ---------------------------------------------------------------------------
create table if not exists public.community_posts (
  id            bigint generated always as identity primary key,
  open_id       text not null,
  author_name   text,
  author_avatar text,
  title         text not null,
  body          text not null default '',
  tags          text[] not null default '{}',
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index if not exists community_posts_created_idx on public.community_posts(created_at desc);
create index if not exists community_posts_tags_idx on public.community_posts using gin(tags);

create table if not exists public.community_post_options (
  id         bigint generated always as identity primary key,
  post_id    bigint not null references public.community_posts(id) on delete cascade,
  label      text not null,
  sort_order int not null default 0
);
create index if not exists community_post_options_post_idx on public.community_post_options(post_id);

create table if not exists public.community_comments (
  id          bigint generated always as identity primary key,
  post_id     bigint not null references public.community_posts(id) on delete cascade,
  open_id     text not null,
  author_name text,
  body        text not null,
  created_at  timestamptz not null default now()
);
create index if not exists community_comments_post_idx on public.community_comments(post_id, created_at);

create table if not exists public.community_post_likes (
  post_id    bigint not null references public.community_posts(id) on delete cascade,
  open_id    text not null,
  created_at timestamptz not null default now(),
  primary key (post_id, open_id)
);

create table if not exists public.community_post_votes (
  post_id    bigint not null references public.community_posts(id) on delete cascade,
  option_id  bigint not null references public.community_post_options(id) on delete cascade,
  open_id    text not null,
  created_at timestamptz not null default now(),
  primary key (post_id, open_id)
);

-- ---------------------------------------------------------------------------
-- Ticket แชทส่วนตัวกับแอดมิน
-- ---------------------------------------------------------------------------
create table if not exists public.tickets (
  id         bigint generated always as identity primary key,
  open_id    text not null,
  subject    text not null,
  category   text not null default 'ทั่วไป',
  status     text not null default 'open',   -- open | answered | closed
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists tickets_open_idx on public.tickets(open_id, updated_at desc);
create index if not exists tickets_status_idx on public.tickets(status, updated_at desc);

create table if not exists public.ticket_messages (
  id          bigint generated always as identity primary key,
  ticket_id   bigint not null references public.tickets(id) on delete cascade,
  sender_type text not null default 'user',   -- user | admin | system
  sender_id   text,
  sender_name text,
  body        text not null,
  created_at  timestamptz not null default now()
);
create index if not exists ticket_messages_ticket_idx on public.ticket_messages(ticket_id, created_at);

-- สถานะออนไลน์ของแอดมิน (heartbeat) — ใช้ตัดสินว่า "ยังไม่มีแอดมินอยู่ในขณะนี้"
create table if not exists public.admin_presence (
  admin_id     text primary key,
  display_name text,
  is_online    boolean not null default false,
  updated_at   timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- RLS: backend เท่านั้นที่เข้าถึงได้
-- ---------------------------------------------------------------------------
alter table public.community_tags enable row level security;
alter table public.community_posts enable row level security;
alter table public.community_post_options enable row level security;
alter table public.community_comments enable row level security;
alter table public.community_post_likes enable row level security;
alter table public.community_post_votes enable row level security;
alter table public.tickets enable row level security;
alter table public.ticket_messages enable row level security;
alter table public.admin_presence enable row level security;
