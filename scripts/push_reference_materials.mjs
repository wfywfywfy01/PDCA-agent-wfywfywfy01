#!/usr/bin/env node
// push_reference_materials.mjs
// 从资料中心基础素材公开接口拉取图片/视频，推送到 6 个海外经销商 VPS 群。
// 用法见文件末尾 usage()。token 通过 --token 或环境变量 REFERENCE_PUBLIC_TOKEN 提供，不写入仓库。
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const API = 'https://online-sales-pdca.vertu.cn/api/public/reference';
const DATA_DIR = process.env.REFERENCE_DATA_DIR || path.dirname(fileURLToPath(import.meta.url));
const HISTORY = path.join(DATA_DIR, '.push_history.log');

const GROUPS = {
  carino:  { id: '466f3f12-5b05-4d7a-9369-ba56b57b5d17', name: 'Carino Jewellery &Vertu', tz: 5.5, hour: 10 },
  nellore: { id: 'c7202298-dc4b-43bf-8604-6606f7c9d0b7', name: 'India Nellore & Vertu', tz: 5.5, hour: 10 },
  naya:    { id: 'ad40a3c5-c2c5-41b5-bc62-2576ba847a33', name: 'VERTU& Indian Naya', tz: 5.5, hour: 10 },
  azimut:  { id: 'e55e5f6f-3a4b-4ecb-8747-a6d6383626d7', name: 'VERTU& Azimut', tz: 3, hour: 10 },
  restore: { id: 'f73f8d63-bb42-49ea-997b-cff01d298d89', name: 'VERTU& reStore', tz: 3, hour: 10 },
  bizcon:  { id: 'c2c26953-83ea-4bd9-985c-15bc8c741391', name: 'Vertu& Bizcon', tz: 5, hour: 10 },
  internal: { id: 'a6be6cb6-2abf-4ece-a2c3-f81c01d99771', name: '经销商内部沟通群(测试)' },
  'bot-test': { id: '67e07684-237e-484c-be25-877145c66670', name: '素材推送测试(机器人)' },
};

// 时区分组：每个市场在当地 hour 点推，换算成北京时间执行
const TZ_GROUPS = {
  india: ['carino', 'nellore', 'naya'],
  uzbek: ['bizcon'],
  russia: ['azimut', 'restore'],
};
function bjTime(g) {
  if (!g.tz) return '--';
  const bj = g.hour - g.tz + 8;
  const h = Math.floor(bj), m = Math.round((bj - h) * 60);
  return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
}

function arg(name, def = null) {
  const i = process.argv.indexOf('--' + name);
  if (i === -1 || !process.argv[i + 1]) return def;
  return process.argv[i + 1];
}
function has(name) { return process.argv.includes('--' + name); }

const BOT_MODE = has('transport-bot') || Boolean(process.env.REFERENCE_BOT_APP_ID);

function resolveCli() {
  // 定位 vertu-cli.cmd shim，提取 VPS.exe 与 cjs 入口，避免 shell 引号问题
  const w = spawnSync('where', ['vertu-cli'], { encoding: 'utf8' });
  const shim = (w.stdout || '').trim().split(/\r?\n/)[0];
  if (!shim || !fs.existsSync(shim)) throw new Error('找不到 vertu-cli shim: ' + shim);
  const text = fs.readFileSync(shim, 'utf8');
  const m = [...text.matchAll(/"(.*?)"/g)].map(x => x[1]);
  if (m.length < 2) throw new Error('无法解析 vertu-cli shim: ' + shim);
  return { exe: m[0], cli: m[1] };
}

let EXE = null, CLI = null;
if (!BOT_MODE) {
  const resolved = resolveCli();
  EXE = resolved.exe;
  CLI = resolved.cli;
}
const ENV = { ...process.env, ELECTRON_RUN_AS_NODE: '1' };

function cli(args) {
  const r = spawnSync(EXE, [CLI, ...args], { encoding: 'utf8', env: ENV });
  if (r.status !== 0) throw new Error('vertu-cli 失败: ' + (r.stderr || '').slice(0, 300));
  try { return JSON.parse(r.stdout || '{}'); } catch { throw new Error('vertu-cli 输出非 JSON'); }
}

