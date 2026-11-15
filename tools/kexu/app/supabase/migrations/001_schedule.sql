-- 在 Supabase SQL Editor 执行。客户端仅使用 anon/publishable key，禁止使用 service_role。
create table if not exists public.schedule_records (
  user_id uuid not null references auth.users(id) on delete cascade,
  id text not null check (length(id) between 1 and 100),
  kind text not null check (kind in ('semester','course','rule','adjustment')),
  payload jsonb,
  revision bigint not null default 1 check (revision > 0),
  updated_at timestamptz not null default now(),
  primary key (user_id,id),
  check (payload is null or (jsonb_typeof(payload) = 'object' and payload->>'id' = id)),
  check (payload is null or octet_length(payload::text) < 65536)
);
alter table public.schedule_records enable row level security;
revoke all on public.schedule_records from anon, authenticated;
grant select on public.schedule_records to authenticated;
drop policy if exists own_schedule on public.schedule_records;
create policy own_schedule on public.schedule_records for select to authenticated using ((select auth.uid()) = user_id);

create or replace function public.write_schedule_record(p_id text, p_kind text, p_payload jsonb, p_expected_revision bigint)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare r public.schedule_records; owner uuid := auth.uid();
begin
  if owner is null then raise exception 'Authentication required'; end if;
  if p_payload = 'null'::jsonb then p_payload := null; end if;
  if p_expected_revision < 0 then raise exception 'Invalid revision'; end if;
  if p_payload is not null and p_payload->>'id' is distinct from p_id then raise exception 'ID mismatch'; end if;
  -- 同一用户记录串行 CAS，锁范围不跨用户，不接受客户端提交的 user_id。
  perform pg_advisory_xact_lock(hashtextextended(owner::text || ':' || p_id, 0));
  select * into r from public.schedule_records where user_id = owner and id = p_id for update;
  if found then
    if r.revision <> p_expected_revision then
      return jsonb_build_object('ok',false,'record',to_jsonb(r) - 'user_id');
    end if;
    if r.kind <> p_kind then raise exception 'Record kind is immutable'; end if;
    update public.schedule_records set payload = p_payload, revision = revision + 1, updated_at = now()
      where user_id = owner and id = p_id returning * into r;
  else
    if p_expected_revision <> 0 then raise exception 'Remote record missing; export backup before retrying'; end if;
    insert into public.schedule_records(user_id,id,kind,payload) values(owner,p_id,p_kind,p_payload) returning * into r;
  end if;
  return jsonb_build_object('ok',true,'record',to_jsonb(r) - 'user_id');
end $$;
revoke all on function public.write_schedule_record(text,text,jsonb,bigint) from public, anon;
grant execute on function public.write_schedule_record(text,text,jsonb,bigint) to authenticated;
