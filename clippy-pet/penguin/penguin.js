// 企鹅桌宠的渲染页（原版素材版）。
// 动画不再手画，而是播 QQ 企鹅原版的 Flash 帧（导成 WebP 精灵图，12 fps）。
// 宿主 IPC（拖拽/点击穿透/右键菜单/托盘/气泡）与 Clippy 那只完全共用。

import { FramePlayer, FRAME_MS } from "./frames.mjs";
import { CELL } from "./sheets/sheets.mjs";
import { POEMS } from "../poems.mjs";
import { LINES, pickLine } from "./lines.mjs";
import { CHASE_TIMES, chaseFor, roundForDate, todayKey, TEACHER_TAIL } from "./chase.mjs";
import { measure, drawTeacher } from "./teacher.mjs";
import {
  normalize,
  settle,
  sleepSettle,
  applyAction,
  worstStat,
  expNeeded,
  ACTIONS,
} from "./nurture.mjs";

const PET_W = CELL[0];
const PET_H = CELL[1];

const host =
  window.petHost ||
  (() => {
    const noop = () => {};
    return {
      ready: noop,
      hover: noop,
      dragStart: noop,
      dragMove: noop,
      dragEnd: noop,
      menu: noop,
      quit: noop,
      log: (m) => console.log("[penguin]", m),
      onPos: noop,
      onPlay: noop,
      onSpeak: noop,
      onMute: noop,
      onList: noop,
      onCmd: noop,
      saveStats: noop,
    };
  })();

const params = new URLSearchParams(location.search);
const diag = params.get("diag") === "1";
const testDblclick = params.get("testDblclick") === "1";
const testPoem = params.get("testPoem") === "1";
const testPet = params.get("testPet") === "1";
const sheetMode = params.get("sheet") === "1";

function log(m) {
  try {
    host.log(m);
  } catch (e) {}
}

// ------------------------------------------------------------------ 画布
const canvas = document.getElementById("penguin");
const ctx = canvas.getContext("2d");
const DPR = Math.max(1, Math.min(3, window.devicePixelRatio || 1));
canvas.width = Math.round(PET_W * DPR);
canvas.height = Math.round(PET_H * DPR);
canvas.style.width = PET_W + "px";
canvas.style.height = PET_H + "px";
ctx.scale(DPR, DPR);

let pos = { x: Number(params.get("x")) || 0, y: Number(params.get("y")) || 0 };
canvas.style.left = pos.x + "px";
canvas.style.top = pos.y + "px";

const player = new FramePlayer(ctx);

// ------------------------------------------------------------------ 督战官（眼镜 + 教鞭）
let teacherUntil = 0; // 这个时间点之前一直戴着
let alwaysTeacher = false;
let lastChaseKey = ""; // "YYYY-MM-DD:第几追"，写进 state.json，重启不重复追
const boundsCache = {};

player.afterDraw = function (idx, name, cw, ch) {
  if (!alwaysTeacher && Date.now() > teacherUntil) return;
  const key = name + ":" + idx;
  let b = boundsCache[key];
  if (b === undefined) {
    // getImageData 用的是设备像素，除以 DPR 换回 CSS 像素
    const m = measure(ctx, canvas.width, canvas.height);
    b = m
      ? {
          all: { x: m.all.x / DPR, y: m.all.y / DPR, w: m.all.w / DPR, h: m.all.h / DPR },
          face: m.face
            ? { x: m.face.x / DPR, y: m.face.y / DPR, w: m.face.w / DPR, h: m.face.h / DPR }
            : null,
        }
      : null;
    boundsCache[key] = b;
  }
  const swing = 0.5 + 0.5 * Math.sin(performance.now() / 240);
  drawTeacher(ctx, b, cw, ch, swing);
};

// ------------------------------------------------------------------ 气泡
const balloon = document.getElementById("balloon");
const btext = document.getElementById("btext");
let hideTimer = null;

