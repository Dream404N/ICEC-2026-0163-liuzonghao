export interface Period { id: string; name: string; start: string; end: string }
export interface Semester {
  id: string; name: string; firstMonday: string; totalWeeks: number; archived: boolean; periods: Period[];
}
export interface Course {
  id: string; semesterId: string; name: string; teacher: string; room: string; color: string;
  notes: string; reminders: number[] | null; muted: boolean; needsReview: boolean;
}
export interface Rule {
  id: string; courseId: string; weekday: number; start: string; end: string;
  weeks: number[]; room: string; teacher: string;
}
export interface Adjustment {
  id: string; courseId: string; ruleId: string; originalDate: string;
  kind: 'cancel' | 'change' | 'extra'; date: string; start: string; end: string; room: string; teacher: string; note: string;
}
export interface Entities { semester: Semester; course: Course; rule: Rule; adjustment: Adjustment }
export type Kind = keyof Entities;
export type Entity = Entities[Kind];
export interface RemoteRecord {
  id: string; kind: Kind; payload: Entity | null; revision: number; updated_at: string;
}
export interface Entry {
  id: string; kind: Kind; value: Entity | null; rev: number; dirty: boolean; modifiedAt: string;
  conflict?: RemoteRecord;
}
export interface DevicePrefs {
  remindersEnabled: boolean; sound: boolean; leads: number[]; autoStart: boolean;
}
export interface AppState {
  schemaVersion: 1; entries: Record<string, Entry>; selectedSemesterId: string;
  device: DevicePrefs; ownerId: string | null; lastSync: string | null; syncError: string;
}
export interface Lesson {
  key: string; course: Course; ruleId: string; originalDate: string; date: string;
  start: string; end: string; room: string; teacher: string; adjusted: boolean; note: string;
}
export interface Reminder {
  id: number; key: string; title: string; body: string; at: string; lessonAt: string;
}
export const COLORS = ['#16786c', '#5479c4', '#a46ac1', '#d59443', '#cc6e7f', '#5b919e'];
export const DEFAULT_PERIODS: Period[] = [
  { id: 'p1', name: '第一大节', start: '08:40', end: '10:00' },
  { id: 'p2', name: '第二大节', start: '10:20', end: '11:40' },
  { id: 'p3', name: '第三大节', start: '13:30', end: '14:50' },
  { id: 'p4', name: '第四大节', start: '15:10', end: '16:30' },
];
export const uid = () => crypto.randomUUID();
export function entities<K extends Kind>(state: AppState, kind: K): Entities[K][] {
  return Object.values(state.entries).filter(e => e.kind === kind && e.value !== null).map(e => e.value as Entities[K]);
}
