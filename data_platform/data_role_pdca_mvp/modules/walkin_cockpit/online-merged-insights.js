/**
 * 线上驾驶舱核心块并入 Walk-in「客流分析」：OKR 表、渠道线索、区域堆叠、客户来源对比。
 * 数据：data/online_channel_reference.json（结构与 Excel 渠道表一致）；客户来源来自当前代理商汇总。
 */
(function (global) {
  'use strict';

  var ref = null;
  var vnRef = null;
  var loadPromise = null;

  function fmtNum(x) {
    return Number(x).toLocaleString('zh-CN', { maximumFractionDigits: 1 });
  }

  function sum(arr, fn) {
    var t = 0;
    for (var i = 0; i < arr.length; i++) t += fn(arr[i]);
    return t;
  }

  /** @param {string} rg @param {string} nm */
  function dealerRegionStoreLabel(rg, nm) {
    return (rg || '—') + ' · ' + (nm || '—');
  }

  function scaleFactor(monthKey) {
    if (!ref || !ref.scaleByMonth) return 1;
    if (ref.scaleByMonth[monthKey] != null) return ref.scaleByMonth[monthKey];
    return 1;
  }

  function scaledStores(monthKey) {
    if (!ref || !ref.stores) return [];
    var f = scaleFactor(monthKey);
    return ref.stores.map(function (r) {
      if (r.hk) {
        return {
          rg: r.rg,
          nm: r.nm,
          mgr: r.mgr,
          hk: 1,
          Ls: 0,
          Ll: 0,
          Lo: 0,
          sal: 0,
        };
      }
      return {
        rg: r.rg,
        nm: r.nm,
        mgr: r.mgr,
        hk: 0,
        Ls: Math.max(0, Math.round(r.Ls * f)),
        Ll: Math.max(0, Math.round(r.Ll * f)),
        Lo: Math.max(0, Math.round(r.Lo * f)),
        sal: Math.round(r.sal * f * 10) / 10,
      };
    });
  }

  function mainland(rows) {
    return rows.filter(function (r) {
      return !r.hk;
    });
  }

  function okrMonthly(nm, monthKey) {
    var M = (ref && ref.okrByMonth && ref.okrByMonth[monthKey]) || null;
    if (!M && ref && ref.okrByMonth) {
      var keys = Object.keys(ref.okrByMonth);
      M = ref.okrByMonth[keys[keys.length - 1]];
    }
    if (!M) return 0;
    return M[nm] != null ? M[nm] : 0;
  }

  function vpsCell(v, unit) {
    unit = unit || '';
    if (v === null || v === undefined || v === '') {
      return '<span style="color:#64748b">—</span>';
    }
    return String(v) + unit;
  }

  /**
   * 大区门店分析（与数据看板 DEALER_REGION 同源，VPS 真实销售）
   * @param {object[]} dealerRegion
   */
  function renderDealerRegionHtml(dealerRegion) {
    if (!dealerRegion || !dealerRegion.length) {
      return '';
    }
    var colors = {
      中东: '#f97316',
      欧洲: '#3b6ef8',
      南亚: '#22c55e',
      东南亚: '#a855f7',
      中亚: '#06b6d4',
      其他: '#6b7280',
    };
    var totalPerf = 0;
    for (var ti = 0; ti < dealerRegion.length; ti++) {
      totalPerf += dealerRegion[ti].perf || 0;
    }
    var mxPerf = 0.01;
    for (var mi = 0; mi < dealerRegion.length; mi++) {
      mxPerf = Math.max(mxPerf, dealerRegion[mi].perf || 0);
    }
    var html =
      '<div class="oi-card">' +
      '<h3>大区门店分析（VPS）</h3>' +
      '<p class="oi-note">门店清单 <code>config/dealers.json</code>；<strong>提货金额/件数</strong>来自 vertu <code>customer_summary</code>（与数据看板一致）。</p>';
    for (var ri = 0; ri < dealerRegion.length; ri++) {
      var rg = dealerRegion[ri];
      var color = colors[rg.region] || '#6b7280';
      var pct = totalPerf > 0 ? ((rg.perf / totalPerf) * 100).toFixed(1) : '0.0';
      var bar = Math.round(((rg.perf || 0) / mxPerf) * 100);
      html +=
        '<div class="oi-region-block" style="margin-bottom:14px;border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:10px 12px">' +
        '<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;border-left:4px solid ' +
        color +
        ';padding-left:10px">' +
        '<strong style="min-width:52px">' +
        rg.region +
        '</strong>' +
        '<div style="flex:1;height:8px;border-radius:4px;background:rgba(255,255,255,.08)"><div style="height:100%;width:' +
        bar +
        '%;background:' +
        color +
        ';border-radius:4px"></div></div>' +
        '<span style="color:' +
        color +
        ';font-weight:700">' +
        (rg.perf || 0) +
        ' 万</span>' +
        '<span style="color:#94a3b8;font-size:12px">' +
        pct +
        '%</span>' +
        '<span style="color:#4ade80;font-size:12px">' +
        (rg.qty || 0) +
        ' 件</span></div>';
      for (var ci = 0; ci < (rg.countries || []).length; ci++) {
        var ct = rg.countries[ci];
        var openAttr = (ct.perf || 0) > 0 || (ct.qty || 0) > 0 ? ' open' : '';
        html +=
          '<details style="margin:4px 0 4px 12px"' +
          openAttr +
          '><summary style="cursor:pointer;font-size:12px;color:#cbd5e1">' +
          ct.country +
          ' · ' +
          (ct.dealers || []).length +
          ' 家';
        if (ct.perf > 0) {
          html += ' · <span style="color:#93c5fd">' + ct.perf + ' 万</span>';
        }
        if (ct.qty > 0) {
          html += ' · <span style="color:#4ade80">' + ct.qty + ' 件</span>';
        }
        html += '</summary><table class="oi-grid oi-grid-wide" style="margin-top:6px"><thead><tr>' +
          '<th>门店</th><th>销售</th><th class="num">真实销售(万)</th><th class="num">件数</th></tr></thead><tbody>';
        for (var di = 0; di < (ct.dealers || []).length; di++) {
          var d = ct.dealers[di];
          var active = (d.perf || 0) > 0 || (d.qty || 0) > 0;
          var nick = d.nickname
            ? ' <span style="color:#94a3b8;font-size:11px">(' + d.nickname + ')</span>'
            : '';
          html +=
            '<tr' +
            (active ? '' : ' style="opacity:.55"') +
            '><td>' +
            d.name +
            nick +
            '</td><td>' +
            (d.salesperson || '—') +
            '</td><td class="num">' +
            vpsCell(d.perf, '') +
            '</td><td class="num">' +
            vpsCell(d.qty, '') +
            '</td></tr>';
        }
        html += '</tbody></table></details>';
      }
      html += '</div>';
    }
    html += '</div>';
    return html;
  }

  function customerTotalsFromDealers(dealerStores) {
    var effective = 0;
    var walkin = 0;
    (dealerStores || []).forEach(function (s) {
      effective += Number(s.effectiveCustomers) || 0;
      walkin += Number(s.walkinPeople) || 0;
    });
    return { effective: effective, walkin: walkin };
  }

  function barUnit(tag, val, mx, cls, unit) {
    unit = unit || '条';
    var pct = Math.round((val / mx) * 130);
    return (
      '<div class="oi-bar-unit">' +
      '<div class="oi-bar-tag">' +
      val +
      ' ' +
      unit +
      '</div>' +
      '<div class="oi-bar-track"><div class="oi-bar-fill ' +
      cls +
      '" style="height:' +
      pct +
      'px"></div></div>' +
      '<div class="oi-bar-cap">' +
      tag +
      '</div></div>'
    );
  }

  function renderOkrTable(ml, monthKey) {
    var tb = '';
    var sumOkr = 0;
    var sumSal = 0;
    for (var i = 0; i < ml.length; i++) {
      var r = ml[i];
      var okr = okrMonthly(r.nm, monthKey);
      var realSal = r.sal;
      sumOkr += okr;
      sumSal += realSal;
      var completion = okr > 0 ? Math.round((realSal / okr) * 1000) / 10 : null;
      tb +=
        '<tr><td>' +
        r.rg +
        '</td><td class="text-left">' +
        dealerRegionStoreLabel(r.rg, r.nm) +
        '</td><td class="num">' +
        fmtNum(okr) +
        '</td><td class="num">' +
        fmtNum(realSal) +
        '</td><td class="num">' +
        (completion != null ? completion + '%' : '—') +
        '</td></tr>';
    }
    var aggCompletion = sumOkr > 0 ? Math.round((sumSal / sumOkr) * 1000) / 10 : 0;
    var foot =
      ml.length +
      ' 家经销商·门店 · OKR 合计 ' +
      fmtNum(sumOkr) +
      ' 万 · 真实销售 ' +
      fmtNum(sumSal) +
      ' 万 · 加权完成率 ' +
      aggCompletion +
      '%';
    return { tbody: tb, foot: foot };
  }

  function renderChannelBars(ml) {
    var labels = (ref && ref.channelLabels) || ['短视频', '直播', '其他'];
    var a;
    var b;
    var c;
    var note = '';
    if (ref && ref.channelLeads) {
      var ch = ref.channelLeads;
      a = ch.shortVideo != null ? ch.shortVideo : ch.tiktok || 0;
      b = ch.live != null ? ch.live : ch.tiktokLive || 0;
      c = ch.other != null ? ch.other : (ch.facebook || 0) + (ch.instagram || 0);
      note =
        '<p class="oi-note">渠道线索来自 <code>越南门店数据.xlsx</code>（TK / Ins / Facebook 列按月汇总）' +
        (ch.displayMonth && ch.displayMonth !== (ref.checkDate || '').slice(0, 7)
          ? ' · 统计月 ' + ch.displayMonth + '（所选月 Excel 无线上记录）'
          : '') +
        (ch.instagram != null && ch.facebook != null
          ? ' · Ins ' + ch.instagram + ' · Facebook ' + ch.facebook
          : '') +
        '。</p>';
    } else {
      a = sum(ml, function (x) {
        return x.Ls;
      });
      b = sum(ml, function (x) {
        return x.Ll;
      });
      c = sum(ml, function (x) {
        return x.Lo;
      });
    }
    var mx = Math.max(a, b, c, 1);
    return (
      note +
      barUnit(labels[0] || '短视频', a, mx, 'a', '条') +
      barUnit(labels[1] || '直播', b, mx, 'b', '条') +
      barUnit(labels[2] || '其他', c, mx, 'c', '条')
    );
  }

  function renderCustomerBars(effective, walkin) {
    var mx = Math.max(effective, walkin, 1);
    return (
      barUnit('有效客户', effective, mx, 'b', '人') + barUnit('进店人数', walkin, mx, 'd', '人')
    );
  }

  /**
   * @param {string} url
   * @returns {Promise<void>}
   */
  /**
   * @param {string} [channelUrl]
   * @param {string} [vnUrl]
   * @returns {Promise<void>}
   */
  function defaultChannelUrl() {
    if (typeof location !== 'undefined' && location.protocol.indexOf('http') === 0) {
      var dateQ = new URLSearchParams(location.search).get('date');
      return dateQ ? '/api/online-channel?date=' + encodeURIComponent(dateQ) : '/api/online-channel';
    }
    return 'data/online_channel_reference.json';
  }

  function init(channelUrl, vnUrl) {
    if (ref && vnRef) return Promise.resolve();
    if (loadPromise) return loadPromise;
    var chUrl = channelUrl || defaultChannelUrl();
    var vUrl = vnUrl || 'data/vn_data_collect_reference.json';
    function fetchJson(url, fallback) {
      return fetch(url)
        .then(function (res) {
          if (!res.ok) throw new Error('HTTP ' + res.status);
          return res.json();
        })
        .catch(function () {
          return fallback;
        });
    }
    loadPromise = Promise.all([
      fetchJson(chUrl, { stores: [], okrByMonth: {}, regionOrder: [] }),
      fetchJson(vnUrl, { months: {}, stores: [] }),
    ]).then(function (pair) {
      ref = pair[0];
      vnRef = pair[1];
    });
    return loadPromise;
  }

  /**
   * @param {{ monthKey?: string, dealerStores?: object[] }} opts
   * @returns {string}
   */
  function renderHtml(opts) {
    opts = opts || {};
    var hasChannel = ref && ref.stores && ref.stores.length;
    var hasVn = vnRef && vnRef.months && Object.keys(vnRef.months).length;
    if (!hasChannel && !hasVn) {
      return (
        '<div class="glass-card oi-merged" id="oi-merged">' +
        '<div class="oi-head"><h2>线上经营 · 渠道与 OKR</h2>' +
        '<p>参考数据加载中或不可用，请刷新页面。</p></div></div>'
      );
    }
    var monthKey = opts.monthKey || '2026-05';
    if (!/^\d{4}-\d{2}$/.test(monthKey)) monthKey = '2026-05';
    var ml = hasChannel ? mainland(scaledStores(monthKey)) : [];
    var okr = hasChannel ? renderOkrTable(ml, monthKey) : { tbody: '', foot: '' };
    var cust = customerTotalsFromDealers(opts.dealerStores || []);
    var channelBlock = hasChannel
      ? '<div class="oi-card">' +
        '<h3>真实销售 ÷ 经销商 OKR（当月目标）</h3>' +
        '<p class="oi-note">全量 <strong>' +
        ((ref && ref.storeCount) || (ref && ref.stores && ref.stores.length) || 0) +
        '</strong> 家门店（<code>config/dealers.json</code>）；大区含中东/欧洲/南亚/东南亚/中亚。<strong>真实销售</strong>来自 <code>vertu-cli sales</code>（万元）；<strong>OKR</strong>来自门店等级配置。</p>' +
        (ref && ref.vpsFile
          ? '<p class="oi-note">VPS 文件：' + ref.vpsFile + (ref.checkDate ? ' · 检查日 ' + ref.checkDate : '') + '</p>'
          : '') +
        '<div class="oi-tbl-wrap"><table class="oi-grid oi-grid-wide"><thead><tr>' +
        '<th>区域</th><th>经销商·区域/门店</th><th class="num">OKR目标(万)</th><th class="num">真实销售(万)</th>' +
        '<th class="num">完成率%</th>' +
        '</tr></thead><tbody>' +
        okr.tbody +
        '</tbody></table></div>' +
        '<p class="oi-foot">' +
        okr.foot +
        '</p></div>' +
        renderDealerRegionHtml(ref && ref.dealerRegion) +
        '<div class="oi-card">' +
        '<h3>客流与有效客户（人）</h3>' +
        '<p class="oi-note">来自当前客流记录，不再根据人数差值推算客户来源。</p>' +
        '<div class="oi-bar-wrap">' +
        renderCustomerBars(cust.effective, cust.walkin) +
        '</div></div>'
      : '';
    return (
      '<div class="glass-card oi-merged p-0 overflow-hidden" id="oi-merged">' +
      '<div class="oi-head">' +
      '<h2>经销商线上经营 · 并入客流分析</h2>' +
      '<p>统计月 <strong>' +
      monthKey +
      '</strong> · 数据来源：vertu-cli 经销商业绩与当前客流记录；没有真实来源的指标不展示。</p>' +
      '</div>' +
      '<div class="oi-dark oi-panel">' +
      channelBlock +
      '</div></div>'
    );
  }

  global.WalkinOnlineMerged = {
    init: init,
    renderHtml: renderHtml,
    isReady: function () {
      return !!(ref && ref.stores && ref.stores.length);
    },
  };
})(typeof window !== 'undefined' ? window : globalThis);