function placeBalloon() {
  const panelEl = document.getElementById("panel");
  const panelOpen = !!panelEl && panelEl.style.display === "block";
  balloon.style.maxWidth = panelOpen ? "186px" : "250px";
  balloon.style.display = "block";
  const bw = balloon.offsetWidth;
  const bh = balloon.offsetHeight;
  const W = window.innerWidth;
  const H = window.innerHeight;
  const gap = 8;
  const pr = panelOpen ? panelEl.getBoundingClientRect() : null;
  const cands = [
    { side: "top", left: pos.x + PET_W / 2 - bw / 2, top: pos.y - bh - gap },
    { side: "left", left: pos.x - bw - gap, top: pos.y + PET_H / 2 - bh / 2 },
    { side: "right", left: pos.x + PET_W + gap, top: pos.y + PET_H / 2 - bh / 2 },
    { side: "bottom", left: pos.x + PET_W / 2 - bw / 2, top: pos.y + PET_H + gap },
  ];
  if (pr) {
    cands.push({ side: "top", left: pos.x + PET_W / 2 - bw / 2, top: pr.top - bh - gap });
    cands.push({ side: "bottom", left: pos.x + PET_W / 2 - bw / 2, top: pr.bottom + gap });
  }
  const petRect = { left: pos.x - 2, top: pos.y - 2, right: pos.x + PET_W + 2, bottom: pos.y + PET_H + 2 };
  const hits = function (r, q) {
    if (!q) return false;
    return !(r.right < q.left + 4 || r.left > q.right - 4 || r.bottom < q.top + 4 || r.top > q.bottom - 4);
  };
  let chosen = null;
  let fallback = null;
  for (let i = 0; i < cands.length; i += 1) {
    const c = cands[i];
    const left = Math.max(4, Math.min(c.left, W - bw - 4));
    const top = Math.max(4, Math.min(c.top, H - bh - 4));
    const r = { left: left, top: top, right: left + bw, bottom: top + bh };
    const fitsInWin = r.left >= 2 && r.top >= 2 && r.right <= W - 2 && r.bottom <= H - 2;
    if (!fitsInWin) continue;
    if (!fallback) fallback = { left: left, top: top, side: c.side };
    if (hits(r, petRect) || hits(r, pr)) continue;
    chosen = { left: left, top: top, side: c.side };
    break;
  }
  const pickPos = chosen || fallback || {
    left: Math.max(4, Math.min(cands[0].left, W - bw - 4)),
    top: Math.max(4, Math.min(cands[0].top, H - bh - 4)),
    side: "top",
  };
  balloon.style.left = Math.round(pickPos.left) + "px";
  balloon.style.top = Math.round(pickPos.top) + "px";
  let tip = balloon.querySelector(".tip");
  if (!tip) {
    tip = document.createElement("div");
    tip.className = "tip";
    balloon.appendChild(tip);
  }
  const px = pos.x + PET_W / 2;
  const py = pos.y + PET_H / 2;
  if (pickPos.side === "top" || pickPos.side === "bottom") {
    const tx = Math.max(10, Math.min(bw - 22, px - pickPos.left - 6));
    tip.style.left = Math.round(tx) + "px";
    tip.style.top = pickPos.side === "top" ? bh - 7 + "px" : "-6px";
    tip.style.transform = pickPos.side === "top" ? "rotate(45deg)" : "rotate(-135deg)";
  } else {
    const ty = Math.max(10, Math.min(bh - 22, py - pickPos.top - 6));
    tip.style.top = Math.round(ty) + "px";
    tip.style.left = pickPos.side === "right" ? "-6px" : bw - 7 + "px";
    tip.style.transform = pickPos.side === "right" ? "rotate(-45deg)" : "rotate(135deg)";
  }
}

function say(text, holdMs) {
  if (hideTimer) clearTimeout(hideTimer);
  btext.textContent = text;
  balloon.style.display = "none";
  placeBalloon();
  const hold = holdMs || Math.max(2400, Math.min(7000, 1200 + 110 * text.length));
  hideTimer = setTimeout(function () {
    balloon.style.display = "none";
  }, hold);
}

window.__balloonState = function () {
  const r = balloon.getBoundingClientRect();
  return JSON.stringify({
    display: getComputedStyle(balloon).display,
    text: (btext.textContent || "").slice(0, 20),
    rect: { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) },
    win: { w: window.innerWidth, h: window.innerHeight },
    fits: r.left >= 0 && r.top >= 0 && r.right <= window.innerWidth && r.bottom <= window.innerHeight,
  });
};

