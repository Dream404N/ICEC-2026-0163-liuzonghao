const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('reminderPopup', {
  content: () => ipcRenderer.invoke('popup-content'),
  action: action => ipcRenderer.invoke('popup-action', action),
});
