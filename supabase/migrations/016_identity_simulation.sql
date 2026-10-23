-- ผลข้อสอบจำลองอาชีพ (หน้า Identity Discovery)
-- เปิด RLS และไม่มี policy: เข้าถึงได้เฉพาะ backend ผ่าน service role (กรองด้วย open_id เสมอ)
-- รันซ้ำได้ (if not exists)

create table if not exists public.identity_simulation_results (
  id         uuid primary key default gen_random_uuid(),
  open_id    text not null,
  career_id  text not null,
  answers    jsonb not null default '[]',
  result     jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create index if not exists identity_simulation_results_user_idx
  on public.identity_simulation_results (open_id, created_at desc);

alter table public.identity_simulation_results enable row level security;
