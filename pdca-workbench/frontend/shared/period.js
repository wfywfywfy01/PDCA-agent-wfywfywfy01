/**
 * 期间工具模块 — 日 / 周 / 月 / 季度
 * 所有函数纯函数，无副作用，可在任意页面 import 或 <script> 引入。
 *
 * 锚定日期（anchorDate）格式：'YYYY-MM-DD'
 * 期间（period）值：'day' | 'week' | 'month' | 'quarter'
 */

/** 把 Date 对象格式化为 'YYYY-MM-DD' */
function _fmt(d) {
  var y = d.getFullYear();
  var m = String(d.getMonth() + 1).padStart(2, '0');
  var day = String(d.getDate()).padStart(2, '0');
  return y + '-' + m + '-' + day;
}

/** 从 'YYYY-MM-DD' 构建本地时间 Date（避免 UTC 偏移坑） */
function _parse(s) {
  var p = String(s || '').split('-');
  return new Date(+p[0], +p[1] - 1, +p[2]);
}

/** 今日 YYYY-MM-DD */
function todayStr() {
  return _fmt(new Date());
}

/**
 * 计算期间的起止日期。
 * @param {string} anchorDate  YYYY-MM-DD 锚定日期（默认今天）
 * @param {string} period      'day'|'week'|'month'|'quarter'
 * @returns {{ start:string, end:string, label:string, ym:string }}
 *   ym = 期间内第一个自然月 'YYYY-MM'（供只接受 month 参数的 API 使用）
 */
function getPeriodRange(anchorDate, period) {
  var anchor = _parse(anchorDate || todayStr());
  var y = anchor.getFullYear();
  var m = anchor.getMonth(); // 0-based
  var start, end, label;

  if (period === 'day') {
    start = end = _fmt(anchor);
    label = start;
  } else if (period === 'week') {
    // ISO 周：周一为第一天
    var dow = anchor.getDay(); // 0=Sun
    var dToMon = dow === 0 ? -6 : 1 - dow;
    var mon = new Date(anchor); mon.setDate(anchor.getDate() + dToMon);
    var sun = new Date(mon);    sun.setDate(mon.getDate() + 6);
    start = _fmt(mon); end = _fmt(sun);
    label = start + ' ~ ' + end.slice(5);
  } else if (period === 'month') {
    var lastDay = new Date(y, m + 1, 0).getDate();
    start = _fmt(new Date(y, m, 1));
    end   = _fmt(new Date(y, m, lastDay));
    label = y + '年' + (m + 1) + '月';
  } else if (period === 'quarter') {
    var q = Math.floor(m / 3);       // 0-3
    var qStartM = q * 3;             // 起始月（0-based）
    var qEndM   = qStartM + 2;       // 结束月（0-based）
    var qLastDay = new Date(y, qEndM + 1, 0).getDate();
    start = _fmt(new Date(y, qStartM, 1));
    end   = _fmt(new Date(y, qEndM, qLastDay));
    label = y + 'Q' + (q + 1);
  } else {
    // 兜底：按月
    return getPeriodRange(anchorDate, 'month');
  }

  return {
    start: start,
    end:   end,
    label: label,
    ym:    start.slice(0, 7), // 'YYYY-MM'
  };
}

/** 期间中文名 */
function periodCN(period) {
  return { day: '日', week: '周', month: '月', quarter: '季度' }[period] || period;
}

/**
 * 从 URL 读取 period；回退顺序：URL > sessionStorage > 默认 'month'
 */
function readPeriod() {
  return new URLSearchParams(location.search).get('period')
    || (typeof sessionStorage !== 'undefined' && sessionStorage.getItem('pdca_period'))
    || 'month';
}

/**
 * 从 URL 读取锚定日期；回退今天
 */
function readAnchor() {
  return new URLSearchParams(location.search).get('date') || todayStr();
}

/**
 * 构造带 date + period 参数的 URL（保留其余 query 参数）
 */
function buildUrl(path, date, period) {
  var p = new URLSearchParams(location.search);
  if (date)   p.set('date',   date);
  if (period) p.set('period', period);
  var qs = p.toString();
  return path + (qs ? '?' + qs : '');
}

// 以 UMD-lite 方式同时支持 ESM import 和全局变量
var PeriodUtils = { getPeriodRange: getPeriodRange, periodCN: periodCN, readPeriod: readPeriod, readAnchor: readAnchor, buildUrl: buildUrl, todayStr: todayStr };

if (typeof module !== 'undefined' && module.exports) {
  module.exports = PeriodUtils;
} else if (typeof define === 'function' && define.amd) {
  define(function () { return PeriodUtils; });
} else {
  (typeof globalThis !== 'undefined' ? globalThis : window).PeriodUtils = PeriodUtils;
}
