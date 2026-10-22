-- 008: ระบบหลังบ้านแอดมิน — จัดการผู้ใช้/สิทธิ์, กระทู้ชุมชน, มหาวิทยาลัย และเกณฑ์รับ
-- รันใน Supabase SQL Editor (รันซ้ำได้ ไม่พัง)
-- ทุกตารางเปิด RLS และไม่มี policy: เข้าถึงได้เฉพาะ backend ผ่าน service role เท่านั้น

-- ---------------------------------------------------------------------------
-- ตาราง users: สิทธิ์แอดมิน + การระงับบัญชี
-- ---------------------------------------------------------------------------
alter table public.users add column if not exists is_admin boolean not null default false;
alter table public.users add column if not exists is_disabled boolean not null default false;
alter table public.users add column if not exists display_name text;
alter table public.users add column if not exists notes text;

create index if not exists users_is_admin_idx on public.users(is_admin);

-- ---------------------------------------------------------------------------
-- มหาวิทยาลัย: เพิ่มรายละเอียดที่หลังบ้านต้องใช้ (ตารางเดิมมี id, name, logoUrl)
-- (migration 009 จะเพิ่ม tc_uid เพิ่ม — ใช้ if not exists เพื่อรันสลับลำดับก็ได้)
-- ---------------------------------------------------------------------------
alter table public.institutions add column if not exists tc_uid text;
alter table public.institutions add column if not exists short_name text;
alter table public.institutions add column if not exists city text;
alter table public.institutions add column if not exists kind text;
alter table public.institutions add column if not exists website_url text;
alter table public.institutions add column if not exists is_published boolean not null default true;
alter table public.institutions add column if not exists updated_at timestamptz not null default now();
create unique index if not exists institutions_tc_uid_uidx on public.institutions(tc_uid) where tc_uid is not null;

-- ---------------------------------------------------------------------------
-- เกณฑ์รับ / รอบสมัคร (ยังไม่เคยมีตารางนี้ในฐานข้อมูล)
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
-- บันทึกการกระทำของแอดมิน (audit trail) — ตรวจสอบย้อนหลังได้ว่าใครแก้อะไร
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
-- RLS: backend เท่านั้นที่เข้าถึงได้
-- ---------------------------------------------------------------------------
alter table public.admissions enable row level security;
alter table public.admin_audit_log enable row level security;