// ------------------------------------------------------------------ 台词 & 诗
const POEMS_PARSED = POEMS.map(function (raw) {
  const i = raw.lastIndexOf("|");
  return { t: raw.slice(0, i), a: raw.slice(i + 1) };
});
const POEM_RATIO = 0.75;

function pick(list) {
  return list[Math.floor(Math.random() * list.length)];
}

// ------------------------------------------------------------------ 养成
let stats = normalize((function () {
  try {
    return JSON.parse(params.get("stats") || "{}");
  } catch (e) {
    return {};
  }
})());
let sleeping = false;
let lastComplain = 0;
let busyUntil = 0;
let muted = params.get("muted") === "1";

function save() {
  try {
    host.saveStats(stats);
  } catch (e) {}
}

// 成长阶段：1 级是蛋，2-4 级幼年，5 级起成年（用原版三套素材）
function stage() {
  if (stats.level <= 1) return "egg";
  if (stats.level <= 4) return "kid";
  return "adult";
}

const IDLE_POOL = {
  egg: ["EggStand"],
  kid: ["KidStand"],
  adult: ["Idle1", "Idle2", "Idle3", "Idle4", "Idle5", "GGIdle"],
};
const REACT_POOL = ["Happy", "Happy2", "Hi1", "Hi2", "Hi3", "HappyHi", "LevelUp", "Enter", "UpsetPlay"];

function idleNext() {
  const face = faceAnim();
  if (face) player.play(face);
  else player.play(pick(IDLE_POOL[stage()]));
}

// 按身体状态挑表情动作
function faceAnim() {
  if (sleeping) return stage() === "adult" ? "ProstratePlay" : null;
  const worst = worstStat(stats);
  if (worst[1] >= 30) return null;
  if (worst[0] === "full") return stage() === "kid" ? "KidHungry" : "UpsetPlay";
  if (worst[0] === "clean") return stage() === "kid" ? "KidDirty" : "Sleep2";
  if (worst[0] === "mood") return "SadPlay";
  if (worst[0] === "energy") return "ProstratePlay";
  return null;
}

function showPanel(on) {
  const p = document.getElementById("panel");
  if (!on) {
    p.style.display = "none";
    return;
  }
  const bar = function (label, v, color) {
    return (
      '<div class="row"><span>' + label + '</span><div class="bar"><i style="width:' +
      Math.round(v) + "%;background:" + color + '"></i></div></div>'
    );
  };
  const stageName = { egg: "蛋", kid: "幼年", adult: "成年" }[stage()];
  p.innerHTML =
    "<h4>🐧 Lv." + stats.level + "　" + stageName + "　🪙 " + stats.coins + "</h4>" +
    bar("经验", (stats.exp / expNeeded(stats.level)) * 100, "#7fb2ff") +
    bar("饱食", stats.full, "#ffb02e") +
    bar("清洁", stats.clean, "#61c9f2") +
    bar("心情", stats.mood, "#ff7a9c") +
    bar("精力", stats.energy, "#8bd36b") +
    '<div class="foot">右键 →「养它」可以喂食 / 洗澡 / 逗它玩 / 打工 / 学习<br>升到 Lv.2 变幼年，Lv.5 起成年</div>';
  p.style.display = "block";
  const W = window.innerWidth;
  const H = window.innerHeight;
  const w = p.offsetWidth;
  const h = p.offsetHeight;
  const preferLeft = pos.x + PET_W / 2 > W / 2;
  const left = preferLeft ? 4 : Math.max(4, W - w - 4);
  let top = pos.y + PET_H - h;
  top = Math.max(4, Math.min(top, H - h - 4));
  p.style.left = Math.round(left) + "px";
  p.style.top = Math.round(top) + "px";
  if (balloon.style.display === "block") placeBalloon();
}

function actionAnim(key) {
  const st = stage();
  if (key === "feed") return st === "kid" ? "KidEat" : st === "egg" ? "EggAppear" : "Eat";
  if (key === "bath") return "Clean";
  if (key === "play") return "Happy";
  if (key === "sleep") return "Sleep2";
  if (key === "work") return "Clean2";
  if (key === "study") return "Speak";
  return "Happy";
}

