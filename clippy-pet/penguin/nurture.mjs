// 企鹅的养成数值：饱食 / 清洁 / 心情 / 精力 + 等级经验金币。
// 规则都写在这一个文件里，想改手感（掉得快不快、喂一次加多少）只改这里。

export const STAT_MAX = 100;

// 掉得速度：每 N 分钟 -1。太快的会烦人，太慢的没存在感，按"上班一天看得出来"调。
const DECAY = {
  full: 5, // 饱食：约 8 小时饿到底
  clean: 8, // 清洁：约 13 小时
  mood: 6, // 心情：约 10 小时
  energy: 7, // 精力：约 12 小时
};
// 离线（关掉桌宠）最多按 10 小时算，不然第二天回来直接饿死
const OFFLINE_CAP_MIN = 600;
// 饿着/脏着的时候心情掉得更快：每 5 分钟额外 -1
const MOOD_PENALTY_MIN = 5;
const BAD_LEVEL = 30;

export const DEFAULT_STATS = {
  full: 80,
  clean: 85,
  mood: 75,
  energy: 90,
  level: 1,
  exp: 0,
  coins: 60,
  ts: Date.now(),
  born: Date.now(),
  feeds: 0,
  plays: 0,
  cleans: 0,
  works: 0,
  levelUps: 0,
};

export function expNeeded(level) {
  return 40 + (level - 1) * 25;
}

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

export function normalize(raw) {
  const s = Object.assign({}, DEFAULT_STATS, raw || {});
  ["full", "clean", "mood", "energy"].forEach(function (k) {
    s[k] = clamp(Number(s[k]) || 0, 0, STAT_MAX);
  });
  s.level = Math.max(1, Math.round(Number(s.level) || 1));
  s.exp = Math.max(0, Math.round(Number(s.exp) || 0));
  s.coins = Math.max(0, Math.round(Number(s.coins) || 0));
  s.ts = Number(s.ts) || Date.now();
  return s;
}

// 按真实时间流逝结算（关掉桌宠期间也算，但有上限）
export function settle(stats, now) {
  const s = normalize(stats);
  const minutes = Math.min(OFFLINE_CAP_MIN, Math.max(0, (now - s.ts) / 60000));
  if (minutes < 0.2) return { stats: s, events: [] };

  const events = [];
  const before = { full: s.full, clean: s.clean, mood: s.mood, energy: s.energy };

  ["full", "clean", "mood", "energy"].forEach(function (k) {
    s[k] = clamp(s[k] - minutes / DECAY[k], 0, STAT_MAX);
  });

  // 饿着或脏着，心情额外掉
  const badMin = (before.full < BAD_LEVEL ? minutes : 0) + (before.clean < BAD_LEVEL ? minutes : 0);
  if (badMin > 0) s.mood = clamp(s.mood - badMin / MOOD_PENALTY_MIN, 0, STAT_MAX);

  ["full", "clean", "mood", "energy"].forEach(function (k) {
    if (before[k] >= BAD_LEVEL && s[k] < BAD_LEVEL) events.push({ type: "low", stat: k });
    if (before[k] > 0 && s[k] <= 0) events.push({ type: "empty", stat: k });
  });

  s.ts = now;
  return { stats: s, events: events };
}

// 睡觉：把经过的时间按"恢复"结算
export function sleepSettle(stats, now) {
  const s = normalize(stats);
  const minutes = Math.min(OFFLINE_CAP_MIN, Math.max(0, (now - s.ts) / 60000));
  s.energy = clamp(s.energy + minutes / 1.5, 0, STAT_MAX);
  s.full = clamp(s.full - minutes / (DECAY.full * 2), 0, STAT_MAX);
  s.mood = clamp(s.mood + minutes / 12, 0, STAT_MAX);
  s.ts = now;
  return s;
}

