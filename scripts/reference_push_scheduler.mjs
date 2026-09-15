// reference_push_scheduler.mjs — 服务器端常驻调度器（跑在 Docker 容器内）
// 每周一/三/五，按北京时间 12:30(india) / 13:00(uzbek) / 15:00(russia) 触发 weekly-top20 对应批次。
// 依赖环境变量：REFERENCE_PUBLIC_TOKEN / REFERENCE_BOT_APP_ID / REFERENCE_BOT_APP_SECRET / REFERENCE_DATA_DIR（可选）
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = process.env.REFERENCE_DATA_DIR || HERE;
const STATE_FILE = path.join(DATA_DIR, 'scheduler_state.json');
const SCRIPT = path.join(HERE, 'push_reference_materials.mjs');

// weekday(1=Mon) -> { 'HH:MM': tz-group }
const SLOTS = {
  1: { '12:30': 'india', '13:00': 'uzbek', '15:00': 'russia' },
  3: { '12:30': 'india', '13:00': 'uzbek', '15:00': 'russia' },
  5: { '12:30': 'india', '13:00': 'uzbek', '15:00': 'russia' },
};
const BATCH_BY_WEEKDAY = { 1: 'mon', 3: 'wed', 5: 'fri' };

// 上线前试跑：周二/周三 19:30 分别推 mon/wed 批次到测试群（正式上线后删除本块）
const TEST_SLOTS = {
  2: { '19:30': 'mon' },
  3: { '19:30': 'wed' },
};

function loadState() {
  try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); } catch { return {}; }
}
function saveState(s) {
  fs.writeFileSync(STATE_FILE, JSON.stringify(s));
}
function bjNow() {
  const d = new Date(Date.now() + 8 * 3600 * 1000);
  const hh = String(d.getUTCHours()).padStart(2, '0');
  const mm = String(d.getUTCMinutes()).padStart(2, '0');
  const dow = d.getUTCDay();
  return { hh, mm, weekday: dow === 0 ? 7 : dow, date: d.toISOString().slice(0, 10) };
}
function runBatch(day, tzGroup) {
  const r = spawnSync(process.execPath, [SCRIPT, 'weekly-top20', '--push-batch', day, '--tz-group', tzGroup], {
    encoding: 'utf8',
    env: process.env,
    timeout: 2 * 3600 * 1000,
  });
  const out = (r.stdout || '').trim();
  const err = (r.stderr || '').trim();
  const line = new Date().toISOString() + ' batch=' + day + ' tz=' + tzGroup + ' exit=' + r.status;
  fs.appendFileSync(path.join(DATA_DIR, 'scheduler.log'), line + '\n' + out.slice(-800) + (err ? '\nERR: ' + err.slice(-400) : '') + '\n');
  console.log(line);
  console.log(out.slice(-800));
  if (err) console.error(err.slice(-400));
}

console.log('reference-push scheduler started, data dir: ' + DATA_DIR);
setInterval(() => {
  const now = bjNow();
  const key = now.date + '|' + now.hh + ':' + now.mm;
  const state = loadState();
  if (state[key]) return;
  const slots = SLOTS[now.weekday];
  const tzGroup = slots && slots[now.hh + ':' + now.mm];
  const testSlots = TEST_SLOTS[now.weekday];
  const testBatch = testSlots && testSlots[now.hh + ':' + now.mm];
  if (!tzGroup && !testBatch) return;
  state[key] = 'running';
  saveState(state);
  try {
    if (tzGroup) {
      console.log('trigger ' + key + ' -> ' + tzGroup);
      runBatch(BATCH_BY_WEEKDAY[now.weekday], tzGroup);
    } else {
      console.log('test trigger ' + key + ' -> batch ' + testBatch + ' to bot-test group');
      const r = spawnSync(process.execPath, [SCRIPT, 'weekly-top20', '--push-batch', testBatch, '--tz-group', 'india', '--test-group', 'bot-test'], {
        encoding: 'utf8',
        env: process.env,
        timeout: 2 * 3600 * 1000,
      });
      const out = (r.stdout || '').trim();
      const err = (r.stderr || '').trim();
      fs.appendFileSync(path.join(DATA_DIR, 'scheduler.log'), new Date().toISOString() + ' TEST batch=' + testBatch + ' exit=' + r.status + '\n' + out.slice(-800) + (err ? '\nERR: ' + err.slice(-400) : '') + '\n');
      console.log(out.slice(-800));
      if (err) console.error(err.slice(-400));
    }
    state[key] = 'done';
  } catch (e) {
    state[key] = 'failed:' + e.message;
  }
  saveState(state);
}, 20 * 1000);