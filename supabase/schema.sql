-- Quote desk tables. Run this in the Supabase SQL editor.
-- The bot writes with the service role key. Status stays pending until a person approves it.

create table if not exists public.quotes (
    id uuid primary key default gen_random_uuid(),
    record_id text not null unique,
    telegram_user_id text,
    chat_id text,
    status text not null default 'pending' check (status in ('pending', 'approved')),
    vendor_name text,
    quote_reference_id text,
    lane text,
    currency text,
    total_amount numeric,
    usd_amount numeric,
    ngn_amount numeric,
    cny_amount numeric,
    usd_ngn_rate numeric,
    usd_cny_rate numeric,
    company_id text,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

alter table public.quotes add column if not exists company_id text;
create index if not exists quotes_company_id_idx on public.quotes (company_id);

create table if not exists public.line_items (
    id uuid primary key default gen_random_uuid(),
    quote_id uuid not null references public.quotes (id) on delete cascade,
    description text,
    category text,
    currency text,
    amount numeric,
    created_at timestamptz not null default now()
);

create table if not exists public.quote_splits (
    id uuid primary key default gen_random_uuid(),
    quote_id uuid not null references public.quotes (id) on delete cascade,
    party text not null,
    share numeric,
    currency text,
    usd_amount numeric,
    ngn_amount numeric,
    cny_amount numeric,
    created_at timestamptz not null default now()
);

create table if not exists public.market_rates (
    id bigint generated always as identity primary key,
    lane text not null,
    equipment text not null,
    mode text not null,
    freight_ngn numeric not null,
    created_at timestamptz not null default now()
);

alter table public.market_rates enable row level security;
alter table public.quotes enable row level security;
alter table public.line_items enable row level security;
alter table public.quote_splits enable row level security;

-- Agency accounts. The API uses the service role key. Render's disk is not the database.
create table if not exists public.users (
    id bigint generated always as identity primary key,
    email text not null unique,
    password_hash text not null,
    business_name text not null,
    home_country text default 'Nigeria',
    api_key text not null unique,
    quota_remaining integer not null,
    period_end bigint,
    created_at bigint not null,
    plan_code text default 'trial',
    plan_parses integer default 5,
    company_code text
);

create table if not exists public.sessions (
    token text primary key,
    user_id bigint not null references public.users (id) on delete cascade,
    created_at bigint not null
);

create table if not exists public.companies (
    id bigint generated always as identity primary key,
    user_id bigint not null unique references public.users (id) on delete cascade,
    code text not null unique,
    legal_name text not null,
    home_country text,
    telegram_chat_ids jsonb not null default '[]'::jsonb,
    inbound_emails jsonb not null default '[]'::jsonb,
    port_risk_level text not null default 'normal',
    custom_parallel_ngn numeric,
    notify_email text
);

create table if not exists public.payments (
    reference text primary key,
    email text not null,
    created_at bigint not null
);

create table if not exists public.batches (
    id text primary key,
    user_id bigint not null references public.users (id) on delete cascade,
    payload jsonb not null,
    created_at bigint not null
);

create table if not exists public.human_reviews (
    id bigint generated always as identity primary key,
    company_id text,
    kind text not null,
    summary text not null,
    detail text,
    chat_id text,
    status text not null default 'pending',
    created_at bigint not null,
    payload jsonb,
    execution_note text
);

alter table public.users enable row level security;
alter table public.sessions enable row level security;
alter table public.companies enable row level security;
alter table public.payments enable row level security;
alter table public.batches enable row level security;
alter table public.human_reviews enable row level security;


-- Run once for existing deployments; also included in schema.sql for new ones.
alter table public.users add column if not exists reset_token_hash text;
alter table public.users add column if not exists reset_expires_at bigint;
alter table public.users add column if not exists reset_requested_at bigint;
create unique index if not exists users_reset_token_idx on public.users (reset_token_hash);

-- One transaction prevents link reuse and partial session revocation.
create or replace function public.complete_password_reset(p_token_hash text, p_password_hash text)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
declare reset_user_id bigint;
begin
    update public.users
       set password_hash = p_password_hash,
           reset_token_hash = null,
           reset_expires_at = null
     where reset_token_hash = p_token_hash
       and reset_expires_at > extract(epoch from clock_timestamp())::bigint
     returning id into reset_user_id;
    if reset_user_id is null then
        return false;
    end if;
    delete from public.sessions where user_id = reset_user_id;
    return true;
end;
$$;

revoke all on function public.complete_password_reset(text, text) from public, anon, authenticated;
grant execute on function public.complete_password_reset(text, text) to service_role;
