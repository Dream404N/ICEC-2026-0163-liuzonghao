const { BrowserWindow, screen, ipcMain } = require('electron');
const path = require('node:path');

class PopupManager {
  constructor({ open, snooze }) {
    this.active = []; this.queue = []; this.open = open; this.snooze = snooze;
    ipcMain.handle('popup-content', event => this.find(event)?.reminder || null);
    ipcMain.handle('popup-action', async (event, action) => {
      const entry = this.find(event);
      if (!entry || !['dismiss', 'snooze', 'open'].includes(action)) return;
      if (action === 'snooze') await this.snooze(entry.reminder);
      if (action === 'open') this.open();
      entry.window.close();
    });
    this.reposition = () => this.layout();
    screen.on('display-metrics-changed', this.reposition);
    screen.on('display-removed', this.reposition);
  }
  find(event) { return this.active.find(e => e.window.webContents === event.sender && event.senderFrame === e.window.webContents.mainFrame); }
  show(reminder) {
    this.queue.push(reminder); this.drain();
  }
  drain() {
    const area = screen.getPrimaryDisplay().workArea;
    const capacity = Math.max(1, Math.min(3, Math.floor((area.height - 16) / 206)));
    while (this.active.length < capacity && this.queue.length) {
      const reminder = this.queue.shift();
      const window = new BrowserWindow({ width: Math.min(396, area.width), height: 200, show: false, frame: false,
        transparent: true, resizable: false, movable: false, minimizable: false, maximizable: false,
        focusable: false, skipTaskbar: true, alwaysOnTop: true, hasShadow: false, title: '课序 · 课程提醒',
        webPreferences: { preload: path.join(__dirname, 'popup-preload.cjs'), nodeIntegration: false, contextIsolation: true, sandbox: true, autoplayPolicy: 'no-user-gesture-required' } });
      const entry = { window, reminder }; this.active.push(entry);
      window.setAlwaysOnTop(true, 'pop-up-menu');
      window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
      window.webContents.on('will-navigate', event => event.preventDefault());
      window.once('ready-to-show', () => { if (!window.isDestroyed()) { this.layout(); window.showInactive(); } });
      window.on('closed', () => { this.active = this.active.filter(e => e !== entry); this.layout(); this.drain(); });
      window.loadFile(path.join(__dirname, 'popup.html')).catch(error => { console.error('Popup load failed', error); window.destroy(); });
    }
    this.layout();
  }
  layout() {
    const area = screen.getPrimaryDisplay().workArea;
    this.active.forEach(({ window }, i) => {
      if (!window.isDestroyed()) window.setBounds({ x: area.x + Math.max(0, area.width - Math.min(396, area.width) - 8), y: area.y + Math.max(0, area.height - (i + 1) * 206 - 8), width: Math.min(396, area.width), height: 200 });
    });
  }
  retain(items) {
    const valid = r => items.some(item => item.key === r.key && item.at === r.at);
    this.queue = this.queue.filter(valid);
    for (const entry of [...this.active]) if (!valid(entry.reminder)) entry.window.close();
  }
  destroy() {
    this.queue = [];
    for (const { window } of [...this.active]) window.destroy();
    screen.removeListener('display-metrics-changed', this.reposition); screen.removeListener('display-removed', this.reposition);
  }
}
module.exports = { PopupManager };
