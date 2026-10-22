-- Online visitor heartbeat for the Dashboard.
create table if not exists public.online_visitors (
  id text primary key,
  last_seen timestamptz not null default now()
);
create index if not exists online_visitors_last_seen_idx on public.online_visitors(last_seen);
