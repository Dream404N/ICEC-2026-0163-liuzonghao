import { useState } from 'react';
import { MapPin, UserRound, Clock3, Pencil, CalendarClock, Ban } from 'lucide-react';
import type { Adjustment, AppState, Course, Lesson, Semester } from '../domain/types';
import { uid, entities } from '../domain/types';
import { addDays, chinaDate, friendlyDate, isDate, validTime } from '../domain/dates';
import { applyEdits } from '../data/state';
import { updateStore } from '../data/store';
import { lessonsBetween, overlaps } from '../domain/schedule';
import { Modal } from './common';
export function LessonDetail({ lesson, onClose, onEdit, onAdjust }: { lesson: Lesson; onClose: () => void; onEdit: () => void; onAdjust: (kind: 'cancel' | 'change') => void }) {
  return <Modal title="课程详情" onClose={onClose}><div className="modal-body"><span className="pill">{friendlyDate(lesson.date)}</span><h2 className="detail-title">{lesson.course.name}</h2><div className="detail-meta"><p><Clock3 size={18}/>{lesson.start}–{lesson.end}</p><p><MapPin size={18}/>{lesson.room || '教室待定'}</p><p><UserRound size={18}/>{lesson.teacher || '教师待定'}</p></div>{lesson.course.needsReview && <div className="notice warning">这门课来自截图，尚未校对，因此暂不提醒。编辑课程并确认信息后可开启提醒。</div>}{lesson.note && <p>{lesson.note}</p>}{lesson.course.notes && <p className="helper">{lesson.course.notes}</p>}<div className="detail-actions"><button className="secondary" onClick={() => onAdjust('change')}><CalendarClock size={16}/>只修改这一次</button><button className="secondary" onClick={onEdit}><Pencil size={16}/>修改整条规则</button><button className="danger-button" onClick={() => onAdjust('cancel')}><Ban size={16}/>本次停课</button></div></div></Modal>;
}
export function AdjustmentEditor({ state, semester, course, lesson, kind, onClose, notify }: { state: AppState; semester: Semester; course: Course; lesson?: Lesson; kind: Adjustment['kind']; onClose: () => void; notify: (s: string) => void }) {
  const old = lesson ? entities(state, 'adjustment').find(a => `adjustment:${a.id}` === lesson.key) : undefined;
  const [draft, setDraft] = useState<Adjustment>({ id: old?.id ?? uid(), courseId: course.id, ruleId: lesson?.ruleId ?? '', originalDate: old?.originalDate ?? lesson?.originalDate ?? chinaDate(), kind: old?.kind === 'extra' && kind === 'change' ? 'extra' : kind, date: lesson?.date ?? chinaDate(), start: lesson?.start ?? '08:40', end: lesson?.end ?? '10:00', room: lesson?.room ?? course.room, teacher: lesson?.teacher ?? course.teacher, note: '' });
  const [error, setError] = useState('');
  function save() {
    try {
      if (!semester.firstMonday) throw new Error('请先设置第一周周一日期');
      if (!isDate(draft.date) || !validTime(draft.start) || !validTime(draft.end) || draft.start >= draft.end) throw new Error('请填写有效日期和起止时间');
      if (draft.date < semester.firstMonday || draft.date > addDays(semester.firstMonday, semester.totalWeeks * 7 - 1)) throw new Error('日期必须在当前学期内');
      let next = state;
      const existing = entities(state, 'adjustment').find(a => a.kind !== 'extra' && a.ruleId === draft.ruleId && a.originalDate === draft.originalDate);
      if (existing && existing.id !== draft.id) next = applyEdits(next, 'adjustment', [], [existing.id]);
      if (old?.kind === 'extra' && kind === 'cancel') {
        updateStore(s => applyEdits(s, 'adjustment', [], [old.id])); notify('补课已取消'); onClose(); return;
      }
      next = applyEdits(next, 'adjustment', [draft]);
      if (kind !== 'cancel') {
        const others = lessonsBetween(next, semester, draft.date, draft.date).filter(l => l.key !== `adjustment:${draft.id}`);
        if (others.some(l => overlaps(l, draft))) throw new Error('本次安排与当天其他课程冲突，请选择其他时间');
      }
      updateStore(s => {
        let n = s;
        if (existing && existing.id !== draft.id) n = applyEdits(n, 'adjustment', [], [existing.id]);
        return applyEdits(n, 'adjustment', [draft]);
      });
      notify('本次安排已更新，其他周不受影响'); onClose();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }
  return <Modal title={kind === 'cancel' ? '确认本次停课' : kind === 'extra' ? '添加一次补课' : '只修改这一次'} onClose={onClose}><div className="modal-body"><h3>{course.name}</h3>{kind === 'cancel' ? <p>取消 {lesson?.date} {lesson?.start} 的这一次课程及其提醒，其他周保持原安排。可在课程管理的调整记录中恢复。</p> : <><p className="helper">本次修改不会改变课程的常规排课规则。</p><div className="form-grid"><label className="full">上课日期<input type="date" value={draft.date} onChange={e => setDraft({ ...draft, date: e.target.value })}/></label><label>开始时间<input type="time" value={draft.start} onChange={e => setDraft({ ...draft, start: e.target.value })}/></label><label>结束时间<input type="time" value={draft.end} onChange={e => setDraft({ ...draft, end: e.target.value })}/></label><label>教室<input value={draft.room} onChange={e => setDraft({ ...draft, room: e.target.value })}/></label><label>教师<input value={draft.teacher} onChange={e => setDraft({ ...draft, teacher: e.target.value })}/></label><label className="full">调整备注<textarea value={draft.note} onChange={e => setDraft({ ...draft, note: e.target.value })}/></label></div></>}{error && <p role="alert" className="error-box">{error}</p>}</div><footer><button className="secondary" onClick={onClose}>取消</button><button className={kind === 'cancel' ? 'danger-button' : 'primary'} onClick={save}>{kind === 'cancel' ? '确认停课' : '保存本次安排'}</button></footer></Modal>;
}
