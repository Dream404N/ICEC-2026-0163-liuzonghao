import type { AppState, Entity, Kind, RemoteRecord } from '../domain/types';
import { entities } from '../domain/types';
import { isDate, validTime, weekday } from '../domain/dates';
import { validateRule } from '../domain/schedule';

const obj = (x: unknown): x is Record<string, unknown> => !!x && typeof x === 'object' && !Array.isArray(x);
const str = (x: unknown): x is string => typeof x === 'string' && x.length <= 5000;
const id = (x: unknown): x is string => str(x) && /^[a-zA-Z0-9_-]{1,100}$/.test(x);
const leads = (x: unknown): x is number[] => Array.isArray(x) && x.length <= 10 && x.every(n => Number.isInteger(n) && n >= 0 && n <= 1440);
export function validateEntity(kind: Kind, value: unknown): asserts value is Entity {
  if (!obj(value) || !id(value.id)) throw new Error('记录 ID 无效');
  const text = (...keys: string[]) => keys.every(k => str(value[k]));
  if (kind === 'semester') {
    if (!text('name', 'firstMonday') || !value.name || String(value.name).length > 200 || typeof value.totalWeeks !== 'number' || !Number.isInteger(value.totalWeeks) || value.totalWeeks < 1 || value.totalWeeks > 60 || typeof value.archived !== 'boolean') throw new Error('学期字段无效');
    if (value.firstMonday !== '' && (!isDate(value.firstMonday as string) || weekday(value.firstMonday as string) !== 1)) throw new Error('第一周起始日期必须是周一');
    if (!Array.isArray(value.periods) || value.periods.length < 1 || value.periods.length > 20 || !value.periods.every(p => obj(p) && id(p.id) && str(p.name) && typeof p.start === 'string' && typeof p.end === 'string' && validTime(p.start) && validTime(p.end) && p.start < p.end)) throw new Error('作息时间无效');
  } else if (kind === 'course') {
    if (!id(value.semesterId) || !text('name', 'teacher', 'room', 'notes', 'color') || !value.name || ['name', 'teacher', 'room'].some(k => String(value[k]).length > 200) || !/^#[0-9a-f]{6}$/i.test(value.color as string) || typeof value.muted !== 'boolean' || typeof value.needsReview !== 'boolean' || (value.reminders !== null && !leads(value.reminders))) throw new Error('课程字段无效（名称、教师、教室最多 200 字）');
  } else if (kind === 'rule') {
    if (!id(value.courseId) || !text('start', 'end', 'room', 'teacher') || !Array.isArray(value.weeks) || value.weeks.length > 60) throw new Error('排课规则无效');
    const errors = validateRule(value as unknown as import('../domain/types').Rule, 60);
    if (errors.length) throw new Error(errors.join('；'));
  } else if (kind === 'adjustment') {
    if (!id(value.courseId) || !(value.ruleId === '' || id(value.ruleId)) || !text('originalDate', 'date', 'start', 'end', 'room', 'teacher', 'note') || !['cancel', 'change', 'extra'].includes(value.kind as string) || !isDate(value.originalDate as string) || !isDate(value.date as string) || !validTime(value.start as string) || !validTime(value.end as string) || (value.start as string) >= (value.end as string)) throw new Error('临时调整字段无效');
  } else throw new Error('未知记录类型');
}
export function validateRemote(value: unknown): asserts value is RemoteRecord {
  if (!obj(value) || !id(value.id) || !['semester', 'course', 'rule', 'adjustment'].includes(value.kind as string) || !Number.isSafeInteger(value.revision) || Number(value.revision) < 1 || !str(value.updated_at)) throw new Error('云端记录格式错误');
  if (value.payload !== null) { validateEntity(value.kind as Kind, value.payload); if (value.payload.id !== value.id) throw new Error('云端记录 ID 不匹配'); }
}
export function validateState(value: unknown): asserts value is AppState {
  if (!obj(value) || value.schemaVersion !== 1 || !obj(value.entries) || !str(value.selectedSemesterId) || !obj(value.device) || typeof value.device.remindersEnabled !== 'boolean' || typeof value.device.sound !== 'boolean' || typeof value.device.autoStart !== 'boolean' || !leads(value.device.leads) || !(value.ownerId === null || str(value.ownerId)) || !(value.lastSync === null || str(value.lastSync)) || !str(value.syncError)) throw new Error('备份格式或版本不支持');
  const records = Object.entries(value.entries);
  if (records.length > 50000) throw new Error('记录过多');
  for (const [key, entry] of records) {
    if (!obj(entry) || entry.id !== key || !id(key) || !['semester', 'course', 'rule', 'adjustment'].includes(entry.kind as string) || !Number.isSafeInteger(entry.rev) || Number(entry.rev) < 0 || typeof entry.dirty !== 'boolean' || !str(entry.modifiedAt)) throw new Error('备份记录格式错误');
    if (entry.value !== null) { validateEntity(entry.kind as Kind, entry.value); if (entry.value.id !== key) throw new Error('记录 ID 不匹配'); }
    if (entry.conflict !== undefined) validateRemote(entry.conflict);
  }
  const state = value as unknown as AppState;
  const semesters = new Map(entities(state, 'semester').map(s => [s.id, s]));
  const courses = new Map(entities(state, 'course').map(c => [c.id, c]));
  const rules = new Map(entities(state, 'rule').map(r => [r.id, r]));
  if (!semesters.has(state.selectedSemesterId)) throw new Error('当前学期不存在');
  for (const c of courses.values()) if (!semesters.has(c.semesterId)) throw new Error('课程引用的学期不存在');
  for (const r of rules.values()) {
    const c = courses.get(r.courseId);
    if (!c || validateRule(r, semesters.get(c.semesterId)!.totalWeeks).length) throw new Error('排课引用或周次超出学期范围');
  }
  const adjusted = new Set<string>();
  for (const a of entities(state, 'adjustment')) {
    if (!courses.has(a.courseId) || (a.kind !== 'extra' && rules.get(a.ruleId)?.courseId !== a.courseId)) throw new Error('调整引用的课程或规则不存在');
    if (a.kind !== 'extra') { const k = a.ruleId + ':' + a.originalDate; if (adjusted.has(k)) throw new Error('同一次课程有重复调整'); adjusted.add(k); }
  }
}
export function restoreBackup(raw: string, current: AppState): AppState {
  if (raw.length > 20_000_000) throw new Error('备份文件不能超过 20 MB');
  const backup: unknown = JSON.parse(raw); validateState(backup);
  let result = { ...backup, entries: { ...backup.entries }, ownerId: current.ownerId, device: current.device, lastSync: current.lastSync, syncError: '' };
  // 恢复也是一次可同步编辑，保留当前云端版本，缺失记录产生墓碑。
  for (const [key, old] of Object.entries(current.entries)) if (!result.entries[key]) result.entries[key] = { ...old, value: null, dirty: true, modifiedAt: new Date().toISOString() };
  for (const [key, e] of Object.entries(backup.entries)) result.entries[key] = { ...e, rev: current.entries[key]?.rev ?? 0, dirty: true, conflict: undefined, modifiedAt: new Date().toISOString() };
  validateState(result); return result;
}
