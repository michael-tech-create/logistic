-- Required for WhatsApp intake and sourced calculation profiles on hosted services.
-- Application access is through the Python API's service role, never browser keys.
create table if not exists public.operation_state (
  namespace text not null, key text not null, company_id text,
  payload jsonb not null, revision bigint not null default 1,
  updated_at double precision not null default extract(epoch from now()),
  primary key(namespace,key)
);
create index if not exists operation_state_company_idx on public.operation_state(namespace,company_id);
create index if not exists operation_state_status_idx on public.operation_state(namespace,(payload->>'status'),updated_at);
alter table public.operation_state enable row level security;
revoke all on public.operation_state from anon, authenticated;
grant all on public.operation_state to service_role;

create table if not exists public.intake_receipts (receipt text primary key, user_id bigint not null references public.users(id));
alter table public.intake_receipts enable row level security;
revoke all on public.intake_receipts from anon, authenticated;
grant all on public.intake_receipts to service_role;

create or replace function public.put_operation_state(p_namespace text,p_key text,p_payload jsonb,p_company_id text,p_expected bigint default null)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare result public.operation_state;
begin
  if p_expected is null then
    insert into public.operation_state(namespace,key,payload,company_id) values(p_namespace,p_key,p_payload,p_company_id)
    on conflict(namespace,key) do update set payload=excluded.payload,company_id=excluded.company_id,
      revision=public.operation_state.revision+1,updated_at=extract(epoch from clock_timestamp()) returning * into result;
  elsif p_expected=0 then
    insert into public.operation_state(namespace,key,payload,company_id) values(p_namespace,p_key,p_payload,p_company_id)
    on conflict do nothing returning * into result;
  else
    update public.operation_state set payload=p_payload,company_id=p_company_id,revision=revision+1,
      updated_at=extract(epoch from clock_timestamp())
      where namespace=p_namespace and key=p_key and revision=p_expected returning * into result;
  end if;
  if result.key is null then return null; end if;
  return to_jsonb(result);
end; $$;
revoke all on function public.put_operation_state(text,text,jsonb,text,bigint) from public,anon,authenticated;
grant execute on function public.put_operation_state(text,text,jsonb,text,bigint) to service_role;

create or replace function public.charge_intake_once(p_user_id bigint,p_receipt text)
returns boolean language plpgsql security invoker set search_path='' as $$
declare receipt_user bigint; remaining integer;
begin
  -- Lock the user before checking receipts, so concurrent retries cannot double debit.
  select quota_remaining into remaining from public.users where id=p_user_id for update;
  if not found then return false; end if;
  select user_id into receipt_user from public.intake_receipts where receipt=p_receipt;
  if found then return receipt_user=p_user_id; end if;
  if remaining<=0 then return false; end if;
  insert into public.intake_receipts values(p_receipt,p_user_id);
  update public.users set quota_remaining=quota_remaining-1 where id=p_user_id;
  return true;
end; $$;
revoke all on function public.charge_intake_once(bigint,text) from public,anon,authenticated;
grant execute on function public.charge_intake_once(bigint,text) to service_role;
