import type { AppState, Lesson, Semester, Rule, Reminder } from './types';
import { entities } from './types';
import { addDays, teachingWeek, weekday, instant, validTime, isDate } from './dates';

export function lessonsBetween(state: AppState, semester: Semester, from: string, to: string): Lesson[] {
  if (!isDate(semester.firstMonday)) return [];
  const courses = new Map(entities(state, 'course').filter(c => c.semesterId === semester.id).map(c => [c.id, c]));
  const adjustments = entities(state, 'adjustment');
  const result: Lesson[] = [];
  for (const rule of entities(state, 'rule')) {
    const course = courses.get(rule.courseId);
    if (!course) continue;
    for (const week of rule.weeks) {
      const date = addDays(semester.firstMonday, (week - 1) * 7 + rule.weekday - 1);
      const change = adjustments.find(a => a.ruleId === rule.id && a.originalDate === date && a.kind !== 'extra');
      if (change) continue;
      if (date >= from && date <= to) result.push({ key: `${rule.id}:${date}`, course, ruleId: rule.id, originalDate: date, date, start: rule.start, end: rule.end, room: rule.room || course.room, teacher: rule.teacher || course.teacher, adjusted: false, note: '' });
    }
  }
  for (const a of adjustments) {
    const course = courses.get(a.courseId);
    if (!course || a.kind === 'cancel' || a.date < from || a.date > to) continue;
    result.push({ key: `adjustment:${a.id}`, course, ruleId: a.ruleId, originalDate: a.originalDate, date: a.date, start: a.start, end: a.end, room: a.room, teacher: a.teacher, adjusted: true, note: a.note });
  }
  return result.sort((a, b) => `${a.date} ${a.start}`.localeCompare(`${b.date} ${b.start}`));
}
export function validateRule(rule: Rule, total: number): string[] {
  const errors: string[] = [];
  if (!Number.isInteger(rule.weekday) || rule.weekday < 1 || rule.weekday > 7) errors.push('星期必须在 1-7 之间');
  if (!validTime(rule.start) || !validTime(rule.end) || rule.start >= rule.end) errors.push('结束时间必须晚于开始时间，且不能跨日');
  if (!rule.weeks.length || rule.weeks.some(w => !Number.isInteger(w) || w < 1 || w > total) || new Set(rule.weeks).size !== rule.weeks.length) errors.push(`周次必须是 1-${total} 内不重复的整数`);
  return errors;
}
export function overlaps(a: Pick<Lesson, 'date' | 'start' | 'end'>, b: Pick<Lesson, 'date' | 'start' | 'end'>): boolean {
  return a.date === b.date && a.start < b.end && b.start < a.end;
}
export function conflicts(lessons: Lesson[]): [Lesson, Lesson][] {
  const result: [Lesson, Lesson][] = [];
  for (let i = 0; i < lessons.length; i++) for (let j = i + 1; j < lessons.length; j++) if (overlaps(lessons[i], lessons[j])) result.push([lessons[i], lessons[j]]);
  return result;
}
export function stableId(key: string): number {
  let h = 2166136261;
  for (const c of key) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return (h >>> 0) % 2000000000 + 1;
}
export function planReminders(state: AppState, now = new Date(), days = 30): Reminder[] {
  if (!state.device.remindersEnabled) return [];
  const from = new Date(now.getTime() + 8 * 3600000).toISOString().slice(0, 10);
  const reminders: Reminder[] = [];
  const used = new Set<number>();
  for (const sem of entities(state, 'semester').filter(s => !s.archived)) {
    for (const lesson of lessonsBetween(state, sem, from, addDays(from, days))) {
      if (lesson.course.muted || lesson.course.needsReview) continue;
      for (const lead of [...new Set(lesson.course.reminders ?? state.device.leads)]) {
        const at = new Date(instant(lesson.date, lesson.start).getTime() - lead * 60000);
        if (at <= now) continue;
        const key = `${lesson.key}:${lead}`;
        let id = stableId(key);
        while (used.has(id)) id = id === 2000000000 ? 1 : id + 1;
        used.add(id);
        reminders.push({ id, key, title: `${lead === 0 ? '现在上课' : `${lead} 分钟后上课`} · ${lesson.course.name}`, body: `${lesson.start}–${lesson.end} · ${lesson.room || '教室待定'}${lesson.teacher ? ' · ' + lesson.teacher : ''}`, at: at.toISOString(), lessonAt: instant(lesson.date, lesson.start).toISOString() });
      }
    }
  }
  return reminders.sort((a, b) => a.at.localeCompare(b.at));
}
export function weekStatus(semester: Semester, date: string): string {
  if (!semester.firstMonday) return '请设置开学日期';
  const w = teachingWeek(date, semester.firstMonday);
  return w < 1 ? '学期尚未开始' : w > semester.totalWeeks ? '本学期已结束' : `第 ${w} 周 · ${w % 2 ? '单周' : '双周'}`;
}
export function ruleDate(sem: Semester, rule: Rule, date: string): boolean {
  return rule.weekday === weekday(date) && rule.weeks.includes(teachingWeek(date, sem.firstMonday));
}
