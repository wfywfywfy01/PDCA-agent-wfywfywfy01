(function () {
  const API = "";
  const state = {
    tab: "overview",
    date: "2026-05-26",
    data: null,
    loading: false,
    source: "",
    error: "",
  };

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function toneClass(tone) {
    if (tone === "ok") return "ok";
    if (tone === "warn") return "warn";
    if (tone === "bad") return "bad";
    return "neutral";
  }

  function pctBar(label, actual, target) {
    const t = Number(target) || 1;
    const a = Number(actual) || 0;
    const p = Math.min(100, Math.round((a / t) * 100));
    return (
      '<div class="gauge-row">' +
      '<span style="width:88px">' + esc(label) + "</span>" +
      '<div class="track"><div class="fill" style="width:' + p + '%"></div></div>' +
      '<span style="width:72px;text-align:right" class="text-muted">' + a + "/" + target + "</span>" +
      "</div>"
    );
  }

  function kpiGrid(kpis) {
    return (
      '<div class="grid-kpi">' +
      (kpis || [])
        .map(function (k) {
          return (
            '<div class="kpi-card">' +
            '<div class="lbl">' + esc(k.label) + "</div>" +
            '<div class="val ' + (k.tone === "bad" ? "text-bad" : k.tone === "warn" ? "text-warn" : "") + '">' +
            esc(k.value) +
            "</div>" +
            '<span class="tag ' + toneClass(k.tone) + '">' + esc(k.tone || "neutral") + "</span>" +
            "</div>"
          );
        })
        .join("") +
      "</div>"
    );
  }

  function viewOverview(d) {
    const team = d.team || {};
    const insights = (d.ai_insights || []).map(function (x) {
      return "<li>" + esc(x) + "</li>";
    }).join("");
    const regionRows = (d.regions || [])
      .map(function (r) {
        return (
          "<tr><td>" + esc(r.name) + "</td><td>" + r.dealer_count + "</td><td>" + r.overdue_count + "</td><td>" + r.owner_count + "</td></tr>"
        );
      })
      .join("");
    const salesRows = (d.sales || [])
      .map(function (s) {
        return (
          "<tr><td>" + esc(s.name) + "</td><td>" + (s.log_submitted ? "已提交" : "未提交") + "</td><td>" + s.process_rate + "%</td><td>" + esc(s.risk) + "</td></tr>"
        );
      })
      .join("");
    return (
      '<section class="mb-6">' +
      '<h2 class="text-lg font-bold mb-4">业务总览 · ' + esc(d.meta.as_of_date) + "</h2>" +
      kpiGrid(d.kpis) +
      '<div class="flex gap-4 mb-6 mt-4 flex-wrap">' +
      '<div class="flex-1 border rounded-xl p-4 bg-white shadow-sm" style="min-width:200px">' +
      '<div class="text-muted text-xs">团队月度目标</div><div class="text-2xl font-bold">' + esc(team.target_wan != null ? team.target_wan + " 万" : "待补充") + "</div>" +
      "</div>" +
      '<div class="flex-1 border rounded-xl p-4 bg-white shadow-sm" style="min-width:200px">' +
      '<div class="text-muted text-xs">客户资源</div><div class="text-2xl font-bold">' + team.dealer_total + " 家</div>" +
      '<div class="text-sm text-muted">组长占比 ' + team.leader_share_pct + "%</div>" +
      "</div>" +
      '<div class="flex-1 border rounded-xl p-4 bg-white shadow-sm" style="min-width:200px">' +
      '<div class="text-muted text-xs">状态</div><div class="text-2xl font-bold">' + esc(team.status) + "</div>" +
      "</div>" +
      "</div>" +
      '<div class="insight-box mb-6"><strong>AI / 规则洞察</strong><ul class="mt-2">' + insights + "</ul></div>" +
      '<h3 class="font-semibold mb-2">区域分布</h3>' +
      '<table class="data mb-6"><thead><tr><th>区域</th><th>客户数</th><th>超期</th><th>负责人数</th></tr></thead><tbody>' +
      (regionRows || "<tr><td colspan='4'>无数据</td></tr>") +
      "</tbody></table>" +
      '<h3 class="font-semibold mb-2">成员摘要</h3>' +
      '<table class="data"><thead><tr><th>成员</th><th>日报</th><th>过程完成率</th><th>风险</th></tr></thead><tbody>' +
      salesRows +
      "</tbody></table>" +
      "</section>"
    );
  }

  function viewSales(d) {
    return (
      '<section><h2 class="text-lg font-bold mb-4">销售监控</h2><div class="sales-grid">' +
      (d.sales || [])
        .map(function (s) {
          const metrics = s.metrics || {};
          const bars = ["有效触达", "客户跟进", "报价", "新增客户", "重点客户维护"]
            .filter(function (k) {
              return metrics[k];
            })
            .map(function (k) {
              return pctBar(k, metrics[k].actual, metrics[k].target);
            })
            .join("");
          const tags = (s.anomalies || [])
            .map(function (a) {
              return '<span class="tag warn">' + esc(a) + "</span> ";
            })
            .join("");
          return (
            '<div class="sale-card">' +
            '<div class="flex justify-between items-center mb-2">' +
            '<span class="font-bold text-lg">' + esc(s.name) + "</span>" +
            '<span class="tag ' + (s.log_submitted ? "ok" : "bad") + '">' + (s.log_submitted ? "日报已交" : "未交日报") + "</span>" +
            "</div>" +
            '<div class="text-sm text-muted mb-2">过程完成率 ' + s.process_rate + "% · 负责客户 " + s.owned_customers + " · 目标 " + esc(s.target_wan != null ? s.target_wan + "万" : "待补充") + "</div>" +
            '<div class="mb-2">' + tags + "</div>" +
            bars +
            "</div>"
          );
        })
        .join("") +
      "</div></section>"
    );
  }

  function viewDealers(d) {
    const filter = state.regionFilter || "all";
    const list = (d.dealers || []).filter(function (c) {
      return filter === "all" || c.region === filter;
    });
    const regions = ["all"].concat(
      Array.from(
        new Set((d.dealers || []).map(function (c) {
          return c.region;
        }))
      ).filter(Boolean)
    );
    const opts = regions
      .map(function (r) {
        const label = r === "all" ? "全部区域" : r;
        return '<option value="' + esc(r) + '"' + (filter === r ? " selected" : "") + ">" + esc(label) + "</option>";
      })
      .join("");
    const cards = list
      .map(function (c) {
        return (
          '<div class="dealer-card' + (c.overdue ? " overdue" : "") + '">' +
          '<div class="flex justify-between"><strong>' + esc(c.name) + "</strong>" +
          '<span class="tag ' + (c.overdue ? "bad" : "ok") + '">' + (c.overdue ? "超期" : c.priority) + "</span></div>" +
          '<div class="text-sm text-muted mt-1">' + esc(c.region) + " · " + esc(c.country) + " · " + esc(c.owner) + "</div>" +
          '<div class="text-xs mt-2">最近跟进：' + esc(c.last_followup || "无") +
          (c.days_since != null ? "（" + c.days_since + " 天前）" : "") +
          "</div>" +
          '<div class="text-xs text-muted mt-1">下一步：' + esc(c.next_action || "—") + "</div>" +
          "</div>"
        );
      })
      .join("");
    return (
      '<section><h2 class="text-lg font-bold mb-4">区域与经销商</h2>' +
      '<div class="mb-4"><label class="text-sm text-muted">筛选 </label><select id="region-filter" class="ml-2">' +
      opts +
      "</select></div>" +
      '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px">' +
      cards +
      "</div></section>"
    );
  }

  function viewCustomers(d) {
    const overdue = (d.dealers || []).filter(function (c) {
      return c.overdue;
    });
    const rows = overdue
      .map(function (c) {
        return (
          "<tr><td>" + esc(c.name) + "</td><td>" + esc(c.owner) + "</td><td>" + c.priority + "</td><td>" + c.days_since + " 天</td><td>" + esc(c.next_action) + "</td></tr>"
        );
      })
      .join("");
    const actions = (d.pdca && d.pdca.actions) || [];
    return (
      '<section><h2 class="text-lg font-bold mb-4">客户健康 & PDCA</h2>' +
      '<h3 class="font-semibold mb-2">超期客户（' + overdue.length + "）</h3>" +
      '<table class="data mb-6"><thead><tr><th>客户</th><th>负责人</th><th>级别</th><th>超期</th><th>下一步</th></tr></thead><tbody>' +
      (rows || "<tr><td colspan='5'>暂无超期</td></tr>") +
      "</tbody></table>" +
      '<h3 class="font-semibold mb-2">明日管理动作</h3>' +
      '<ul class="insight-box">' +
      actions.map(function (a) {
        return "<li>" + esc(a) + "</li>";
      }).join("") +
      "</ul></section>"
    );
  }

  function mainContent() {
    if (state.loading) return '<p class="text-muted">加载中…</p>';
    if (state.error) return '<p class="text-bad">' + esc(state.error) + "</p>";
    if (!state.data) return '<p class="text-muted">暂无 snapshot，点击「刷新数据」</p>';
    const d = state.data;
    if (state.tab === "overview") return viewOverview(d);
    if (state.tab === "sales") return viewSales(d);
    if (state.tab === "dealers") return viewDealers(d);
    if (state.tab === "customers") return viewCustomers(d);
    return "";
  }

  function banner() {
    if (state.loading) {
      return '<div class="banner warn">正在加载 / 重建 snapshot…</div>';
    }
    if (state.error) {
      return '<div class="banner bad">' + esc(state.error) + "</div>";
    }
    const m = state.data && state.data.meta;
    return (
      '<div class="banner ok">数据源：' +
      esc((m && m.source) || "") +
      " · 检查日 " +
      esc((m && m.as_of_date) || "") +
      " · 文件 " +
      esc(state.source) +
      " · 生成于 " +
      esc((m && m.generated_at) || "") +
      "</div>"
    );
  }

  function navBtn(id, label) {
    return (
      '<button type="button" class="nav-btn' +
      (state.tab === id ? " active" : "") +
      '" data-tab="' +
      id +
      '">' +
      esc(label) +
      "</button>"
    );
  }

  function render() {
    const root = document.getElementById("root");
    root.innerHTML =
      '<aside class="sidebar w-64 border-r bg-white flex flex-col h-screen">' +
      '<div class="p-6">' +
      '<div class="mb-6"><div class="text-lg font-bold">经销商 PDCA</div>' +
      '<div class="text-xs text-muted">杨晶晶小组 · v1</div></div>' +
      '<nav class="flex flex-col gap-2">' +
      navBtn("overview", "业务总览") +
      navBtn("sales", "销售监控") +
      navBtn("dealers", "区域与经销商") +
      navBtn("customers", "客户健康") +
      "</nav></div>" +
      '<div class="p-6 mt-auto border-t text-xs text-muted">数据源：本地 Check + 客户池</div>' +
      "</aside>" +
      '<main class="flex-1 flex flex-col overflow-hidden">' +
      banner() +
      '<div class="mobile-tabs">' +
      navBtn("overview", "总览") +
      navBtn("sales", "销售") +
      navBtn("dealers", "经销商") +
      navBtn("customers", "客户") +
      "</div>" +
      '<header class="flex items-center justify-between px-4 py-3 border-b bg-white gap-3 flex-wrap">' +
      '<div class="flex items-center gap-3">' +
      '<label class="text-sm text-muted">检查日</label>' +
      '<input type="date" id="date-input" value="' +
      esc(state.date) +
      '" />' +
      '<button type="button" class="btn btn-primary" id="btn-reload">刷新数据</button>' +
      "</div>" +
      '<span class="text-sm text-muted">http://127.0.0.1:8766</span>' +
      "</header>" +
      '<div class="flex-1 overflow-y-auto p-8">' +
      mainContent() +
      "</div></main>";
    bind();
  }

  function bind() {
    document.querySelectorAll(".nav-btn").forEach(function (btn) {
      btn.onclick = function () {
        state.tab = btn.getAttribute("data-tab");
        render();
      };
    });
    const dateInput = document.getElementById("date-input");
    if (dateInput) {
      dateInput.onchange = function () {
        state.date = dateInput.value;
        loadSnapshot(false);
      };
    }
    const reload = document.getElementById("btn-reload");
    if (reload) {
      reload.onclick = function () {
        loadSnapshot(true);
      };
    }
    const rf = document.getElementById("region-filter");
    if (rf) {
      rf.onchange = function () {
        state.regionFilter = rf.value;
        render();
      };
    }
  }

  function loadSnapshot(rebuild) {
    state.loading = true;
    state.error = "";
    render();
    const done = function (payload) {
      state.loading = false;
      if (!payload.ok) {
        state.error = payload.error || "加载失败";
        state.data = null;
      } else {
        state.data = payload.data;
        state.source = payload.file || "";
        if (payload.data && payload.data.meta) {
          state.date = payload.data.meta.as_of_date;
        }
      }
      render();
    };
    if (rebuild) {
      fetch(API + "/api/rebuild", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: state.date }),
      })
        .then(function (r) {
          return r.json();
        })
        .then(done)
        .catch(function (e) {
          done({ ok: false, error: String(e) });
        });
      return;
    }
    fetch(API + "/api/snapshot?date=" + encodeURIComponent(state.date))
      .then(function (r) {
        return r.json();
      })
      .then(done)
      .catch(function (e) {
        done({ ok: false, error: String(e) });
      });
  }

  render();
  loadSnapshot(true);
})();
