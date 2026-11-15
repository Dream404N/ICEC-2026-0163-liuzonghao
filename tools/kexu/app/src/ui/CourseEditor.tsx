import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import type { AppState, Course, Rule, Semester } from '../domain/types';
import { COLORS, uid, entities } from '../domain/types';
import { parseWeeks, formatWeeks } from '../domain/weeks';
import { validateRule } from '../domain/schedule';
import { applyEdits, contentSignature } from '../data/state';
import { addDays, WEEKDAYS } from '../domain/dates';
import { conflicts, lessonsBetween } from '../domain/schedule';
import { getState, updateStore } from '../data/store';
import { validateEntity } from '../data/validation';
import { Modal } from './common';
interface Draft extends Omit<Rule, 'weeks'> { weekText: string }
export function CourseEditor({ state, semester, course, defaults, onClose, notify }: { state: AppState; semester: Semester; course?: Course; defaults?: { day?: number; start?: string; end?: string }; onClose: () => void; notify: (s: string) => void }) {
  const [draft, setDraft] = useState<Course>(course ? { ...course } : { id: uid(), semesterId: semester.id, name: '', teacher: '', room: '', notes: '', color: COLORS[0], reminders: null, muted: false, needsReview: false });
  const originalRules = entities(state, 'rule').filter(r => r.courseId === draft.id);
  const [baseVersion] = useState(() => contentSignature([course, originalRules]));
  const newRule = (): Draft => ({ id: uid(), courseId: draft.id, weekday: defaults?.day || 1, start: defaults?.start || semester.periods[0].start, end: defaults?.end || semester.periods[0].end, weekText: `1-${semester.totalWeeks}`, room: '', teacher: '' });
  const [rules, setRules] = useState<Draft[]>(originalRules.length ? originalRules.map(r => ({ ...r, weekText: formatWeeks(r.weeks) })) : [newRule()]);
  const [leadText, setLeadText] = useState(draft.reminders?.join(',') ?? '');
  const [error, setError] = useState('');
  const patch = (id: string, fields: Partial<Draft>) => setRules(rs => rs.map(r => r.id === id ? { ...r, ...fields } : r));
  function save() {
    try {
      const latest = getState();
      const live = entities(latest, 'course').find(c => c.id === draft.id);
      const liveRules = entities(latest, 'rule').filter(r => r.courseId === draft.id);
      if (contentSignature([live, liveRules]) !== baseVersion) throw new Error('这门课已在其他设备或窗口更新，请保留当前输入并关闭弹窗，重新打开最新课程后编辑。');
      if (!draft.name.trim()) throw new Error('请填写课程名称');
      const reminders = leadText.trim() ? leadText.split(/[,，]/).map(v => Number(v.trim())) : null;
      if (reminders && (reminders.length > 10 || reminders.some(n => !Number.isInteger(n) || n < 0 || n > 1440))) throw new Error('提前时间填写 0-1440 的整数，用逗号分隔，最多 10 个');
      if (!rules.length) throw new Error('至少保留一条排课规则');
      validateEntity('course', { ...draft, reminders });
      const saved = rules.map(r => { const { weekText, ...rest } = r; const rule = { ...rest, weeks: parseWeeks(weekText, semester.totalWeeks) }; const errors = validateRule(rule, semester.totalWeeks); if (errors.length) throw new Error(errors.join('；')); return rule; });
      const changed = applyEdits(applyEdits(state, 'course', [{ ...draft, name: draft.name.trim(), reminders }]), 'rule', saved, originalRules.filter(r => !saved.some(n => n.id === r.id)).map(r => r.id));
      // 排课规则改变会影响已存在的单次调整，显式要求先移除，避免幽灵补课。
      const dependent = entities(state, 'adjustment').filter(a => a.courseId === draft.id && a.kind !== 'extra' && originalRules.some(old => old.id === a.ruleId && JSON.stringify(old) !== JSON.stringify(saved.find(r => r.id === old.id))));
      if (dependent.length) throw new Error('变更的规则已有单次调整，请先在课程详情的调整记录中恢复这些安排，再修改规则。');
      if (semester.firstMonday) {
        const clash = conflicts(lessonsBetween(changed, semester, semester.firstMonday, addDays(semester.firstMonday, semester.totalWeeks * 7 - 1))).find(([a, b]) => a.course.id === draft.id || b.course.id === draft.id);
        if (clash) throw new Error(`时间冲突：${clash[0].date} ${clash[0].start}，${clash[0].course.name} 与 ${clash[1].course.name}`);
      } else {
        const all = entities(changed, 'rule').filter(r => entities(changed, 'course').some(c => c.id === r.courseId && c.semesterId === semester.id));
        for (const r of saved) if (all.some(o => o.id !== r.id && o.weekday === r.weekday && o.start < r.end && r.start < o.end && o.weeks.some(w => r.weeks.includes(w)))) throw new Error('排课时间与已有课程重叠，请检查星期、时间和上课周次');
      }
      updateStore(s => {
        const next = applyEdits(applyEdits(s, 'course', [{ ...draft, name: draft.name.trim(), reminders }]), 'rule', saved, originalRules.filter(r => !saved.some(n => n.id === r.id)).map(r => r.id));
        return next;
      });
      notify('课程已保存，提醒已更新'); onClose();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  return <Modal title={course ? '编辑课程与排课规则' : '添加一门新课程'} onClose={onClose} wide><div className="modal-body"><div className="form-grid"><label className="full">课程名称<input autoFocus placeholder="例如：工程数学" value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })}/></label><label>默认教师<input value={draft.teacher} onChange={e => setDraft({ ...draft, teacher: e.target.value })}/></label><label>默认教室<input value={draft.room} onChange={e => setDraft({ ...draft, room: e.target.value })}/></label><label className="full">课程颜色<div className="color-picker">{COLORS.map(c => <button key={c} type="button" aria-label={`颜色 ${c}`} className={draft.color === c ? 'selected' : ''} style={{ background: c }} onClick={() => setDraft({ ...draft, color: c })}/>)}</div></label></div>
    <div className="inline-heading"><h3>排课规则</h3><button className="text-button" onClick={() => setRules([...rules, newRule()])}><Plus size={15}/>添加规则</button></div><p className="helper">不同周次、教室或教师可拆成多条规则；跨大节课程直接填写完整起止时间。</p>
    {rules.map((r, i) => <div className="rule-editor" key={r.id}><div className="inline-heading"><b>规则 {i + 1}</b><button className="icon-button danger" aria-label={`删除规则 ${i + 1}`} onClick={() => setRules(rules.filter(v => v.id !== r.id))}><Trash2 size={16}/></button></div><div className="form-grid three"><label>星期<select aria-label={`规则 ${i + 1} 星期`} value={r.weekday} onChange={e => patch(r.id, { weekday: Number(e.target.value) })}>{WEEKDAYS.map((d, i) => <option key={d} value={i + 1}>星期{d}</option>)}</select></label><label>开始时间<input type="time" value={r.start} onChange={e => patch(r.id, { start: e.target.value })}/></label><label>结束时间<input type="time" value={r.end} onChange={e => patch(r.id, { end: e.target.value })}/></label><label className="full">上课周次<input aria-label={`规则 ${i + 1} 上课周次`} placeholder="3-13,16-18 或 1-18单周" value={r.weekText} onChange={e => patch(r.id, { weekText: e.target.value })}/></label><label>本规则教室<input placeholder="留空使用默认值" value={r.room} onChange={e => patch(r.id, { room: e.target.value })}/></label><label>本规则教师<input placeholder="留空使用默认值" value={r.teacher} onChange={e => patch(r.id, { teacher: e.target.value })}/></label></div></div>)}
    <div className="form-grid"><label className="full">备注<textarea rows={2} value={draft.notes} onChange={e => setDraft({ ...draft, notes: e.target.value })}/></label><label className="full">单独设置提前提醒（分钟）<input placeholder="留空使用默认值，例如 15,5" value={leadText} onChange={e => setLeadText(e.target.value)}/></label></div><label className="checkbox"><input type="checkbox" checked={draft.muted} onChange={e => setDraft({ ...draft, muted: e.target.checked })}/>关闭这门课的提醒</label><label className="checkbox"><input type="checkbox" checked={draft.needsReview} onChange={e => setDraft({ ...draft, needsReview: e.target.checked })}/>待校对：暂不生成提醒</label>{error && <p role="alert" className="error-box">{error}</p>}</div><footer><button className="secondary" onClick={onClose}>取消</button><button className="primary" onClick={save}>保存课程</button></footer></Modal>;
}
