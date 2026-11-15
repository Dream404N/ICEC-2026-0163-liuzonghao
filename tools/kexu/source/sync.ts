import { createClient, type SupabaseClient, type User } from '@supabase/supabase-js';
import { acknowledge, mergeCloudSnapshot, mergeRemote } from './state';
import { getState, updateStore, subscribe } from './store';
import { validateRemote } from './validation';
import type { Entry, RemoteRecord } from '../domain/types';

let client: SupabaseClient | null = null;
let user: User | null = null;
let running = false;
let activeAccount = '';
let timer: ReturnType<typeof setTimeout>;
const watchers = new Set<() => void>();
let authError = '';
export const cloudConfigured = () => !!import.meta.env.VITE_SUPABASE_URL && !!import.meta.env.VITE_SUPABASE_ANON_KEY;
export const authSnapshot = () => ({ user, running, error: authError, configured: cloudConfigured() });
export function watchAuth(fn: () => void) { watchers.add(fn); return () => { watchers.delete(fn); }; }
const emit = () => watchers.forEach(fn => fn());
export function cloud() {
  if (!cloudConfigured()) throw new Error('请先按 README 配置 Supabase，再重新构建应用');
  if (!client) client = createClient(import.meta.env.VITE_SUPABASE_URL, import.meta.env.VITE_SUPABASE_ANON_KEY);
  return client;
}
export async function signIn(email: string, password: string) {
  const { error } = await cloud().auth.signInWithPassword({ email, password }); if (error) throw error;
}
export async function signUp(email: string, password: string) {
  const { data, error } = await cloud().auth.signUp({ email, password }); if (error) throw error;
  return !data.session;
}
export async function signOut() { if (running) throw new Error('同步中，请稍后退出'); const { error } = await cloud().auth.signOut(); if (error) throw error; }
export async function initSync() {
  if (!cloudConfigured()) return;
  const c = cloud();
  const { data, error } = await c.auth.getSession();
  if (error) authError = error.message;
  user = data.session?.user ?? null; emit();
  c.auth.onAuthStateChange((_event, session) => { user = session?.user ?? null; pendingFingerprint = ''; emit(); queueSync(); if (user) setTimeout(() => { void syncNow(); }, 0); });
  subscribe(queueSync);
  window.addEventListener('online', () => { pendingFingerprint = ''; void syncNow(); });
  window.setInterval(() => { if (user && navigator.onLine) void syncNow(); }, 60000);
  queueSync();
  if (user) setTimeout(() => { void syncNow(); }, 0);
}
let pendingFingerprint = '';
function queueSync() {
  const dirty = Object.values(getState().entries).filter(e => e.dirty && !e.conflict);
  const fingerprint = JSON.stringify(dirty.map(e => [e.id, e.value, e.rev]));
  if (fingerprint === pendingFingerprint) return;
  pendingFingerprint = fingerprint;
  clearTimeout(timer);
  if (user && dirty.length) timer = setTimeout(() => { void syncNow(); }, 1200);
}
export async function syncNow() {
  if (running || !user || !navigator.onLine) return;
  const account = user.id;
  const state = getState();
  if (state.ownerId && state.ownerId !== account) {
    authError = '本地数据属于其他账号。请先导出备份并在“账号数据”中清空本地数据，再连接新账号。'; emit(); return;
  }
  running = true; activeAccount = account; authError = ''; emit();
  try {
    if (!state.ownerId) updateStore(s => ({ ...s, ownerId: account }));
    // 全量分页拉取包含墓碑的版本，不能仅依赖易漏边界的客户端时间游标。
    const remote: RemoteRecord[] = [];
    for (let offset = 0; ; offset += 500) {
      const { data, error } = await cloud().from('schedule_records').select('id,kind,payload,revision,updated_at').eq('user_id', account).order('id').range(offset, offset + 499);
      if (error) throw error;
      for (const row of data ?? []) { validateRemote(row); remote.push(row); }
      if (!data || data.length < 500) break;
    }
    if (activeAccount !== account || user?.id !== account) return;
    updateStore(s => mergeCloudSnapshot(s, remote));
    const priority = { semester: 0, course: 1, rule: 2, adjustment: 3 };
    const pending = Object.values(getState().entries).filter(e => e.dirty && !e.conflict).sort((a, b) => {
      // 创建先父后子，删除先子后父，避免拉取时出现引用已删除父记录的短暂状态。
      if ((a.value === null) !== (b.value === null)) return a.value === null ? 1 : -1;
      return a.value === null ? priority[b.kind] - priority[a.kind] : priority[a.kind] - priority[b.kind];
    });
    for (const sent of pending) {
      if (user?.id !== account) return;
      await pushOne(sent);
    }
    updateStore(s => ({ ...s, lastSync: new Date().toISOString(), syncError: '' }));
  } catch (e) { updateStore(s => ({ ...s, syncError: e instanceof Error ? e.message : String(e) })); }
  finally { running = false; emit(); }
}
async function pushOne(sent: Entry) {
  const { data, error } = await cloud().rpc('write_schedule_record', { p_id: sent.id, p_kind: sent.kind, p_payload: sent.value, p_expected_revision: sent.rev });
  if (error) throw error;
  if (!data || typeof data.ok !== 'boolean') throw new Error('同步服务返回格式错误');
  const record: unknown = data.record; validateRemote(record);
  if (data.ok) updateStore(s => acknowledge(s, sent, record));
  else updateStore(s => mergeRemote(s, [record]));
}
