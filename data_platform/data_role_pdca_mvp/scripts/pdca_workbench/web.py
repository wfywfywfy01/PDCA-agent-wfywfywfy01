# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：首页仪表盘 / 驾驶舱 / 走店客流的页面与静态资源
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。
try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / "pdca-workbench" / ".env")
except Exception:
    pass

RUN_SCRIPT = WORKSPACE / "scripts" / "run_data_role_pdca_daily.ps1"
QUESTION_TEMPLATE = WORKSPACE / "templates" / "daily_questionnaire.md"
HERMES_HOME = Path.home() / ".hermes" / "profiles"
DATA_REPORTS = REPO_ROOT / "data_reports"
HOST = "127.0.0.1"
PORT = int(os.environ.get("PDCA_WORKBENCH_PORT", "8765"))
VPS_CACHE_SECONDS = 300
RAW_SALES_CACHE_SECONDS = 600
_VPS_CACHE = {}

_CUSTOMER_MGMT_ROOT_ENV = os.environ.get("PDCA_CUSTOMER_MGMT_ROOT", "").strip()
CUSTOMER_MGMT_ROOT = Path(_CUSTOMER_MGMT_ROOT_ENV) if _CUSTOMER_MGMT_ROOT_ENV else Path("__pdca_customer_mgmt_not_configured__")
CUSTOMER_MGMT_PORT = 8787
WALKIN_COCKPIT_DIR = WORKSPACE / "modules" / "walkin_cockpit"
WALKIN_COCKPIT_ROOT = WALKIN_COCKPIT_DIR.resolve()
ONLINE_COCKPIT_DIR = WORKSPACE / "modules" / "online_cockpit"
ONLINE_COCKPIT_ROOT = ONLINE_COCKPIT_DIR.resolve()
HOME_DASHBOARD_DIR = WORKSPACE / "modules" / "home_dashboard"
HOME_DASHBOARD_ROOT = HOME_DASHBOARD_DIR.resolve()
HOME_DASHBOARD_INDEX = HOME_DASHBOARD_DIR / "index.html"
MEETING_CENTER_DIR = WORKSPACE / "modules" / "meeting_center"
MEETING_CENTER_ROOT = MEETING_CENTER_DIR.resolve()
MEETING_CENTER_INDEX = MEETING_CENTER_DIR / "index.html"
DEALER_REF_JSON = WALKIN_COCKPIT_DIR / "data" / "dealer_distribution_reference.json"
CUSTOMER_TIER_TARGETS = {"S": 8, "A": 20, "B": 45, "C": 30}
TIER_ESTIMATE_SELL_OUT = {"A": 1200000, "B": 650000, "S": 380000, "C": 280000}


def resolve_cockpit_asset(base_dir, root_dir, rel_path):
    """解析驾驶舱模块静态资源路径，禁止目录穿越。"""
    rel = unquote((rel_path or "").lstrip("/"))
    if not rel:
        rel = "index.html"
    parts = rel.replace("\\", "/").split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    target = (base_dir / rel).resolve()
    if not target.is_relative_to(Path(root_dir).resolve()):
        return None
    if not target.is_file():
        return None
    return target


def resolve_walkin_asset(rel_path):
    return resolve_cockpit_asset(WALKIN_COCKPIT_DIR, WALKIN_COCKPIT_ROOT, rel_path)


def resolve_online_asset(rel_path):
    return resolve_cockpit_asset(ONLINE_COCKPIT_DIR, ONLINE_COCKPIT_ROOT, rel_path)


def resolve_home_dashboard_asset(rel_path):
    return resolve_cockpit_asset(HOME_DASHBOARD_DIR, HOME_DASHBOARD_ROOT, rel_path)


def resolve_meeting_center_asset(rel_path):
    return resolve_cockpit_asset(MEETING_CENTER_DIR, MEETING_CENTER_ROOT, rel_path)


def serve_home_dashboard_index(handler):
    """经营驾驶舱首页（dashboard_template_with_api_hooks）。"""
    if not HOME_DASHBOARD_INDEX.is_file():
        handler.send_response(404)
        handler.end_headers()
        return
    handler.send_file(HOME_DASHBOARD_INDEX)


DASHBOARD_THEME_CSS = HOME_DASHBOARD_DIR / "workbench-unified.css"
DASHBOARD_THEME_MARKER = "workbench-unified.css"
COCKPIT_SHELL_CSS = HOME_DASHBOARD_DIR / "workbench-cockpit-shell.css"
COCKPIT_SHELL_MARKER = "workbench-cockpit-shell.css"

try:
    from workbench_data import build_online_channel_payload, build_walkin_api_payload
except ImportError:
    build_walkin_api_payload = None
    build_online_channel_payload = None

try:
    from vemory_bridge import (
        classify_meeting_bucket,
        fetch_vemory_meetings,
        meeting_center_counts,
        todo_assignments,
        vemory_people,
    )
except ImportError:
    classify_meeting_bucket = None
    fetch_vemory_meetings = None
    meeting_center_counts = None
    todo_assignments = None
    vemory_people = None


def skin_cockpit_html(html, date_text, page_title="经销商驾驶舱"):
    """客流/线上子页：统一浅色皮肤 + 顶栏返回工作台。"""
    date_text = date_text or today_text()
    back_href = f"/?date={date_text}"
    if COCKPIT_SHELL_MARKER not in html and COCKPIT_SHELL_CSS.is_file():
        shell_css = COCKPIT_SHELL_CSS.read_text(encoding="utf-8")
        unified = ""
        if DASHBOARD_THEME_CSS.is_file():
            unified = DASHBOARD_THEME_CSS.read_text(encoding="utf-8")
        html = html.replace(
            "</head>",
            f'<link rel="stylesheet" href="/workbench-cockpit-shell.css?v=2">\n'
            f'<style id="wb-cockpit-skin">\n{unified}\n{shell_css}\n</style>\n</head>',
            1,
        )
    if "wb-cockpit-backbar" not in html:
        bar = (
            f'<div class="wb-cockpit-backbar">'
            f'<a class="back-to-workbench" href="{back_href}" title="返回 PDCA 工作台">← 返回工作台</a>'
            f'<span class="wb-cockpit-title">{esc(page_title)}</span>'
            f"</div>"
        )
        html = re.sub(r"(<body[^>]*>)", r"\1" + bar, html, count=1)
    else:
        html = re.sub(
            r'(<a class="back-to-workbench" href=")[^"]*(")',
            rf"\1{back_href}\2",
            html,
            count=1,
        )
    return html


def skin_dashboard_html(html, date_text):
    """为数据看板注入与主页一致的样式，并修正返回工作台链接。"""
    if "wb-unified-skin" not in html and DASHBOARD_THEME_CSS.is_file():
        theme_css = DASHBOARD_THEME_CSS.read_text(encoding="utf-8")
        html = html.replace(
            "</head>",
            f'<style id="wb-unified-skin">\n{theme_css}\n</style>\n'
            '<link rel="stylesheet" href="/dashboard-theme.css?v=1">\n</head>',
            1,
        )
    back_href = f"/?date={date_text}"
    html = re.sub(
        r'(<a class="back-to-workbench" href=")[^"]*(")',
        rf"\1{back_href}\2",
        html,
        count=1,
    )
    return html


def serve_dashboard_html(handler, dashboard_path, date_text):
    html = dashboard_path.read_text(encoding="utf-8")
    handler.send_html(skin_dashboard_html(html, date_text))
