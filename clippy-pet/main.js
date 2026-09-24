"use strict";
// Standalone Clippy desktop pet.
// - runs its own Electron instance (uses the runtime bundled with VPS, no install)
// - never reads or writes the VPS install directory
// - own window, own tray, own data folder
const { app, BrowserWindow, ipcMain, screen, Menu, Tray, nativeImage, dialog } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const zlib = require("node:zlib");

const HERE = __dirname;
const DATA_DIR = path.join(HERE, "data");
const LOG_FILE = path.join(DATA_DIR, "pet.log");
const STATE_FILE = path.join(DATA_DIR, "state.json");
const TRAY_FILE = path.join(DATA_DIR, "tray.png");

// 角色表：每个角色有自己的尺寸、页面，以及渲染页里那套动作名（换角色时菜单要跟着换）。
// 加第三个角色只要在这里加一行 + 写一个页面。
const CHARS = {
  clippy: {
    label: "Clippy 曲别针",
    page: "index.html",
    w: 124,
    h: 93,
    actions: [
      ["打招呼", "Greeting"],
      ["挥手", "Wave"],
      ["思考", "Thinking"],
      ["解释", "Explain"],
      ["恭喜", "Congratulate"],
      ["保存", "Save"],
      ["打印", "Print"],
      ["搜索", "Searching"],
      ["检查一下", "CheckingSomething"],
      ["写点东西", "Writing"],
      ["清空回收站", "EmptyTrash"],
      ["随便来一个", "__random__"],
    ],
  },
  penguin: {
    label: "QQ 企鹅",
    page: "penguin.html",
    w: 140,
    h: 140,
    actions: [
      ["打个招呼", "Hi1"],
      ["作个揖", "Hi2"],
      ["开心", "Happy"],
      ["更开心", "Happy2"],
      ["升级庆祝", "LevelUp"],
      ["出场", "Enter"],
      ["吃东西", "Eat"],
      ["洗澡", "Clean"],
      ["学习", "Speak"],
      ["犯困", "Sleep2"],
      ["趴一会儿", "ProstratePlay"],
      ["不高兴", "UpsetPlay"],
      ["随便来一个", "__random__"],
    ],
  },
};

let charKey = "clippy";
let PET_W = CHARS.clippy.w;
let PET_H = CHARS.clippy.h;

function applyChar(key) {
  const k = CHARS[key] ? key : "clippy";
  charKey = k;
  PET_W = CHARS[k].w;
  PET_H = CHARS[k].h;
  return CHARS[k];
}
// The window must stay inside the work area, so its padding around the sprite
// directly limits how far the pet can be dragged. It also has to be big enough
// for the speech balloon: measured 218x59 (plus a 15px margin) for a normal
// line, and the engine places the balloon next to the sprite. 380x200 clipped
// it completely (measured rect y=215 in a 200px window), so this is sized to
// hold sprite + balloon with room to spare.
const WIN_W = 420;
const WIN_H = 280;
const SMOKE = process.argv.includes("--smoke");
const DIAG = process.argv.includes("--diag");
// 自测用：临时指定角色，不改 state.json（--char=penguin）
function argValue(prefix) {
  for (let i = 0; i < process.argv.length; i += 1) {
    if (process.argv[i].indexOf(prefix) === 0) return process.argv[i].slice(prefix.length);
  }
  return "";
}
const FORCE_CHAR = argValue("--char=");

let win = null;
let tray = null;
let pet = { x: 0, y: 0 };
// start interactive: while click-through is on, Chromium never forwards the
// pointer, so the pet could otherwise never notice the cursor arriving
let interactive = true;
let hitTimer = null;
let watchdog = null;
let diagTimer = null;
let dragging = false;
let quitting = false;

function log() {
  try {
    fs.mkdirSync(DATA_DIR, { recursive: true });
    const parts = [];
    for (let i = 0; i < arguments.length; i += 1) parts.push(String(arguments[i]));
    fs.appendFileSync(LOG_FILE, new Date().toISOString() + " " + parts.join(" ") + "\n");
  } catch (e) {}
}

