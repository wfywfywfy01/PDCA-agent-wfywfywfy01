# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：通用工具：日期、路径、文本读写、转义
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。


_customer_proc = None  # 客户管理后台进程句柄


AGENT_CARDS = [
    {
        "key": "data-access-agent",
        "title": "数据出表 Agent",
        "profile": "data-access-agent",
        "source": "Hermes profile",
        "desc": "从 VPS/Odoo 按你的要求拉取真实数据，并输出 Excel 表格和数据结论。",
    },
    {
        "key": "logistics-browser-agent",
        "title": "物流官网核查 Agent",
        "profile": "logistics-browser-agent",
        "source": "data_role_pdca_mvp/agents/logistics-browser-agent.md",
        "desc": "拿物流单号访问 UPS/FedEx/DHL 等官网，判断正常、异常或待人工确认。",
    },
    {
        "key": "research-agent",
        "title": "市场调研 Agent",
        "profile": "research-agent",
        "source": "data_role_pdca_mvp/agents/research-agent.md",
        "desc": "调研竞品、客户背景、国家市场、门店资料和公开网页信息，并输出带来源的 Markdown 报告。",
    },
]
AGENT_CORE_FILES = ["SOUL.md", "IDENTITY.md", "AGENTS.md", "MEMORY.md", "USER.md"]


def vertu_command():
    configured = os.environ.get("VERTU_COMMAND")
    if configured:
        if Path(configured).name.lower() in {"vertu", "vertu.cmd", "vertu.ps1"}:
            configured = "vertu-cli"
        configured_path = Path(configured)
        if configured_path.exists():
            return str(configured_path)
        discovered = shutil.which(configured)
        if discovered:
            return discovered
    discovered = shutil.which("vertu-cli")
    if discovered:
        return discovered
    npm_cmd = Path.home() / "AppData" / "Roaming" / "npm" / "vertu-cli.cmd"
    if npm_cmd.exists():
        return str(npm_cmd)
    return "vertu-cli"

QUESTION_TITLES = [
    "1. 今天完成了什么？",
    "2. 明天要完成什么？",
    "3. 昨天未完成事项，今天完成了哪些？",
    "4. 上级临时交办，今天交付了哪些？",
    "5. 今天还有哪些未完成？",
    "6. 今天遇到的卡点",
    "7. 需要上级或业务方确认的事项",
]


def today_text():
    return datetime.now().strftime("%Y-%m-%d")


def esc(value):
    return html.escape(str(value or ""), quote=True)


def output_dir(date_text):
    return WORKSPACE / "outputs" / date_text


def latest_file(paths):
    existing = [Path(path) for path in paths if Path(path).exists()]
    return max(existing, key=lambda path: path.stat().st_mtime) if existing else None


def latest_output_file(date_text, target):
    out = output_dir(date_text)
    if target == "workbook":
        return latest_file(out.glob(f"{date_text}_data_summary*.xlsx"))
    if target == "report":
        return latest_file([out / "data_summary_report.md"])
    if target == "pdca":
        return latest_file([out / "pdca_daily_check.md"])
    if target == "dashboard":
        return latest_file([out / "dashboard.html"])
    if target == "im":
        return latest_file([WORKSPACE / "outbox" / f"{date_text}_im_message.md"])
    return None


def file_time_label(path):
    if not path or not Path(path).exists():
        return "运行后生成"
    return datetime.fromtimestamp(Path(path).stat().st_mtime).strftime("%H:%M:%S")


def questionnaire_path(date_text):
    return WORKSPACE / "inputs" / "questionnaires" / f"{date_text}_questionnaire.md"


def todo_path(date_text):
    return WORKSPACE / "inputs" / "todos" / f"{date_text}_todos.csv"


def logistics_path(date_text):
    return WORKSPACE / "inputs" / "logistics" / f"{date_text}_tracking.csv"


def read_text(path):
    return path.read_text(encoding="utf-8-sig") if path.exists() else ""


def read_json(path):
    return json.loads(read_text(path) or "{}")


def write_text(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")
