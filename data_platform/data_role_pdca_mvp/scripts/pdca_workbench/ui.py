# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：UI 组件与卡片
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。


def status_card(label, ok, detail):
    state = "ok" if ok else "warn"
    text = "正常" if ok else "待处理"
    return f"""
    <div class="card {state}">
      <div class="label">{esc(label)}</div>
      <div class="state">{text}</div>
      <p>{esc(detail)}</p>
    </div>
    """


def metric_card(label, value, detail, ok=True, href=None):
    state = "ok" if ok else "warn"
    content = f"""
      <div class="label">{esc(label)}</div>
      <div class="state">{esc(value)}</div>
      <p>{esc(detail)}</p>
    """
    if href:
        return f"""
    <a class="card {state} entry-card" href="{esc(href)}">
{content}
    </a>
    """
    return f"""
    <div class="card {state}">
{content}
    </div>
    """


def is_port_listening(port: int) -> bool:
    """检查本机指定端口是否已在监听。"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def ensure_customer_server() -> str:
    """确保客户管理服务在 8787 端口运行。返回错误信息或空字符串。"""
    global _customer_proc
    if is_port_listening(CUSTOMER_MGMT_PORT):
        return ""
    server_script = CUSTOMER_MGMT_ROOT / "server.py"
    if not server_script.exists():
        return f"客户管理服务脚本不存在：{server_script}"
    try:
        python = sys.executable
        _customer_proc = subprocess.Popen(
            [python, str(server_script)],
            cwd=str(CUSTOMER_MGMT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        # 等待最多 3 秒让端口就绪
        import time
        for _ in range(12):
            time.sleep(0.25)
            if is_port_listening(CUSTOMER_MGMT_PORT):
                return ""
            if _customer_proc.poll() is not None:
                return f"客户管理服务启动后退出，退出码：{_customer_proc.returncode}"
        return "客户管理服务启动超时，请手动运行 server.py"
    except Exception as exc:
        return f"客户管理服务启动失败：{exc}"


def render_customer_mgmt_frame(date_text):
    """把客户管理 8787 以 iframe 方式嵌入工作台，顶部保留返回导航。"""
    back_href = route_url("/", date_text)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>客户管理 · 经销商PDCA工作台</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{display:flex;flex-direction:column;height:100vh;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}}
.frame-bar{{display:flex;align-items:center;gap:12px;padding:0 16px;height:42px;background:#1e1e2e;color:#fff;flex-shrink:0;border-bottom:1px solid #313147}}
.frame-bar a.back{{display:flex;align-items:center;gap:6px;color:#cdd6f4;text-decoration:none;font-size:13px;padding:4px 10px;border-radius:6px;border:1px solid #45475a;transition:background .15s}}
.frame-bar a.back:hover{{background:#313147;color:#fff}}
.frame-bar .sep{{width:1px;height:20px;background:#45475a}}
.frame-bar .title{{font-size:13px;font-weight:600;color:#cdd6f4}}
.frame-bar .sub{{font-size:11px;color:#6c7086;margin-left:4px}}
.frame-bar .ext{{margin-left:auto;font-size:12px;color:#6c7086}}
.frame-bar a.ext-link{{color:#89b4fa;text-decoration:none;font-size:12px}}
.frame-bar a.ext-link:hover{{text-decoration:underline}}
iframe{{flex:1;border:none;width:100%}}
</style>
</head>
<body>
<div class="frame-bar">
  <a class="back" href="{esc(back_href)}">← 返回工作台</a>
  <div class="sep"></div>
  <span class="title">客户管理</span>
  <span class="sub">经销商客户台账 · 拜访记录 · 漏斗与回款</span>
  <a class="ext-link ext" href="http://127.0.0.1:{CUSTOMER_MGMT_PORT}?v=20260529-2" target="_blank">在新标签页打开 ↗</a>
</div>
<iframe src="http://127.0.0.1:{CUSTOMER_MGMT_PORT}?v=20260529-2" allowfullscreen></iframe>
</body>
</html>"""


def customer_mgmt_card():
    running = is_port_listening(CUSTOMER_MGMT_PORT)
    state_text = "进入客户管理" if running else "点击启动并进入"
    detail = "经销商客户台账、拜访记录、漏斗与回款管理" if running else "服务未启动，点击后自动启动"
    return f"""
    <a class="card ok entry-card" href="/customer-mgmt">
      <div class="entry-top">
        <div>
          <div class="label">客户管理</div>
          <div class="state">{esc(state_text)}</div>
        </div>
        <span class="entry-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="28" height="28" fill="none">
            <circle cx="9" cy="7" r="3" stroke="currentColor" stroke-width="2"/>
            <path d="M3 19c0-3.314 2.686-6 6-6s6 2.686 6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
            <path d="M16 11l2 2 4-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </span>
      </div>
      <p>{esc(detail)}</p>
    </a>
    """


def dashboard_card(date_text, exists):
    state_text = "打开看板" if exists else "先运行生成"
    detail = "点击进入今日数据看板" if exists else "运行今日 PDCA 后生成看板"
    return f"""
    <a class="card ok entry-card" href="{esc(route_url('/dashboard', date_text))}">
      <div class="entry-top">
        <div>
          <div class="label">数据看板</div>
          <div class="state">{esc(state_text)}</div>
        </div>
        <span class="entry-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="28" height="28" fill="none">
            <rect x="3" y="4" width="18" height="16" rx="3" stroke="currentColor" stroke-width="2"/>
            <path d="M7 15v-3M12 15V8M17 15v-5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          </svg>
        </span>
      </div>
      <p>{esc(detail)}</p>
    </a>
    """


def walkin_cockpit_card():
    """经销商海外客流分析台入口（modules/walkin_cockpit）。"""
    return """
    <a class="card ok entry-card entry-card-wide" href="/walkin-cockpit/">
      <div class="entry-top">
        <div>
          <div class="label">海外客流</div>
          <div class="state">打开分析台</div>
        </div>
        <span class="entry-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="28" height="28" fill="none">
            <path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1v-9.5Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
          </svg>
        </span>
      </div>
      <p>海外经销客流：代理商终销、大区与团队表现（墨绿主题）</p>
    </a>
    """


def online_cockpit_card():
    """经销商线上经营入口（已并入客流分析）。"""
    return """
    <a class="card ok entry-card entry-card-wide" href="/walkin-cockpit/#oi-merged">
      <div class="entry-top">
        <div>
          <div class="label">线上经营</div>
          <div class="state">打开驾驶舱</div>
        </div>
        <span class="entry-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="28" height="28" fill="none">
            <rect x="3" y="5" width="18" height="14" rx="2" stroke="currentColor" stroke-width="2"/>
            <path d="M8 15h8M8 11h5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
            <circle cx="17" cy="8" r="2" fill="currentColor"/>
          </svg>
        </span>
      </div>
      <p>经销商线上经营：OKR、渠道线索、区域汇总（已并入客流分析台）</p>
    </a>
    """


def button(label, href, style=""):
    target = ' target="_blank" rel="noopener"' if str(href).startswith(("http://", "https://")) else ""
    return f'<a class="button {style}" href="{esc(href)}"{target}>{esc(label)}</a>'


def header_subtitle():
    cached = _VPS_CACHE.get("current_user")
    if cached:
        user = cached.get("payload", {})
        name = user.get("employee_name") or user.get("name") or user.get("login")
        if name:
            return f"IM 登录：{name} · 数据看板 · 今日待办 · Hermes 智能体"
    return "IM 登录识别中 · 数据看板 · 今日待办 · Hermes 智能体"