function doAction(key) {
  const now = Date.now();
  if (key === "status") {
    const p = document.getElementById("panel");
    showPanel(p.style.display !== "block");
    return;
  }
  const r = applyAction(stats, key, now);
  if (!r.ok) {
    say(r.reason);
    player.play("UpsetPlay");
    log("action " + key + " refused: " + r.reason);
    return;
  }
  const before = stage();
  stats = r.stats;
  sleeping = key === "sleep";
  const anim = actionAnim(key);
  busyUntil = now + (player.frameCount(anim) * FRAME_MS) + 400;
  player.play(anim, key === "sleep" ? null : idleNext);
  say(r.line);
  save();
  log(
    "action " + key + " anim=" + anim + " -> full=" + Math.round(stats.full) +
      " clean=" + Math.round(stats.clean) + " mood=" + Math.round(stats.mood) +
      " energy=" + Math.round(stats.energy) + " lv=" + stats.level +
      " exp=" + Math.round(stats.exp) + " coins=" + stats.coins,
  );
  if (before !== stage()) {
    setTimeout(function () {
      say("我长大啦！现在是" + { egg: "蛋", kid: "幼年企鹅", adult: "成年企鹅" }[stage()] + "了。", 4200);
      player.play("LevelUp", idleNext);
    }, 600);
  } else if (r.leveled) {
    setTimeout(function () {
      player.play("LevelUp", idleNext);
      say(pickLine("levelUp") + "（Lv." + stats.level + "）", 4200);
    }, 900);
  }
  const panel = document.getElementById("panel");
  if (panel.style.display === "block") showPanel(true);
}

function tick() {
  const now = Date.now();
  const beforeLv = stats.level;
  const beforeStage = stage();
  const res = sleeping ? { stats: sleepSettle(stats, now), events: [] } : settle(stats, now);
  stats = res.stats;
  if (sleeping && stats.energy >= 99) {
    sleeping = false;
    player.play("Wake", idleNext);
    say("睡饱啦，精神百倍！");
  }
  save();
  if (stats.level !== beforeLv && beforeStage === stage()) {
    player.play("LevelUp", idleNext);
    say(pickLine("levelUp") + "（Lv." + stats.level + "）", 4200);
  }
  const panel = document.getElementById("panel");
  if (panel.style.display === "block") showPanel(true);
  if (Date.now() < busyUntil || sleeping) return;
  const worst = worstStat(stats);
  if (worst[1] < 30 && Date.now() - lastComplain > 3 * 60000) {
    lastComplain = Date.now();
    const kind =
      worst[0] === "full" ? "hungry" : worst[0] === "clean" ? "dirty" : worst[0] === "mood" ? "lonely" : "sleepy";
    player.play(faceAnim() || "UpsetPlay", idleNext);
    say(pickLine(kind));
    log("complain " + kind + " (" + worst[0] + "=" + Math.round(worst[1]) + ")");
  }
}

// ------------------------------------------------------------------ 三追
// 每天 09:30 / 14:00 / 17:30 各追一次：早追待办、午追业绩、晚追进度+收尾。
// 刻意不读任何数据，就是敲打；错过的那一追重启后会补一次（每次只补一次，记在 stats.lastChase）。
function doChase(round, manual) {
  const now = Date.now();
  const c = chaseFor(round);
  teacherUntil = now + 15000;
  const anim = pick(["Speak", "Hi1", "UpsetPlay"]);
  player.play(player.has(anim) ? anim : "Speak", idleNext);
  const tail = manual ? "" : "\n" + pick(TEACHER_TAIL);
  say("【第" + (round + 1) + "追·" + { todo: "待办", perf: "业绩", project: "进度" }[c.topic] + "】" + c.text + tail, 9000);
  busyUntil = now + 6000;
  log("chase #" + (round + 1) + " (" + c.topic + ")" + (manual ? " [手动]" : "") + " -> " + c.text.replace(/\n/g, " "));
  const panel = document.getElementById("panel");
  if (panel.style.display === "block") showPanel(true);
}

