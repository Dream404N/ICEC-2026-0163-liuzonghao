const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain, shell, powerMonitor, dialog } = require('electron');
const path = require('node:path');
const fs = require('node:fs/promises');
const { spawn } = require('node:child_process');
const { ReminderScheduler, validReminders } = require('./reminder-scheduler.cjs');
const { PopupManager } = require('./popup-manager.cjs');
const { LogSync } = require('./log-sync.cjs');
const AUMID = 'cn.kexu.schedule';
let win, tray, quitting = false, scheduler, popups, schedulerError = '', logSync;
const devUrl = process.env.VITE_DEV_SERVER_URL;
const customData = app.commandLine.getSwitchValue('user-data-dir');
if (customData) app.setPath('userData', customData);
app.setAppUserModelId(AUMID);
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { win?.show(); win?.focus(); });
  app.whenReady().then(async () => {
    // 与 Electron 自己的 userData 保持一致：安装版目录名取自 package.json 的 name，
    // 即 %APPDATA%\classmate-reminder。命令行脚本按同一规则探测，避免「装了却没配置」。
    logSync = new LogSync({ userDataDir: app.getPath('userData'), version: app.getVersion(), platform: process.platform });
    logSync.start().catch(e => console.error('运行日志启动失败', e));
    popups = new PopupManager({ open: () => { win?.show(); win?.focus(); }, snooze: r => scheduler.snooze(r) });
    scheduler = new ReminderScheduler({
      filename: path.join(app.getPath('userData'), 'popup-reminders.json'),
      deliver: r => {
        popups.show(r);
        void logSync?.log('reminder_delivered', [r.title, r.body, r.at].filter(Boolean).join(' | '));
      },
      changed: items => popups.retain(items),
    });
    try { await scheduler.load(); } catch (e) { schedulerError = e.message; }
    // Migrate only an existing legacy profile; never touch other apps' notification plans.
    if (process.platform === 'win32') {
      try {
        await fs.access(path.join(app.getPath('userData'), 'scheduled-reminders.json'));
        try { await fs.access(path.join(app.getPath('userData'), 'popup-migrated')); }
        catch { await runNative('replace', { reminders: [], sound: false }); await fs.writeFile(path.join(app.getPath('userData'), 'popup-migrated'), '1'); }
      } catch (e) { if (e.code !== 'ENOENT') console.error('Legacy toast cleanup', e); }
    }
    createWindow(); createTray();
    scheduler.start();
    powerMonitor.on('resume', () => {
      scheduler.tick().catch(e => { scheduler.error = e.message; });
      void logSync?.log('system_resume', '系统从休眠恢复');
      // 长定时器在休眠期间可能失准：醒来后按最新配置重排，不额外联网、不补写日志。
      void logSync?.config().then(c => logSync.scheduleNext(c)).catch(() => {});
    });
    app.on('activate', () => { if (win) win.show(); else createWindow(); });
  });
}
app.on('before-quit', () => {
  quitting = true; popups?.destroy();
  if (scheduler) clearInterval(scheduler.timer);
  logSync?.logNow('app_exit', '课序退出');
  logSync?.stop();
});
function createWindow() {
  win = new BrowserWindow({ width: 1360, height: 900, minWidth: 780, minHeight: 640, backgroundColor: '#f5f7fa', title: '课序', icon: path.join(__dirname, '../build/icon.png'), autoHideMenuBar: true, webPreferences: { preload: path.join(__dirname, 'preload.cjs'), nodeIntegration: false, contextIsolation: true, sandbox: true } });
  if (devUrl) win.loadURL(devUrl); else win.loadFile(path.join(__dirname, '../dist/index.html'));
  win.on('close', event => { if (!quitting) { event.preventDefault(); win.hide(); } });
  win.webContents.setWindowOpenHandler(({ url }) => { if (/^https:\/\//.test(url)) shell.openExternal(url); return { action: 'deny' }; });
  win.webContents.on('will-navigate', (event, url) => {
    if (devUrl ? new URL(url).origin !== new URL(devUrl).origin : !url.startsWith('file://')) event.preventDefault();
  });
}
function createTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, '../build/icon.png')).resize({ width: 20, height: 20 });
  tray = new Tray(icon); tray.setToolTip('课序 · 课表提醒');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '打开课序', click: () => { win?.show(); win?.focus(); } },
    { type: 'separator' },
    { label: '立即同步运行日志', click: async () => {
      try {
        const r = await logSync.sync('manual');
        await dialog.showMessageBox({ title: '课序 · 运行日志', type: r.ok ? 'info' : 'warning', message: r.message || (r.ok ? '已提交' : '同步未完成'), buttons: ['知道了'] });
      } catch (e) { await dialog.showMessageBox({ title: '课序 · 运行日志', type: 'error', message: String(e.message || e), buttons: ['知道了'] }); }
    } },
    { label: '打开运行日志目录', click: () => { void shell.openPath(logSync.logsDir); } },
    { type: 'separator' },
    { label: '退出课序（停止提醒）', click: () => app.quit() },
  ]));
  tray.on('double-click', () => win.show());
}
function trusted(event) {
  if (!win || event.sender !== win.webContents || event.senderFrame !== win.webContents.mainFrame) throw new Error('Untrusted sender');
}
let operations = Promise.resolve();
function runNative(action, payload) {
  const operation = operations.catch(() => {}).then(async () => {
    if (process.platform !== 'win32') throw new Error('该原生通知适配器仅支持 Windows');
    const filename = path.join(app.getPath('userData'), 'scheduled-reminders.json');
    if (payload) await fs.writeFile(filename, JSON.stringify(payload), 'utf8');
    const script = app.isPackaged ? path.join(process.resourcesPath, 'app.asar.unpacked/electron/reminders.ps1') : path.join(__dirname, 'reminders.ps1');
    return new Promise((resolve, reject) => {
      const child = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', script, '-Action', action, '-DataPath', filename, '-AppId', AUMID], { windowsHide: true });
      let output = '', error = '';
      child.stdout.on('data', data => { output += data.toString('utf8'); }); child.stderr.on('data', data => { error += data.toString('utf8'); });
      const timeout = setTimeout(() => child.kill(), 60000);
      child.on('error', reject);
      child.on('close', code => { clearTimeout(timeout); if (code !== 0) reject(new Error(error || output || 'Windows 通知服务未响应')); else { try { resolve(JSON.parse(output.trim())); } catch { reject(new Error('系统通知返回格式无效')); } } });
    });
  });
  operations = operation; return operation;
}
ipcMain.handle('notification-status', event => { trusted(event); return { enabled: !!scheduler && !schedulerError && !scheduler.error, error: schedulerError || scheduler?.error || '', warning: '右下角轻提醒，不抢焦点；关闭主窗口后在托盘继续运行。彻底退出或关机期间不提醒。' }; });
ipcMain.handle('schedule', async (event, reminders, sound) => {
  trusted(event); validReminders(reminders);
  try {
    const result = await scheduler.replace(reminders, sound); schedulerError = '';
    void logSync?.log('reminders_scheduled', '已安排 ' + (result.count ?? 0) + ' 条提醒');
    return result;
  } catch (e) { schedulerError = e.message; return { count: 0, error: e.message }; }
});
ipcMain.handle('test-notification', async (event, reminder, sound) => {
  trusted(event); validReminders([reminder]);
  await scheduler.append(reminder, sound);
  void logSync?.log('test_notification', reminder.title || '使用者触发测试提醒');
});
ipcMain.handle('auto-start', (event, enabled) => {
  trusted(event);
  if (!app.isPackaged) throw new Error('请安装打包后的 Windows 应用再启用开机启动');
  app.setLoginItemSettings({ openAtLogin: !!enabled, path: process.execPath });
  const actual = app.getLoginItemSettings().openAtLogin;
  void logSync?.log('autostart_changed', actual ? '已开启开机启动' : '已关闭开机启动');
  return actual;
});
ipcMain.handle('get-auto-start', event => { trusted(event); return app.getLoginItemSettings().openAtLogin; });

// 运行日志 · 每天自动提交到 GitHub。事件全部来自真实操作，不生成心跳。
ipcMain.handle('log-sync-status', event => { trusted(event); return logSync.status(); });
ipcMain.handle('log-sync-now', event => { trusted(event); return logSync.sync('manual'); });
ipcMain.handle('log-sync-config', (event, patch) => { trusted(event); return logSync.configure(patch); });
ipcMain.handle('log-sync-open', event => { trusted(event); return shell.openPath(logSync.logsDir); });
