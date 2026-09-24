const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("petHost", {
  ready: (info) => ipcRenderer.send("pet:ready", info),
  hover: (over) => ipcRenderer.send("pet:hover", Boolean(over)),
  dragStart: (at) => ipcRenderer.send("pet:drag-start", at),
  dragMove: (at) => ipcRenderer.send("pet:drag-move", at),
  drag: (pos) => ipcRenderer.send("pet:drag", pos),
  dragEnd: () => ipcRenderer.send("pet:drag-end"),
  menu: () => ipcRenderer.send("pet:menu"),
  quit: () => ipcRenderer.send("pet:quit"),
  log: (message) => ipcRenderer.send("pet:log", String(message)),
  saveStats: (data) => ipcRenderer.send("pet:stats", data),
  onPos: (cb) => ipcRenderer.on("pet:pos", (_e, pos) => cb(pos)),
  onPlay: (cb) => ipcRenderer.on("pet:play", (_e, name) => cb(name)),
  onSpeak: (cb) => ipcRenderer.on("pet:speak", (_e, text) => cb(text)),
  onMute: (cb) => ipcRenderer.on("pet:mute", (_e, muted) => cb(muted)),
  onList: (cb) => ipcRenderer.on("pet:list", () => cb()),
  onCmd: (cb) => ipcRenderer.on("pet:cmd", (_e, cmd) => cb(cmd)),
});