function chaseCheck() {
  const now = new Date();
  const r = roundForDate(now);
  if (r < 0) return;
  const key = todayKey(now) + ":" + r;
  if (key === lastChaseKey || key === stats.lastChase) return;
  lastChaseKey = key;
  stats.lastChase = key;
  save();
  doChase(r, false);
}

// ------------------------------------------------------------------ 双击互动
function doRandomInteraction() {
  const t0 = performance.now();
  const name = pick(REACT_POOL).replace(/^/, "");
  player.play(player.has(name) ? name : "Happy", idleNext);
  const asPoem = Math.random() < POEM_RATIO;
  if (asPoem) {
    const p = pick(POEMS_PARSED);
    say(p.t + "\n——" + p.a);
  } else {
    say(pick(LINES.happy));
  }
  log("double click -> action=" + name + (asPoem ? " poem" : " line") + " dispatch=" + Math.round(performance.now() - t0) + "ms");
}

// ------------------------------------------------------------------ 交互
let dragging = false;
let dragged = false;
let downAt = null;

canvas.addEventListener("mousedown", function (e) {
  if (e.button !== 0) return;
  e.preventDefault();
  dragging = true;
  dragged = false;
  downAt = { x: e.screenX, y: e.screenY, t: Date.now() };
  host.dragStart({ x: Math.round(e.screenX), y: Math.round(e.screenY) });
});

window.addEventListener("mousemove", function (e) {
  if (!dragging) return;
  if (!dragged) {
    const dx = e.screenX - downAt.x;
    const dy = e.screenY - downAt.y;
    if (dx * dx + dy * dy < 9) return;
    dragged = true;
  }
  host.dragMove({ x: Math.round(e.screenX), y: Math.round(e.screenY) });
});

window.addEventListener("mouseup", function (e) {
  if (!dragging) return;
  dragging = false;
  host.dragEnd();
  if (!dragged && Date.now() - downAt.t < 400) player.play("Hi1", idleNext);
  downAt = null;
});

canvas.addEventListener("dblclick", function (e) {
  e.preventDefault();
  if (dragged) return;
  doRandomInteraction();
});

canvas.addEventListener("contextmenu", function (e) {
  e.preventDefault();
  host.menu();
});

host.onPos(function (p) {
  pos = { x: Number(p.x) || 0, y: Number(p.y) || 0 };
  canvas.style.left = pos.x + "px";
  canvas.style.top = pos.y + "px";
  if (balloon.style.display === "block") placeBalloon();
});
host.onPlay(function (name) {
  if (!player.play(name, idleNext)) log("unknown animation: " + name);
});
host.onSpeak(function (text) {
  say(text);
});
host.onMute(function (m) {
  muted = !!m;
});
host.onList(function () {
  log("animations(" + player.names().length + "): " + player.names().join(" "));
});
host.onCmd(function (cmd) {
  const c = String(cmd);
  if (c === "chase") {
    const r = roundForDate(new Date());
    doChase(r < 0 ? 0 : r, true);
    return;
  }
  if (c === "teacher") {
    alwaysTeacher = !alwaysTeacher;
    teacherUntil = alwaysTeacher ? Number.MAX_SAFE_INTEGER : 0;
    say(alwaysTeacher ? "督战官模式：开。我盯着你。" : "督战官下班了，我正常待着。", 3600);
    log("teacher mode = " + alwaysTeacher);
    return;
  }
  if (c === "chasetime") {
    say("每天三追：" + CHASE_TIMES.join(" / ") + "\n到点我自己来，想看现在就来一下：右键 →「督战官 → 现在追一下」。", 7000);
    return;
  }
  doAction(c);
});