// 每个动作：花多少钱、加什么、播哪个动画、说什么
export const ACTIONS = {
  feed: {
    label: "喂小鱼干",
    cost: 10,
    anim: "Eat",
    dur: 2600,
    gain: { full: 30, mood: 6, exp: 8 },
    counter: "feeds",
    ok: function (s) {
      if (s.coins < 10) return "金币不够啦（要 10 个，打工能赚）";
      if (s.full >= 99) return "我吃不下了，肚子都圆了";
      return null;
    },
    say: function (s) {
      return "咔嚓咔嚓……好吃！饱食度 " + Math.round(s.full) + " 了。";
    },
  },
  bath: {
    label: "洗个澡",
    cost: 5,
    anim: "Bath",
    dur: 3200,
    gain: { clean: 40, mood: 6, exp: 6 },
    counter: "cleans",
    ok: function (s) {
      if (s.coins < 5) return "洗澡要 5 个金币，先攒攒";
      if (s.clean >= 99) return "我刚洗过，香着呢";
      return null;
    },
    say: function (s) {
      return "搓搓搓……清爽！清洁度 " + Math.round(s.clean) + "。";
    },
  },
  play: {
    label: "逗它玩",
    cost: 0,
    anim: "Happy",
    dur: 2000,
    gain: { mood: 26, energy: -12, full: -4, exp: 10 },
    counter: "plays",
    ok: function (s) {
      if (s.energy < 12) return "我太累了，让我先睡会儿";
      return null;
    },
    say: function (s) {
      return "好玩好玩！心情 " + Math.round(s.mood) + " 了～";
    },
  },
  sleep: {
    label: "哄它睡觉",
    cost: 0,
    anim: "Sleep",
    dur: 5200,
    gain: { energy: 30, mood: 4, exp: 4 },
    ok: function (s) {
      if (s.energy >= 99) return "我现在精神得很，睡不着";
      return null;
    },
    say: function (s) {
      return "呼……睡了一觉，精力 " + Math.round(s.energy) + "。";
    },
  },
  work: {
    label: "去打工",
    cost: 0,
    anim: "Work",
    dur: 3000,
    gain: { coins: 28, energy: -20, full: -12, mood: -6, exp: 12 },
    counter: "works",
    ok: function (s) {
      if (s.energy < 25) return "没力气干活了，先让我吃点睡点";
      if (s.full < 20) return "饿着肚子打不了工";
      return null;
    },
    say: function (s) {
      return "搬砖回来啦，赚了 28 个金币（共 " + s.coins + "）。";
    },
  },
  study: {
    label: "去学习",
    cost: 0,
    anim: "Study",
    dur: 3400,
    gain: { exp: 22, energy: -14, full: -8, mood: -3 },
    ok: function (s) {
      if (s.energy < 20) return "困得看不进书，先歇会儿";
      return null;
    },
    say: function (s) {
      return "学了一课，经验 +22（" + Math.floor(s.exp) + "/" + expNeeded(s.level) + "）。";
    },
  },
};

// 结算一个动作：返回新的 stats + 要说的话 + 是否升级
export function applyAction(stats, key, now) {
  const act = ACTIONS[key];
  if (!act) return { ok: false, reason: "没有这个动作" };
  const s = normalize(stats);
  const bad = act.ok ? act.ok(s) : null;
  if (bad) return { ok: false, reason: bad };

  if (act.cost) s.coins -= act.cost;
  const g = act.gain || {};
  Object.keys(g).forEach(function (k) {
    if (k === "coins") s.coins = Math.max(0, s.coins + g[k]);
    else if (k === "exp") s.exp += g[k];
    else s[k] = clamp((s[k] || 0) + g[k], 0, STAT_MAX);
  });
  if (act.counter) s[act.counter] = (s[act.counter] || 0) + 1;
  s.ts = now;

  let leveled = 0;
  while (s.exp >= expNeeded(s.level)) {
    s.exp -= expNeeded(s.level);
    s.level += 1;
    s.coins += 20;
    s.levelUps = (s.levelUps || 0) + 1;
    leveled += 1;
  }
  return { ok: true, stats: s, line: act.say ? act.say(s) : "", anim: act.anim, leveled: leveled };
}

// 现在最该管哪一项（用于主动撒娇）
export function worstStat(s) {
  const list = [
    ["full", s.full],
    ["clean", s.clean],
    ["mood", s.mood],
    ["energy", s.energy],
  ].sort(function (a, b) {
    return a[1] - b[1];
  });
  return list[0];
}

export function moodFace(s) {
  if (s.energy < 15) return "Sleep";
  if (s.full < 25) return "Hungry";
  if (s.mood < 25) return "Sad";
  if (s.clean < 25) return "Angry";
  if (s.mood > 80) return "Happy";
  return "Idle";
}
