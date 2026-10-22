-- TCAS Buddy schema. Run in Supabase SQL editor after enabling Google provider.
create extension if not exists pgcrypto;

create type public.user_role as enum ('student','parents','teacher','admin');
create type public.ticket_status as enum ('open','pending','resolved','closed');

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  name text not null,
  email text not null,
  role public.user_role not null default 'student',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table if not exists public.onboarding_answers (id uuid primary key default gen_random_uuid(), user_id uuid not null references public.profiles(id) on delete cascade, question_key text not null, answer text not null, answered_at timestamptz not null default now());
create table if not exists public.page_views (id bigint generated always as identity primary key, path text not null, user_id uuid references public.profiles(id) on delete set null, viewed_at timestamptz not null default now());
create table if not exists public.registrations (id uuid primary key default gen_random_uuid(), user_id uuid references public.profiles(id) on delete set null, status text not null default 'interested', created_at timestamptz not null default now());
create table if not exists public.news (id uuid primary key default gen_random_uuid(), title text not null, summary text not null default '', body text not null default '', category text not null default 'TCAS', cover_url text, source_url text, published boolean not null default false, published_at timestamptz, created_at timestamptz not null default now());
create table if not exists public.news_follows (id uuid primary key default gen_random_uuid(), user_id uuid not null references public.profiles(id) on delete cascade, category text not null, created_at timestamptz not null default now(), unique(user_id, category));
create table if not exists public.bookmarks (id uuid primary key default gen_random_uuid(), user_id uuid not null references public.profiles(id) on delete cascade, news_id uuid not null references public.news(id) on delete cascade, created_at timestamptz not null default now(), unique(user_id, news_id));
create table if not exists public.notifications (id uuid primary key default gen_random_uuid(), user_id uuid references public.profiles(id) on delete cascade, role_target public.user_role, title text not null, body text not null, read_at timestamptz, created_at timestamptz not null default now());
create table if not exists public.institutions (id uuid primary key default gen_random_uuid(), name text not null, short_name text, city text, logo_url text, website_url text, kind text, published boolean not null default true, created_at timestamptz not null default now());
create table if not exists public.admissions (id uuid primary key default gen_random_uuid(), institution_id uuid references public.institutions(id) on delete cascade, faculty text not null, program text, round text not null, criteria text not null, source_url text, source_label text, deadline date, published boolean not null default true, updated_at timestamptz not null default now());
create table if not exists public.identity_results (id uuid primary key default gen_random_uuid(), user_id uuid not null references public.profiles(id) on delete cascade, answers jsonb not null default '{}', result jsonb not null default '{}', created_at timestamptz not null default now());
create table if not exists public.polls (id uuid primary key default gen_random_uuid(), user_id uuid not null references public.profiles(id) on delete cascade, question text not null, tags text[] not null default '{}', created_at timestamptz not null default now(), closed_at timestamptz);
create table if not exists public.poll_options (id uuid primary key default gen_random_uuid(), poll_id uuid not null references public.polls(id) on delete cascade, label text not null, sort_order int not null default 0);
create table if not exists public.poll_votes (id uuid primary key default gen_random_uuid(), poll_id uuid not null references public.polls(id) on delete cascade, option_id uuid not null references public.poll_options(id) on delete cascade, user_id uuid not null references public.profiles(id) on delete cascade, created_at timestamptz not null default now(), unique(poll_id, user_id));
create table if not exists public.tickets (id uuid primary key default gen_random_uuid(), user_id uuid not null references public.profiles(id) on delete cascade, subject text not null, category text not null default 'ทั่วไป', status public.ticket_status not null default 'open', created_at timestamptz not null default now(), updated_at timestamptz not null default now());
create table if not exists public.ticket_messages (id uuid primary key default gen_random_uuid(), ticket_id uuid not null references public.tickets(id) on delete cascade, sender_id uuid references public.profiles(id) on delete set null, body text not null, is_system boolean not null default false, created_at timestamptz not null default now());
create table if not exists public.admin_presence (id uuid primary key default gen_random_uuid(), admin_id uuid not null references public.profiles(id) on delete cascade, is_online boolean not null default false, updated_at timestamptz not null default now(), unique(admin_id));
create table if not exists public.notebooks (id uuid primary key default gen_random_uuid(), user_id uuid not null references public.profiles(id) on delete cascade, title text not null, subject text not null default 'TCAS', created_at timestamptz not null default now(), updated_at timestamptz not null default now());
create table if not exists public.notebook_sources (id uuid primary key default gen_random_uuid(), notebook_id uuid not null references public.notebooks(id) on delete cascade, title text not null, content text not null default '', source_url text, is_ai_generated boolean not null default false, created_at timestamptz not null default now());
create table if not exists public.ai_messages (id uuid primary key default gen_random_uuid(), user_id uuid not null references public.profiles(id) on delete cascade, notebook_id uuid references public.notebooks(id) on delete set null, model text not null, role text not null, content text not null, created_at timestamptz not null default now());

