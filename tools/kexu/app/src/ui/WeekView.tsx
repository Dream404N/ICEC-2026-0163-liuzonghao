import { useState } from 'react';
import { ChevronLeft, ChevronRight, Plus, CalendarDays } from 'lucide-react';
import type { AppState, Lesson, Semester } from '../domain/types';
import { addDays, chinaDate, teachingWeek, WEEKDAYS, minutes } from '../domain/dates';
import { lessonsBetween, conflicts } from '../domain/schedule';
import { Empty } from './common';
export function WeekView({ state, semester, onLesson, onAdd, onSettings }: { state: AppState; semester: Semester; onLesson: (l: Lesson) => void; onAdd: (day?: number, start?: string, end?: string) => void; onSettings: () => void }) {
  const current = teachingWeek(chinaDate(), semester.firstMonday);
  const [week, setWeek] = useState(Math.min(semester.totalWeeks, Math.max(1, current)));
  if (!semester.firstMonday) return <><div className="page-heading"><div><div className="eyebrow">WEEKLY PLANNER</div><h1>周课表</h1><p>让一周的安排一目了然</p></div></div><section className="panel"><Empty title="先设置第一周日期" detail="日期决定每一周实际上哪些课，请填写第一周的周一日期。"><button className="primary" onClick={onSettings}>设置学期</button></Empty></section></>;
  const safeWeek = Math.min(semester.totalWeeks, week);
  const start = addDays(semester.firstMonday, (safeWeek - 1) * 7);
  const lessons = lessonsBetween(state, semester, start, addDays(start, 6));
  const earliest = Math.min(8 * 60, ...semester.periods.map(p => minutes(p.start)), ...lessons.map(l => minutes(l.start)));
  const latest = Math.max(17 * 60, ...semester.periods.map(p => minutes(p.end)), ...lessons.map(l => minutes(l.end)));
  const height = (latest - earliest) * 1.3;
  return <><div className="page-heading"><div><div className="eyebrow">WEEKLY PLANNER</div><h1>每一周，有条不紊<span className="heading-dot">.</span></h1><p>{semester.name}</p></div><button className="primary" onClick={() => onAdd()}><Plus size={17}/>添加课程</button></div>
    <div className="week-controls"><div className="week-switch"><button className="icon-button" disabled={safeWeek <= 1} aria-label="上一周" onClick={() => setWeek(w => Math.max(1, w - 1))}><ChevronLeft size={18}/></button><select aria-label="选择教学周" value={safeWeek} onChange={e => setWeek(Number(e.target.value))}>{Array.from({ length: semester.totalWeeks }, (_, i) => <option key={i} value={i + 1}>第 {i + 1} 周 · {(i + 1) % 2 ? '单周' : '双周'}</option>)}</select><button className="icon-button" disabled={safeWeek >= semester.totalWeeks} aria-label="下一周" onClick={() => setWeek(w => Math.min(semester.totalWeeks, w + 1))}><ChevronRight size={18}/></button></div><button className="secondary" onClick={() => setWeek(Math.min(semester.totalWeeks, Math.max(1, current)))}><CalendarDays size={15}/>返回本周</button><span className="week-range">{start} — {addDays(start, 6)}</span></div>
    {conflicts(lessons).length > 0 && <div className="notice warning">本周存在时间冲突，重叠课程会并排显示，请核对。</div>}
    <div className="week-scroll panel"><div className="week-table"><div className="week-table-head"><div className="time-heading">时间</div>{WEEKDAYS.map((d, i) => { const date = addDays(start, i); return <div className={date === chinaDate() ? 'is-today' : ''} key={d}><span>星期{d}</span><b>{Number(date.slice(5, 7))}/{Number(date.slice(8))}</b></div>; })}</div><div className="week-columns" style={{ height }}><div className="time-axis">{Array.from({ length: Math.ceil((latest - earliest) / 60) + 1 }, (_, i) => earliest + i * 60).filter(m => m <= latest).map(m => <span key={m} style={{ top: (m - earliest) * 1.3 }}>{String(Math.floor(m / 60)).padStart(2, '0')}:{String(m % 60).padStart(2, '0')}</span>)}</div>{WEEKDAYS.map((_, i) => <div className="day-column" key={i}>{semester.periods.map(p => <button key={p.id} className="empty-slot" style={{ top: (minutes(p.start) - earliest) * 1.3, height: (minutes(p.end) - minutes(p.start)) * 1.3 }} title={`星期${WEEKDAYS[i]} ${p.start} 添加课程`} onClick={() => onAdd(i + 1, p.start, p.end)}><Plus size={16}/></button>)}{lessons.filter(l => l.date === addDays(start, i)).map(l => {
      const peers = lessons.filter(o => o.date === l.date && o.start < l.end && l.start < o.end); const index = peers.findIndex(o => o.key === l.key);
      return <button key={l.key} className="week-course" onClick={() => onLesson(l)} style={{ top: (minutes(l.start) - earliest) * 1.3, height: Math.max(40, (minutes(l.end) - minutes(l.start)) * 1.3 - 5), left: `calc(${index / peers.length * 100}% + 4px)`, width: `calc(${100 / peers.length}% - 8px)`, '--course-color': l.course.color } as React.CSSProperties}><b>{l.course.name}</b><span>{l.start}–{l.end}</span><span>{l.room || '教室待定'}</span>{l.course.needsReview && <small>待校对</small>}{l.adjusted && <small>临时调整</small>}</button>;
    })}</div>)}</div></div></div><p className="helper">点击空白时段可添加课程 · 点击课程可修改本次安排或整条规则</p>
  </>;
}