function readState() {
  try {
    const s = JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
    return {
      x: Number(s.x) || 0,
      y: Number(s.y) || 0,
      muted: Boolean(s.muted),
      visible: s.visible !== false,
      character: CHARS[s.character] ? s.character : "clippy",
      pets: s.pets && typeof s.pets === "object" ? s.pets : {},
    };
  } catch (e) {
    return { x: 0, y: 0, muted: false, visible: true, character: "clippy", pets: {} };
  }
}

function writeState(patch) {
  const next = Object.assign({}, readState(), patch);
  try {
    fs.mkdirSync(DATA_DIR, { recursive: true });
    fs.writeFileSync(STATE_FILE, JSON.stringify(next, null, 2));
  } catch (e) {
    log("state write failed", e);
  }
  return next;
}

function workArea() {
  const cursor = screen.getCursorScreenPoint();
  const display = screen.getDisplayNearestPoint(cursor) || screen.getPrimaryDisplay();
  return display.workArea;
}

function clamp(x, y) {
  const a = workArea();
  return {
    x: Math.max(a.x, Math.min(Math.round(x), a.x + a.width - PET_W)),
    y: Math.max(a.y, Math.min(Math.round(y), a.y + a.height - PET_H)),
  };
}

function defaultPet() {
  const a = workArea();
  return { x: a.x + a.width - PET_W - 40, y: a.y + a.height - PET_H - 40 };
}

// Window origin: the sprite sits in the top-left corner so the rest of the
// window is free for the speech balloon (measured 218x59 + 15px margin). With
// the sprite at the bottom-right the engine found every side blocked and the
// balloon was clipped outside the window entirely.
// The sprite is parked PET_PAD px inside the window instead of flush at (0,0).
// Reason: the engine's balloon placement (_isOut in engine/index.mjs) rejects a
// side that leaves less than 5 px of margin, so a sprite at x=0 lost every side -
// including the two "right" ones it actually fits on - and the balloon fell back
// to the last tried side and was clipped by the window edge. Measured with the
// longest poem (218x101 balloon): sprite at 0 -> fits:false, y=252 in a 280px
// window; at 8 -> fits:true. The window is allowed to hang up to PET_PAD px off
// the top/left screen edge, and that strip is transparent anyway.
const PET_PAD_X = 8;
const PET_PAD_Y = 8;

function windowOriginFor(p) {
  const a = workArea();
  return {
    x: Math.min(p.x - PET_PAD_X, a.x + a.width - WIN_W),
    y: Math.min(p.y - PET_PAD_Y, a.y + a.height - WIN_H),
  };
}

function send(channel, payload) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, payload);
}

function setInteractive(next) {
  if (!win || win.isDestroyed() || interactive === next) return;
  interactive = next;
  try {
    win.setIgnoreMouseEvents(!next, { forward: true });
    log("interactive =", next);
  } catch (e) {
    log("setIgnoreMouseEvents failed", e);
  }
}

// setIgnoreMouseEvents rebuilds the window's hit-test region and toggles
// WS_EX_TRANSPARENT on Windows, which is expensive if it flips constantly.
// The logs showed true/false/true inside 60 ms, which reads as stutter, so the
// switch is debounced: react quickly to entering, tolerate brief exits.
const ENTER_DELAY_MS = 40;
const LEAVE_DELAY_MS = 260;
let pendingState = null;
let pendingSince = 0;

function setInteractiveDebounced(next) {
  if (interactive === next) {
    pendingState = null;
    return;
  }
  if (pendingState !== next) {
    pendingState = next;
    pendingSince = Date.now();
    return;
  }
  const wait = next ? ENTER_DELAY_MS : LEAVE_DELAY_MS;
  if (Date.now() - pendingSince >= wait) {
    pendingState = null;
    setInteractive(next);
  }
}

// Click-through must be decided from the main process: while the window is
// click-through Chromium does NOT forward mouse events, so a renderer-side
// hover reporter can never turn interaction back on (the pet becomes dead to
// the mouse). Polling the OS cursor position has no such chicken-and-egg.
//
// The hit area is deliberately larger than the sprite: the paperclip has thin
// arms and transparent corners, and users aim at the shape, not its bounding
// box, so a tight rect feels broken.
const HIT_PAD_X = 26;
const HIT_PAD_Y = 22;
// hysteresis: a wider rect turns interaction on, a tighter one turns it off, so
// the window cannot flap between click-through and interactive at the boundary
const RELEASE_PAD_X = 14;
const RELEASE_PAD_Y = 12;

