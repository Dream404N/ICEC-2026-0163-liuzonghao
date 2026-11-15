import { Capacitor } from '@capacitor/core';
import { LocalNotifications } from '@capacitor/local-notifications';
import type { AppState, Reminder } from '../domain/types';
import { planReminders, stableId } from '../domain/schedule';
import { getState } from '../data/store';

export interface NotificationStatus { platform: string; permission: string; exact: string; scheduled: number; message: string }
let status: NotificationStatus = { platform: '浏览器预览', permission: '尚未检查', exact: '不支持后台定时', scheduled: 0, message: '' };
const listeners = new Set<() => void>();
export const getNotificationStatus = () => status;
export function watchNotifications(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn); }; }
function report(value: Partial<NotificationStatus>) { status = { ...status, ...value }; listeners.forEach(fn => fn()); }
const desktop = () => window.kexu;
let revision = 0;
let chain = Promise.resolve();
export async function initNotifications() {
  if (Capacitor.isNativePlatform()) {
    report({ platform: '安卓本地通知' });
    await LocalNotifications.registerActionTypes({ types: [{ id: 'CLASS', actions: [{ id: 'snooze', title: '5 分钟后提醒', foreground: true }, { id: 'dismiss', title: '知道了', destructive: false }] }] });
    await LocalNotifications.addListener('localNotificationActionPerformed', async event => {
      if (event.actionId !== 'snooze' || !getState().device.remindersEnabled) return;
      const at = new Date(Date.now() + 300000);
      const id = stableId(`snooze:${event.notification.id}:${Date.now()}`);
      await LocalNotifications.schedule({ notifications: [{ id, title: event.notification.title, body: event.notification.body, sound: getState().device.sound ? 'reminder.wav' : undefined, schedule: { at, allowWhileIdle: true }, actionTypeId: 'CLASS', channelId: getState().device.sound ? 'classes-sound' : 'classes-quiet', extra: { snooze: true } }] });
    });
  }
  await checkPermissions(false);
}
export async function checkPermissions(request: boolean) {
  if (Capacitor.isNativePlatform()) {
    const p = request ? await LocalNotifications.requestPermissions() : await LocalNotifications.checkPermissions();
    const exact = await LocalNotifications.checkExactNotificationSetting();
    report({ permission: p.display === 'granted' ? '已允许' : '未允许', exact: exact.exact_alarm === 'granted' ? '已允许准时提醒' : '未允许准时提醒；可能延迟' });
    return p.display === 'granted';
  }
  if (desktop()) {
    const info = await desktop()!.notificationStatus();
    report({ platform: 'Windows 右下角轻提醒', permission: info.enabled ? '弹窗服务已就绪' : '弹窗服务不可用', exact: '主进程定时提醒', message: info.error || info.warning || '关闭主窗口后仍在托盘提醒；彻底退出后停止。' });
    return info.enabled;
  }
  let permission = '当前浏览器不支持';
  if ('Notification' in window) permission = request ? await Notification.requestPermission() : Notification.permission;
  report({ permission, message: '浏览器仅供预览：需保持页面运行。安装 Windows / 安卓应用才能使用后台定时提醒。' });
  return permission === 'granted';
}
export async function requestExact() {
  if (Capacitor.isNativePlatform()) await LocalNotifications.changeExactNotificationSetting();
}
export function refreshReminders(state: AppState) {
  const current = ++revision;
  const snapshot = structuredClone(state);
  chain = chain.catch(() => {}).then(async () => {
    if (current !== revision) return;
    try { await arrange(snapshot); } catch (e) { report({ message: `提醒安排失败：${e instanceof Error ? e.message : String(e)}` }); }
  });
  return chain;
}
async function arrange(state: AppState) {
  // 全学期排入系统，避免应用长期未打开时仅有短期提醒。
  const reminders = planReminders(state, new Date(), 430);
  if (Capacitor.isNativePlatform()) {
    const pending = await LocalNotifications.getPending();
    // 保留用户主动选择的稍后提醒；关闭总开关时全部取消。
    const cancel = pending.notifications.filter(n => !n.extra?.snooze || !state.device.remindersEnabled);
    if (cancel.length) await LocalNotifications.cancel({ notifications: cancel.map(n => ({ id: n.id })) });
    if ((await LocalNotifications.checkPermissions()).display !== 'granted') { report({ scheduled: 0, message: '请允许通知后重新安排提醒。' }); return; }
    // 安卓 8+ 的渠道由 MainActivity 创建；安卓 7 不调用不支持的渠道 API。
    const batch = reminders.slice(0, 450);
    if (batch.length) await LocalNotifications.schedule({ notifications: batch.map(r => ({ id: r.id, title: r.title, body: r.body, sound: state.device.sound ? 'reminder.wav' : undefined, schedule: { at: new Date(r.at), allowWhileIdle: true }, actionTypeId: 'CLASS', channelId: state.device.sound ? 'classes-sound' : 'classes-quiet', extra: { key: r.key } })) });
    report({ scheduled: batch.length, message: reminders.length > batch.length ? `待安排 ${reminders.length} 条，已安排最近 450 条；请定期打开应用补充后续提醒。` : '已由系统安排；系统省电策略可能影响提醒，请用真机测试。' });
  } else if (desktop()) {
    // Keep source keys for today's snoozed reminders when refreshing the UI.
    const desktopPlan = planReminders(state, new Date(Date.now() - 86400000), 431);
    const result = await desktop()!.schedule(desktopPlan, state.device.sound);
    report({ scheduled: result.count, message: result.error || '已安排右下角轻提醒，不抢焦点，12 秒后收起，悬停暂停。请保持托盘运行；彻底退出、锁屏或关机期间无法显示。' });
  } else {
    previewReminders = reminders; report({ scheduled: reminders.length });
  }
}
let previewReminders: Reminder[] = [];
const shown = new Set<string>();
window.setInterval(() => {
  if (desktop() || Capacitor.isNativePlatform() || !('Notification' in window) || Notification.permission !== 'granted') return;
  for (const r of previewReminders) {
    if (new Date(r.at).getTime() <= Date.now() && new Date(r.at).getTime() > Date.now() - 60000 && !shown.has(r.key)) {
      shown.add(r.key); new Notification(r.title, { body: r.body, silent: !getState().device.sound });
    }
  }
}, 15000);
export async function testNotification() {
  if (!await checkPermissions(true)) throw new Error('通知权限未允许');
  const reminder: Reminder = { id: stableId(`test:${Date.now()}`), key: 'test', title: '课序 · 测试提醒', body: '下一节课的信息会显示在这里。', at: new Date(Date.now() + 5000).toISOString(), lessonAt: new Date(Date.now() + 60000).toISOString() };
  if (desktop()) await desktop()!.testNotification(reminder, getState().device.sound);
  else if (Capacitor.isNativePlatform()) await LocalNotifications.schedule({ notifications: [{ id: reminder.id, title: reminder.title, body: reminder.body, sound: getState().device.sound ? 'reminder.wav' : undefined, schedule: { at: new Date(reminder.at) }, channelId: getState().device.sound ? 'classes-sound' : 'classes-quiet', actionTypeId: 'CLASS', extra: { snooze: true } }] });
  else new Notification(reminder.title, { body: reminder.body });
}
