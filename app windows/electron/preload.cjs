const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktop", {
  version: () => "1.0.0",
  setTitleBarTheme: (theme) => ipcRenderer.send("set-titlebar-theme", theme),
  toggleFloatChat: () => ipcRenderer.send("float-toggle-chat"),
  openMainTab: (tab) => ipcRenderer.send("open-main-tab", tab),
  showFloat: () => ipcRenderer.send("float-show"),
  hideFloat: () => ipcRenderer.send("float-hide"),
  startFloatDrag: (payload) => ipcRenderer.send("float-drag-start", payload),
  updateFloatDrag: (payload) => ipcRenderer.send("float-drag-move", payload),
  endFloatDrag: () => ipcRenderer.send("float-drag-end"),
  setFloatInteractive: (enabled) => ipcRenderer.send("float-set-interactive", enabled),
  notifySystem: (payload) => ipcRenderer.send("notify-system", payload),
  setBackendSession: (payload) => ipcRenderer.invoke("backend-session:set", payload),
  clearBackendSession: () => ipcRenderer.invoke("backend-session:clear"),
  onBridgeStatus: (handler) => {
    if (typeof handler !== "function") return () => {};
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on("bridge-status", listener);
    return () => ipcRenderer.removeListener("bridge-status", listener);
  },
  onNavigate: (handler) => {
    if (typeof handler !== "function") return () => {};
    const listener = (_event, tab) => handler(tab);
    ipcRenderer.on("navigate-tab", listener);
    return () => ipcRenderer.removeListener("navigate-tab", listener);
  },
});