// ------------------------------------------------------------------ 动作接触表（自检）
// 必须在精灵图加载完之后才能画，所以放在 boot 里调用
function buildSheet() {
  const SAMPLES = 6;
  const names = player.names();
  const sheet = document.createElement("canvas");
  sheet.width = PET_W * SAMPLES;
  sheet.height = PET_H * names.length;
  const sctx = sheet.getContext("2d");
  sctx.fillStyle = "#f2f2ef";
  sctx.fillRect(0, 0, sheet.width, sheet.height);
  sctx.font = "11px monospace";
  let drawn = 0;
  names.forEach(function (n, row) {
    const img = player.images[n];
    if (!img) return;
    drawn++;
    const cnt = player.frameCount(n);
    for (let i = 0; i < SAMPLES; i++) {
      const idx = Math.floor((i / SAMPLES) * cnt);
      sctx.drawImage(
        img, (idx % 10) * PET_W, Math.floor(idx / 10) * PET_H, PET_W, PET_H,
        i * PET_W, row * PET_H, PET_W, PET_H,
      );
    }
    sctx.fillStyle = "rgba(255,255,255,0.85)";
    sctx.fillRect(0, row * PET_H, 92, 14);
    sctx.fillStyle = "#333";
    sctx.fillText(n + " " + cnt + "f", 3, row * PET_H + 11);
  });
  sheet.style.position = "fixed";
  sheet.style.left = "0";
  sheet.style.top = "0";
  sheet.style.zIndex = "9999";
  document.body.appendChild(sheet);
  window.__sheetPng = function () {
    return sheet.toDataURL("image/png");
  };
  log("sheet ready: " + drawn + "/" + names.length + " anims x " + SAMPLES + " samples, " + sheet.width + "x" + sheet.height);
}

// ------------------------------------------------------------------ 启动
(async function boot() {
  const t0 = performance.now();
  const n = await player.load(function (done, total) {
    if (done === total) log("sheets loaded " + done + "/" + total + " in " + Math.round(performance.now() - t0) + "ms");
  });
  log("frames ready: " + n + " animations, " + (window.devicePixelRatio || 1) + "x dpr");
  if (sheetMode) {
    if (params.get("teacherStrip") === "1" && window.__buildTeacherStrip) {
      await window.__buildTeacherStrip();
      log("teacher strip ready");
    } else {
      buildSheet();
    }
  } else {
    player.play(pick(IDLE_POOL[stage()]));
    player.start();
    setTimeout(function () {
      try {
        tick();
      } catch (e) {
        log("first tick failed: " + e);
      }
      setInterval(tick, 20000);
      // 三追：每分钟看一次表，到点就追
      setTimeout(function () {
        try {
          chaseCheck();
        } catch (e) {
          log("first chase failed: " + e);
        }
        setInterval(chaseCheck, 60000);
      }, 6000);
    }, 3000);
  }
  const info = { w: PET_W, h: PET_H, animations: player.names().length, muted: muted, display: "block" };
  host.ready(info);
  log("booted " + JSON.stringify(info));
})();

// 自检：双击
if (testDblclick) {
  setTimeout(function () {
    const samples = [];
    const t0 = performance.now();
    [120, 300, 900, 3000].forEach(function (ms) {
      setTimeout(function () {
        samples.push({
          t: Math.round(performance.now() - t0),
          anim: player.name,
          balloon: balloon.style.display === "block" ? btext.textContent.slice(0, 12) : "-",
        });
      }, ms);
    });
    const opts = { bubbles: true, cancelable: true, detail: 2, button: 0, clientX: 60, clientY: 60 };
    canvas.dispatchEvent(new MouseEvent("mousedown", opts));
    window.dispatchEvent(new MouseEvent("mouseup", opts));
    canvas.dispatchEvent(new MouseEvent("dblclick", opts));
    setTimeout(function () {
      log("test-dblclick timeline: " + JSON.stringify(samples));
      log("test-dblclick balloon: " + window.__balloonState());
      setTimeout(function () {
        host.quit();
      }, 300);
    }, 3200);
  }, 1200);
}

if (testPoem) {
  setTimeout(function () {
    const p = pick(POEMS_PARSED);
    say(p.t + "\n——" + p.a, 6000);
    player.play("Speak");
    setTimeout(function () {
      log("test-poem: " + window.__balloonState());
      setTimeout(function () {
        host.quit();
      }, 300);
    }, 1200);
  }, 1200);
}

