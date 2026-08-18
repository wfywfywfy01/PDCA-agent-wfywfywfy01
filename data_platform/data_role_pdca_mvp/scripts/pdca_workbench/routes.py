# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：Hermes/Agent/输出面板/VPS 页渲染
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。


def route_url(route_path, date_text, **params):
    payload = {"date": date_text}
    payload.update(params)
    return f"{route_path}?{urlencode(payload)}"


def render_hermes_panel(date_text, result=""):
    result_html = ""
    if result:
        if isinstance(result, dict):
            state = "ok" if result.get("ok") else "warn"
            path = result.get("path")
            actions = ""
            preview = ""
            if path:
                primary_href = route_url("/view-path", date_text, path=path) if is_previewable(path) else route_url("/open-path", date_text, path=path)
                extra_links = "".join(
                    button(link.get("label", "打开官网"), link.get("url", ""), "secondary")
                    for link in result.get("links", [])
                )
                actions = (
                    f'<div class="actions">'
                    f'{button("查看结果", primary_href)}'
                    f'{button("用本机软件打开", route_url("/open-path", date_text, path=path), "light")}'
                    f'{button("打开所在目录", route_url("/open-path", date_text, path=str(Path(path).parent)), "light")}'
                    f'{extra_links}'
                    f'</div>'
                )
                preview = (
                    f'<div class="result-preview">{esc(result.get("content", ""))}</div>'
                    f'<div class="result-file">已生成：{esc(result.get("filename") or Path(path).name)}</div>'
                )
            else:
                preview = f'<div class="result-preview">{esc(result.get("content", ""))}</div>'
            result_html = f"""
            <div class="result-banner {state}">
              <h3>{"执行完成" if result.get("ok") else "执行失败"}</h3>
              <p>{esc("报告已生成，可直接在下方查看或点按钮打开。" if path and result.get("ok") else "请查看下方反馈。")}</p>
              {actions}
              {preview}
            </div>
            """
        else:
            result_html = f'<div class="hermes-result">{esc(result)}</div>'
    return f"""
    <section style="margin-top:16px">
      <h2>向 Hermes 派任务</h2>
      <p>这是日常唯一任务入口。数据类任务交给 Hermes 数据 Agent；物流单号会进入物流核查流程，避免生成空报告。</p>
      <form method="post" action="{esc(route_url('/hermes-chat', date_text))}" id="hermesTaskForm">
        <textarea name="query" placeholder="例如：从 VPS 拉 5 月经销商业绩，按团队汇总并生成 Excel 表格；或：查这些物流单号并判断是否异常"></textarea>
        <div class="actions">
          <button type="submit" id="hermesSubmitBtn">交给 Hermes 拆解执行</button>
          <span class="thinking-inline" id="hermesThinking"><span class="spinner"></span>thinking...</span>
        </div>
      </form>
      <script>
      (function() {{
        const form = document.getElementById('hermesTaskForm');
        const btn = document.getElementById('hermesSubmitBtn');
        const thinking = document.getElementById('hermesThinking');
        if (!form || !btn || !thinking) return;
        form.addEventListener('submit', function() {{
          btn.disabled = true;
          btn.textContent = '执行中...';
          thinking.classList.add('on');
        }});
      }})();
      </script>
      {result_html}
    </section>
    """


def render_tracking_cards(result):
    rows = result.get("tracking_results") if isinstance(result, dict) else None
    if not rows:
        return ""
    cards = []
    for row in rows:
        status = row.get("status", "")
        ok = "delivered" in status.lower() or "签收" in status
        color = "#178a4b" if ok else "#b26b00"
        bg = "#eefaf3" if ok else "#fff7e6"
        cards.append(f"""
        <div style="border:1px solid #d8e4d8;background:{bg};border-radius:14px;padding:16px;margin:12px 0">
          <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px">
            <div>
              <div style="font-size:12px;color:#7b8496">Tracking Code</div>
              <div style="font-size:20px;font-weight:800;color:#111827">{esc(row.get("tracking_number", ""))}</div>
            </div>
            <div style="border-radius:999px;background:{color};color:white;padding:6px 12px;font-weight:700;font-size:13px">
              {esc(status)}
            </div>
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-top:14px">
            <div><b>承运商</b><br>{esc(row.get("carrier", ""))}</div>
            <div><b>更新时间</b><br>{esc(row.get("last_update", "") or "未识别")}</div>
            <div><b>始发地</b><br>{esc(row.get("origin", "") or "未识别")}</div>
            <div><b>目的地</b><br>{esc(row.get("destination", "") or "未识别")}</div>
          </div>
          <div style="margin-top:14px;height:8px;background:#d8d8d8;border-radius:999px;overflow:hidden">
            <div style="height:100%;width:{'100' if ok else '65'}%;background:{color};border-radius:999px"></div>
          </div>
        </div>
        """)
    return "".join(cards)


