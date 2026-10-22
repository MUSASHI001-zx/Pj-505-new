-- ===========================================================================
-- รวม migration 007 + 008 + 009 ไว้ที่เดียว — สำหรับคัดลอกไปวางใน Supabase SQL Editor
-- รันซ้ำได้ (ใช้ if not exists ทั้งหมด) ไม่พัง
-- หรือรันอัตโนมัติด้วย: python scripts/run_migrations.py
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1) ผู้ใช้ & สิทธิ์แอดมิน
-- ---------------------------------------------------------------------------
alter table public.users add column if not exists is_admin boolean not null default false;
alter table public.users add column if not exists is_disabled boolean not null default false;
alter table public.users add column if not exists display_name text;
alter table public.users add column if not exists notes text;
create index if not exists users_is_admin_idx on public.users(is_admin);

-- ---------------------------------------------------------------------------
-- 2) มหาวิทยาลัย/สถาบัน — เติมรายละเอียดที่ขาดจาก seed เดิม (เดิมมี id, name, logoUrl)
--    tc_uid = รหัสประจำสถาบันจาก myTCAS ใช้ upsert กันข้อมูลซ้ำ
-- ---------------------------------------------------------------------------
alter table public.institutions add column if not exists tc_uid text;
alter table public.institutions add column if not exists short_name text;
alter table public.institutions add column if not exists city text;
alter table public.institutions add column if not exists kind text;
alter table public.institutions add column if not exists website_url text;
alter table public.institutions add column if not exists is_published boolean not null default true;
alter table public.institutions add column if not exists updated_at timestamptz not null default now();
create unique index if not exists institutions_tc_uid_uidx on public.institutions(tc_uid) where tc_uid is not null;
create index if not exists institutions_name_idx on public.institutions(name);

-- ---------------------------------------------------------------------------
-- 3) Tag ของกระทู้ (Discord style) — ผู้ใช้สร้าง tag ใหม่ได้เอง
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
-- 4) กระทู้ + ตัวเลือกโพล + ความคิดเห็น + กดไลก์ + โหวต
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
-- 5) Ticket แชทส่วนตัวกับแอดมิน
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
-- 6) คณะและหลักสูตรของแต่ละมหาวิทยาลัย (ข้อมูลจาก myTCAS)
-- ---------------------------------------------------------------------------
create table if not exists public.faculties (
  id             bigint generated always as identity primary key,
  institution_id bigint references public.institutions(id) on delete cascade,
  tc_uid         text,
  institution    text not null,
  name           text not null,
  program        text,
  degree         text,
  tc_faculty_uid text,
  source_url     text,
  is_published   boolean not null default true,
  updated_at     timestamptz not null default now(),
  created_at     timestamptz not null default now()
);
create index if not exists faculties_institution_idx on public.faculties(institution_id);
create index if not exists faculties_name_idx on public.faculties(name);
create unique index if not exists faculties_tc_uid_uidx on public.faculties(tc_faculty_uid) where tc_faculty_uid is not null;

-- ---------------------------------------------------------------------------
-- 7) เกณฑ์รับ / รอบสมัคร — ต้องอ้างอิงประกาศทางการเสมอ
-- ---------------------------------------------------------------------------
create table if not exists public.admissions (
  id             bigint generated always as identity primary key,
  institution_id bigint references public.institutions(id) on delete cascade,
  tc_uid         text,
  institution    text not null,
  faculty        text not null,
  program        text,
  round          text not null,
  criteria       text not null default '',
  source_url     text,
  source_label   text,
  deadline       date,
  is_published   boolean not null default true,
  updated_at     timestamptz not null default now(),
  created_at     timestamptz not null default now()
);
alter table public.admissions add column if not exists tc_uid text;
create index if not exists admissions_institution_idx on public.admissions(institution_id);
create index if not exists admissions_faculty_idx on public.admissions(faculty);
create index if not exists admissions_round_idx on public.admissions(round);
create unique index if not exists admissions_tc_uid_uidx on public.admissions(tc_uid) where tc_uid is not null;

-- ---------------------------------------------------------------------------
-- 8) บันทึกการกระทำของแอดมิน (audit trail)
-- ---------------------------------------------------------------------------
create table if not exists public.admin_audit_log (
  id          bigint generated always as identity primary key,
  actor_id    text,
  actor_name  text,
  action      text not null,
  target_type text,
  target_id   text,
  detail      text,
  created_at  timestamptz not null default now()
);
create index if not exists admin_audit_created_idx on public.admin_audit_log(created_at desc);

-- ---------------------------------------------------------------------------
-- 9) RLS: เปิดทุกตาราง ไม่มี policy = เข้าถึงได้เฉพาะ backend ผ่าน service role
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
alter table public.faculties enable row level security;
alter table public.admissions enable row level security;
alter table public.admin_audit_log enable row level security;