function petScreenRect(padX, padY) {
  return {
    x: pet.x - padX,
    y: pet.y - padY,
    w: PET_W + padX * 2,
    h: PET_H + padY * 2,
  };
}

function pointInRect(c, r) {
  return c.x >= r.x && c.x <= r.x + r.w && c.y >= r.y && c.y <= r.y + r.h;
}

function cursorOverPet() {
  if (!win || win.isDestroyed() || !win.isVisible()) return false;
  const c = screen.getCursorScreenPoint();
  // already interactive -> use the tighter release rect; otherwise the wider one
  return interactive
    ? pointInRect(c, petScreenRect(RELEASE_PAD_X, RELEASE_PAD_Y))
    : pointInRect(c, petScreenRect(HIT_PAD_X, HIT_PAD_Y));
}

// Hit loop. 80 ms keeps hover responsive while cutting the number of blocking
// getCursorScreenPoint() calls; the actual window switch is debounced.
function startHitLoop() {
  if (hitTimer) return;
  hitTimer = setInterval(function () {
    if (!win || win.isDestroyed()) return;
    if (dragging) {
      pendingState = null;
      setInteractive(true);
      return;
    }
    setInteractiveDebounced(cursorOverPet());
  }, 80);
}

// Verbose state diagnostics: only when launched with --diag (they are noisy).
let lastDiag = "";
function startDiagLoop() {
  if (!DIAG || diagTimer) return;
  diagTimer = setInterval(function () {
    if (!win || win.isDestroyed()) return;
    let snap;
    try {
      snap = [
        "vis=" + win.isVisible(),
        "focus=" + win.isFocused(),
        "aot=" + win.isAlwaysOnTop(),
        "inter=" + interactive,
        "pos=" + win.getBounds().x + "," + win.getBounds().y,
      ].join(" ");
    } catch (e) {
      return;
    }
    if (snap === lastDiag) return;
    lastDiag = snap;
    log("diag", snap);
  }, 400);
}

// Watchdog: an always-on-top transparent window can be hidden by the OS, by a
// fullscreen app or by a failed drag. Bring it back so the pet never "vanishes".
function startWatchdog() {
  if (watchdog) return;
  watchdog = setInterval(function () {
    if (!win || win.isDestroyed()) return;
    let hidden = false;
    try {
      hidden = !win.isVisible();
    } catch (e) {
      return;
    }
    if (hidden) {
      if (!readState().visible) return;
      log("watchdog: window was hidden -> showInactive");
      try {
        win.showInactive();
      } catch (e) {
        log("watchdog show failed", e);
      }
      return;
    }
    // 活着但不再置顶（被别的窗口盖住）就重新压一次 —— 用户视角就是"桌宠不见了"
    try {
      if (!win.isAlwaysOnTop()) {
        log("watchdog: lost always-on-top -> re-raise");
        raiseToTop();
      }
    } catch (e) {}
  }, 2000);
}

function stopWatchdog() {
  if (watchdog) {
    clearInterval(watchdog);
    watchdog = null;
  }
}

function stopHitLoop() {
  if (hitTimer) {
    clearInterval(hitTimer);
    hitTimer = null;
  }
}

function placePet(p, persist) {
  const c = clamp(p.x, p.y);
  pet = c;
  if (persist) writeState({ x: c.x, y: c.y });
  if (!win || win.isDestroyed()) return;
  const origin = windowOriginFor(c);
  const b = win.getBounds();
  if (b.x !== origin.x || b.y !== origin.y) {
    win.setBounds({ x: origin.x, y: origin.y, width: b.width, height: b.height });
  }
  send("pet:pos", { x: c.x - origin.x, y: c.y - origin.y });
}

function play(name) {
  send("pet:play", name);
}