create index if not exists page_views_path_idx on public.page_views(path);
create index if not exists news_category_idx on public.news(category);
create index if not exists admissions_faculty_idx on public.admissions(faculty);
create index if not exists notifications_user_idx on public.notifications(user_id, read_at);

alter table public.profiles enable row level security;
alter table public.onboarding_answers enable row level security;
alter table public.page_views enable row level security;
alter table public.registrations enable row level security;
alter table public.news enable row level security;
alter table public.news_follows enable row level security;
alter table public.bookmarks enable row level security;
alter table public.notifications enable row level security;
alter table public.institutions enable row level security;
alter table public.admissions enable row level security;
alter table public.identity_results enable row level security;
alter table public.polls enable row level security;
alter table public.poll_options enable row level security;
alter table public.poll_votes enable row level security;
alter table public.tickets enable row level security;
alter table public.ticket_messages enable row level security;
alter table public.admin_presence enable row level security;
alter table public.notebooks enable row level security;
alter table public.notebook_sources enable row level security;
alter table public.ai_messages enable row level security;

create policy "public reads published news" on public.news for select using (published = true);
create policy "public reads institutions" on public.institutions for select using (published = true);
create policy "public reads admissions" on public.admissions for select using (published = true);
create policy "users read own profile" on public.profiles for select using (auth.uid() = id);
create policy "users update own profile" on public.profiles for update using (auth.uid() = id);
create policy "users manage own onboarding" on public.onboarding_answers for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "users read own notifications" on public.notifications for select using (auth.uid() = user_id);
create policy "users update own notifications" on public.notifications for update using (auth.uid() = user_id);
create policy "users manage own follows" on public.news_follows for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "users manage own bookmarks" on public.bookmarks for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "users manage own identity results" on public.identity_results for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "users manage own polls" on public.polls for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "authenticated read poll options" on public.poll_options for select to authenticated using (true);
create policy "users manage own votes" on public.poll_votes for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "users manage own tickets" on public.tickets for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "ticket participants read messages" on public.ticket_messages for select using (exists (select 1 from public.tickets t where t.id = ticket_id and t.user_id = auth.uid()) or exists (select 1 from public.profiles p where p.id = auth.uid() and p.role = 'admin'));
create policy "ticket participants write messages" on public.ticket_messages for insert with check (exists (select 1 from public.tickets t where t.id = ticket_id and t.user_id = auth.uid()) or exists (select 1 from public.profiles p where p.id = auth.uid() and p.role = 'admin'));
create policy "users manage own notebooks" on public.notebooks for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "users manage own notebook sources" on public.notebook_sources for all using (exists (select 1 from public.notebooks n where n.id = notebook_id and n.user_id = auth.uid())) with check (exists (select 1 from public.notebooks n where n.id = notebook_id and n.user_id = auth.uid()));
create policy "users manage own ai messages" on public.ai_messages for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create or replace function public.handle_new_user() returns trigger language plpgsql security definer set search_path = public as $$
begin insert into public.profiles (id, name, email) values (new.id, coalesce(new.raw_user_meta_data->>'full_name', new.email), new.email) on conflict (id) do update set name = excluded.name, email = excluded.email; return new; end; $$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users for each row execute procedure public.handle_new_user();
