# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：HTML 渲染（问卷、待办、IM、物流、文件浏览）
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。


def render_questionnaire(date_text, message=""):
    values = parse_questionnaire(date_text)
    fields = []
    for index, title in enumerate(QUESTION_TITLES):
        content = values.get(title, "")
        if content == "-":
            content = ""
        fields.append(f"<label><h3>{esc(title)}</h3><textarea name='q{index}'>{esc(content)}</textarea></label>")
    body = f"""
    <section>
      <div class="page-toolbar">
        <div><h2>填写每日问卷</h2></div>
        {button("← 返回首页", route_url("/", date_text), "light")}
      </div>
      <form method="post" action="{esc(route_url('/questionnaire', date_text))}">
        {''.join(fields)}
        <div class="actions"><button type="submit">保存问卷</button>{button("返回首页", route_url("/", date_text), "light")}</div>
      </form>
    </section>
    """
    return page("填写每日问卷", body, date_text, message)


def render_todos(date_text, message=""):
    today_todos = fetch_vps_today_todos()
    if today_todos["ok"]:
        table = todo_table_rows(today_todos["rows"]) or '<tr><td colspan="4">VPS 暂无今日待办</td></tr>'
    else:
        table = f'<tr><td colspan="4">VPS 待办拉取失败：{esc(today_todos["error"])}</td></tr>'
    body = f"""
    <section>
      <div class="page-toolbar">
        <div>
          <h2>今日待办（VPS）</h2>
          <p>来源：vertu odoo project todo list --for-me --due-within-days 0</p>
        </div>
        {button("← 返回首页", route_url("/", date_text), "light")}
      </div>
      <table><tr><th>优先级</th><th>事项</th><th>状态</th><th>截止</th></tr>{table}</table>
      <div class="actions">{button("返回首页", route_url("/", date_text), "light")}</div>
    </section>
    """
    return page("今日待办", body, date_text, message)


def render_im_unread(date_text, message=""):
    im_unread = fetch_vps_im_unread()
    if im_unread["ok"]:
        table = im_table_rows(im_unread["channels"], date_text) or '<tr><td colspan="4">VPS 暂无未读 IM</td></tr>'
        summary = f"合计 {im_unread['unread_count']} 条未读，分布在 {im_unread['channel_count']} 个会话。"
    else:
        table = f'<tr><td colspan="4">VPS IM 拉取失败：{esc(im_unread["error"])}</td></tr>'
        summary = "VPS IM 拉取失败。"
    body = f"""
    <section>
      <div class="page-toolbar">
        <div>
          <h2>IM 未读消息（VPS）</h2>
          <p>{esc(summary)}</p>
        </div>
        {button("← 返回首页", route_url("/", date_text), "light")}
      </div>
      <table><tr><th>会话</th><th>未读数</th><th>最新消息</th><th>最后活跃</th></tr>{table}</table>
      <div class="actions">{button("返回首页", route_url("/", date_text), "light")}</div>
    </section>
    """
    return page("IM 未读消息", body, date_text, message)


def render_logistics(date_text, message=""):
    rows = read_csv_rows(logistics_path(date_text))
    table = "".join(
        f"<tr><td>{esc(row.get('tracking_number'))}</td><td>{esc(row.get('carrier'))}</td><td>{esc(row.get('customer'))}</td><td>{esc(row.get('salesperson'))}</td><td>{esc(row.get('current_status'))}</td></tr>"
        for row in rows
    ) or '<tr><td colspan="5">暂无物流单号</td></tr>'
    body = f"""
    <section>
      <div class="page-toolbar">
        <div><h2>录入物流单号</h2></div>
        {button("← 返回首页", route_url("/", date_text), "light")}
      </div>
      <form method="post" action="{esc(route_url('/logistics', date_text))}">
        <div class="two">
          <label>物流单号<input name="tracking_number" required style="width:100%"></label>
          <label>承运商<select name="carrier" style="width:100%"><option>UPS</option><option>FedEx</option><option>DHL</option><option>SF</option></select></label>
          <label>客户<input name="customer" style="width:100%"></label>
          <label>销售<input name="salesperson" style="width:100%"></label>
          <label>发货日期<input type="date" name="ship_date" value="{esc(date_text)}" style="width:100%"></label>
          <label>当前状态<input name="current_status" placeholder="不知道可留空" style="width:100%"></label>
          <label>预期状态<input name="expected_status" style="width:100%"></label>
          <label>备注<input name="note" style="width:100%"></label>
        </div>
        <div class="actions"><button type="submit">保存物流单号</button>{button("返回首页", route_url("/", date_text), "light")}</div>
      </form>
    </section>
    <section style="margin-top:16px">
      <h2>当前物流</h2>
      <table><tr><th>单号</th><th>承运商</th><th>客户</th><th>销售</th><th>当前状态</th></tr>{table}</table>
    </section>
    """
    return page("录入物流单号", body, date_text, message)


def open_target(date_text, target):
    path = latest_output_file(date_text, target)
    if path and path.exists():
        return f"文件已生成：{path}"
        pass
    return "文件还不存在，请先运行今日 PDCA。"


def open_path(path_text):
    path = Path(path_text)
    try:
        resolved = path.resolve()
        if not resolved.exists():
            return "文件还不存在。"
        return f"文件路径：{resolved}"
        pass
    except OSError as exc:
        return f"打开失败：{exc}"


def render_view_path(date_text, path_text, back_url=""):
    path = Path(path_text)
    back_href = back_url or route_url("/", date_text)
    back_label = "← 返回"
    if not path.exists():
        return page("查看结果", f"""
        <section>
          <div class="page-toolbar">
            <div><h2>结果文件不存在</h2><p>可能是文件路径已变化，请重新执行 Hermes 任务。</p></div>
            {button(back_label, back_href, "light")}
          </div>
        </section>
        """, date_text)
    if path.suffix.lower() in {".html", ".htm"}:
        return read_text(path)
    content = read_text(path)
    return page("查看结果", f"""
    <section>
      <div class="page-toolbar">
        <div>
          <h2>Hermes 执行结果</h2>
          <p>{esc(path.name)}</p>
        </div>
        <div class="actions">
          {button("用本机软件打开", route_url("/open-path", date_text, path=str(path)))}
          {button(back_label, back_href, "light")}
        </div>
      </div>
      <div class="result-preview">{esc(content)}</div>
    </section>
    """, date_text)


def open_im_channel(channel_id):
    if not channel_id:
        return "缺少 IM 会话 ID。"
    url = im_channel_url(channel_id)
    return f"IM 会话链接：{url}"
    pass