function log(line) {
  fs.appendFileSync(HISTORY, new Date().toISOString() + ' ' + line + '\n');
}

function readHistoryIds() {
  try {
    const t = fs.readFileSync(HISTORY, 'utf8');
    return new Set([...t.matchAll(/id=(\d+)/g)].map(m => Number(m[1])));
  } catch { return new Set(); }
}

const BLOCKLIST_FILE = process.env.REFERENCE_BLOCKLIST_FILE || path.join(DATA_DIR, 'reference_blocklist.json');
function readBlocklist() {
  try {
    const j = JSON.parse(fs.readFileSync(BLOCKLIST_FILE, 'utf8'));
    return new Set((j.ids || []).map(Number));
  } catch { return new Set(); }
}

async function fetchMaterials(wantedIds) {
  const token = arg('token') || process.env.REFERENCE_PUBLIC_TOKEN;
  if (!token) throw new Error('缺少 token：传 --token 或设置环境变量 REFERENCE_PUBLIC_TOKEN');
  const type = arg('type', 'all');
  const region = arg('region', 'overseas');
  const pages = type === 'all' ? ['base-images', 'base-videos'] : [type === 'image' ? 'base-images' : 'base-videos'];
  let all = [];
  for (const ep of pages) {
    for (let p = 1; p <= 15; p++) {
      const q = new URLSearchParams({ page: String(p), pageSize: '100' });
      if (region) q.set('assetRegion', region);
      if (arg('q')) q.set('q', arg('q'));
      if (arg('asset-name')) q.set('assetName', arg('asset-name'));
      if (arg('days')) {
        const d = new Date(Date.now() - Number(arg('days')) * 86400000).toISOString().slice(0, 10);
        q.set('creativeStartDate', d);
      }
      const r = await fetch(API + '/' + ep + '?' + q, { headers: { Authorization: 'Bearer ' + token } });
      if (!r.ok) throw new Error(ep + ' HTTP ' + r.status);
      const j = await r.json();
      if (!j.success) throw new Error(ep + ' error: ' + (j.error || 'unknown'));
      all = all.concat(j.items || []);
      if (j.total <= p * 100) break;
      if (wantedIds && wantedIds.length && wantedIds.every(id => all.some(m => m.id === id))) break;
    }
  }
  if (wantedIds && wantedIds.length) {
    return wantedIds.map(id => all.find(m => m.id === id)).filter(Boolean);
  }
  const top = Number(arg('top', '30'));
  return all.slice(0, top);
}

function pick(ids, materials) {
  if (ids) {
    const set = new Set(ids.split(',').map(Number));
    return materials.filter(m => set.has(m.id));
  }
  return materials;
}

function pickGroups(g) {
  const keys = g === 'all' ? Object.keys(GROUPS) : g.split(',');
  return keys.map(k => GROUPS[k.trim()]).filter(Boolean);
}

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CONTENT_FILE = path.join(HERE, 'reference_content.json');
const DEFAULT_FFMPEG = path.join(HERE, '..', '.st', 'ffmpeg', 'ffmpeg-master-latest-win64-gpl', 'bin', 'ffmpeg.exe');