function buildMenu() {
  const state = readState();
  const actions = CHARS[charKey].actions;
  return Menu.buildFromTemplate([
    {
      label: "角色",
      submenu: Object.keys(CHARS).map(function (k) {
        return {
          label: CHARS[k].label,
          type: "radio",
          checked: charKey === k,
          click: function () {
            switchChar(k);
          },
        };
      }),
    },
    { type: "separator" },
    {
      label: "动作",
      submenu: actions.map(function (pair) {
        return { label: pair[0], click: function () { play(pair[1]); } };
      }),
    },
    { type: "separator" },
    { label: "说句话", click: function () { send("pet:speak", "需要我帮你看点什么吗？"); } },
    // 企鹅专属：养成动作 + 督战官
    (function () {
      if (charKey !== "penguin") return { type: "separator" };
      return {
        label: "督战官",
        submenu: [
          { label: "现在追一下", click: function () { send("pet:cmd", "chase"); } },
          { label: "眼镜教鞭常驻（开/关）", click: function () { send("pet:cmd", "teacher"); } },
          { type: "separator" },
          { label: "三追是几点？", click: function () { send("pet:cmd", "chasetime"); } },
        ],
      };
    })(),
    (function () {
      if (charKey !== "penguin") return { type: "separator" };
      return {
        label: "养它",
        submenu: [
          { label: "喂小鱼干（10 金币）", click: function () { send("pet:cmd", "feed"); } },
          { label: "洗个澡（5 金币）", click: function () { send("pet:cmd", "bath"); } },
          { label: "逗它玩", click: function () { send("pet:cmd", "play"); } },
          { label: "哄它睡觉", click: function () { send("pet:cmd", "sleep"); } },
          { type: "separator" },
          { label: "去打工（赚金币）", click: function () { send("pet:cmd", "work"); } },
          { label: "去学习（涨经验）", click: function () { send("pet:cmd", "study"); } },
          { type: "separator" },
          { label: "看状态", click: function () { send("pet:cmd", "status"); } },
        ],
      };
    })(),    {
      label: "静音音效",
      type: "checkbox",
      checked: state.muted,
      click: function (item) {
        writeState({ muted: item.checked });
        send("pet:mute", item.checked);
      },
    },
    { type: "separator" },
    { label: "回到右下角", click: function () { placePet(defaultPet(), true); } },
    { label: "动画列表", click: function () { send("pet:list"); } },
    { type: "separator" },
    {
      label: "隐藏桌宠",
      click: function () {
        writeState({ visible: false });
        if (win && !win.isDestroyed()) win.hide();
      },
    },
    {
      label: "显示桌宠",
      click: function () {
        writeState({ visible: true });
        if (!win || win.isDestroyed()) createWindow();
        else win.showInactive();
      },
    },
    { type: "separator" },
    {
      label: "退出",
      click: function () {
        quitting = true;
        app.quit();
      },
    },
  ]);
}

// 换角色：尺寸变了要重算窗口原点，然后让渲染页重新加载成另一个角色。
function switchChar(key) {
  if (!CHARS[key] || key === charKey) return;
  applyChar(key);
  writeState({ character: key });
  const p = clamp(pet.x, pet.y);
  pet = p;
  writeState({ x: p.x, y: p.y });
  const origin = windowOriginFor(p);
  if (win && !win.isDestroyed()) {
    win.setTitle("Clippy 桌宠 - " + CHARS[key].label);
    win.setBounds({ x: origin.x, y: origin.y, width: WIN_W, height: WIN_H });
    // setBounds 有可能把窗口踢出 topmost 层（实测：切到企鹅后被 VPS 全屏窗盖住），
    // 所以改完尺寸必须重新压一次置顶。
    raiseToTop();
    loadPage(origin);
  }
  if (tray) tray.setContextMenu(buildMenu());
  log("character -> " + key + " (" + PET_W + "x" + PET_H + ")");
}

