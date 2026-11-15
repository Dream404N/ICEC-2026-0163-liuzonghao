import { ArrowUpRight, Clock3, MapPin, Plus, CalendarDays, Check, ArrowRight } from 'lucide-react';
import type { AppState, Lesson, Semester } from '../domain/types';
import { entities } from '../domain/types';
import { addDays, chinaDate, instant, friendlyDate } from '../domain/dates';
import { lessonsBetween, weekStatus } from '../domain/schedule';
import { Empty, LessonCard } from './common';
export function Dashboard({ state, semester, now, onLesson, onAdd, onWeek, onSettings }: { state: AppState; semester: Semester; now: Date; onLesson: (l: Lesson) => void; onAdd: () => void; onWeek: () => void; onSettings: () => void }) {
  const today = chinaDate(now);
  const upcoming = lessonsBetween(state, semester, today, addDays(today, 430));
  const lessons = upcoming.filter(l => l.date === today);
  const current = upcoming.find(l => instant(l.date, l.start) <= now && instant(l.date, l.end) > now);
  const next = upcoming.find(l => instant(l.date, l.start) > now);
  const mins = next ? Math.ceil((instant(next.date, next.start).getTime() - now.getTime()) / 60000) : 0;
  const countdown = mins < 60 ? `${mins} 分钟` : mins < 1440 ? `${Math.floor(mins / 60)} 小时 ${mins % 60} 分` : `${Math.floor(mins / 1440)} 天`;
  const review = entities(state, 'course').filter(c => c.semesterId === semester.id && c.needsReview).length;
  const done = lessons.filter(l => instant(l.date, l.end) <= now).length;
  return <>
    <div className="page-heading"><div><div className="eyebrow">YOUR DAY, AT A GLANCE</div><h1>每一节课，都从容以赴<span className="heading-dot">.</span></h1><p>{friendlyDate(today)}<span className="text-dot">·</span>{weekStatus(semester, today)}</p></div><button className="primary" onClick={onAdd}><Plus size={17} />添加课程</button></div>
    {!semester.firstMonday && <div className="notice"><CalendarDays size={19} /><div><b>先告诉课序，第一周从哪一天开始</b><span>已整理你的截图课程；设置第一周周一日期后，即可计算每日课表。</span></div><button onClick={onSettings}>设置学期 <ArrowRight size={15} /></button></div>}
    <div className="dashboard-grid"><section className="next-card"><div className="next-top"><span className="light-label"><span className="pulse" />{current ? '正在进行' : '下一节课'}</span><span className="next-mark">NEXT UP</span></div>{(current || next) ? (() => { const l = (current || next)!; return <><div className="next-countdown">{current ? '专注此刻' : `还有 ${countdown}`}</div><h2>{l.course.name}</h2><div className="next-meta"><span><Clock3 size={17} />{l.date === today ? '今天' : friendlyDate(l.date)} {l.start}–{l.end}</span><span><MapPin size={17} />{l.room || '教室待定'}</span></div><button className="light-button" onClick={() => onLesson(l)}>查看课程详情 <ArrowUpRight size={17} /></button></>; })() : <><div className="next-countdown">给自己一点留白</div><h2>{semester.firstMonday ? '暂时没有待上课程' : '新学期，准备就绪'}</h2><p className="next-description">{semester.firstMonday ? '享受课余时间，也别忘了查看之后的安排。' : '设置学期日期，校对截图课表，让提醒准时到来。'}</p><button className="light-button" onClick={semester.firstMonday ? onWeek : onSettings}>{semester.firstMonday ? '查看周课表' : '完善学期设置'} <ArrowUpRight size={17} /></button></> }<div className="card-orbit orbit-one"/><div className="card-orbit orbit-two"/></section>
      <div className="stat-stack"><section className="stat-card"><span className="stat-icon mint"><CalendarDays size={21}/></span><div><span>今日课程</span><div className="stat-value">{lessons.length}<small>节课</small></div></div><div className="stat-foot">{done ? `已完成 ${done} 节，继续保持` : '安排好节奏，开启新一天'}</div></section><section className="stat-card"><span className="stat-icon lavender"><Check size={21}/></span><div><span>提醒状态</span><div className="stat-value text-value">{state.device.remindersEnabled ? '已开启' : '已暂停'}</div></div><div className="stat-foot">{review ? `${review} 门截图课程待校对，暂不提醒` : `默认提前 ${state.device.leads.join('、')} 分钟提醒`}</div></section></div>
    </div>
    <div className="section-heading"><div><h2>今日安排 <span className="count-badge">{lessons.length}</span></h2><p>把一天的节奏，握在自己手里</p></div><button className="text-button" onClick={onWeek}>查看整周 <ArrowRight size={16}/></button></div>
    <section className="panel today-list">{lessons.length ? lessons.map(l => <LessonCard key={l.key} lesson={l} now={now} onClick={() => onLesson(l)} />) : <Empty title={semester.firstMonday ? '今天没有课程' : '每日课表等待开启'} detail={semester.firstMonday ? '留点时间给自己，学习之外也有很多美好。' : '先设置学期起始日期，再查看按周次展开的课程。'}><button className="secondary" onClick={semester.firstMonday ? onWeek : onSettings}>{semester.firstMonday ? '浏览课表' : '设置学期'}</button></Empty>}</section>
    <div className="daily-note"><span>✦</span><p>不必赶路，让课序提前提醒你。</p><span className="note-line"/></div>
  </>;
}