def render_hermes_result_modal(date_text, result):
    if not result:
        return ""
    if not isinstance(result, dict):
        content = esc(result)
        return f"""
        <div class="result-modal" role="dialog" aria-modal="true">
          <div class="result-dialog">
            <div class="result-dialog-head">
              <div><h2>执行结果</h2><p>Hermes 已返回反馈。</p></div>
              <a class="result-close" href="{esc(route_url('/', date_text))}">×</a>
            </div>
            <div class="result-preview">{content}</div>
          </div>
        </div>
        """
    state = "ok" if result.get("ok") else "warn"
    path = result.get("path")
    actions = ""
    if path:
        primary_href = route_url("/view-path", date_text, path=path) if is_previewable(path) else route_url("/open-path", date_text, path=path)
        extra_links = "".join(
            button(link.get("label", "打开官网"), link.get("url", ""), "secondary")
            for link in result.get("links", [])
        )
        actions = (
            f'<div class="actions">'
            f'{button("查看结果", primary_href)}'
            f'{button("用本机软件打开", route_url("/open-path", date_text, path=path), "light")}'
            f'{button("打开所在目录", route_url("/open-path", date_text, path=str(Path(path).parent)), "light")}'
            f'{extra_links}'
            f'</div>'
        )
    title = "执行完成" if result.get("ok") else "执行失败"
    desc = "报告已生成，可直接查看或打开。" if path and result.get("ok") else "请查看下方反馈。"
    filename = result.get("filename") or (Path(path).name if path else "")
    file_html = f'<div class="result-file">已生成：{esc(filename)}</div>' if filename else ""
    tracking_html = render_tracking_cards(result)
    return f"""
    <div class="result-modal" role="dialog" aria-modal="true">
      <div class="result-dialog {state}">
        <div class="result-dialog-head">
          <div>
            <h2>{esc(title)}</h2>
            <p>{esc(desc)}</p>
          </div>
          <a class="result-close" href="{esc(route_url('/', date_text))}">×</a>
        </div>
        {actions}
        {tracking_html}
        <div class="result-preview">{esc(result.get("content", ""))}</div>
        {file_html}
      </div>
    </div>
    """


def render_agent_cards(date_text):
    cards = []
    avatars = ["🤖", "📦", "🔎"]
    for index, agent in enumerate(AGENT_CARDS):
        agent_key = agent["key"]
        ensure_agent_soul(agent)
        skill_count = len(list_agent_skills(agent))
        cards.append(f"""
        <div class="card agent-card">
          <div class="agent-avatar">{esc(avatars[index % len(avatars)])}</div>
          <h3>{esc(agent["title"])}</h3>
          <div class="agent-meta">{esc(agent["key"])}</div>
          <p>{esc(agent["desc"])}</p>
          <div class="actions">
            {button("+ 编辑 Agent", route_url("/agent-edit", date_text, agent=agent_key), "agent-button")}
          </div>
          <div class="agent-meta">Core files 5 · Skills {skill_count}</div>
        </div>
        """)
    return f"""
    <section class="agent-section" style="margin-top:16px">
      <h2>子 Agent 能力与维护</h2>
      <p>这些是真实存在的本地 Hermes profile 或项目 agent 定义。日常不要直接点子 Agent 派活，而是在上方告诉 Hermes，由 Hermes 选择谁来做。</p>
      <div class="agent-grid">{''.join(cards)}</div>
    </section>
    """


def render_agent_soul(date_text, agent_key, message=""):
    agent = agent_by_key(agent_key)
    if not agent:
        return page("未知 Agent", "<section><h2>未知 Agent</h2></section>", date_text, message)
    path = ensure_agent_soul(agent)
    content = read_text(path)
    title = agent["title"]
    body = f"""
    <section>
      <div class="page-toolbar">
        <div>
          <h2>编辑 SOUL.md：{esc(title)}</h2>
          <p>{esc(path)}</p>
        </div>
        {button("← 返回首页", route_url("/", date_text), "light")}
      </div>
      <form method="post" action="{esc(route_url('/agent-soul', date_text, agent=agent_key))}">
        <textarea name="content" style="min-height:420px">{esc(content)}</textarea>
        <div class="actions">
          <button type="submit">保存 SOUL.md</button>
          {button("返回首页", route_url("/", date_text), "light")}
        </div>
      </form>
    </section>
    """
    return page("编辑 SOUL.md", body, date_text, message)