// 把桌宠重新压到最上层。"floating" 比 "screen-saver" 温和，不会跟全屏应用打架，
// 但普通最大化窗口盖不住它。
function raiseToTop() {
  if (!win || win.isDestroyed()) return false;
  try {
    win.setAlwaysOnTop(false);
    win.setAlwaysOnTop(true, "floating");
    // moveTop 把窗口挪到 z 序最前（不抢焦点），"置顶"标志还在但被压住时靠它救回来
    if (typeof win.moveTop === "function") win.moveTop();
    return win.isAlwaysOnTop();
  } catch (e) {
    log("raiseToTop failed", e);
    return false;
  }
}

// 渲染页的加载（query 里带上宠物在窗口内的位置等参数）
function loadPage(origin) {
  if (!win || win.isDestroyed()) return;
  win.loadFile(path.join(HERE, CHARS[charKey].page), {
    query: {
      x: String(pet.x - origin.x),
      y: String(pet.y - origin.y),
      muted: readState().muted ? "1" : "0",
      char: charKey,
      smoke: SMOKE ? "1" : "0",
      testDblclick: process.argv.includes("--test-dblclick") ? "1" : "0",
      testBalloon: process.argv.includes("--test-balloon") ? "1" : "0",
      testPoem: process.argv.includes("--test-poem") ? "1" : "0",
      testPet: process.argv.includes("--test-pet") ? "1" : "0",
      testChase: process.argv.includes("--test-chase") ? "1" : "0",
      sheet: process.argv.includes("--sheet") ? "1" : "0",
      teacherStrip: process.argv.includes("--teacher-strip") ? "1" : "0",
      sheetScale: argValue("--sheet-scale=") || "1",
      sheetOnly: argValue("--sheet-only=") || "",
      stats: JSON.stringify(readState().pets && readState().pets.penguin ? readState().pets.penguin : {}),
      diag: DIAG ? "1" : "0",
    },
  });
}

// ---------- tray icon: 32x32 RGBA PNG drawn in code (no asset file needed) ----------
function buildTrayPng(size, scale) {
  const s = size * scale;
  const px = Buffer.alloc(s * s * 4);
  const dots = [];
  const cx = 0.5 * s;
  const cy = 0.42 * s;
  const r = 0.3 * s;
  let i;
  for (i = 0; i < 260; i += 1) {
    const t = ((200 - i * 1.15) * Math.PI) / 180;
    dots.push([cx + r * Math.cos(t), cy + r * Math.sin(t)]);
  }
  for (i = 0; i < 200; i += 1) {
    const t = ((-60 + i) * Math.PI) / 180;
    dots.push([0.52 * s + 0.18 * s * Math.cos(t), 0.6 * s + 0.16 * s * Math.sin(t)]);
  }
  const w = 1.15 * scale;
  for (i = 0; i < dots.length; i += 1) {
    const x = dots[i][0];
    const y = dots[i][1];
    const x0 = Math.max(0, Math.floor(x - w));
    const x1 = Math.min(s - 1, Math.ceil(x + w));
    const y0 = Math.max(0, Math.floor(y - w));
    const y1 = Math.min(s - 1, Math.ceil(y + w));
    for (let yy = y0; yy <= y1; yy += 1) {
      for (let xx = x0; xx <= x1; xx += 1) {
        const d = Math.sqrt((xx - x) * (xx - x) + (yy - y) * (yy - y));
        if (d <= w) {
          const a = d <= w - 1 ? 255 : Math.round(255 * (w - d + 1));
          const o = (yy * s + xx) * 4;
          if (a > px[o + 3]) {
            px[o] = 176;
            px[o + 1] = 176;
            px[o + 2] = 184;
            px[o + 3] = a;
          }
        }
      }
    }
  }
  const raw = Buffer.alloc(size * (size * 4 + 1));
  let p = 0;
  for (let y = 0; y < size; y += 1) {
    raw[p] = 0;
    p += 1;
    for (let x = 0; x < size; x += 1) {
      let rr = 0;
      let gg = 0;
      let bb = 0;
      let aa = 0;
      for (let dy = 0; dy < scale; dy += 1) {
        for (let dx = 0; dx < scale; dx += 1) {
          const o = ((y * scale + dy) * s + (x * scale + dx)) * 4;
          rr += px[o];
          gg += px[o + 1];
          bb += px[o + 2];
          aa += px[o + 3];
        }
      }
      const n = scale * scale;
      raw[p] = Math.round(rr / n);
      raw[p + 1] = Math.round(gg / n);
      raw[p + 2] = Math.round(bb / n);
      raw[p + 3] = Math.round(aa / n);
      p += 4;
    }
  }
  function crc32(buf) {
    let c = ~0;
    for (let k = 0; k < buf.length; k += 1) {
      c ^= buf[k];
      for (let b = 0; b < 8; b += 1) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
    }
    return (~c) >>> 0;
  }
  function chunk(tag, data) {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length, 0);
    const body = Buffer.concat([Buffer.from(tag, "ascii"), data]);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(body), 0);
    return Buffer.concat([len, body, crc]);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8;
  ihdr[9] = 6;
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", zlib.deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

