-- Upload counters for the public demo's caps (tallyhawk.limits). One row per browser
-- session per UTC day; the API sums a day's rows for the cap across all visitors.
-- Requests without a session id (direct API use) count under session_id 'anonymous'.

create table public.demo_usage (
  session_id text not null,
  day date not null,
  uploads integer not null default 0 check (uploads >= 0),
  primary key (session_id, day)
);

create index demo_usage_day_idx on public.demo_usage (day);

alter table public.demo_usage enable row level security;
