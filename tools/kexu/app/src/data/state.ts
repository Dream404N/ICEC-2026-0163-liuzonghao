import type { AppState, Entity, Entry, Kind, RemoteRecord } from '../domain/types';
import { entities, uid, DEFAULT_PERIODS } from '../domain/types';
export function applyEdits(state: AppState, kind: Kind, values: Entity[], deletions: string[] = []): AppState {
  const entries = { ...state.entries };
  const at = new Date().toISOString();
  for (const value of values) {
    const old = entries[value.id];
    if (old && old.kind !== kind) throw new Error('记录类型不可变更');
    entries[value.id] = { ...old, id: value.id, kind, value, rev: old?.rev ?? 0, dirty: true, modifiedAt: at };
  }
  for (const id of deletions) if (entries[id]) entries[id] = { ...entries[id], value: null, rev: entries[id].conflict?.revision ?? entries[id].rev, dirty: true, conflict: undefined, modifiedAt: at };
  return { ...state, entries };
}
export function deleteCourse(state: AppState, id: string): AppState {
  return applyEdits(state, 'course', [], [id, ...entities(state, 'rule').filter(r => r.courseId === id).map(r => r.id), ...entities(state, 'adjustment').filter(a => a.courseId === id).map(a => a.id)]);
}
export function contentSignature(value: unknown): string {
  return JSON.stringify(value, (_key, v) => v && typeof v === 'object' && !Array.isArray(v) ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => a.localeCompare(b))) : v);
}
export function mergeCloudSnapshot(state: AppState, remote: RemoteRecord[]): AppState {
  const entries = { ...state.entries }; const ids = new Set(remote.map(r => r.id));
  const protectedIds = new Set(Object.values(entries).filter(e => e.dirty).map(e => e.id));
  for (let pass = 0; pass < 3; pass++) for (const e of Object.values(entries)) {
    if (e.value && 'courseId' in e.value && protectedIds.has(e.value.courseId) && !ids.has(e.value.courseId)) protectedIds.add(e.id);
    if (!protectedIds.has(e.id) || !e.value) continue;
    if ('semesterId' in e.value) protectedIds.add(e.value.semesterId);
    if ('courseId' in e.value) protectedIds.add(e.value.courseId);
    if ('ruleId' in e.value && e.value.ruleId) protectedIds.add(e.value.ruleId);
  }
  for (const e of Object.values(entries)) if (e.rev === 0 && !e.dirty && !ids.has(e.id)) {
    // 首次连接：空云端接收初始课表；已有云数据时，未编辑的内置样例让位于账号课表。
    if (!remote.length || protectedIds.has(e.id)) entries[e.id] = { ...e, dirty: true };
    else delete entries[e.id];
  }
  return mergeRemote({ ...state, entries }, remote);
}
export function mergeRemote(state: AppState, remote: RemoteRecord[]): AppState {
  const entries = { ...state.entries };
  for (const r of remote) {
    const local = entries[r.id];
    if (local?.dirty && r.revision !== local.rev && contentSignature(local.value) === contentSignature(r.payload)) {
      entries[r.id] = { id: r.id, kind: r.kind, value: r.payload, rev: r.revision, dirty: false, modifiedAt: r.updated_at }; continue;
    }
    if (local?.value && r.payload === null && r.revision !== local.rev) {
      const dirtyDescendant = Object.values(entries).some(e => e.dirty && e.value && (
        (r.kind === 'course' && 'courseId' in e.value && e.value.courseId === r.id) ||
        (r.kind === 'rule' && 'ruleId' in e.value && e.value.ruleId === r.id) ||
        (r.kind === 'semester' && 'semesterId' in e.value && e.value.semesterId === r.id)
      ));
      if (dirtyDescendant) { entries[r.id] = { ...local, dirty: true, conflict: r }; continue; }
    }
    if (local?.dirty) {
      if (r.revision !== local.rev) entries[r.id] = { ...local, conflict: r };
    } else if (!local || r.revision >= local.rev) {
      entries[r.id] = { id: r.id, kind: r.kind, value: r.payload, rev: r.revision, dirty: false, modifiedAt: r.updated_at };
    }
  }
  let next = { ...state, entries };
  if (!entries[next.selectedSemesterId]?.value) {
    let sem = entities(next, 'semester')[0];
    if (!sem) { sem = { id: uid(), name: '我的新学期', firstMonday: '', totalWeeks: 18, archived: false, periods: structuredClone(DEFAULT_PERIODS) }; next = applyEdits(next, 'semester', [sem]); }
    next.selectedSemesterId = sem.id;
  }
  return next;
}
export function acknowledge(state: AppState, sent: Entry, remote: RemoteRecord): AppState {
  const local = state.entries[sent.id];
  if (!local) return state;
  const unchanged = local.modifiedAt === sent.modifiedAt && JSON.stringify(local.value) === JSON.stringify(sent.value);
  return { ...state, entries: { ...state.entries, [sent.id]: { ...local, rev: remote.revision, dirty: !unchanged, conflict: undefined } } };
}
export function resolveConflict(state: AppState, id: string, choice: 'local' | 'remote'): AppState {
  const entry = state.entries[id]; const remote = entry?.conflict;
  if (!remote) return state;
  let next = { ...state, entries: { ...state.entries, [id]: choice === 'remote'
    ? { id, kind: remote.kind, value: remote.payload, rev: remote.revision, dirty: false, modifiedAt: remote.updated_at }
    : { ...entry, rev: remote.revision, dirty: true, modifiedAt: new Date().toISOString(), conflict: undefined } } };
  if (choice === 'remote' && remote.payload === null) {
    if (entry.kind === 'course') {
      const children = [...entities(next, 'rule'), ...entities(next, 'adjustment')].filter(r => r.courseId === id).map(r => r.id);
      next = applyEdits(next, 'rule', [], children);
    }
    if (entry.kind === 'rule') next = applyEdits(next, 'adjustment', [], entities(next, 'adjustment').filter(a => a.ruleId === id).map(a => a.id));
    if (entry.kind === 'semester') {
      for (const c of entities(next, 'course').filter(c => c.semesterId === id)) next = deleteCourse(next, c.id);
      let sem = entities(next, 'semester')[0];
      if (!sem) { sem = { id: uid(), name: '我的新学期', firstMonday: '', totalWeeks: 18, archived: false, periods: structuredClone(DEFAULT_PERIODS) }; next = applyEdits(next, 'semester', [sem]); }
      if (next.selectedSemesterId === id) next = { ...next, selectedSemesterId: sem.id };
    }
  }
  return next;
}
