// "三追"：每天三个时间点，企鹅变身督战官（戴眼镜、拿教鞭）来追问一句。
// 刻意不读任何真实数据 —— 就是提醒/敲打，具体内容你自己心里有数。

export const CHASE_TIMES = ["09:30", "14:00", "17:30"];

// 每一追追什么：早追待办、午追业绩、晚追进度 + 收尾
export const TOPICS = ["todo", "perf", "project"];

export const LINES = {
  todo: [
    "今天的任务完成了吗？",
    "待办清单清了几条了？",
    "这件事拖了几天了，今天得有个说法。",
    "别光记不做，做完打勾。",
    "今天最重要的一件事，做了吗？",
    "早上定的三件事，现在推进到哪了？",
  ],
  perf: [
    "这个月业绩做了多少了？",
    "目标还差多少，心里有数吗？",
    "离月底没几天了，进度跟得上吗？",
    "数字不会骗人，报个数。",
    "这个月能不能达标，你自己说。",
    "别等到月底再说'差一点'。",
  ],
  project: [
    "项目进度如何？",
    "卡在哪一步了，说清楚。",
    "这周该交付的东西，到哪了？",
    "别让事情停在「快了」两个字上。",
    "Plan 写了吗？Do 到哪了？Check 过了吗？Act 呢？",
    "光说不练假把式，闭环了吗？",
  ],
  // 晚追的收尾那句，跟着进度一起说
  wrapup: [
    "今天的日报交了吗？",
    "今天没做完的，写进明天的第一条。",
    "收工前把明天第一件事定下来。",
    "今天的事今天结，别留给明天。",
  ],
};

export function pick(list, rand) {
  const r = rand || Math.random;
  return list[Math.floor(r() * list.length)];
}

// 第几追（0/1/2）该说什么
export function chaseFor(round, rand) {
  const topic = TOPICS[((round % TOPICS.length) + TOPICS.length) % TOPICS.length];
  const main = pick(LINES[topic], rand);
  const extra = topic === "project" ? pick(LINES.wrapup, rand) : "";
  return { topic, text: extra ? main + "\n" + extra : main, round: round };
}

// 按当前时间判断现在该是第几追（用来做"错过就补一次"）
export function roundForDate(d) {
  const mins = d.getHours() * 60 + d.getMinutes();
  let round = -1;
  CHASE_TIMES.forEach(function (t, i) {
    const parts = t.split(":");
    const m = Number(parts[0]) * 60 + Number(parts[1]);
    if (mins >= m) round = i;
  });
  return round;
}

export function todayKey(d) {
  const p = function (n) {
    return n < 10 ? "0" + n : String(n);
  };
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
}

// 督战官的收尾台词（追问完了自己补一句）
export const TEACHER_TAIL = [
  "别嫌我烦，我是为你好。",
  "记下来，别又忘了。",
  "我看着你呢。",
  "做到的打勾，没做的说原因。",
];
