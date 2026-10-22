-- 012: ระบบ AI Tutor / Notebook — สมุดโน้ตเรียนรายผู้ใช้
-- รันใน Supabase SQL Editor (รันซ้ำได้ ไม่พัง)
-- เปิด RLS ไม่มี policy: เข้าถึงได้เฉพาะ backend ผ่าน service role เท่านั้น
-- (ระบบตรวจสิทธิ์ผู้ใช้จาก Bearer token ก่อนอ่าน/เขียนทุกครั้ง)

-- สมุดโน้ตเรียน — 1 สมุดต่อ 1 วิชา (subject) ของผู้ใช้
create table if not exists public.notebooks (
  id          bigint generated always as identity primary key,
  open_id     text not null,
  title       text not null default 'สมุดโน้ตของฉัน',
  subject     text not null default 'TCAS',
  description text not null default '',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create unique index if not exists notebooks_user_subject_uidx on public.notebooks(open_id, subject);
create index if not exists notebooks_open_id_idx on public.notebooks(open_id);

-- บทเรียน/เนื้อหาในสมุด — เก็บได้ทั้งที่ผู้ใช้เขียนเองและที่ AI สร้างให้
create table if not exists public.notebook_sources (
  id              bigint generated always as identity primary key,
  notebook_id     bigint not null references public.notebooks(id) on delete cascade,
  title           text not null,
  content         text not null default '',
  source_url      text,
  kind            text not null default 'note',   -- note | practice | summary
  is_ai_generated boolean not null default false,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index if not exists notebook_sources_notebook_idx on public.notebook_sources(notebook_id);

-- ข้อความคุยกับ AI ในสมุด (เก็บไว้ให้ AI จำบริบทต่อสมุด)
create table if not exists public.tutor_messages (
  id          bigint generated always as identity primary key,
  open_id     text not null,
  notebook_id bigint references public.notebooks(id) on delete cascade,
  role        text not null,                 -- user | assistant
  content     text not null default '',
  model       text not null default '',
  created_at  timestamptz not null default now()
);
create index if not exists tutor_messages_open_id_idx on public.tutor_messages(open_id);
create index if not exists tutor_messages_notebook_idx on public.tutor_messages(notebook_id);

alter table public.notebooks enable row level security;
alter table public.notebook_sources enable row level security;
alter table public.tutor_messages enable row level security;
