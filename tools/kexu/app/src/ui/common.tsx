import { useEffect, useRef, type ReactNode } from 'react';
import { X, BookOpen, MapPin, UserRound, BellOff } from 'lucide-react';
import type { Lesson } from '../domain/types';
export function Modal({ title, children, onClose, wide = false }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  const ref = useRef<HTMLElement>(null); const close = useRef(onClose); close.current = onClose;
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null; const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    (ref.current?.querySelector('input,select,textarea') as HTMLElement | null ?? ref.current?.querySelector('button'))?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); close.current(); }
      if (event.key !== 'Tab') return;
      const items = [...(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]') ?? [])];
      if (!items.length) return;
      if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1)?.focus(); }
      else if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0].focus(); }
    };
    document.addEventListener('keydown', keydown);
    return () => { document.body.style.overflow = overflow; document.removeEventListener('keydown', keydown); before?.focus(); };
  }, []);
  return <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}><section ref={ref} role="dialog" aria-modal="true" aria-label={title} className={`modal ${wide ? 'wide' : ''}`}><header><h2>{title}</h2><button className="icon-button" aria-label="关闭弹窗" onClick={onClose}><X size={20} /></button></header>{children}</section></div>;
}
export function Empty({ title, detail, children }: { title: string; detail: string; children?: ReactNode }) {
  return <div className="empty"><div className="empty-icon"><BookOpen size={26} /></div><h3>{title}</h3><p>{detail}</p>{children}</div>;
}
export function LessonCard({ lesson, onClick, now }: { lesson: Lesson; onClick: () => void; now: Date }) {
  const current = new Date(`${lesson.date}T${lesson.start}:00+08:00`) <= now && new Date(`${lesson.date}T${lesson.end}:00+08:00`) > now;
  return <button className={`lesson-row ${current ? 'current' : ''}`} onClick={onClick} style={{ '--course-color': lesson.course.color } as React.CSSProperties}>
    <div className="lesson-time"><b>{lesson.start}</b><span>{lesson.end}</span></div><span className="course-stripe" /><div className="lesson-info"><h3>{lesson.course.name}{current && <small className="pill">正在上课</small>}{lesson.adjusted && <small className="pill amber">临时调整</small>}</h3><div className="metadata"><span><MapPin size={14} />{lesson.room || '教室待定'}</span>{lesson.teacher && <span><UserRound size={14} />{lesson.teacher}</span>}</div></div><span className="lesson-status">{lesson.course.needsReview ? '待校对' : lesson.course.muted ? <BellOff size={16} /> : '查看详情 →'}</span>
  </button>;
}
