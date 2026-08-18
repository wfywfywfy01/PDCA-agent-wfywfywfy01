# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：首页渲染与 VPS 汇总
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。


def render_pdca_vps(date_text, message=""):
    yesterday_text = previous_date_text(date_text)
    if should_use_local_pdca_cache(date_text):
        daily = local_daily_report_cache(date_text, "本地汇报缓存")
        yesterday = local_daily_report_cache(yesterday_text, "本地汇报缓存")
        month_okr = local_month_okr_cache(date_text, "本地汇报缓存")
        all_todos = {"ok": True, "rows": local_todo_payload_rows(date_text), "count": len(local_todo_payload_rows(date_text)), "error": ""}
    else:
        daily = fetch_vps_daily_report(date_text)
        yesterday = fetch_vps_daily_report(yesterday_text)
        month_okr = fetch_vps_month_okr(date_text)
        all_todos = fetch_vps_all_todos()
    today_plan_rows = report_payload_items(yesterday, "tomorrow") if yesterday["ok"] else []
    yesterday_done_rows = report_payload_items(yesterday, "today") if yesterday["ok"] else []
    today_done_rows = report_payload_items(daily, "today") if daily["ok"] else []
    delivery_checks = build_delivery_checks(
        today_plan_rows,
        today_done_rows,
        all_todos["rows"] if all_todos["ok"] else [],
        date_text,
    )
    user = daily.get("identity", {}).get("user", {})
    if daily["ok"]:
        report_rows = daily_report_table_rows(daily["reports"]) or '<tr><td colspan="3">未查询到「经销商-日报推送」群的今日日报，建议补交或确认 IM 日报是否同步。</td></tr>'
        report_status = "已同步" if daily["reports"] else "未查询到今日日报"
    else:
        report_rows = f'<tr><td colspan="3">VPS 日报拉取失败：{esc(daily["error"])}</td></tr>'
        report_status = "拉取失败"
    if yesterday["ok"]:
        today_rows = pdca_todo_rows(today_plan_rows) or '<tr><td colspan="4">「经销商-日报推送」群昨日日报未写入今日计划。</td></tr>'
        done_rows = pdca_todo_rows(yesterday_done_rows) or '<tr><td colspan="4">「经销商-日报推送」群昨日日报未写入完成事项。</td></tr>'
    else:
        today_rows = f'<tr><td colspan="4">「经销商-日报推送」群昨日日报拉取失败：{esc(yesterday["error"])}</td></tr>'
        done_rows = f'<tr><td colspan="4">「经销商-日报推送」群昨日日报拉取失败：{esc(yesterday["error"])}</td></tr>'
    if month_okr["ok"]:
        okr_table = okr_rows(month_okr["rows"]) or '<tr><td colspan="3">VPS 暂无本月 OKR/月待办数据。</td></tr>'
    else:
        okr_table = f'<tr><td colspan="3">VPS OKR 拉取失败：{esc(month_okr["error"])}</td></tr>'
    source_note = pdca_vps_source_note(daily, yesterday, month_okr, all_todos)
    cache_banner = ""
    if daily.get("from_cache") or yesterday.get("from_cache") or month_okr.get("from_cache"):
        cache_banner = f'<p class="message" style="border-color:#efc7c3;background:#fff6f4;color:#8a3b2f;">{esc(source_note)}</p>'
    else:
        cache_banner = f'<p class="message">{esc(source_note)}</p>'
    body = f"""
    <section>
      <div class="page-toolbar">
        <div>
          <h2>PDCA 日结（VPS）</h2>
          <p>来源：「经销商-日报推送」IM 群日报 + VPS OKR。今日计划优先取昨日群日报里的“明日计划”，月待办取本月 OKR。</p>
          {cache_banner}
        </div>
        {button("返回首页", route_url("/", date_text), "light")}
      </div>
      <div class="grid">
        {metric_card("群日报状态", report_status, f"经销商-日报推送 / {date_text}", daily["ok"] and bool(daily["reports"]))}
        {metric_card("今日预计待办", f"{len(today_plan_rows)} 项", f"来自 {yesterday_text} 群日报的明日计划", bool(today_plan_rows))}
        {metric_card("交付检查", f"{sum(1 for item in delivery_checks if item['level'] == 'done')} / {len(delivery_checks)}", "已交付 / 今日计划", bool(delivery_checks) and all(item["level"] != "risk" for item in delivery_checks))}
        {metric_card("本月 OKR/月待办", f"{month_okr.get('count', 0)} 项", "来自 VPS OKR employee-okr-list", month_okr["ok"] and month_okr.get("count", 0) > 0)}
      </div>
    </section>
    {render_delivery_agent(delivery_checks, daily["ok"] and bool(daily["reports"]))}
    <section>
      <h2>今日群日报记录（经销商-日报推送）</h2>
      <table><tr><th>提交时间</th><th>状态</th><th>内容摘要</th></tr>{report_rows}</table>
    </section>
    <section>
      <h2>今日预计待办（来自昨日「经销商-日报推送」群日报）</h2>
      <table><tr><th>事项</th><th>状态</th><th>截止</th><th>进度</th></tr>{today_rows}</table>
    </section>
    <section>
      <h2>昨天完成与进度（来自「经销商-日报推送」群日报）</h2>
      <table><tr><th>事项</th><th>状态</th><th>截止</th><th>进度</th></tr>{done_rows}</table>
    </section>
    <section>
      <h2>本月 OKR / 月待办</h2>
      <table><tr><th>目标</th><th>得分</th><th>KR 数</th></tr>{okr_table}</table>
    </section>
    """
    return page("PDCA 日结（VPS）", body, date_text, message)