function loadContent() {
  try { return JSON.parse(fs.readFileSync(CONTENT_FILE, 'utf8')); } catch { return {}; }
}
function resolveFfmpeg() {
  const p = arg('ffmpeg') || process.env.REFERENCE_FFMPEG || DEFAULT_FFMPEG;
  return p && fs.existsSync(p) ? p : null;
}
function probeDuration(ffprobe, file) {
  const r = spawnSync(ffprobe, ['-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file], { encoding: 'utf8' });
  const d = parseFloat((r.stdout || '').trim());
  return Number.isFinite(d) && d > 0 ? d : null;
}
function compressVideo(ffmpeg, src, out, maxMb) {
  const ffprobe = ffmpeg.replace(/ffmpeg\.exe$/, 'ffprobe.exe');
  const dur = probeDuration(ffprobe, src) || 60;
  const videoK = Math.max(500, Math.floor(maxMb * 1024 * 8 / dur * 0.95) - 128);
  for (const kbps of [videoK, Math.floor(videoK * 0.8)]) {
    const r = spawnSync(ffmpeg, ['-y', '-i', src, '-c:v', 'libx264', '-preset', 'medium', '-b:v', String(kbps) + 'k', '-maxrate', String(kbps) + 'k', '-bufsize', String(kbps * 2) + 'k', '-vf', 'scale=1080:1920', '-c:a', 'aac', '-b:a', '128k', out], { encoding: 'utf8' });
    if (r.status === 0 && fs.existsSync(out) && fs.statSync(out).size <= maxMb * 1048576) return true;
  }
  return false;
}

const BOT_PUSH_URL = 'https://vps-service.vertu.cn/v1/im/user-robots/push';
async function botSend(channelId, body, attachments) {
  const appId = process.env.REFERENCE_BOT_APP_ID;
  const secret = process.env.REFERENCE_BOT_APP_SECRET;
  if (!appId || !secret) throw new Error('bot 模式缺少 REFERENCE_BOT_APP_ID / REFERENCE_BOT_APP_SECRET');
  const r = await fetch(BOT_PUSH_URL, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-vertu-bot-app-id': appId, 'x-vertu-bot-app-secret': secret },
    body: JSON.stringify({ channel_id: channelId, body, ...(attachments && attachments.length ? { attachments } : {}) }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || !j.ok) throw new Error('bot push 失败: ' + r.status + ' ' + (j.error || ''));
  return j;
}

const PREP = new Map();
async function prepareMaterial(mat) {
  if (PREP.has(mat.id)) return PREP.get(mat.id);
  const content = loadContent()[mat.id] || {};
  const title = content.title || mat.assetName;
  const intro = content.intro || '';
  const bodyText = intro ? title + '\n' + intro : title;
  if (BOT_MODE) {
    const p = { mediaType: mat.mediaType, file: null, body: bodyText, urlOnly: false, botUrl: mat.materialUrl, botName: mat.assetName };
    PREP.set(mat.id, p);
    return p;
  }
  const p = { mediaType: mat.mediaType, file: null, body: bodyText, urlOnly: false };
  const maxMb = Number(arg('max-mb', '24'));
  if (mat.mediaType === 'image') {
    const tmp = path.join(os.tmpdir(), 'ref-' + mat.id + '.webp');
    const buf = await (await fetch(mat.materialUrl)).arrayBuffer();
    fs.writeFileSync(tmp, Buffer.from(buf));
    p.file = tmp;
  } else if ((mat.fileSize || 0) <= maxMb * 1048576) {
    const tmp = path.join(os.tmpdir(), 'ref-' + mat.id + '.mp4');
    const buf = await (await fetch(mat.materialUrl)).arrayBuffer();
    fs.writeFileSync(tmp, Buffer.from(buf));
    p.file = tmp;
  } else {
    const ffmpeg = resolveFfmpeg();
    if (ffmpeg) {
      const tmp = path.join(os.tmpdir(), 'ref-' + mat.id + '.mp4');
      const buf = await (await fetch(mat.materialUrl)).arrayBuffer();
      fs.writeFileSync(tmp, Buffer.from(buf));
      const out = tmp.replace(/\.mp4$/, '.comp.mp4');
      if (compressVideo(ffmpeg, tmp, out, maxMb)) {
        fs.unlinkSync(tmp);
        p.file = out;
        p.body = bodyText + '\nOriginal: ' + mat.materialUrl;
        p.compressed = true;
      } else {
        fs.unlinkSync(tmp);
      }
    }
    if (!p.file) {
      p.body = bodyText + '\nOriginal: ' + mat.materialUrl;
      p.urlOnly = true;
    }
  }
  PREP.set(mat.id, p);
  return p;
}

async function pushOne(mat, group, dryRun) {
  const p = await prepareMaterial(mat);
  const cmid = 'ref-' + mat.id + '-' + group.id;
  if (p.botUrl) {
    const attType = p.mediaType === 'image' ? 'image' : 'video';
    if (dryRun) { console.log('[dry-run] bot-' + attType + '-url -> ' + group.name + ': ' + p.body.split('\n')[0]); return; }
    const r = await botSend(group.id, p.body, [{ attachment_type: attType, name: p.botName, url: p.botUrl }]);
    log('ok ' + group.name + ' bot-' + attType + ' id=' + mat.id);
    console.log('sent bot-' + attType + ' #' + mat.id + ' -> ' + group.name + ' (' + r.message?.id + ')');
    return;
  }
  if (dryRun) {
    const mode = p.urlOnly ? 'url-text' : (p.compressed ? 'video-compressed' : 'attach-original');
    console.log('[dry-run] ' + mode + ' -> ' + group.name + ': ' + p.body.split('\n')[0]);
    return;
  }
  const base = ['im', '+send', '--channel-id', group.id, '--body', p.body, '--client-message-id', cmid];
  if (p.file) {
    const type = p.mediaType === 'image' ? 'image' : 'video';
    const r = cli([...base, '--message-type', type, '--attach', p.file]);
    log('ok ' + group.name + ' ' + (p.compressed ? 'video-comp' : p.mediaType) + ' id=' + mat.id);
    console.log('sent ' + type + ' #' + mat.id + ' -> ' + group.name + ' (' + r.message?.id + ')');
  } else {
    const r = cli(base);
    log('ok ' + group.name + ' video-url id=' + mat.id);
    console.log('sent video-url #' + mat.id + ' -> ' + group.name + ' (' + r.message?.id + ')');
  }
}

function cleanupPrepared() {
  for (const p of PREP.values()) {
    if (p.file) { try { fs.unlinkSync(p.file); } catch {} }
  }
  PREP.clear();
}

function lastWeekRange() {
  const cn = new Date(Date.now() + 8 * 3600 * 1000); // 北京时间
  const dow = cn.getUTCDay();
  const thisMonUtc = Date.UTC(cn.getUTCFullYear(), cn.getUTCMonth(), cn.getUTCDate() - ((dow + 6) % 7));
  const lastMon = new Date(thisMonUtc - 7 * 86400000);
  const lastSun = new Date(thisMonUtc - 86400000);
  const fmt = d => d.toISOString().slice(0, 10);
  return { start: fmt(lastMon), end: fmt(lastSun) };
}

async function fetchWindowVideos() {
  const token = arg('token') || process.env.REFERENCE_PUBLIC_TOKEN;
  if (!token) throw new Error('缺少 token：传 --token 或设置环境变量 REFERENCE_PUBLIC_TOKEN');
  const { start, end } = lastWeekRange();
  let all = [];
  for (let p = 1; p <= 20; p++) {
    const q = new URLSearchParams({ page: String(p), pageSize: '100', assetRegion: 'overseas', creativeStartDate: start, creativeEndDate: end });
    const r = await fetch(API + '/base-videos?' + q, { headers: { Authorization: 'Bearer ' + token } });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const j = await r.json();
    if (!j.success) throw new Error(j.error || 'query error');
    all = all.concat(j.items || []);
    if (j.total <= p * 100) break;
  }
  return { all, start, end };
}

async function cmdWeekly() {
  const { all, start, end } = await fetchWindowVideos();
  const pushed = readHistoryIds();
  const blocked = readBlocklist();
  const scored = all.map(m => ({ m, s: m.qualityScore?.overallScore ?? 0 }))
    .filter(x => !pushed.has(x.m.id))
    .filter(x => !blocked.has(x.m.id))
    .sort((a, b) => b.s - a.s || b.m.id - a.m.id);
  const topN = Number(arg('top', '20'));
  const top = scored.slice(0, topN);
  const batches = { mon: top.slice(0, 7), wed: top.slice(7, 14), fri: top.slice(14, 20) };
  console.log('上周窗口: ' + start + ' ~ ' + end + ' | 海外视频 ' + all.length + ' 条 | 去重后候选 ' + scored.length + ' 条');
  for (const [day, list] of Object.entries(batches)) {
    console.log('--- ' + day + ' (' + list.length + ' 条) ---');
    for (const x of list) {
      const m = x.m;
      console.log(['#' + m.id, (m.qualityScore?.level || '-') + '/' + (x.s || '-'), m.assetName, (m.creativeTime || '').slice(0, 10), (m.fileSize / 1048576).toFixed(1) + 'MB'].join(' | '));
    }
  }
  console.log('--- 推送时刻（当地 ' + GROUPS.carino.hour + ':00） ---');
  for (const [tg, keys] of Object.entries(TZ_GROUPS)) {
    const names = keys.map(k => GROUPS[k].name).join(' / ');
    console.log(tg + ' 群（' + names + '）→ 北京时间 ' + bjTime(GROUPS[keys[0]]));
  }
  const batch = arg('push-batch');
  if (batch) {
    const tg = arg('tz-group');
    if (!TZ_GROUPS[tg]) throw new Error('--tz-group 需要 india / uzbek / russia');
    const testGroup = arg('test-group');
    const groups = testGroup ? [GROUPS[testGroup]].filter(Boolean) : TZ_GROUPS[tg].map(k => GROUPS[k]);
    if (!groups.length) throw new Error('--test-group 无效: ' + testGroup);
    const dryRun = has('dry-run');
    for (const x of batches[batch] || []) for (const g of groups) await pushOne(x.m, g, dryRun);
    console.log('完成：' + (batches[batch] || []).length + ' 条 x ' + groups.length + ' 群（batch=' + batch + ', tz-group=' + tg + (testGroup ? ', test-group=' + testGroup : '') + (dryRun ? ', dry-run' : '') + '）');
  }
}

function usage() {
  console.log(`用法:
  node scripts/push_reference_materials.mjs list [--region overseas|domestic] [--type image|video|all] [--q 关键词] [--asset-name 名称] [--days N] [--top N] [--token T]
  node scripts/push_reference_materials.mjs push [--ids 1,2,3 | --q 关键词 --top N] [--type image|video] [--region overseas|domestic] [--groups carino,nellore,naya,azimut,restore,bizcon|all|internal] [--max-mb 24] [--ffmpeg 路径] [--dry-run] [--token T]
  node scripts/push_reference_materials.mjs weekly-top20 [--top 20] [--push-batch mon|wed|fri --tz-group india|uzbek|russia] [--dry-run] [--token T]
   weekly-top20：取上周（周一~周日）海外视频按质量评分排 Top20，去重后分 3 批（mon 1-7 / wed 8-14 / fri 15-20）；--push-batch 指定批次并按 --tz-group 时区分组在当地时间推送
群别名: carino / nellore / naya / azimut / restore / bizcon / all（6 群全发）/ internal（经销商内部沟通群，测试用）
英文标题/简介写在 scripts/reference_content.json（按素材 id: {title, intro}），缺省用素材名。
视频 <= --max-mb（默认 24MB）发原件；超限且配置 ffmpeg 时压缩到 24MB 内发视频，正文附 Original 原链；无 ffmpeg 则只发正文+原链。图片一律下载直发。
token 也可用环境变量 REFERENCE_PUBLIC_TOKEN 提供（不写入仓库）。`);
}

const cmd = process.argv[2];
try {
  if (cmd === 'list') {
    const ms = await fetchMaterials();
    console.log('共 ' + ms.length + ' 条:');
    for (const m of ms) console.log(['#' + m.id, m.mediaType, m.assetRegion, m.assetName, m.creativeTime || '-', (m.fileSize / 1048576).toFixed(1) + 'MB'].join(' | '));
  } else if (cmd === 'push') {
    const ids = arg('ids');
    if (!ids && !arg('q') && !has('top')) throw new Error('push 需要 --ids 或 --q（可配 --top）');
    const wanted = ids ? ids.split(',').map(Number) : null;
    const ms = wanted ? await fetchMaterials(wanted) : await fetchMaterials();
    if (!ms.length) throw new Error('没有匹配的素材');
    const groups = pickGroups(arg('groups', 'all'));
    const dryRun = has('dry-run');
    for (const m of ms) for (const g of groups) await pushOne(m, g, dryRun);
    console.log('完成：' + ms.length + ' 条素材 x ' + groups.length + ' 个群' + (dryRun ? '（dry-run，未发送）' : ''));
  } else if (cmd === 'weekly-top20') {
    await cmdWeekly();
  } else {
    usage();
  }
} catch (e) {
  console.error('ERROR: ' + e.message);
  process.exit(1);
}