// 自检：养成一条龙
if (testPet === "1" || testPet === true) {
  setTimeout(function () {
    log(
      "test-pet before: " + JSON.stringify({
        stage: stage(), full: Math.round(stats.full), clean: Math.round(stats.clean),
        mood: Math.round(stats.mood), energy: Math.round(stats.energy),
        lv: stats.level, exp: Math.round(stats.exp), coins: stats.coins,
      }),
    );
    doAction("feed");
    doAction("status");
    setTimeout(function () {
      const p = document.getElementById("panel");
      const r = p.getBoundingClientRect();
      log(
        "test-pet panel: display=" + getComputedStyle(p).display +
          " rect=" + JSON.stringify({ x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) }) +
          " fits=" + (r.left >= 0 && r.top >= 0 && r.right <= window.innerWidth && r.bottom <= window.innerHeight),
      );
      log("test-pet balloon: " + window.__balloonState());
      log("test-pet anim=" + player.name);
      setTimeout(function () {
        host.quit();
      }, 2500);
    }, 1500);
  }, 1500);
}

// 自检：督战官（眼镜 + 教鞭 + 追一句）
if (params.get("testChase") === "1") {
  setTimeout(function () {
    alwaysTeacher = true;
    teacherUntil = Number.MAX_SAFE_INTEGER;
    doChase(0, true);
    log("test-chase teacher on, anim=" + player.name);
    setTimeout(function () {
      log("test-chase balloon: " + window.__balloonState());
    }, 900);
    setTimeout(function () {
      host.quit();
    }, 3200);
  }, 1500);
}

// 自检：督战官道具对位预览（放大 2 倍，几组动作各抽几帧）
if (params.get("teacherStrip") === "1") {
  const strip = document.createElement("canvas");
  const PICK = ["Speak", "Hi1", "Idle1", "UpsetPlay", "KidStand", "EggStand"];
  const N = 4;
  const Z = 2;
  strip.width = PET_W * Z * N;
  strip.height = PET_H * Z * PICK.length;
  const sctx = strip.getContext("2d");
  sctx.fillStyle = "#eef0f4";
  sctx.fillRect(0, 0, strip.width, strip.height);
  sctx.font = "12px monospace";
  window.__buildTeacherStrip = async function () {
    for (let r = 0; r < PICK.length; r++) {
      const name = PICK[r];
      if (!player.has(name)) continue;
      const cnt = player.frameCount(name);
      for (let i = 0; i < N; i++) {
        const idx = Math.floor((i / N) * cnt);
        player.draw(idx, cnt);
        const m = measure(ctx, canvas.width, canvas.height);
        const b = m
          ? {
              all: { x: m.all.x / DPR, y: m.all.y / DPR, w: m.all.w / DPR, h: m.all.h / DPR },
              face: m.face
                ? { x: m.face.x / DPR, y: m.face.y / DPR, w: m.face.w / DPR, h: m.face.h / DPR }
                : null,
            }
          : null;
        drawTeacher(ctx, b, PET_W, PET_H, i / N);
        sctx.drawImage(canvas, 0, 0, canvas.width, canvas.height, i * PET_W * Z, r * PET_H * Z, PET_W * Z, PET_H * Z);
        if (b) {
          sctx.strokeStyle = "rgba(0,140,255,0.5)";
          sctx.strokeRect(i * PET_W * Z + b.all.x * Z, r * PET_H * Z + b.all.y * Z, b.all.w * Z, b.all.h * Z);
          if (b.face) {
            sctx.strokeStyle = "rgba(255,120,0,0.8)";
            sctx.strokeRect(i * PET_W * Z + b.face.x * Z, r * PET_H * Z + b.face.y * Z, b.face.w * Z, b.face.h * Z);
          }
        }
      }
      sctx.fillStyle = "rgba(255,255,255,0.85)";
      sctx.fillRect(0, r * PET_H * Z, 110, 15);
      sctx.fillStyle = "#222";
      sctx.fillText(name, 3, r * PET_H * Z + 12);
    }
    return true;
  };
  window.__sheetPng = function () {
    return strip.toDataURL("image/png");
  };
}

window.__penguinInfo = function () {
  return { anim: player.name, animations: player.names().length, pos: pos, stage: stage(), lines: Object.keys(LINES) };
};