function trayImage() {
  try {
    if (!fs.existsSync(TRAY_FILE)) {
      fs.mkdirSync(DATA_DIR, { recursive: true });
      fs.writeFileSync(TRAY_FILE, buildTrayPng(32, 4));
      log("tray icon generated");
    }
    const img = nativeImage.createFromPath(TRAY_FILE);
    if (img && !img.isEmpty()) return img.resize({ width: 16, height: 16 });
    log("tray icon empty");
  } catch (e) {
    log("tray icon failed", e);
  }
  return null;
}

function createTray() {
  try {
    const img = trayImage();
    if (!img) return null;
    tray = new Tray(img);
    tray.setToolTip("Clippy 桌宠");
    tray.setContextMenu(buildMenu());
    tray.on("double-click", function () {
      play("Greeting");
      if (win && !win.isDestroyed()) win.showInactive();
    });
    log("tray created");
    return tray;
  } catch (e) {
    log("tray failed", e);
    return null;
  }
}

function onDisplayChange() {
  if (!win || win.isDestroyed()) return;
  placePet(pet, false);
}

function createWindow() {
  const state = readState();
  applyChar(FORCE_CHAR || state.character); // 尺寸要在这个角色下算，窗口原点才对
  const start = state.x || state.y ? clamp(state.x, state.y) : defaultPet();
  const origin = windowOriginFor(start);
  pet = start;

  win = new BrowserWindow({
    x: origin.x,
    y: origin.y,
    width: WIN_W,
    height: WIN_H,
    frame: false,
    transparent: true,
    backgroundColor: "#00000000",
    hasShadow: false,
    resizable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    show: false,
    focusable: true,
    roundedCorners: false,
    title: "Clippy 桌宠 - " + CHARS[charKey].label,
    webPreferences: {
      preload: path.join(HERE, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
    },
  });

  // "floating" keeps the pet above normal windows without the screen-saver
  // level, which fights other apps and can make windows flicker or hide.
  // setVisibleOnAllWorkspaces is a macOS concept - dropped on win32.
  win.setAlwaysOnTop(true, "floating");
  try {
    win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: false });
  } catch (e) {}
  win.setMenuBarVisibility(false);
  // 刚创建也可能被 VPS 那种整屏窗口压住，统一走一次 raiseToTop
  raiseToTop();
  // keep the window interactive at first; the renderer switches to click-through
  // as soon as it knows the pointer is not over the pet
  interactive = true;

  win.webContents.on("console-message", function (_e, level, message) {
    log("renderer", level, message);
  });
  win.webContents.on("render-process-gone", function (_e, details) {
    log("renderer gone", JSON.stringify(details));
  });
  win.webContents.on("did-fail-load", function (_e, code, desc, url) {
    log("did-fail-load", code, desc, url);
  });
  win.webContents.on("did-finish-load", function () {
    log("renderer loaded");
    // 换角色时会重新 loadFile：新页面画出来之后必须再压一次置顶 + 触发重绘，
    // 否则透明分层窗口可能停在"内容已更新但屏幕上还是空的"状态（用户视角就是桌宠没了）
    setTimeout(function () {
      if (!win || win.isDestroyed()) return;
      raiseToTop();
      try {
        if (win.webContents && win.webContents.invalidate) win.webContents.invalidate();
      } catch (e) {}
    }, 120);
  });

  loadPage(origin);

  win.once("ready-to-show", function () {
    if (readState().visible) win.showInactive();
    log("window ready", JSON.stringify({ pet: pet, origin: origin, smoke: SMOKE, char: charKey }));
    // 动作接触表：渲染页把每个动作的多个时间点画进一张大 canvas，这里取回 PNG 存盘
    if (process.argv.includes("--sheet")) {
      setTimeout(async function () {
        try {
          const dataUrl = await win.webContents.executeJavaScript(
            "window.__sheetPng ? window.__sheetPng() : ''",
          );
          if (dataUrl && dataUrl.indexOf("base64,") > 0) {
            const out = path.join(DATA_DIR, "penguin-sheet.png");
            fs.writeFileSync(out, Buffer.from(dataUrl.split("base64,")[1], "base64"));
            log("sheet written", out, fs.statSync(out).size);
          } else {
            log("sheet probe returned nothing");
          }
        } catch (e) {
          log("sheet capture failed", e);
        }
        setTimeout(function () {
          quitting = true;
          app.quit();
        }, 200);
      }, 2000);
    }
    if (SMOKE) {
      setTimeout(async function () {
        try {
          const state = await win.webContents.executeJavaScript("window.__balloonState ? window.__balloonState() : 'no-hook'");
          log("balloon state at capture:", state);
        } catch (e) {
          log("balloon probe failed", e);
        }
        try {
          const image = await win.webContents.capturePage();
          const out = path.join(DATA_DIR, "smoke-shot.png");
          fs.writeFileSync(out, image.toPNG());
          log("smoke shot written", out);
        } catch (e) {
          log("smoke capture failed", e);
        }
        setTimeout(function () {
          quitting = true;
          app.quit();
        }, 300);
      }, 2000);
    }
  });

  win.on("hide", function () {
    log("window hide event");
  });
  win.on("minimize", function () {
    log("window minimize event");
  });
  win.on("closed", function () {
    win = null;
    stopHitLoop();
    stopWatchdog();
  });

  startHitLoop();
  startWatchdog();
  startDiagLoop();

  screen.on("display-metrics-changed", onDisplayChange);
  screen.on("display-added", onDisplayChange);
  screen.on("display-removed", onDisplayChange);
}

