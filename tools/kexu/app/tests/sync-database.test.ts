import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { PGlite } from '@electric-sql/pglite';
import { readFile } from 'node:fs/promises';
const db = new PGlite();
const A = '11111111-1111-4111-8111-111111111111';
const B = '22222222-2222-4222-8222-222222222222';
beforeAll(async () => {
  await db.exec(`create schema auth; create role anon; create role authenticated;
    create table auth.users (id uuid primary key);
    create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub', true),'')::uuid $$;
    grant usage on schema auth to authenticated, anon;
    grant execute on function auth.uid() to authenticated, anon;
    insert into auth.users values ('${A}'),('${B}');`);
  await db.exec(await readFile('supabase/migrations/001_schedule.sql', 'utf8'));
}, 30000);
afterAll(async () => { await db.close(); });
async function asUser(id: string) { await db.exec(`reset role; select set_config('request.jwt.claim.sub','${id}',false); set role authenticated;`); }
async function write(id: string, payload: unknown, revision: number) {
  const result = await db.query<{ result: { ok: boolean; record: { revision: number; payload: unknown } } }>(`select public.write_schedule_record($1,'course',$2::jsonb,$3) as result`, [id, JSON.stringify(payload), revision]);
  return result.rows[0].result;
}
describe('真实 PostgreSQL 引擎中的云同步数据库约束', () => {
  it('写入、版本递增、旧版本拒绝、删除保留墓碑', async () => {
    await asUser(A);
    const first = await write('course-one', { id: 'course-one', name: '本地' }, 0); expect(first.ok).toBe(true); expect(first.record.revision).toBe(1);
    const second = await write('course-one', { id: 'course-one', name: '新版本' }, 1); expect(second.record.revision).toBe(2);
    const conflict = await write('course-one', { id: 'course-one', name: '旧客户端' }, 1); expect(conflict.ok).toBe(false); expect(conflict.record.payload).toEqual({ id: 'course-one', name: '新版本' });
    const tombstone = await write('course-one', null, 2); expect(tombstone.record.payload).toBeNull(); expect(tombstone.record.revision).toBe(3);
  });
  it('RLS 隔离账号，禁止客户端直接改表或伪造 ID', async () => {
    await asUser(B); const result = await db.query('select * from public.schedule_records'); expect(result.rows).toHaveLength(0);
    const own = await write('course-one', { id: 'course-one', name: '用户 B' }, 0); expect(own.record.revision).toBe(1);
    await expect(db.exec(`update public.schedule_records set revision=99`)).rejects.toThrow(/permission denied/);
    await expect(write('bad-id', { id: 'mismatch' }, 0)).rejects.toThrow(/ID mismatch/);
    await asUser(A); const original = await db.query<{ revision: number }>('select revision from public.schedule_records'); expect(Number(original.rows[0].revision)).toBe(3);
  });
  it('匿名角色无读写权限', async () => {
    await db.exec(`reset role; select set_config('request.jwt.claim.sub','',false); set role anon;`);
    await expect(db.query('select * from public.schedule_records')).rejects.toThrow(/permission denied/);
    await expect(write('anonymous', { id: 'anonymous' }, 0)).rejects.toThrow(/permission denied/);
  });
});
