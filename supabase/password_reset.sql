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
