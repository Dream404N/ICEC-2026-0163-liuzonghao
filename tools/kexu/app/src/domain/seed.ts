import { COLORS, DEFAULT_PERIODS } from './types';
import type { AppState, Entry, Course, Rule, Semester } from './types';
import { parseWeeks } from './weeks';

// 从用户提供的截图人工转录。不开猜测的学期起始日期，所有课程需确认后才提醒。
export function initialState(): AppState {
  const sem: Semester = { id: 'semester-2026-1', name: '2026–2027 学年 · 第一学期', firstMonday: '', totalWeeks: 18, archived: false, periods: DEFAULT_PERIODS.map(p => ({ ...p })) };
  const entries: Record<string, Entry> = {};
  const put = (kind: Entry['kind'], value: Entry['value']) => { if (value) entries[value.id] = { id: value.id, kind, value, rev: 0, dirty: false, modifiedAt: new Date().toISOString() }; };
  put('semester', sem);
  const add = (id: string, name: string, teacher: string, room: string, color: number, rows: [number, string, string, string, string?, string?][]) => {
    const course: Course = { id, semesterId: sem.id, name, teacher, room, color: COLORS[color], notes: '来自课表截图，请核对课程名称、教师、教室与周次后取消“待校对”。', reminders: null, muted: false, needsReview: true };
    put('course', course);
    rows.forEach(([weekday, start, end, weeks, roomOverride = '', teacherOverride = ''], i) => {
      const rule: Rule = { id: `${id}-rule-${i}`, courseId: id, weekday, start, end, weeks: parseWeeks(weeks, 18), room: roomOverride, teacher: teacherOverride };
      put('rule', rule);
    });
  };
  add('drawing', '机械制图与计算机辅助设计', '彭灵勇', '天工楼 361', 0, [[1, '08:40', '11:40', '3-13,16-18']]);
  add('math', '工程数学', '汪志忠', '教学楼 525', 1, [[1, '13:30', '14:50', '3-13,16-18'], [5, '10:20', '11:40', '3-13,16-18']]);
  add('ethics', '思想道德与法治', '张春香', '教学楼东 601', 2, [
    [1, '15:10', '16:30', '3,4-13,16-18'],
    [4, '10:20', '11:40', '3,4-7,12-13,16-18', '教学楼东 701'],
  ]);
  add('career', '职业生涯规划', '红辉', '教学楼 714', 3, [[2, '13:30', '14:50', '3-11']]);
  add('english', '大学英语', '刘鑫萍', '教学楼 621', 4, [[2, '15:10', '16:30', '3-13,16-18'], [4, '15:10', '16:30', '3-13,16-18']]);
  add('manufacture', '智能制造与数字化认知', '何睿卿', '天工楼 375', 5, [[3, '13:30', '14:50', '3-13,16-18']]);
  add('psychology', '大学生心理健康教育', '邓元元', '教学楼 917', 2, [[3, '15:10', '16:30', '3,6,9,12,17']]);
  add('politics', '形势与政策', '张春香', '教学楼东 701', 3, [[4, '10:20', '11:40', '8-9,11'], [4, '10:20', '11:40', '10', '', '文首文']]);
  add('sports', '体育', '查士君', '文体中心 204', 0, [[5, '13:30', '14:50', '3-13,16-18']]);
  return { schemaVersion: 1, entries, selectedSemesterId: sem.id, device: { remindersEnabled: true, sound: true, leads: [15], autoStart: false }, ownerId: null, lastSync: null, syncError: '' };
}
