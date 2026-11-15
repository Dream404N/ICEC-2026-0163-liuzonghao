import { createRoot } from 'react-dom/client';
import App from './App';
import { getState, loadStore, subscribe } from './data/store';
import { initSync } from './data/sync';
import { initNotifications, refreshReminders, checkPermissions } from './platform/notifications';
import './styles.css';
async function start() {
  await loadStore();
  createRoot(document.getElementById('root')!).render(<App/>);
  let fingerprint = '';
  let timer: ReturnType<typeof setTimeout>;
  const schedule = () => {
    const s = getState();
    const next = JSON.stringify([Object.values(s.entries).map(e => [e.id, e.value]), s.device]);
    if (next === fingerprint) return;
    fingerprint = next; clearTimeout(timer); timer = setTimeout(() => { void refreshReminders(getState()); }, 600);
  };
  subscribe(schedule);
  try { await initNotifications(); } catch (error) { console.error('Notifications initialization', error); }
  schedule();
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { void checkPermissions(false).catch(console.error); void refreshReminders(getState()); } });
  await initSync();
}
void start().catch(error => {
  const root = document.getElementById('root')!;
  root.className = 'fatal'; const title = document.createElement('h1'); title.textContent = '课序未能读取本地数据';
  const message = document.createElement('p'); message.textContent = String(error);
  const hint = document.createElement('p'); hint.textContent = '请勿清除应用数据。检查存储权限或使用之前导出的备份恢复。'; root.replaceChildren(title, message, hint);
});
