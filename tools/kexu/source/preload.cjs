const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('kexu', {
  schedule: (reminders, sound) => ipcRenderer.invoke('schedule', reminders, sound),
  testNotification: (reminder, sound) => ipcRenderer.invoke('test-notification', reminder, sound),
  notificationStatus: () => ipcRenderer.invoke('notification-status'),
  setAutoStart: enabled => ipcRenderer.invoke('auto-start', enabled),
  getAutoStart: () => ipcRenderer.invoke('get-auto-start'),
  // 运行日志与 GitHub 自动提交
  logSyncStatus: () => ipcRenderer.invoke('log-sync-status'),
  syncLogsNow: () => ipcRenderer.invoke('log-sync-now'),
  setLogSyncConfig: patch => ipcRenderer.invoke('log-sync-config', patch),
  openLogsDir: () => ipcRenderer.invoke('log-sync-open'),
});