def fetch_home_vps_summary():
    results = {}

    def load_im():
        results["im"] = fetch_vps_im_unread(with_latest=False)

    def load_todos():
        results["todos"] = fetch_vps_today_todos()

    threads = [threading.Thread(target=load_im), threading.Thread(target=load_todos)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=0.8)
    return (
        results.get("im") or {"ok": False, "channels": [], "channel_count": 0, "unread_count": 0, "error": "IM 请求超时"},
        results.get("todos") or {"ok": False, "rows": [], "count": 0, "error": "待办请求超时"},
    )


def home_module_card(title, value, detail, href, progress=50):
    return f"""
    <a class="home-module" href="{esc(href)}">
      <b>{esc(title)}</b>
      <span>{esc(detail)}</span>
      <strong>{esc(value)}</strong>
      <div class="home-progress"><i style="width:{max(0, min(100, int(progress)))}%"></i></div>
    </a>
    """


def home_todo_cards(rows, date_text):
    if not rows:
        return """
        <div class="home-todo">
          <span class="home-check"></span>
          <div><b>暂无今日待办</b><small>VPS 没有返回待处理事项</small></div>
          <span class="home-chip ok">正常</span>
        </div>
        """
    cards = []
    for row in rows[:5]:
        priority = first_text(row, "priority", "priority_name") or "普通"
        title = first_text(row, "title", "name") or "未命名事项"
        status = first_text(row, "status_name", "status.name", "stage_name") or "待处理"
        deadline = first_text(row, "deadline", "due_date", "date_deadline") or date_text
        chip_class = "warn" if any(word in priority for word in ("高", "紧急", "High", "high")) else ""
        cards.append(f"""
        <div class="home-todo">
          <span class="home-check"></span>
          <div><b>{esc(title)}</b><small>{esc(status)} · 截止 {esc(deadline)}</small></div>
          <span class="home-chip {chip_class}">{esc(priority)}</span>
        </div>
        """)
    return "".join(cards)


