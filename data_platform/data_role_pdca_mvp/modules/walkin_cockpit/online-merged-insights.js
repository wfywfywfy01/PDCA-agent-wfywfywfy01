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

  /** @param {string} s */
  function hashStr(s) {
    var h = 0;
    for (var i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
    return Math.abs(h);
  }

  /**
   * VERTU 介绍客户业绩（mock，按门店+月份稳定随机）
   * @param {string} nm
   * @param {number} realSal
   * @param {string} monthKey
   */
  function mockVertuSales(nm, realSal, monthKey) {
    if (!realSal || realSal <= 0) return 0;
    var h = hashStr(nm + '|' + monthKey);
    var share = 0.06 + (h % 19) / 100;
    return Math.round(realSal * share * 10) / 10;
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

  function aggRegions(ml) {
    var order = (ref && ref.regionOrder) || ['中东', '欧洲', '南亚', '东南亚', '中亚'];
    var out = [];
    for (var i = 0; i < order.length; i++) {
      var rg = order[i];
      var L = ml.filter(function (x) {
        return x.rg === rg;
      });
      if (!L.length) continue;
      var Ls = sum(L, function (x) {
        return x.Ls;
      });
      var Ll = sum(L, function (x) {
        return x.Ll;
      });
      var Lo = sum(L, function (x) {
        return x.Lo;
      });
      out.push({ rg: rg, Ls: Ls, Ll: Ll, Lo: Lo, ld: Ls + Ll + Lo });
    }
    return out;
  }

  function customerOwnershipFromDealers(dealerStores) {
    var own = 0;
    var vertu = 0;
    (dealerStores || []).forEach(function (s) {
      var eff = Number(s.effectiveCustomers) || 0;
      var people = Number(s.walkinPeople) || 0;
      own += eff;
      vertu += Math.max(0, people - eff);
    });
    if (own <= 0 && vertu <= 0 && dealerStores && dealerStores.length) {
      own = sum(dealerStores, function (x) {
        return Number(x.wechatAddCount) || 0;
      });
      vertu = sum(dealerStores, function (x) {
        return Math.max(0, (Number(x.walkinPeople) || 0) - (Number(x.wechatAddCount) || 0));
      });
    }
    return { own: own, vertu: vertu };
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
    var est = (ref && ref.estRatio) || 4;
    var tb = '';
    var sumOkr = 0;
    var sumSal = 0;
    var sumVertu = 0;
    for (var i = 0; i < ml.length; i++) {
      var r = ml[i];
      var okr = okrMonthly(r.nm, monthKey);
      var realSal = r.sal;
      var vertuSal = mockVertuSales(r.nm, realSal, monthKey);
      sumOkr += okr;
      sumSal += realSal;
      sumVertu += vertuSal;
      var completion = okr > 0 ? Math.round((realSal / okr) * 1000) / 10 : null;
      var vertuShare =
        realSal > 0 ? Math.round((vertuSal / realSal) * 1000) / 10 : null;
      var diff =
        completion != null ? Math.round((completion - est) * 10) / 10 : null;
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
        '</td><td class="num">' +
        fmtNum(vertuSal) +
        '</td><td class="num">' +
        (vertuShare != null ? vertuShare + '%' : '—') +
        '</td><td class="num">' +
        est +
        '%</td><td class="num ' +
        (diff != null && diff >= 0 ? 'oi-delta-ok' : '') +
        '">' +
        (diff != null ? (diff >= 0 ? '+' : '') + diff + '%' : '—') +
        '</td></tr>';
    }
    var aggCompletion = sumOkr > 0 ? Math.round((sumSal / sumOkr) * 1000) / 10 : 0;
    var aggVertuShare =
      sumSal > 0 ? Math.round((sumVertu / sumSal) * 1000) / 10 : 0;
    var foot =
      ml.length +
      ' 家经销商·门店 · OKR 合计 ' +
      fmtNum(sumOkr) +
      ' 万 · 真实销售 ' +
      fmtNum(sumSal) +
      ' 万 · 加权完成率 ' +
      aggCompletion +
      '% · VERTU 介绍业绩(mock) ' +
      fmtNum(sumVertu) +
      ' 万 · 占真实销售 ' +
      aggVertuShare +
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

  function renderCustomerBars(own, vertu) {
    var mx = Math.max(own, vertu, 1);
    return (
      barUnit('自有有效客户', own, mx, 'b', '人') + barUnit('VERTU 推送', vertu, mx, 'd', '人')
    );
  }

  /**
   * 区域汇总表：短视频/直播/线索/真实销售/完成率均 mock（按区域+月稳定）
   * @param {string} rg
   * @param {number} storeCount
   * @param {string} monthKey
   * @param {number} scale
   */
  function mockRegionMetrics(rg, storeCount, monthKey, scale) {
    var h = hashStr(rg + '|' + monthKey);
    var n = Math.max(1, storeCount);
    var sv = Math.round(n * (68 + (h % 28)) * scale);
    var lv = Math.round(n * (7 + ((h >> 4) % 7)) * scale);
    var ld = Math.round(sv * (0.78 + (h % 15) / 100) + lv * 2.2);
    var sal = Math.round(n * (48 + (h % 35)) * scale * 10) / 10;
    var avgCompletion = Math.round((3.5 + (h % 9) / 10) * 10) / 10;
    return { sv: sv, lv: lv, ld: ld, sal: sal, avgCompletion: avgCompletion };
  }

  /**
   * @param {string} monthKey
   * @param {object[]} dealerStores
   */
  function buildRegionSummaryRows(monthKey, dealerStores) {
    var scale = scaleFactor(monthKey);
    var rows = [];
    var vnMonth =
      vnRef && vnRef.months
        ? vnRef.months[monthKey] || vnRef.months[Object.keys(vnRef.months).sort().pop()]
        : null;
    if (vnMonth && vnMonth.regions) {
      for (var vi = 0; vi < vnMonth.regions.length; vi++) {
        var vr = vnMonth.regions[vi];
        var vm = mockRegionMetrics(vr.rg, vr.storeCount, monthKey, scale);
        rows.push({
          rg: vr.rg,
          storeCount: vr.storeCount,
          realRegion: true,
          realStores: true,
          storeNames: vr.storeNames || [],
          sv: vm.sv,
          lv: vm.lv,
          ld: vm.ld,
          sal: vm.sal,
          avgCompletion: vm.avgCompletion,
        });
      }
    }
    var byRg = {};
    (dealerStores || []).forEach(function (s) {
      if (s.region === '越南区' && s.dataSource === 'vietnam_reference') return;
      var rg = s.region || '其他';
      byRg[rg] = (byRg[rg] || 0) + 1;
    });
    var order = (ref && ref.regionOrder) || ['中东', '欧洲', '南亚', '东南亚', '中亚', '其他'];
    for (var oi = 0; oi < order.length; oi++) {
      var rgName = order[oi];
      if (!byRg[rgName] || rgName === '越南区') continue;
      var dm = mockRegionMetrics(rgName, byRg[rgName], monthKey, scale);
      rows.push({
        rg: rgName,
        storeCount: byRg[rgName],
        realRegion: true,
        realStores: true,
        sv: dm.sv,
        lv: dm.lv,
        ld: dm.ld,
        sal: dm.sal,
        avgCompletion: dm.avgCompletion,
      });
    }
    return rows;
  }

  function renderRegionSummaryTable(monthKey, dealerStores) {
    var rows = buildRegionSummaryRows(monthKey, dealerStores);
    if (!rows.length) {
      return { tbody: '', foot: '暂无区域汇总数据' };
    }
    var tb = '';
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      tb +=
        '<tr><td>' +
        r.rg +
        '</td><td class="num">' +
        r.storeCount +
        '</td><td class="num">' +
        r.sv +
        '</td><td class="num">' +
        r.lv +
        '</td><td class="num">' +
        r.ld +
        '</td><td class="num">' +
        fmtNum(r.sal) +
        '</td><td class="num">' +
        r.avgCompletion +
        '%</td></tr>';
    }
    var vnNames =
      rows[0] && rows[0].storeNames && rows[0].storeNames.length
        ? ' · 越南店：' + rows[0].storeNames.join('、')
        : '';
    var foot =
      '区域/门店数：越南区来自 Data collecet(5).xlsx（' +
      (vnRef && vnRef.sourceFile ? vnRef.sourceFile : 'vn_data_collect_reference.json') +
      '）；海外代理商大区来自当前数据包统计' +
      vnNames +
      ' · 短视频/直播/线索/真实销售/完成率均值为演示 mock。';
    return { tbody: tb, foot: foot };
  }

  function renderStack(agg) {
    var h = '';
    for (var i = 0; i < agg.length; i++) {
      var r = agg[i];
      var t = r.ld || 1;
      var hs = Math.max(8, Math.round((r.Ls / t) * 110));
      var hl = Math.max(8, Math.round((r.Ll / t) * 110));
      var ho = Math.max(8, 130 - hs - hl);
      h +=
        '<div class="oi-stack-one">' +
        '<div class="oi-stack-v" style="height:130px">' +
        '<div class="seg oi-seg-o" style="height:' +
        ho +
        'px">' +
        r.Lo +
        '</div>' +
        '<div class="seg oi-seg-l" style="height:' +
        hl +
        'px">' +
        r.Ll +
        '</div>' +
        '<div class="seg oi-seg-s" style="height:' +
        hs +
        'px">' +
        r.Ls +
        '</div></div>' +
        '<div class="oi-stack-sum">合计 ' +
        r.ld +
        ' 条</div>' +
        '<div class="oi-stack-rg">' +
        r.rg +
        '</div></div>';
    }
    return h;
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
      fetchJson(chUrl, { stores: [], okrByMonth: {}, estRatio: 4, regionOrder: [] }),
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
    var agg = hasChannel ? aggRegions(ml) : [];
    var cust = customerOwnershipFromDealers(opts.dealerStores || []);
    var regionTbl = renderRegionSummaryTable(monthKey, opts.dealerStores || []);
    var channelBlock = hasChannel
      ? '<div class="oi-card">' +
        '<h3>真实销售 ÷ 经销商 OKR（当月目标）</h3>' +
        '<p class="oi-note">全量 <strong>' +
        ((ref && ref.storeCount) || (ref && ref.stores && ref.stores.length) || 0) +
        '</strong> 家门店（<code>config/dealers.json</code>）；大区含中东/欧洲/南亚/东南亚/中亚。<strong>真实销售</strong>来自 vertu <code>customer_summary</code>（万元）；<strong>OKR</strong>默认月目标 120 万（可按 level 配置）；<strong>VERTU 介绍业绩</strong>为演示 mock；<strong>预估占比</strong> 固定 ' +
        ((ref && ref.estRatio) || 4) +
        '%。</p>' +
        (ref && ref.vpsFile
          ? '<p class="oi-note">VPS 文件：' + ref.vpsFile + (ref.checkDate ? ' · 检查日 ' + ref.checkDate : '') + '</p>'
          : '') +
        '<div class="oi-tbl-wrap"><table class="oi-grid oi-grid-wide"><thead><tr>' +
        '<th>区域</th><th>经销商·区域/门店</th><th class="num">OKR目标(万)</th><th class="num">真实销售(万)</th>' +
        '<th class="num">完成率%</th><th class="num">VERTU介绍业绩(万)</th><th class="num">VERTU占业绩%</th>' +
        '<th class="num">预估占比%</th><th class="num">与预估差异</th>' +
        '</tr></thead><tbody>' +
        okr.tbody +
        '</tbody></table></div>' +
        '<p class="oi-foot">' +
        okr.foot +
        '</p></div>' +
        renderDealerRegionHtml(ref && ref.dealerRegion) +
        '<div class="oi-card">' +
        '<h3>客户来源（人）</h3>' +
        '<p class="oi-note">替代原「四周线索趋势」：代理商 <strong>自有有效客户</strong> 与 <strong>VERTU 推送</strong>（进店人数扣除自有有效口径）。</p>' +
        '<div class="oi-bar-wrap">' +
        renderCustomerBars(cust.own, cust.vertu) +
        '</div></div>' +
        '<div class="oi-card">' +
        '<h3>区域线索堆叠（条）</h3>' +
        '<div class="oi-stack-row">' +
        renderStack(agg) +
        '</div></div>'
      : '';
    return (
      '<div class="glass-card oi-merged p-0 overflow-hidden" id="oi-merged">' +
      '<div class="oi-head">' +
      '<h2>经销商线上经营 · 并入客流分析</h2>' +
      '<p>统计月 <strong>' +
      monthKey +
      '</strong> · 数据优先级：vertu CLI 经销商业绩 JSON → 静态参考 JSON。渠道线索为派生演示；客户来源为当前代理商汇总。</p>' +
      '</div>' +
      '<div class="oi-dark oi-panel">' +
      channelBlock +
      '<div class="oi-card">' +
      '<h3>区域汇总表（经销商·越南登记门店）</h3>' +
      '<p class="oi-note"><strong>区域、门店数</strong>为真实（越南四店来自 Data collecet(5).xlsx；代理商大区来自当前页数据包）；<strong>短视频 / 直播 / 线索 / 真实销售 / 完成率均值</strong>为 mock。</p>' +
      '<div class="oi-tbl-wrap"><table class="oi-grid oi-grid-wide"><thead><tr>' +
      '<th>区域</th><th class="num">门店数</th><th class="num">短视频条数</th><th class="num">直播场次</th>' +
      '<th class="num">线索</th><th class="num">真实销售(万)</th><th class="num">完成率均值%</th>' +
      '</tr></thead><tbody>' +
      regionTbl.tbody +
      '</tbody></table></div>' +
      '<p class="oi-foot">' +
      regionTbl.foot +
      '</p></div>' +
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
