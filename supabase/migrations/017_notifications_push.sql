-- Notification center, universal follows, and Web Push subscriptions.
-- Run after the existing migrations using Supabase SQL editor or scripts/run_migrations.py.
create extension if not exists pgcrypto;

-- The existing notifications table may reference public.profiles; authenticated users
-- are Supabase auth.users IDs, so use that canonical identity for notification ownership.
do $$
declare c record;
begin
  for c in
    select conname from pg_constraint
    where conrelid = 'public.notifications'::regclass and contype = 'f'
      and pg_get_constraintdef(oid) like 'FOREIGN KEY (user_id)%'
  loop
    execute format('alter table public.notifications drop constraint %I', c.conname);
  end loop;
end $$;
alter table public.notifications
  add column if not exists url text not null default '/',
  add column if not exists entity_type text,
  add column if not exists entity_id text,
  add column if not exists dedupe_key text;

do $$ begin
  alter table public.notifications add constraint notifications_user_auth_fk
    foreign key (user_id) references auth.users(id) on delete cascade;
exception when duplicate_object then null;
end $$;

create unique index if not exists notifications_user_dedupe_key
  on public.notifications(user_id, dedupe_key) where dedupe_key is not null;
create index if not exists notifications_user_created_at
  on public.notifications(user_id, created_at desc);
create index if not exists notifications_user_unread
  on public.notifications(user_id, created_at desc) where read_at is null;

create table if not exists public.notification_follows (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  entity_type text not null check (entity_type in ('news','scholarship','institution','admission','event','schedule')),
  entity_id text not null,
  title text not null,
  url text not null default '/',
  created_at timestamptz not null default now(),
  unique(user_id, entity_type, entity_id)
);
create index if not exists notification_follows_entity on public.notification_follows(entity_type, entity_id);

create table if not exists public.push_subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  endpoint text not null unique,
  p256dh text not null,
  auth text not null,
  created_at timestamptz not null default now()
);
create index if not exists push_subscriptions_user on public.push_subscriptions(user_id);

alter table public.notifications enable row level security;
alter table public.notification_follows enable row level security;
alter table public.push_subscriptions enable row level security;

drop policy if exists "notifications_select_own" on public.notifications;
create policy "notifications_select_own" on public.notifications for select to authenticated using (auth.uid() = user_id);
drop policy if exists "notifications_update_own" on public.notifications;
create policy "notifications_update_own" on public.notifications for update to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
drop policy if exists "notification_follows_own" on public.notification_follows;
create policy "notification_follows_own" on public.notification_follows for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
drop policy if exists "push_subscriptions_own" on public.push_subscriptions;
create policy "push_subscriptions_own" on public.push_subscriptions for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- API writes through service-role key after independently verifying the Supabase access token.
