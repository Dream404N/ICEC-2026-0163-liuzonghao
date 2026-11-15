import { describe, it, expect } from 'vitest';
import { initialState } from '../src/domain/seed';
import { entities } from '../src/domain/types';
import type { AppState, Adjustment, RemoteRecord } from '../src/domain/types';
import { addDays, teachingWeek, chinaDate, weekday } from '../src/domain/dates';
import { parseWeeks, formatWeeks } from '../src/domain/weeks';
import { conflicts, lessonsBetween, planReminders } from '../src/domain/schedule';
import { acknowledge, applyEdits, deleteCourse, mergeCloudSnapshot, mergeRemote, resolveConflict } from '../src/data/state';
import { restoreBackup, validateState } from '../src/data/validation';
import { commitImport, csvRows, encodeCsv, encodeXlsx, HEADERS, previewImport, readTable } from '../src/data/tables';

function ready(): AppState {
  let s = initialState();
  const sem = entities(s, 'semester')[0]; s = applyEdits(s, 'semester', [{ ...sem, firstMonday: '2026-08-31' }]);
  return applyEdits(s, 'course', entities(s, 'course').map(c => ({ ...c, needsReview: false })));
}
describe('教学周与周次', () => {
  it('解析连续、不连续、单双周与中文分隔', () => {
    expect(parseWeeks('3-5，16-18')).toEqual([3, 4, 5, 16, 17, 18]);
    expect(parseWeeks('1-8（单周）')).toEqual([1, 3, 5, 7]); expect(parseWeeks('双周', 6)).toEqual([2, 4, 6]);
    expect(parseWeeks('每周', 3)).toEqual([1, 2, 3]); expect(formatWeeks([5, 3, 4, 16, 18, 17, 3])).toBe('3-5,16-18');
  });
  it.each(['', '0', '19', '8-3', '3-a', '1,,2', '单双周'])('拒绝非法周次 %s', text => { expect(() => parseWeeks(text, 18)).toThrow(); });
  it('周日不提前切周，学期前与学期后可识别', () => {
    expect(teachingWeek('2026-09-06', '2026-08-31')).toBe(1); expect(teachingWeek('2026-09-07', '2026-08-31')).toBe(2);
    expect(teachingWeek('2026-08-30', '2026-08-31')).toBe(0); expect(weekday('2026-08-31')).toBe(1);
    expect(chinaDate(new Date('2026-11-15T16:01:00Z'))).toBe('2026-11-16'); expect(addDays('2026-12-31', 1)).toBe('2027-01-01');
  });
});
describe('排课与本地提醒', () => {
  it('初始截图不猜开学日期，不生成提醒', () => { const s = initialState(); validateState(s); expect(planReminders(s)).toEqual([]); });
  it('相同时间按周切换课程，跨两大节仅一次', () => {
    const s = ready(), sem = entities(s, 'semester')[0];
    const monday = lessonsBetween(s, sem, '2026-09-14', '2026-09-14');
    expect(monday.filter(l => l.course.id === 'drawing')).toHaveLength(1); expect(monday[0].end).toBe('11:40');
    const w8 = addDays(sem.firstMonday, 7 * 7 + 3); const thursday = lessonsBetween(s, sem, w8, w8);
    expect(thursday.some(l => l.course.id === 'politics')).toBe(true); expect(thursday.some(l => l.course.id === 'ethics')).toBe(false);
    expect(conflicts(lessonsBetween(s, sem, sem.firstMonday, addDays(sem.firstMonday, 125)))).toEqual([]);
  });
  it('停课只取消目标日期，调课跨周只出现一次', () => {
    let s = ready(); const sem = entities(s, 'semester')[0]; const lesson = lessonsBetween(s, sem, '2026-09-14', '2026-09-14')[0];
    const a: Adjustment = { id: 'test-adjust', courseId: lesson.course.id, ruleId: lesson.ruleId, originalDate: lesson.date, kind: 'cancel', date: lesson.date, start: lesson.start, end: lesson.end, room: lesson.room, teacher: lesson.teacher, note: '' };
    s = applyEdits(s, 'adjustment', [a]); expect(lessonsBetween(s, sem, lesson.date, lesson.date).some(l => l.course.id === lesson.course.id)).toBe(false);
    expect(lessonsBetween(s, sem, '2026-09-21', '2026-09-21').some(l => l.course.id === lesson.course.id)).toBe(true);
    s = applyEdits(s, 'adjustment', [{ ...a, kind: 'change', date: '2026-09-20', room: '新教室' }]);
    const changed = lessonsBetween(s, sem, '2026-09-20', '2026-09-20'); expect(changed).toHaveLength(1); expect(changed[0].room).toBe('新教室');
    validateState(s);
  });
  it('提前时间去重，静音/校对/归档/删除取消提醒', () => {
    let s = ready(); const now = new Date('2026-09-14T00:00:00Z');
    s.device.leads = [15, 15, 5]; let reminders = planReminders(s, now, 1);
    expect(new Set(reminders.map(r => r.id)).size).toBe(reminders.length);
    expect(reminders.filter(r => r.key.startsWith('drawing-rule-0:2026-09-14'))).toHaveLength(2);
    expect(reminders[0].at).toBe('2026-09-14T00:25:00.000Z');
    const c = entities(s, 'course').find(c => c.id === 'drawing')!;
    for (const patch of [{ muted: true }, { needsReview: true }]) { const n = applyEdits(s, 'course', [{ ...c, ...patch }]); expect(planReminders(n, now, 1).some(r => r.key.startsWith('drawing'))).toBe(false); }
    s = deleteCourse(s, c.id); expect(planReminders(s, now, 1).some(r => r.key.startsWith('drawing'))).toBe(false);
    const sem = entities(s, 'semester')[0]; s = applyEdits(s, 'semester', [{ ...sem, archived: true }]); expect(planReminders(s, now)).toEqual([]);
  });
});
describe('表格与备份', () => {
  it('真实 XLSX 写入和读取保持中文、周次与文本时间', async () => {
    const rows = [HEADERS, ['新课程', '6', '09:00', '10:00', '3-13,16-18', '实验楼 301', '教师', '中文备注']];
    const blob = await encodeXlsx(rows); const file = new File([blob], '课程.xlsx');
    expect(await readTable(file)).toEqual(rows);
  }, 30000);
  it('另一学期的同名同时间课程不应被当作本学期重复', () => {
    let s = ready(); const old = entities(s, 'semester')[0];
    const sem = { ...old, id: 'new-semester', name: '新学期' }; s = applyEdits(s, 'semester', [sem]);
    const p = previewImport([HEADERS, ['工程数学', '1', '13:30', '14:50', '3-13,16-18', '教学楼 525', '汪志忠']], s, sem);
    expect(p[0].duplicate).toBe(false); expect(p[0].errors).toEqual([]);
  });
  it('CSV 保留引号、逗号和换行，防止公式注入', () => {
    const rows = [['课程名称', '备注'], ['课,程', '说"你好"\n第二行']]; expect(csvRows(encodeCsv(rows))).toEqual(rows);
    expect(encodeCsv([['=HYPERLINK("url")']])).toContain("'=HYPERLINK"); expect(() => csvRows('"abc')).toThrow();
  });
  it('追加预览检查重复、非法时间和实际冲突', () => {
    const s = ready(), sem = entities(s, 'semester')[0];
    const rows = [HEADERS, ['机械制图与计算机辅助设计', '1', '08:40', '11:40', '3-13,16-18', '天工楼 361', '彭灵勇', ''], ['冲突课程', '1', '09:00', '10:00', '3'], ['新课程', '6', '09:00', '10:00', '3'], ['坏时间', '6', '10:00', '09:00', '3']];
    const p = previewImport(rows, s, sem); expect(p[0].duplicate).toBe(true); expect(p[1].errors.join()).toContain('冲突'); expect(p[2].errors).toEqual([]); expect(p[3].errors).not.toHaveLength(0);
    expect(() => commitImport(s, sem, p, false)).toThrow();
    const n = commitImport(s, sem, [p[2]], false); expect(entities(n, 'course').some(c => c.name === '新课程')).toBe(true);
  });
  it('无开学日期也检测规则冲突，拒绝错误表头', () => {
    const s = initialState(), sem = entities(s, 'semester')[0];
    expect(previewImport([HEADERS, ['冲突课程', '1', '09:00', '10:00', '3']], s, sem)[0].errors.join()).toContain('冲突');
    expect(() => previewImport([['课程']], s, sem)).toThrow();
  });
  it('完整恢复保留当前账号/设备，生成缺失记录墓碑', () => {
    const backup = initialState(); let current = ready(); current.ownerId = 'user-a'; current.device.sound = false;
    const extra = { ...entities(current, 'course')[0], id: 'extra-course', name: '备份外课程' }; current = applyEdits(current, 'course', [extra]);
    const result = restoreBackup(JSON.stringify(backup), current); validateState(result);
    expect(result.ownerId).toBe('user-a'); expect(result.device.sound).toBe(false); expect(result.entries[extra.id].value).toBeNull(); expect(result.entries[extra.id].dirty).toBe(true);
    const broken = structuredClone(backup); (broken.device.leads as unknown[]) = ['坏值']; expect(() => restoreBackup(JSON.stringify(broken), current)).toThrow();
    expect(() => restoreBackup('{', current)).toThrow();
  });
});
describe('同步 CAS 合并与冲突', () => {
  it('首次连接已有云课表采用云数据，不把未编辑内置课表当冲突', () => {
    const s = initialState(); const sem = { ...entities(s, 'semester')[0], id: 'cloud-semester', firstMonday: '2026-08-31' };
    const next = mergeCloudSnapshot(s, [{ id: sem.id, kind: 'semester', payload: sem, revision: 1, updated_at: '2026-11-15T00:00:00Z' }]);
    expect(entities(next, 'course')).toHaveLength(0); expect(next.selectedSemesterId).toBe(sem.id); expect(Object.values(next.entries).some(e => e.conflict)).toBe(false); validateState(next);
    const emptyCloud = mergeCloudSnapshot(s, []); expect(Object.values(emptyCloud.entries).every(e => e.dirty)).toBe(true);
  });
  it('新设备登录前编辑的课程及所属学期保留并待上传', () => {
    let s = initialState(); const course = entities(s, 'course')[0]; s = applyEdits(s, 'course', [{ ...course, notes: '我的编辑' }]);
    const sem = { ...entities(s, 'semester')[0], id: 'cloud-semester' };
    const next = mergeCloudSnapshot(s, [{ id: sem.id, kind: 'semester', payload: sem, revision: 1, updated_at: '2026-11-15T00:00:00Z' }]);
    expect(entities(next, 'course').find(c => c.id === course.id)?.notes).toBe('我的编辑'); expect(next.entries[course.semesterId].dirty).toBe(true); expect(entities(next, 'rule').filter(r => r.courseId === course.id)).toHaveLength(1); validateState(next);
  });
  it('并发修改保留双方，明确选择后才能推送', () => {
    let s = ready(); const local = s.entries.math; local.rev = 2;
    const remote: RemoteRecord = { id: 'math', kind: 'course', payload: { ...entities(s, 'course').find(c => c.id === 'math')!, name: '远端数学' }, revision: 3, updated_at: '2026-11-15T00:00:00Z' };
    s = mergeRemote(s, [remote]); expect(s.entries.math.value).toEqual(local.value); expect(s.entries.math.conflict?.payload).toEqual(remote.payload);
    const localChoice = resolveConflict(s, 'math', 'local'); expect(localChoice.entries.math.rev).toBe(3); expect(localChoice.entries.math.dirty).toBe(true);
    const remoteChoice = resolveConflict(s, 'math', 'remote'); expect(remoteChoice.entries.math.value).toEqual(remote.payload); expect(remoteChoice.entries.math.dirty).toBe(false);
  });
  it('上传期间继续编辑不会被上传确认覆盖', () => {
    let s = ready(); const sent = structuredClone(s.entries.math); const value = { ...entities(s, 'course').find(c => c.id === 'math')!, name: '上传时的新编辑' };
    s = applyEdits(s, 'course', [value]); const ack: RemoteRecord = { id: sent.id, kind: sent.kind, payload: sent.value, revision: 1, updated_at: new Date().toISOString() };
    s = acknowledge(s, sent, ack); expect(s.entries.math.dirty).toBe(true); expect(s.entries.math.value).toEqual(value); expect(s.entries.math.rev).toBe(1);
  });
  it('远端删除同步为墓碑，不复活课程', () => {
    let s = ready(); for (const entry of Object.values(s.entries)) entry.dirty = false;
    s = mergeRemote(s, [{ id: 'math', kind: 'course', payload: null, revision: 3, updated_at: '2026-11-15T00:00:00Z' }]);
    expect(s.entries.math.value).toBeNull(); expect(entities(s, 'course').some(c => c.id === 'math')).toBe(false);
  });
  it('远端删除课程遇到本地改排课时保留冲突，确认删除才级联清理', () => {
    let s = ready(); for (const entry of Object.values(s.entries)) entry.dirty = false;
    const rule = entities(s, 'rule').find(r => r.courseId === 'math')!;
    s = applyEdits(s, 'rule', [{ ...rule, room: '本地新教室' }]);
    s = mergeRemote(s, [{ id: 'math', kind: 'course', payload: null, revision: 2, updated_at: '2026-11-15T00:00:00Z' }]);
    expect(s.entries.math.conflict?.payload).toBeNull(); expect(s.entries.math.value).not.toBeNull();
    s = resolveConflict(s, 'math', 'remote'); expect(s.entries.math.value).toBeNull();
    expect(entities(s, 'rule').some(r => r.courseId === 'math')).toBe(false); validateState(s);
  });
});