def render_home(date_text, message="", hermes_result=None):
    out = output_dir(date_text)
    report = out / "data_summary_report.md"
    dashboard = out / "dashboard.html"
    workbook = out / f"{date_text}_data_summary.xlsx"
    pdca = out / "pdca_daily_check.md"
    latest_workbook = latest_output_file(date_text, "workbook")
    latest_report = latest_output_file(date_text, "report")
    latest_pdca = latest_output_file(date_text, "pdca")
    im_unread, today_todos = fetch_home_vps_summary()
    unread_im_count = im_unread["unread_count"]
    unread_channel_count = im_unread["channel_count"]
    today_todo_count = today_todos["count"]
    if today_todos["ok"]:
        todo_rows = todo_table_rows(today_todos["rows"][:8]) or '<tr><td colspan="4">VPS 暂无今日待办</td></tr>'
        todo_cards = home_todo_cards(today_todos["rows"], date_text)
    else:
        todo_rows = f'<tr><td colspan="4">VPS 待办拉取失败：{esc(today_todos["error"])}</td></tr>'
        todo_cards = f"""
        <div class="home-todo">
          <span class="home-check"></span>
          <div><b>VPS 待办拉取失败</b><small>{esc(today_todos["error"][:80])}</small></div>
          <span class="home-chip warn">异常</span>
        </div>
        """
    dashboard_state = "已生成" if dashboard.exists() else "待生成"
    output_count = sum(1 for item in (latest_workbook, latest_report, latest_pdca) if item)
    issue_count = (0 if im_unread["ok"] else 1) + (0 if today_todos["ok"] else 1) + (0 if dashboard.exists() else 1)
    health_text = "正常" if issue_count == 0 else f"{issue_count} 项待处理"
    body = f"""
    <div class="workbench-home">
      <div class="period-tabs" aria-label="周期切换">
        <a class="period-tab active" href="{esc(route_url('/', date_text))}">日</a>
        <a class="period-tab" href="{esc(route_url('/', date_text))}">周</a>
        <a class="period-tab" href="{esc(route_url('/', date_text))}">月</a>
        <a class="period-tab" href="{esc(route_url('/', date_text))}">季度</a>
        <a class="period-tab" href="{esc(route_url('/', date_text))}">年度</a>
      </div>

      <div class="home-top">
        <div class="home-metric">
          <div class="home-metric-row"><span class="home-metric-kicker">负责人</span><span class="home-chip">工作台</span></div>
          <div><div class="home-metric-value">{today_todo_count}</div><p>今日待办事项</p></div>
        </div>
        <div class="home-metric">
          <div class="home-metric-row"><span class="home-metric-kicker">业务入口</span><span class="home-chip ok">4 个模块</span></div>
          <div><div class="home-metric-value">{output_count}/3</div><p>今日输出物完成度</p></div>
        </div>
        <div class="home-metric">
          <div class="home-metric-row"><span class="home-metric-kicker">事务状态</span><span class="home-chip {'ok' if issue_count == 0 else 'warn'}">{esc(health_text)}</span></div>
          <div><div class="home-metric-value">{unread_im_count}</div><p>IM 未读消息 · {unread_channel_count} 个会话</p></div>
        </div>
      </div>

      <div class="home-section-banner">
        <h2><strong>01</strong>行动闭环</h2>
        <p>把 AI 提醒、OKR 拆解和日常管理动作沉淀为个人任务中心，员工可自行标记状态、维护备注和完成进度。</p>
      </div>

      <div class="home-board">
        <div class="home-stack">
          <section class="home-panel">
            <div class="home-panel-head">
              <h2>今日待办</h2>
              <a class="button light" href="{esc(route_url('/todos', date_text))}">More</a>
            </div>
            <div class="home-panel-body home-todo-list">{todo_cards}</div>
          </section>

          <section class="home-panel">
            <div class="home-panel-head"><h2>待分析消息</h2><span class="home-chip {'ok' if unread_im_count == 0 else 'warn'}">{unread_im_count} 条</span></div>
            <div class="home-panel-body">
              <p>{esc("IM 暂无未读会话" if unread_im_count == 0 else f"来自 {unread_channel_count} 个会话，需要判断是否转任务或转 Hermes。")}</p>
              <div class="home-quick-actions">{button("打开 IM 未读", route_url("/im-unread", date_text), "light")}</div>
            </div>
          </section>
        </div>

        <section class="home-panel">
          <div class="home-panel-head">
            <h2>业务进度</h2>
            <span class="home-chip">{esc(date_text)}</span>
          </div>
          <div class="home-panel-body">
            <div class="home-module-grid">
              {home_module_card("数据看板", dashboard_state, "日报、业务指标与风险摘要", route_url("/dashboard", date_text), 80 if dashboard.exists() else 30)}
              {home_module_card("客户管理", "CRM", "经销商客户台账、拜访与回款", "/customer-mgmt", 72)}
              {home_module_card("客流分析", "Sell Out", "海外客流与线上经营（代理商终销、OKR、渠道线索）", "/walkin-cockpit/", 72)}
            </div>
            <div class="home-status-grid">
              <div class="home-status-cell"><span>数据报告</span><strong>{'1' if latest_report else '0'}</strong></div>
              <div class="home-status-cell"><span>Excel 表格</span><strong>{'1' if latest_workbook else '0'}</strong></div>
              <div class="home-status-cell"><span>PDCA 日结</span><strong>{'1' if latest_pdca else '0'}</strong></div>
            </div>
          </div>
        </section>

        <div class="home-stack right">
          <section class="home-panel">
            <div class="home-panel-head"><h2>异常情况</h2><span class="home-chip {'ok' if issue_count == 0 else 'warn'}">{issue_count}</span></div>
            <div class="home-panel-body">
              <div class="home-alert">
                <div class="home-alert-icon">!</div>
                <div><b>{esc("首页服务正常" if issue_count == 0 else "存在待处理事项")}</b><p>{esc("VPS、看板与输出入口均可继续使用。" if issue_count == 0 else "优先检查 VPS 拉取状态和今日看板是否生成。")}</p></div>
              </div>
              <div class="home-alert">
                <div class="home-alert-icon">i</div>
                <div><b>当前端口 8767</b><p>首页与客流分析台（含线上经营）由 pdca_workbench.py 托管。</p></div>
              </div>
            </div>
          </section>

          <section class="home-panel">
            <div class="home-panel-head"><h2>服务健康</h2><span class="home-chip ok">在线</span></div>
            <div class="home-panel-body">
              <div class="home-alert"><div class="home-alert-icon">D</div><div><b>数据看板</b><p>{esc("今日 dashboard.html 已生成" if dashboard.exists() else "今日 dashboard.html 尚未生成")}</p></div></div>
              <div class="home-alert"><div class="home-alert-icon">V</div><div><b>VPS 摘要</b><p>{esc("待办和 IM 摘要已返回" if im_unread["ok"] and today_todos["ok"] else "部分 VPS 摘要拉取失败")}</p></div></div>
            </div>
          </section>
        </div>
      </div>

      <div class="home-section-banner">
        <h2><strong>02</strong>行政事务</h2>
        <p>把合同、审批、资料、报销和跨部门协同集中处理，确保行政节点不拖慢销售动作和 OKR 执行。</p>
      </div>

      <div class="home-important">
        <section class="home-panel">
          <div class="home-panel-head"><h2>重要事项</h2><span class="home-chip">业务</span></div>
          <div class="home-panel-body">
            <ul class="home-note-list">
              <li>先确认今日看板与 Excel 是否生成，缺失时运行 PDCA 日跑。</li>
              <li>今日待办需要和 IM 消息闭环，避免只看数据不落行动。</li>
              <li>点击 Sell Out 或「客流分析」进入海外客流与线上经营合一的分析台。</li>
            </ul>
            <div class="home-quick-actions">
              {button("运行今日 PDCA", route_url("/run", date_text))}
              {button("打开今日输出", route_url("/open", date_text, target="report"), "light")}
            </div>
          </div>
        </section>

        <section class="home-panel">
          <div class="home-panel-head"><h2>处理建议</h2><span class="home-chip">事务</span></div>
          <div class="home-panel-body">
            <ul class="home-note-list">
              <li>有未读 IM 时，先判断是否需要派给 Hermes 生成报告或动作清单。</li>
              <li>代理商名单和客流指标只从 JSON 数据包读取，更新 Excel 后需重跑构建脚本。</li>
              <li>改完首页样式后重启服务，并在浏览器 Ctrl+F5 强制刷新。</li>
            </ul>
          </div>
        </section>
      </div>

      <section class="home-panel">
        <div class="home-panel-head"><h2>任务中心</h2><a class="button light" href="{esc(route_url('/pdca-vps', date_text))}">PDCA 日结</a></div>
        <div class="home-panel-body home-mini-grid">
          <div class="home-mini"><span>总任务数</span><strong>{today_todo_count}</strong><p>来自 VPS 今日待办</p></div>
          <div class="home-mini"><span>已完成</span><strong>{max(0, output_count)}</strong><p>今日已生成输出物</p></div>
          <div class="home-mini"><span>未完成</span><strong>{max(0, today_todo_count - output_count)}</strong><p>待继续跟进事项</p></div>
        </div>
      </section>

      <section class="home-panel">
        <div class="home-panel-head"><h2>会议中心</h2><span class="home-chip">复盘</span></div>
        <div class="home-panel-body home-mini-grid">
          <div class="home-mini"><span>待确认</span><strong>{unread_channel_count}</strong><p>可从 IM 会话转入</p></div>
          <div class="home-mini"><span>业务复盘</span><strong>1</strong><p>客流分析台</p></div>
          <div class="home-mini"><span>输出闭环</span><strong>{output_count}</strong><p>报告、Excel、PDCA</p></div>
        </div>
      </section>

      <section class="home-panel">
        <div class="home-panel-head"><h2>今日待办明细（VPS）</h2><a class="button light" href="{esc(route_url('/todos', date_text))}">查看全部</a></div>
        <div class="home-panel-body"><table><tr><th>优先级</th><th>事项</th><th>状态</th><th>截止</th></tr>{todo_rows}</table></div>
      </section>

      {render_hermes_panel(date_text)}
      {render_agent_cards(date_text)}
      {render_output_panel(date_text, out, dashboard, workbook, report, pdca)}
      {render_hermes_result_modal(date_text, hermes_result)}
    </div>
    """
    return page("数据岗位 PDCA 工作台", body, date_text, message)