def render_agent_edit(date_text, agent_key, active_file="SOUL.md", message=""):
    agent = agent_by_key(agent_key)
    if not agent:
        return page("未知 Agent", "<section><h2>未知 Agent</h2></section>", date_text, message)
    if active_file not in AGENT_CORE_FILES:
        active_file = "SOUL.md"
    path = ensure_agent_core_file(agent, active_file)
    content = read_text(path)
    nav = "".join(
        f'<a class="{"active" if name == active_file else ""}" href="{esc(route_url("/agent-edit", date_text, agent=agent_key, file=name))}">{esc(name)}</a>'
        for name in AGENT_CORE_FILES
    )
    skills = list_agent_skills(agent)
    skill_html = "".join(f'<span class="skill-chip">{esc(name)}</span>' for name in skills) or "暂无已安装 Skill"
    body = f"""
    <section>
      <div class="page-toolbar">
        <div>
          <h2>{esc(agent["title"])}</h2>
          <p>这里维护该 Agent 的核心文件和 Skill。保存后下一次 Hermes 调用会读取最新内容，不需要重启。</p>
        </div>
        {button("← 返回首页", route_url("/", date_text), "light")}
      </div>
      <div class="editor-layout">
        <div class="file-nav">
          <h3>Core Files</h3>
          {nav}
        </div>
        <div>
          <form method="post" action="{esc(route_url('/agent-core-file', date_text, agent=agent_key, file=active_file))}">
            <h3>{esc(active_file)}</h3>
            <textarea name="content" style="min-height:430px">{esc(content)}</textarea>
            <div class="actions">
              <button type="submit">保存</button>
              {button("返回首页", route_url("/", date_text), "light")}
            </div>
          </form>
        </div>
      </div>
    </section>
    <section style="margin-top:16px">
      <h2>Skill 热插拔</h2>
      <p>拖入或选择一个 `SKILL.md`，会立即安装到该 Agent 的 skills 目录。下一次 Hermes 执行任务时即可使用。</p>
      <form class="drop-zone" method="post" action="{esc(route_url('/agent-skill', date_text, agent=agent_key))}" enctype="multipart/form-data">
        <input type="file" name="skill" accept=".md,.txt" required style="width:100%">
        <div class="actions"><button type="submit">安装 Skill</button></div>
      </form>
      <p>{skill_html}</p>
    </section>
    """
    return page("编辑 Agent", body, date_text, message)


def output_result_card(title, icon, desc, exists, href, meta=""):
    if exists:
        action = button("打开", href)
        state = ""
    else:
        action = '<span class="button light">运行后生成</span>'
        state = " missing"
    return f"""
    <div class="output-card{state}">
      <span class="output-icon">{esc(icon)}</span>
      <h3>{esc(title)}</h3>
      <p>{esc(desc)}</p>
      {f'<p class="output-meta">{esc(meta)}</p>' if meta else ''}
      <div class="actions">{action}</div>
    </div>
    """


def render_output_panel(date_text, out, dashboard, workbook, report, pdca):
    latest_workbook = latest_output_file(date_text, "workbook")
    latest_report = latest_output_file(date_text, "report")
    latest_pdca = latest_output_file(date_text, "pdca")
    cards = "".join([
        output_result_card("Excel 表格", "📄", "每次打开最新生成的数据汇总 Excel，可直接发给业务使用。", bool(latest_workbook), route_url("/open", date_text, target="workbook"), f"最新：{file_time_label(latest_workbook)}"),
        output_result_card("数据报告", "🧾", "每次查看最新的数据来源、口径、团队汇总和风险说明。", bool(latest_report), route_url("/open", date_text, target="report"), f"最新：{file_time_label(latest_report)}"),
        output_result_card("PDCA 日结", "✅", "从「经销商-日报推送」群日报和 VPS 待办生成今日完成、进度、上级交办和明日计划。", True, route_url("/pdca-vps", date_text)),
    ])
    return f"""
    <section>
      <h2>今日输出</h2>
      <p>这些是 Hermes/PDCA 已经产出的结果，直接点开使用。路径只作为技术详情保留。</p>
      <div class="output-grid">{cards}</div>
      <details class="output-paths">
        <summary>查看文件路径</summary>
        <p>输出目录：<code>{esc(out)}</code></p>
        <p>最新 Excel：<code>{esc(latest_workbook or "运行后生成")}</code></p>
        <p>最新数据报告：<code>{esc(latest_report or "运行后生成")}</code></p>
        <p>旧版本地 PDCA 日结：<code>{esc(latest_pdca or "运行后生成")}</code></p>
      </details>
    </section>
    """
