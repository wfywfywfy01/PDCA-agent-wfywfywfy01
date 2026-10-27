/* Shared presentation for authenticated PDCA and the offline seven-route snapshot. */
(() => {
  'use strict';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => value == null ? 'N/A' : new Intl.NumberFormat('zh-CN').format(value);
  const sourceType = {seo:'自然搜索 · SEO', ai:'可识别AI来源 · GEO观察', other:'其他来源'};
  const day = value => /^\d{8}$/.test(value) ? `${value.slice(0,4)}-${value.slice(4,6)}-${value.slice(6)}` : value;
  const fields = ['screenPageViews','sessions','activeUsers','engagedSessions'];
  const labels = ['浏览量 PV','会话','活跃用户','互动会话'];
  function table(head, rows) {
    return `<div class="pt-scroll"><table><thead><tr>${head.map(v=>`<th scope="col">${esc(v)}</th>`).join('')}</tr></thead><tbody>${rows.join('') || `<tr><td colspan="${head.length}">N/A · 本次报告未返回匹配行，不能据此认定没有访问。</td></tr>`}</tbody></table></div>`;
  }
  const metrics = row => fields.map(key=>`<td class="pt-number">${number(row[key])}</td>`).join('');
  function csv(data, key) {
    const scope=data.scopes[key], rows=[['范围','起日','止日','时区','维度','记录','PV','会话','活跃用户','互动会话']];
    const add=(kind,name,item)=>rows.push([scope.label,data.period.start_date,data.period.end_date,data.period.time_zone,kind,name,...fields.map(f=>item[f] ?? 'N/A')]);
    add('独立汇总','全部来源',scope.summary);add('独立汇总','Organic Search',scope.seo);add('独立汇总','显式AI来源白名单',scope.ai);
    add('核对汇总','正式主机原始流量（含已标记QA）',scope.raw_summary);add('核对汇总','已标记QA流量（已排除）',scope.excluded_qa);
    scope.daily.forEach(row=>add('日期',day(row.date),row));
    scope.pages.forEach(row=>add('页面',row.pagePath,row));
    scope.sources.forEach(row=>add('来源',`${row.sessionSource} / ${row.sessionMedium} / ${row.sessionDefaultChannelGroup}`,row));
    const cell=value=>{let text=String(value);if(/^\s*[=+\-@]|^[\t\r\n]/.test(text))text="'"+text;return '"'+text.replace(/"/g,'""')+'"';};
    const blob=new Blob(['\ufeff'+rows.map(row=>row.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'});
    const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`Partner_GA4_${key}_${data.period.end_date}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  function mount(root, data) {
    root.classList.add('partner-traffic');
    if(!data || data.schema_version!==1 || data.test_traffic_excluded!==true || !data.scopes?.recruitment || !data.scopes?.content) {
      root.textContent='Partner流量 N/A · 尚未载入可核验的GA4报表。';return;
    }
    let key='recruitment';
    function draw() {
      const scope=data.scopes[key],period=data.period;
      const stale=data.stale || Date.now()-new Date(data.fetched_at).getTime()>86400000;
      const fetched=new Date(data.fetched_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
      const stats=[['页面浏览量 PV',scope.summary.screenPageViews,'同一人多次浏览会重复计数'],
        ['访问会话',scope.summary.sessions,'涉及这些页面的会话'],['活跃用户',scope.summary.activeUsers,'GA4口径，非已核客户'],
        ['自然搜索会话 · SEO',scope.seo.sessions,'GA4渠道：Organic Search'],
        ['可识别AI来源会话',scope.ai.sessions,'GEO观察；不代表全部AI曝光']];
      const daily=[...scope.daily].sort((a,b)=>a.date.localeCompare(b.date));
      const max=Math.max(1,...daily.map(r=>r.screenPageViews));
      root.innerHTML=`<div class="pt-heading"><div><span class="pt-kicker">路径 05 · SEO / GEO</span><h2>Partner 页面流量</h2></div><button type="button" class="pt-export">导出当前范围 CSV</button></div>
        <div class="pt-tabs" aria-label="页面范围">${Object.entries(data.scopes).map(([id,s])=>`<button type="button" data-pt-scope="${esc(id)}" aria-pressed="${id===key}">${esc(s.label)}</button>`).join('')}</div>
        <p class="pt-period">${esc(period.start_date)} 至 ${esc(period.end_date)} · ${esc(period.time_zone)} · ${data.days}个完整自然日</p>
        <p class="pt-muted">${key==='recruitment'?'范围：vertu.com 的 /partners 及语言版本。':'范围：vertu.com 的 /news/partners 频道及语言版本；原始重复斜杠路径分别保留。'}排除本地主机、已标记QA流量与其他仅含 partner 字样的文章。</p>
        <p class="pt-status" role="status">GA4报表快照 · 获取 ${esc(fetched)} 北京时间${stale?' · 数据已过期，需重新同步':''}${data.error?' · 本次同步失败：'+esc(data.error):''}</p>
        ${(data.quality || []).length?'<p class="pt-warning">GA4提示阈值、抽样或高基数限制：'+esc(data.quality.join(' / '))+'。当前报告可能受限，不能当作完整覆盖。</p>':''}
        <div class="pt-stats">${stats.map(([title,value,note])=>`<div><span>${esc(title)}</span><strong>${number(value)}</strong><small>${esc(note)}</small></div>`).join('')}</div>
        <details class="pt-exclusions"><summary>测试流量核对 · 已标记QA ${number(scope.excluded_qa.screenPageViews)} PV / ${number(scope.excluded_qa.sessions)}会话，已从上方排除</summary>${table(['独立查询范围',...labels],[['正式主机原始流量（含QA）',scope.raw_summary],['已标记QA流量',scope.excluded_qa],['排除已标记QA后',scope.summary]].map(([label,row])=>`<tr><th scope="row">${esc(label)}</th>${metrics(row)}</tr>`))}<p class="pt-muted">排除规则：媒介为 qa，或来源为 codex_prod_canary / codex_release_test。三组数据分别查询，用户数不可相减。仍可能含未标记内部访问；管理后台等来源保留在明细中供核查。</p></details>
        <p class="pt-boundary">这些是获客上游流量。表单提交、有效线索、客户、订单与回款尚未关联，均不由访问量推算。以下统计不随客户名单的国家、负责人、期间筛选变化。</p>
        <h3>每日浏览量</h3><div class="pt-chart" role="img" aria-label="每日浏览量柱形图，精确数值见下方每日数据表">${daily.map(row=>`<span title="${esc(day(row.date))}：${row.screenPageViews} PV"><i style="height:${row.screenPageViews/max*100}%"></i></span>`).join('')}</div><p class="pt-chart-caption">${daily.length?esc(day(daily[0].date))+' — '+esc(day(daily[daily.length-1].date)):'N/A · 未返回日期行'} · 未报告日期不补成零</p>
        <details><summary>每日数据 · ${daily.length}个已报告日期</summary>${table(['日期',...labels],daily.map(row=>`<tr><th scope="row">${esc(day(row.date))}</th>${metrics(row)}</tr>`))}</details>
        <h3>流量从哪里来</h3><p class="pt-muted">展示会话来源；自然搜索按GA4渠道识别。可识别AI来源为显式来源白名单，丢失来源的访问及搜索内AI结果无法完整区分。</p>
        ${table(['来源 / 媒介','GA4渠道','观察分类',...labels], [...scope.sources].sort((a,b)=>b.sessions-a.sessions).map(row=>`<tr><th scope="row">${esc(row.sessionSource)} / ${esc(row.sessionMedium)}</th><td>${esc(row.sessionDefaultChannelGroup)}</td><td>${esc(sourceType[row.source_type] || '其他来源')}</td>${metrics(row)}</tr>`))}
        <h3>具体页面</h3>${table(['页面',...labels],[...scope.pages].sort((a,b)=>b.screenPageViews-a.screenPageViews).map(row=>`<tr><th scope="row"><a href="https://vertu.com${esc(row.pagePath.startsWith('/')?row.pagePath:'/'+row.pagePath)}" target="_blank" rel="noopener noreferrer">${esc(row.pagePath)}</a></th>${metrics(row)}</tr>`))}
        <details class="pt-provenance"><summary>获取方式与统计口径</summary><p>来源：GA4 Data API · 属性 ${esc(data.property_id)}。后端服务账号以 analytics.readonly 权限查询；页面不保存凭据。</p><p>总量由GA4独立汇总查询取得，用户和会话不相加页面或日期明细，也不把两个页面范围相加去重。空查询结果显示N/A，只有API明确返回0才显示0。GA4后续处理可能修订最近日期。</p><p>明细已按返回总行数完整分页；查询条件、原始返回及采集时间保存在报表依据中。<a href="https://developers.google.com/analytics/devguides/reporting/data/v1/quickstart" target="_blank" rel="noopener noreferrer">官方API说明</a></p></details>`;
      root.querySelectorAll('[data-pt-scope]').forEach(button=>button.addEventListener('click',()=>{key=button.dataset.ptScope;draw();root.querySelector(`[data-pt-scope="${key}"]`).focus();}));
      root.querySelector('.pt-export').addEventListener('click',()=>csv(data,key));
    }
    draw();
    return {export:()=>csv(data,key)};
  }
  window.PartnerTraffic={mount};
})();
