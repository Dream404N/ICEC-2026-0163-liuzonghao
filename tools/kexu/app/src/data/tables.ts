import type { AppState, Course, Rule, Semester } from '../domain/types';
import { COLORS, uid, entities } from '../domain/types';
import { formatWeeks, parseWeeks } from '../domain/weeks';
import { validTime } from '../domain/dates';
import { applyEdits, deleteCourse } from './state';
import { conflicts, lessonsBetween } from '../domain/schedule';
import { addDays } from '../domain/dates';
import { validateEntity } from './validation';
export const HEADERS = ['课程名称', '星期', '开始时间', '结束时间', '上课周次', '教室', '教师', '备注'];
export interface ImportRow { line: number; values: string[]; errors: string[]; duplicate: boolean; course?: Course; rule?: Rule }
export function csvRows(raw: string): string[][] {
  const rows: string[][] = []; let row: string[] = []; let cell = ''; let quoted = false;
  raw = raw.replace(/^\uFEFF/, '');
  for (let i = 0; i < raw.length; i++) {
    const c = raw[i];
    if (c === '"') { if (quoted && raw[i + 1] === '"') { cell += '"'; i++; } else quoted = !quoted; }
    else if (c === ',' && !quoted) { row.push(cell); cell = ''; }
    else if ((c === '\n' || c === '\r') && !quoted) { if (c === '\r' && raw[i + 1] === '\n') i++; row.push(cell); rows.push(row); row = []; cell = ''; }
    else cell += c;
  }
  if (quoted) throw new Error('CSV 引号未闭合');
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows.filter(r => r.some(c => c.trim()));
}
function timeCell(v: unknown) {
  if (typeof v === 'number' && v >= 0 && v < 1) { const mins = Math.round(v * 1440); return `${String(Math.floor(mins / 60)).padStart(2, '0')}:${String(mins % 60).padStart(2, '0')}`; }
  if (v && typeof v === 'object' && 'text' in v) return String(v.text);
  return String(v ?? '').trim();
}
export async function readTable(file: File): Promise<string[][]> {
  if (file.size > 10_000_000) throw new Error('表格不能超过 10 MB');
  if (/\.csv$/i.test(file.name)) return csvRows(await file.text());
  if (!/\.xlsx$/i.test(file.name)) throw new Error('请选择 .xlsx 或 UTF-8 编码的 .csv 文件');
  const { Workbook } = await import('exceljs'); const workbook = new Workbook();
  await workbook.xlsx.load(await file.arrayBuffer());
  const sheet = workbook.worksheets[0]; if (!sheet) throw new Error('表格没有工作表');
  const rows: string[][] = [];
  sheet.eachRow(row => { rows.push(Array.from({ length: 8 }, (_, i) => timeCell(row.getCell(i + 1).value))); });
  return rows;
}
const signature = (c: Course, r: Rule) => [c.name, r.weekday, r.start, r.end, formatWeeks(r.weeks), r.room || c.room, r.teacher || c.teacher].join('|');
export function previewImport(rows: string[][], state: AppState, sem: Semester, replace = false): ImportRow[] {
  if (!rows.length || HEADERS.slice(0, 5).some((h, i) => rows[0][i]?.trim() !== h)) throw new Error('表头不匹配，请下载模板后填写（前五列必填）');
  if (rows.length > 2001) throw new Error('每次最多导入 2000 条规则');
  let provisional = state;
  if (replace) for (const c of entities(state, 'course').filter(c => c.semesterId === sem.id)) provisional = deleteCourse(provisional, c.id);
  const names = new Map(entities(provisional, 'course').filter(c => c.semesterId === sem.id).map(c => [c.name, c]));
  const existing = new Set(entities(provisional, 'rule').map(r => { const c = entities(provisional, 'course').find(c => c.id === r.courseId && c.semesterId === sem.id); return c ? signature(c, r) : ''; }));
  const result: ImportRow[] = [];
  rows.slice(1).forEach((values, idx) => {
    const item: ImportRow = { line: idx + 2, values, errors: [], duplicate: false }; result.push(item);
    try {
      const [name, day, start, end, weekText, room = '', teacher = '', notes = ''] = values.map(v => v.trim());
      if (!name || !day || !start || !end || !weekText) throw new Error('前五列不能为空');
      const weekday = Number(day.replace(/星期|周/g, '').replace('一', '1').replace('二', '2').replace('三', '3').replace('四', '4').replace('五', '5').replace('六', '6').replace(/[日天]/g, '7'));
      if (!Number.isInteger(weekday) || weekday < 1 || weekday > 7) throw new Error('星期须为 1-7 或星期一至星期日');
      if (!validTime(start) || !validTime(end) || start >= end) throw new Error('时间须为 HH:mm，且结束晚于开始');
      const weeks = parseWeeks(weekText, sem.totalWeeks);
      const course: Course = names.get(name) ?? { id: uid(), semesterId: sem.id, name, room, teacher, notes, color: COLORS[names.size % COLORS.length], reminders: null, muted: false, needsReview: false };
      names.set(name, course);
      const rule: Rule = { id: uid(), courseId: course.id, weekday, start, end, weeks, room, teacher };
      validateEntity('course', course); validateEntity('rule', rule);
      item.course = course; item.rule = rule;
      const key = signature(course, rule); if (existing.has(key)) { item.duplicate = true; return; } existing.add(key);
      const next = applyEdits(applyEdits(provisional, 'course', [course]), 'rule', [rule]);
      if (sem.firstMonday) {
        const clash = conflicts(lessonsBetween(next, sem, sem.firstMonday, addDays(sem.firstMonday, sem.totalWeeks * 7 - 1))).find(([a, b]) => a.ruleId === rule.id || b.ruleId === rule.id);
        if (clash) throw new Error(`时间冲突：${clash[0].date} ${clash[0].course.name} / ${clash[1].course.name}`);
      } else {
        const clash = entities(provisional, 'rule').find(r => r.weekday === weekday && r.start < end && start < r.end && r.weeks.some(w => weeks.includes(w)) && namesHasSemester(provisional, r, sem.id));
        if (clash) throw new Error('与已有课程或表格前面的行存在时间冲突');
      }
      provisional = next;
    } catch (error) { item.errors.push(error instanceof Error ? error.message : String(error)); }
  });
  return result;
}
function namesHasSemester(state: AppState, rule: Rule, semId: string) { return entities(state, 'course').some(c => c.id === rule.courseId && c.semesterId === semId); }
export function commitImport(state: AppState, sem: Semester, rows: ImportRow[], replace: boolean) {
  if (rows.some(r => r.errors.length)) throw new Error('请修正所有错误后重新导入');
  let next = state;
  if (replace) for (const c of entities(state, 'course').filter(c => c.semesterId === sem.id)) next = deleteCourse(next, c.id);
  for (const row of rows) if (!row.duplicate && row.course && row.rule) next = applyEdits(applyEdits(next, 'course', [row.course]), 'rule', [row.rule]);
  return next;
}
export function exportRows(state: AppState, semesterId: string): string[][] {
  const courses = new Map(entities(state, 'course').filter(c => c.semesterId === semesterId).map(c => [c.id, c]));
  return [HEADERS, ...entities(state, 'rule').filter(r => courses.has(r.courseId)).map(r => { const c = courses.get(r.courseId)!; return [c.name, String(r.weekday), r.start, r.end, formatWeeks(r.weeks), r.room || c.room, r.teacher || c.teacher, c.notes]; })];
}
export function encodeCsv(rows: string[][]): string {
  // 禁止表格程序将用户输入当作公式执行。
  return '\uFEFF' + rows.map(row => row.map(cell => `"${(/^[=+@\-\t\r]/.test(cell) ? "'" + cell : cell).replace(/"/g, '""')}"`).join(',')).join('\r\n');
}
export async function encodeXlsx(rows: string[][]): Promise<Blob> {
  const { Workbook } = await import('exceljs'); const wb = new Workbook(); const ws = wb.addWorksheet('课表');
  rows.forEach(r => ws.addRow(r)); ws.getRow(1).font = { bold: true, color: { argb: 'FFFFFFFF' } }; ws.getRow(1).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF16786C' } };
  ws.columns.forEach((c, i) => { c.width = i === 0 || i === 7 ? 32 : 18; });
  return new Blob([await wb.xlsx.writeBuffer() as ArrayBuffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
}
