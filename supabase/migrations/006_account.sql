-- 006: ระบบจัดการบัญชี (โปรไฟล์ที่ผู้ใช้เลือกเอง, คณะที่สนใจ, การแจ้งเตือน, ลิงก์คำเชิญ)
-- ผูกกับ public.users ด้วย open_id (= Supabase auth user id เดียวกับคอลัมน์ "openId")
-- ทุกตารางเปิด RLS และไม่มี policy: เข้าถึงได้เฉพาะ backend ผ่าน service role เท่านั้น

create table if not exists public.user_settings (
  open_id            text primary key,
  display_name       text,
  avatar_key         text,
  school             text,
  grade_level        text,
  classroom          text,
  interested_faculties text[] not null default '{}',
  notify_prefs       jsonb not null default '{"news":true,"deadlines":true,"community":true,"ticket":true}',
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create table if not exists public.invite_links (
  code        text primary key,
  created_by  text not null,
  label       text,
  max_uses    int check (max_uses is null or max_uses > 0),
  expires_at  timestamptz,
  revoked_at  timestamptz,
  created_at  timestamptz not null default now()
);
create index if not exists invite_links_created_by_idx on public.invite_links(created_by);

create table if not exists public.invite_redemptions (
  code         text not null references public.invite_links(code) on delete cascade,
  open_id      text not null,
  redeemed_at  timestamptz not null default now(),
  primary key (code, open_id)
);

alter table public.user_settings enable row level security;
alter table public.invite_links enable row level security;
alter table public.invite_redemptions enable row level security;
