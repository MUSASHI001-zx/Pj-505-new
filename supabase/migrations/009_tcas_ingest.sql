-- 009: รับข้อมูลมหาวิทยาลัย/คณะ/เกณฑ์รับจาก myTCAS ผ่าน Make.com
-- รันใน Supabase SQL Editor (รันซ้ำได้ ไม่พัง)
-- เปิด RLS ไม่มี policy: เข้าถึงได้เฉพาะ backend ผ่าน service role เท่านั้น

-- เติมรายละเอียดที่ขาดจาก seed เดิม (เดิมมีแค่ id, name, logoUrl)
-- tc_uid = รหัสประจำสถาบันจาก myTCAS ใช้ upsert กันข้อมูลซ้ำ
alter table public.institutions add column if not exists tc_uid text;
alter table public.institutions add column if not exists short_name text;
alter table public.institutions add column if not exists city text;
alter table public.institutions add column if not exists kind text;
alter table public.institutions add column if not exists website_url text;
alter table public.institutions add column if not exists is_published boolean not null default true;
alter table public.institutions add column if not exists updated_at timestamptz not null default now();

create unique index if not exists institutions_tc_uid_uidx on public.institutions(tc_uid) where tc_uid is not null;
create index if not exists institutions_name_idx on public.institutions(name);

-- คณะและหลักสูตรของแต่ละมหาวิทยาลัย
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

-- เกณฑ์รับ / รอบสมัคร — ต้องอ้างอิงประกาศทางการเสมอ
-- (migration 008 อาจสร้างตารางนี้ไว้แล้ว — เพิ่มคอลัมน์ที่ขาดให้ครบเสมอ)
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

alter table public.faculties enable row level security;
alter table public.admissions enable row level security;
