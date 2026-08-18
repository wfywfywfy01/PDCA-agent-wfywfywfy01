# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：页面外壳 page() 与路由参数工具
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。


def warm_identity_cache():
    try:
        fetch_vps_identity()
    except Exception as exc:
        _VPS_CACHE["identity_warmup_error"] = {"time": datetime.now().timestamp(), "payload": {"error": str(exc)}}


def is_previewable(path):
    return Path(path).suffix.lower() in {".md", ".txt", ".json", ".csv", ".html", ".htm"}


def page(title, body, date_text, message=""):
    msg_html = f'<div class="message">{esc(message)}</div>' if message else ""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <style>
    :root {{
      --bg: #eef4fb;
      --surface: #ffffff;
      --surface-soft: #f6f9ff;
      --ink: #17223a;
      --ink-soft: #56647a;
      --ink-muted: #8da0bb;
      --line: #d7e3f2;
      --line-soft: #e7eef8;
      --accent: #2f6fed;
      --accent-soft: #eaf2ff;
      --accent-ink: #174fbf;
      --success: #0f8a4b;
      --warn: #b46a00;
      --shadow-sm: 0 1px 2px rgba(31,34,48,.05);
      --shadow-md: 0 10px 28px rgba(31,80,150,.10);
      --shadow-lg: 0 18px 46px rgba(31,80,150,.16);
    }}
    * {{ box-sizing:border-box; }}
    body {{
      margin:0; background:linear-gradient(180deg,#f6faff 0%, var(--bg) 240px); color:var(--ink);
      font-family:"Inter","SF Pro Text","PingFang SC","Microsoft YaHei",system-ui,sans-serif;
      font-size:15px; line-height:1.6; -webkit-font-smoothing:antialiased;
    }}
    h1,h2,h3 {{ font-family:"Inter","SF Pro Display","PingFang SC","Microsoft YaHei",system-ui,sans-serif; letter-spacing:0; }}
    h2 {{ font-size:18px; margin:0 0 6px; font-weight:600; }}
    h3 {{ font-size:15px; margin:0 0 6px; font-weight:600; color:var(--ink); }}
    p {{ color:var(--ink-soft); margin:6px 0; }}
    a {{ color:var(--accent-ink); }}
    input, textarea, select {{
      background:var(--surface); border:1px solid var(--line); border-radius:10px;
      padding:11px 13px; font-size:14px; color:var(--ink); width:auto;
      font-family:inherit; transition:border-color .15s, box-shadow .15s;
    }}
    input:focus, textarea:focus, select:focus {{
      outline:none; border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-soft);
    }}
    textarea {{ width:100%; min-height:96px; resize:vertical; line-height:1.6; }}
    header {{
      background:rgba(255,255,255,.9); border-bottom:1px solid var(--line);
      padding:18px 36px;
      backdrop-filter:blur(10px);
    }}
    header h1 {{ margin:0 0 4px; font-size:20px; font-weight:700; color:var(--ink); }}
    header p {{ color:var(--ink-muted); margin:0; font-size:13px; }}
    main {{ max-width:1440px; margin:0 auto; padding:24px 28px 56px; display:flex; flex-direction:column; gap:18px; }}
    section {{
      background:var(--surface); border:1px solid var(--line); border-radius:18px;
      box-shadow:var(--shadow-sm); padding:22px 24px;
    }}
    section + section {{ margin-top:0; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:16px; }}
    .grid-secondary {{ margin-top:16px; grid-template-columns:repeat(auto-fit, minmax(320px, 1fr)); }}
    .entry-card-wide {{ min-height:88px; }}
    .card {{
      background:var(--surface); border:1px solid var(--line); border-radius:18px;
      padding:18px; box-shadow:var(--shadow-sm); transition:transform .15s, box-shadow .15s, border-color .15s;
    }}
    .card.ok {{ border-top:3px solid var(--success); }}
    .card.warn {{ border-top:3px solid var(--warn); }}
    .entry-card {{ color:inherit; display:block; text-decoration:none; }}
    .entry-card:hover {{ transform:translateY(-2px); box-shadow:var(--shadow-md); border-color:#dcd5c6; }}
    .entry-top {{ display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }}
    .entry-icon {{ align-items:center; background:var(--accent-soft); border-radius:12px; color:var(--accent-ink); display:inline-flex; height:42px; justify-content:center; width:42px; }}
    .label {{ color:var(--ink-muted); font-size:12px; letter-spacing:.04em; text-transform:uppercase; }}
    .state {{ font-size:24px; font-weight:600; margin:6px 0; color:var(--ink); }}
    .actions {{ display:flex; gap:10px; flex-wrap:wrap; margin:14px 0 0; }}
    .button, button {{
      border:0; border-radius:12px; background:var(--accent); color:white;
      padding:10px 18px; font-size:14px; font-weight:600;
      text-decoration:none; cursor:pointer; display:inline-block; line-height:1.2;
      transition:background .15s, transform .05s;
      font-family:inherit;
    }}
    .button:hover, button:hover {{ background:var(--accent-ink); }}
    .button:active, button:active {{ transform:translateY(1px); }}
    button:disabled {{ background:#d8c7bb; color:#fff; cursor:not-allowed; transform:none; opacity:.75; }}
    .button.secondary {{ background:var(--ink); }}
    .button.secondary:hover {{ background:#000; }}
    .button.light {{ background:#fff; color:var(--accent-ink); border:1px solid #b9d1ff; }}
    .button.light:hover {{ background:var(--accent-soft); color:var(--accent-ink); }}
    .button.danger {{ background:#c0413e; }}
    .thinking-inline {{ align-items:center; color:var(--ink-muted); display:none; gap:8px; font-size:13px; font-weight:600; }}
    .thinking-inline.on {{ display:inline-flex; }}
    .spinner {{ animation:spin .8s linear infinite; border:2px solid #eadbd0; border-top-color:var(--accent); border-radius:50%; display:inline-block; height:16px; width:16px; }}
    @keyframes spin {{ to {{ transform:rotate(360deg); }} }}
    table {{ width:100%; border-collapse:collapse; margin-top:10px; font-size:14px; }}
    th, td {{ border-bottom:1px solid var(--line-soft); padding:11px 8px; text-align:left; vertical-align:top; }}
    th {{ color:var(--ink-muted); font-size:12px; font-weight:600; letter-spacing:.04em; text-transform:uppercase; }}
    .message {{ background:var(--accent-soft); color:var(--accent-ink); border:1px solid #ecd6c7; padding:11px 16px; border-radius:10px; font-size:14px; }}
    .two {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
    .agent-section {{ background:var(--surface-soft); border-color:var(--line); }}
    .agent-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:18px; margin-top:18px; }}
    .agent-card {{
      background:var(--surface); border:1px solid var(--line); border-top:none;
      border-radius:14px; padding:24px 20px; text-align:center; min-height:240px;
      display:flex; flex-direction:column; align-items:center;
      transition:transform .15s, box-shadow .15s, border-color .15s;
    }}
    .agent-card:hover {{ transform:translateY(-2px); box-shadow:var(--shadow-md); border-color:#dcd5c6; }}
    .agent-card h3 {{ margin:12px 0 4px; font-size:16px; }}
    .agent-card p {{ color:var(--ink-soft); line-height:1.6; min-height:48px; font-size:14px; }}
    .agent-card .actions {{ justify-content:center; margin-top:auto; }}
    .agent-avatar {{
      align-items:center; background:var(--accent-soft); color:var(--accent-ink);
      border-radius:999px; display:inline-flex; font-size:30px; height:64px; width:64px;
      justify-content:center;
    }}
    .agent-meta {{ color:var(--ink-muted); font-size:12px; margin:4px 0; letter-spacing:.02em; }}
    .agent-button {{ background:var(--accent); color:#fff; min-width:160px; }}
    .agent-button:hover {{ background:var(--accent-ink); }}
    .editor-layout {{ display:grid; grid-template-columns:220px 1fr; gap:20px; }}
    .file-nav {{ background:var(--surface-soft); border:1px solid var(--line); border-radius:12px; padding:8px; }}
    .file-nav h3 {{ color:var(--ink-muted); font-size:11px; letter-spacing:.08em; text-transform:uppercase; padding:8px 12px 6px; margin:0; }}
    .file-nav a {{ color:var(--ink-soft); display:block; padding:9px 12px; text-decoration:none; border-radius:8px; font-size:14px; }}
    .file-nav a:hover {{ background:#efe9da; color:var(--ink); }}
    .file-nav a.active {{ background:var(--accent-soft); color:var(--accent-ink); font-weight:600; }}
    .page-toolbar {{ align-items:flex-start; display:flex; justify-content:space-between; gap:12px; margin-bottom:18px; }}
    .skill-chip {{ background:var(--surface-soft); border:1px solid var(--line); color:var(--ink-soft); border-radius:999px; display:inline-block; margin:4px 6px 4px 0; padding:5px 11px; font-size:13px; }}
    .drop-zone {{ border:1px dashed #cfc7b3; border-radius:12px; color:var(--ink-muted); margin-top:12px; padding:18px; background:var(--surface-soft); }}
    .hermes-result {{ background:#1c1e2a; color:#e8e6df; border-radius:12px; margin-top:14px; max-height:280px; overflow:auto; padding:16px; white-space:pre-wrap; font-family:"JetBrains Mono","SF Mono",ui-monospace,monospace; font-size:13px; line-height:1.6; }}
    .output-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:14px; margin-top:14px; }}
    .output-card {{ background:var(--surface-soft); border:1px solid var(--line); border-radius:12px; padding:16px; display:flex; flex-direction:column; gap:10px; min-height:150px; }}
    .output-card h3 {{ font-size:16px; margin:0; }}
    .output-card p {{ flex:1; font-size:13px; margin:0; }}
    .output-card .output-meta {{ color:var(--ink-muted); flex:0; font-size:12px; }}
    .output-icon {{ align-items:center; background:var(--accent-soft); border-radius:12px; color:var(--accent-ink); display:inline-flex; font-size:22px; height:42px; justify-content:center; width:42px; }}
    .output-card.missing {{ opacity:.55; }}
    details.output-paths {{ background:var(--surface-soft); border:1px solid var(--line); border-radius:12px; margin-top:14px; padding:12px 14px; }}
    details.output-paths summary {{ color:var(--ink-muted); cursor:pointer; font-weight:600; }}
    details.output-paths code {{ color:var(--ink-soft); word-break:break-all; }}
    .result-banner {{ background:var(--surface); border:1px solid var(--line); border-radius:14px; box-shadow:var(--shadow-md); padding:18px; margin-top:14px; }}
    .result-banner.ok {{ border-top:3px solid var(--success); }}
    .result-banner.warn {{ border-top:3px solid var(--warn); }}
    .result-banner h3 {{ margin:0 0 8px; }}
    .result-preview {{ background:var(--surface-soft); border:1px solid var(--line); border-radius:12px; color:var(--ink); margin-top:14px; max-height:360px; overflow:auto; padding:16px; white-space:pre-wrap; }}
    .result-file {{ color:var(--ink-muted); font-size:13px; margin-top:8px; word-break:break-all; }}
    .result-modal {{ align-items:center; background:rgba(31,34,48,.38); bottom:0; display:flex; justify-content:center; left:0; padding:28px; position:fixed; right:0; top:0; z-index:50; }}
    .result-dialog {{ background:var(--surface); border:1px solid var(--line); border-top:3px solid var(--success); border-radius:18px; box-shadow:var(--shadow-lg); max-height:86vh; max-width:900px; overflow:auto; padding:22px; width:min(900px, 100%); }}
    .result-dialog.warn {{ border-top-color:var(--warn); }}
    .result-dialog-head {{ align-items:flex-start; display:flex; gap:14px; justify-content:space-between; }}
    .result-close {{ align-items:center; border:1px solid var(--line); border-radius:999px; color:var(--ink-muted); display:inline-flex; height:34px; justify-content:center; text-decoration:none; width:34px; }}
    .result-close:hover {{ background:var(--surface-soft); color:var(--ink); }}
    .delivery-list {{ display:flex; flex-direction:column; gap:10px; margin-top:14px; }}
    .delivery-card {{ background:var(--surface-soft); border:1px solid var(--line); border-radius:12px; padding:0; overflow:hidden; }}
    .delivery-card summary {{ align-items:center; cursor:pointer; display:flex; justify-content:space-between; gap:12px; padding:14px 16px; }}
    .delivery-title {{ color:var(--ink); font-weight:600; }}
    .delivery-badge {{ border-radius:999px; font-size:12px; font-weight:700; padding:4px 10px; white-space:nowrap; }}
    .delivery-card.done .delivery-badge {{ background:#e1f1e8; color:var(--success); }}
    .delivery-card.progress .delivery-badge {{ background:#fff1d8; color:var(--warn); }}
    .delivery-card.pending .delivery-badge {{ background:#ece8df; color:var(--ink-soft); }}
    .delivery-card.risk .delivery-badge {{ background:#f7dddd; color:#b23a35; }}
    .delivery-card.risk {{ border-color:#efc7c3; }}
    .delivery-body {{ border-top:1px solid var(--line); padding:14px 16px; }}
    .delivery-body p {{ margin:4px 0; }}
    .progress-form {{ align-items:end; background:var(--surface); border:1px solid var(--line); border-radius:12px; display:grid; gap:10px; grid-template-columns:120px 140px 1fr auto; margin-top:12px; padding:12px; }}
    .progress-form label {{ color:var(--ink-muted); font-size:12px; font-weight:600; }}
    .progress-form input, .progress-form select {{ margin-top:4px; width:100%; }}
    .workbench-home {{ display:flex; flex-direction:column; gap:20px; }}
    .period-tabs {{ display:grid; grid-template-columns:repeat(5, minmax(0, 1fr)); gap:14px; }}
    .period-tab {{
      align-items:center; background:#fff; border:1px solid var(--line); border-radius:18px;
      box-shadow:var(--shadow-sm); color:#233451; display:flex; font-size:17px; font-weight:800;
      height:56px; justify-content:center; text-decoration:none;
    }}
    .period-tab.active {{ background:var(--accent); border-color:var(--accent); color:#fff; box-shadow:0 14px 26px rgba(47,111,237,.22); }}
    .home-top {{ display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:16px; }}
    .home-metric {{
      background:rgba(255,255,255,.94); border:1px solid #cfe0f5; border-radius:22px;
      box-shadow:var(--shadow-sm); min-height:118px; padding:18px;
      display:flex; flex-direction:column; justify-content:space-between;
    }}
    .home-metric-row {{ align-items:center; display:flex; justify-content:space-between; gap:12px; }}
    .home-metric-kicker {{ color:var(--ink-muted); font-size:12px; font-weight:700; text-transform:uppercase; }}
    .home-metric-value {{ color:var(--ink); font-size:34px; font-weight:800; line-height:1; margin:10px 0 6px; }}
    .home-chip {{ background:#edf5ff; border:1px solid #cddfff; border-radius:999px; color:var(--accent-ink); display:inline-flex; font-size:12px; font-weight:800; line-height:1; padding:7px 11px; white-space:nowrap; }}
    .home-chip.ok {{ background:#e7f4ed; border-color:#cfe8d9; color:var(--success); }}
    .home-chip.warn {{ background:#fff4dc; border-color:#ffd36e; color:var(--warn); }}
    .home-board {{ display:grid; grid-template-columns:320px minmax(0, 1fr) 300px; gap:18px; align-items:start; }}
    .home-stack {{ display:flex; flex-direction:column; gap:18px; }}
    .home-panel {{
      background:rgba(255,255,255,.94); border:1px solid #cfe0f5; border-radius:22px;
      box-shadow:var(--shadow-sm); overflow:hidden;
    }}
    .home-panel-head {{
      align-items:center; border-bottom:1px solid var(--line-soft); display:flex;
      justify-content:space-between; gap:12px; min-height:54px; padding:14px 16px;
    }}
    .home-panel-head h2 {{ color:#15223a; font-size:18px; font-weight:800; margin:0; }}
    .home-panel-body {{ padding:14px 16px 16px; }}
    .home-todo-list {{ display:flex; flex-direction:column; }}
    .home-todo {{
      display:grid; grid-template-columns:24px 1fr auto; gap:10px; padding:11px 0;
      border-bottom:1px solid var(--line-soft); align-items:start;
    }}
    .home-todo:last-child {{ border-bottom:0; }}
    .home-check {{ border:1px solid #d7cfc0; border-radius:7px; height:22px; width:22px; }}
    .home-todo b {{ display:block; font-size:14px; line-height:1.35; }}
    .home-todo small {{ color:var(--ink-muted); display:block; font-size:12px; margin-top:3px; }}
    .home-module-grid {{ display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:12px; }}
    .home-module {{
      background:linear-gradient(180deg,#fff 0%, #f8fbff 100%); border:1px solid #cfe0f5; border-radius:18px;
      color:inherit; display:flex; flex-direction:column; min-height:144px; padding:14px; text-decoration:none;
    }}
    .home-module:hover {{ border-color:#aecaef; box-shadow:var(--shadow-md); transform:translateY(-1px); }}
    .home-module b {{ color:var(--ink); font-size:15px; margin-bottom:4px; }}
    .home-module strong {{ color:var(--ink); display:block; font-size:30px; line-height:1; margin:14px 0 8px; }}
    .home-module span {{ color:var(--ink-soft); font-size:13px; line-height:1.45; }}
    .home-progress {{ background:#e1ebfa; border-radius:999px; height:8px; margin-top:auto; overflow:hidden; }}
    .home-progress i {{ background:var(--accent); border-radius:inherit; display:block; height:100%; }}
    .home-status-grid {{ border:1px solid #cfe0f5; border-radius:18px; display:grid; grid-template-columns:repeat(3, 1fr); margin-top:14px; overflow:hidden; }}
    .home-status-cell {{ background:var(--surface); border-right:1px solid var(--line); padding:14px; }}
    .home-status-cell:last-child {{ border-right:0; }}
    .home-status-cell span {{ color:var(--ink-muted); font-size:12px; }}
    .home-status-cell strong {{ display:block; font-size:24px; margin-top:4px; }}
    .home-alert {{ display:grid; grid-template-columns:30px 1fr; gap:10px; padding:12px 0; border-bottom:1px solid var(--line-soft); }}
    .home-alert:last-child {{ border-bottom:0; }}
    .home-alert-icon {{ align-items:center; background:#edf5ff; border-radius:10px; color:var(--accent-ink); display:flex; font-weight:800; height:30px; justify-content:center; width:30px; }}
    .home-alert b {{ display:block; font-size:13px; line-height:1.35; }}
    .home-alert p {{ font-size:12px; line-height:1.45; margin:3px 0 0; }}
    .home-important {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
    .home-note-list {{ margin:10px 0 0; padding-left:20px; color:var(--ink-soft); }}
    .home-note-list li {{ margin:6px 0; }}
    .home-mini-grid {{ display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:12px; }}
    .home-mini {{
      background:linear-gradient(180deg,#fff 0%, #f8fbff 100%); border:1px solid #cfe0f5; border-radius:18px;
      min-height:104px; padding:14px;
    }}
    .home-section-banner {{
      align-items:center; background:linear-gradient(100deg,#16386d 0%, #2f6fed 100%);
      border-radius:20px; color:#fff; display:flex; justify-content:space-between; gap:18px;
      min-height:80px; padding:18px 22px;
    }}
    .home-section-banner strong {{ align-items:center; background:rgba(255,255,255,.16); border-radius:14px; display:inline-flex; font-size:18px; height:42px; justify-content:center; margin-right:14px; width:42px; }}
    .home-section-banner h2 {{ align-items:center; color:#fff; display:inline-flex; font-size:24px; margin:0; }}
    .home-section-banner p {{ color:#dce9ff; margin:0; max-width:760px; }}
    .home-mini span {{ color:var(--ink-muted); font-size:12px; }}
    .home-mini strong {{ display:block; font-size:26px; margin:10px 0 4px; }}
    .home-quick-actions {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:14px; }}
    @media (max-width:1200px) {{
      .home-board {{ grid-template-columns:300px 1fr; }}
      .home-stack.right {{ grid-column:1 / -1; display:grid; grid-template-columns:1fr 1fr; }}
      .home-module-grid {{ grid-template-columns:repeat(2, minmax(0, 1fr)); }}
      .home-important {{ grid-template-columns:1fr; }}
    }}
    @media (max-width:800px) {{
      .two, .editor-layout, .period-tabs, .home-top, .home-board, .home-stack.right, .home-module-grid, .home-status-grid, .home-mini-grid {{ grid-template-columns:1fr; }}
      main {{ padding:18px 14px 36px; }}
      header {{ padding:16px 18px; }}
      .home-status-cell {{ border-right:0; border-bottom:1px solid var(--line); }}
      .home-status-cell:last-child {{ border-bottom:0; }}
    }}
  </style>
</head>
<body>
<header>
  <h1>经销商PDCA工作台</h1>
  <p>{esc(header_subtitle())}</p>
</header>
<main>
{msg_html}
{body}
</main>
</body>
</html>"""
