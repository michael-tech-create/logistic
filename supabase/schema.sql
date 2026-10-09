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

alter table public.quotes enable row level security;
alter table public.line_items enable row level security;
alter table public.quote_splits enable row level security;