ipcMain.on("pet:hover", function () {
  // The renderer's hover reports are intentionally ignored: the renderer only
  // sees events while the window is already interactive, so its reports fight
  // the main-process hit loop and made the window flap between click-through
  // and interactive (clicks then fell through to the desktop). The hit loop is
  // the single source of truth.
  if (dragging) return;
});
// Window drag.
//
// win.startDrag() does NOT exist on Electron 33's BrowserWindow (verified:
// "win.startDrag is not a function"), so dragging is done by moving the window
// by the pointer delta. Delta-based moves avoid all coordinate-space issues and
// setPosition is throttled to one move per animation frame.
let dragPos = null;
let dragRaf = null;

ipcMain.on("pet:drag-start", function (_e, at) {  if (!win || win.isDestroyed()) return;
  dragging = true;
  setInteractive(true);
  const b = win.getBounds();
  // the sprite's offset inside the window never changes during a window move
  const local = { x: pet.x - b.x, y: pet.y - b.y };
  const c = at && Number.isFinite(at.x) && Number.isFinite(at.y) ? { x: Number(at.x), y: Number(at.y) } : screen.getCursorScreenPoint();
  dragPos = { winX: b.x, winY: b.y, cursor: { x: c.x, y: c.y }, local: local, moves: 0 };
  log("drag start", JSON.stringify({ win: { x: b.x, y: b.y }, local: local, cursor: dragPos.cursor }));
});

