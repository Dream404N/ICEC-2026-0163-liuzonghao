import { useEffect, useState } from 'react';
import { LayoutDashboard, CalendarDays, LibraryBig, FolderSync, Settings2, Bell, Cloud, ChevronDown, Check, X, GraduationCap, ArrowUpRight } from 'lucide-react';
import type { Course, Lesson, Adjustment } from './domain/types';
import { entities } from './domain/types';
import { getStorageError, useStore, updateStore } from './data/store';
import { Dashboard } from './ui/Dashboard';
import { WeekView } from './ui/WeekView';
import { Courses } from './ui/Courses';
import { CourseEditor } from './ui/CourseEditor';
import { LessonDetail, AdjustmentEditor } from './ui/LessonDetail';
import { Transfer } from './ui/Transfer';
import { Settings } from './ui/Settings';
import { weekStatus } from './domain/schedule';
import { chinaDate } from './domain/dates';
import { authSnapshot, watchAuth } from './data/sync';

type Page = 'home' | 'week' | 'courses' | 'transfer' | 'settings';
const NAV = [{ id: 'home', label: '今日概览', icon: LayoutDashboard }, { id: 'week', label: '周课表', icon: CalendarDays }, { id: 'courses', label: '课程管理', icon: LibraryBig }, { id: 'transfer', label: '导入与备份', icon: FolderSync }, { id: 'settings', label: '偏好设置', icon: Settings2 }] as const;
export default function App() {
  const state = useStore(); const semesters = entities(state, 'semester');
  const semester = semesters.find(s => s.id === state.selectedSemesterId) ?? semesters[0];
  const [page, setPage] = useState<Page>('home'); const [now, setNow] = useState(new Date());
  const [editor, setEditor] = useState<{ course?: Course; defaults?: { day?: number; start?: string; end?: string } }>();
  const [detail, setDetail] = useState<Lesson>(); const [adjustment, setAdjustment] = useState<{ course: Course; lesson?: Lesson; kind: Adjustment['kind'] }>();
  const [toast, setToast] = useState(''); const [auth, setAuth] = useState(authSnapshot());
  useEffect(() => { const id = setInterval(() => setNow(new Date()), 15000); return () => clearInterval(id); }, []);
  useEffect(() => watchAuth(() => setAuth(authSnapshot())), []);
  useEffect(() => { if (toast) { const id = setTimeout(() => setToast(''), 6000); return () => clearTimeout(id); } }, [toast]);
  const go = (p: Page) => { setPage(p); window.scrollTo({ top: 0 }); };
  if (!semester) return <div className="fatal">没有可用学期，请恢复完整备份。</div>;
  const add = (day?: number, start?: string, end?: string) => setEditor({ defaults: { day, start, end } });
  return <div className="app-shell"><aside className="sidebar"><a className="brand" href="#" onClick={e => { e.preventDefault(); go('home'); }}><span className="brand-icon"><GraduationCap size={25}/></span><span>课序<small>CLASSMATE</small></span></a><div className="workspace-label">我的学习空间</div><nav aria-label="主导航">{NAV.map(n => <button key={n.id} aria-label={n.label} className={page === n.id ? 'active' : ''} onClick={() => go(n.id)}><n.icon size={19}/><span>{n.label}</span>{n.id === 'courses' && <small>{entities(state, 'course').filter(c => c.semesterId === semester.id).length}</small>}</button>)}</nav><div className="sidebar-bottom"><div className="sidebar-note"><span>好好上课，慢慢成长。</span><small>把每一天，过成喜欢的样子。</small><div className="little-line"/></div><button className="sync-profile" onClick={() => go('settings')}><span className="avatar">我</span><span><b>{auth.user ? '我的云端课表' : '我的本地课表'}</b><small><span className={`status-dot ${auth.user ? '' : 'gray'}`}/>{auth.user ? '自动同步已连接' : '离线也能安心使用'}</small></span><ArrowUpRight size={16}/></button></div></aside>
    <div className="main-shell"><header className="topbar"><div className="breadcrumb">我的课表<span>/</span><b>{NAV.find(n => n.id === page)?.label}</b></div><div className="topbar-actions"><span className="top-week">{weekStatus(semester, chinaDate(now))}</span><button className="icon-button" aria-label="提醒设置" onClick={() => go('settings')}><Bell size={19}/>{state.device.remindersEnabled && <i className="notification-dot"/>}</button><span className="top-avatar">我</span></div></header><main><div className="semester-toolbar"><span className="semester-pill"><span className="status-dot"/>{semester.archived ? '历史学期' : '学习进行时'}</span><div className="semester-select"><CalendarDays size={15}/><select aria-label="切换学期" value={semester.id} onChange={e => { const value = e.target.value; updateStore(s => ({ ...s, selectedSemesterId: value })); }}>{semesters.map(s => <option key={s.id} value={s.id}>{s.name}{s.archived ? '（已归档）' : ''}</option>)}</select><ChevronDown size={14}/></div></div>{getStorageError() && <div className="error-box">{getStorageError()}</div>}
      {page === 'home' && <Dashboard state={state} semester={semester} now={now} onLesson={setDetail} onAdd={() => add()} onWeek={() => go('week')} onSettings={() => go('settings')}/>}
      {page === 'week' && <WeekView key={semester.id} state={state} semester={semester} onLesson={setDetail} onAdd={add} onSettings={() => go('settings')}/>}
      {page === 'courses' && <Courses state={state} semester={semester} onEdit={course => setEditor({ course })} onAdd={() => add()} onExtra={course => setAdjustment({ course, kind: 'extra' })} notify={setToast}/>}
      {page === 'transfer' && <Transfer state={state} semester={semester} notify={setToast}/>}
      {page === 'settings' && <Settings key={semester.id} state={state} semester={semester} notify={setToast}/>}
      <footer className="page-footer"><span>课序 · 把时间留给学习</span><span><Cloud size={13}/>{auth.running ? '正在同步' : state.syncError ? '同步失败，请检查设置' : auth.user ? '自动同步' : '本地保存'}<span className="text-dot">·</span>北京时间 UTC+8</span></footer>
    </main></div>
    {editor && <CourseEditor state={state} semester={semester} course={editor.course} defaults={editor.defaults} onClose={() => setEditor(undefined)} notify={setToast}/>}
    {detail && <LessonDetail lesson={detail} onClose={() => setDetail(undefined)} onEdit={() => { setEditor({ course: detail.course }); setDetail(undefined); }} onAdjust={kind => { setAdjustment({ course: detail.course, lesson: detail, kind }); setDetail(undefined); }}/>}
    {adjustment && <AdjustmentEditor state={state} semester={semester} {...adjustment} onClose={() => setAdjustment(undefined)} notify={setToast}/>}
    {toast && <div className="toast" role="status"><Check size={18}/><span>{toast}</span><button className="icon-button" aria-label="关闭消息" onClick={() => setToast('')}><X size={15}/></button></div>}
  </div>;
}
