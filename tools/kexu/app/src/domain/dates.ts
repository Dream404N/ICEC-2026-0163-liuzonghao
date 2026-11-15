const DAY = 86400000;
export function isDate(s: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(s) && !Number.isNaN(Date.parse(s + 'T00:00:00Z')) && new Date(s + 'T00:00:00Z').toISOString().slice(0, 10) === s;
}
export const dayNumber = (date: string) => Date.parse(date + 'T00:00:00Z') / DAY;
export const addDays = (date: string, count: number) => new Date((dayNumber(date) + count) * DAY).toISOString().slice(0, 10);
export const weekday = (date: string) => ((new Date(date + 'T00:00:00Z').getUTCDay() + 6) % 7) + 1;
export const monday = (date: string) => addDays(date, 1 - weekday(date));
export const teachingWeek = (date: string, first: string) => isDate(first) ? Math.floor((dayNumber(date) - dayNumber(first)) / 7) + 1 : 0;
export function chinaDate(date = new Date()): string {
  return new Date(date.getTime() + 8 * 3600000).toISOString().slice(0, 10);
}
export const instant = (date: string, time: string) => new Date(`${date}T${time}:00+08:00`);
export const validTime = (s: string) => /^([01]\d|2[0-3]):[0-5]\d$/.test(s);
export const minutes = (s: string) => Number(s.slice(0, 2)) * 60 + Number(s.slice(3));
export const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];
export const friendlyDate = (date: string) => `${Number(date.slice(5, 7))}月${Number(date.slice(8))}日 · 星期${WEEKDAYS[weekday(date) - 1]}`;