ipcMain.on("pet:drag-move", function (_e, at) {
  if (!dragging || !win || win.isDestroyed() || !dragPos) return;
  if (!at || !Number.isFinite(at.x) || !Number.isFinite(at.y)) return;
  const dx = Number(at.x) - dragPos.cursor.x;
  const dy = Number(at.y) - dragPos.cursor.y;
  dragPos.cursor = { x: Number(at.x), y: Number(at.y) };
  dragPos.winX += dx;
  dragPos.winY += dy;
  if (dragRaf) return;
  dragRaf = setTimeout(function () {
    dragRaf = null;
    if (!win || win.isDestroyed() || !dragging || !dragPos) return;
    try {
      win.setPosition(Math.round(dragPos.winX), Math.round(dragPos.winY));
    } catch (e) {
      log("setPosition failed", e);
    }
  }, 16);
});

ipcMain.on("pet:drag-end", function () {
  if (dragRaf) {
    clearTimeout(dragRaf);
    dragRaf = null;
  }
  if (win && !win.isDestroyed() && dragPos) {
    try {
      const b = win.getBounds();
      const moved = { x: Math.round(b.x + dragPos.local.x), y: Math.round(b.y + dragPos.local.y) };
      log("drag end raw", JSON.stringify({ win: { x: b.x, y: b.y }, moved: moved }));
      pet = clamp(moved.x, moved.y);
      const origin = windowOriginFor(pet);
      if (b.x !== origin.x || b.y !== origin.y) {
        win.setBounds({ x: origin.x, y: origin.y, width: b.width, height: b.height });
      }
      send("pet:pos", { x: pet.x - origin.x, y: pet.y - origin.y });
    } catch (e) {
      log("drag-end sync failed", e);
    }
  }
  dragging = false;
  dragPos = null;
  writeState({ x: pet.x, y: pet.y });
  log("drag end", JSON.stringify(pet));
  setInteractive(cursorOverPet());
});

// legacy absolute-position drag channel (kept registered, not used by the
// renderer anymore; the delta-based pet:drag-move path replaced it)
ipcMain.on("pet:drag", function (_e, pos) {
  if (!pos) return;
  const b = win && !win.isDestroyed() ? win.getBounds() : { x: 0, y: 0 };
  placePet({ x: b.x + Number(pos.x), y: b.y + Number(pos.y) }, false);
});
ipcMain.on("pet:menu", function () {
  const menu = buildMenu();
  if (win && !win.isDestroyed()) menu.popup({ window: win });
  else if (tray) tray.popUpContextMenu(menu);
});
ipcMain.on("pet:log", function (_e, message) {
  log("renderer:", String(message));
});
ipcMain.on("pet:ready", function (_e, info) {
  log("ready", JSON.stringify(info));
});
// 养成数值由渲染页算，主进程只负责落盘（渲染页没有 fs 权限）
ipcMain.on("pet:stats", function (_e, data) {
  try {
    const s = readState();
    const pets = Object.assign({}, s.pets);
    pets.penguin = data && typeof data === "object" ? data : {};
    writeState({ pets: pets });
  } catch (e) {
    log("stats save failed", e);
  }
});
ipcMain.on("pet:quit", function () {
  quitting = true;
  app.quit();
});

app.on("window-all-closed", function () {
  if (quitting || SMOKE) app.quit();
});
process.on("uncaughtException", function (e) {
  log("uncaught", e && e.stack ? e.stack : e);
  try {
    dialog.showErrorBox("Clippy 桌宠出错", String((e && e.stack) || e).slice(0, 900));
  } catch (x) {}
});

app.whenReady().then(function () {
  log("start; electron", process.versions.electron, "data", DATA_DIR);
  createTray();
  const state = readState();
  log("state", JSON.stringify(state));
  if (state.visible || SMOKE) createWindow();

  // 自测：来回切一次角色，验证尺寸/窗口原点/页面重载都对（结束后切回原角色）
  if (process.argv.includes("--test-switch")) {
    const back = FORCE_CHAR || state.character;
    const other = back === "penguin" ? "clippy" : "penguin";
    setTimeout(function () {
      log("TEST switch -> " + other);
      switchChar(other);
    }, 3500);
    setTimeout(function () {
      log("TEST switch back -> " + back);
      switchChar(back);
    }, 9000);
    setTimeout(function () {
      const s = readState();
      log("TEST final state " + JSON.stringify({ character: s.character, pet: pet, win: win ? win.getBounds() : null }));
      quitting = true;
      app.quit();
    }, 13500);
  }
});
