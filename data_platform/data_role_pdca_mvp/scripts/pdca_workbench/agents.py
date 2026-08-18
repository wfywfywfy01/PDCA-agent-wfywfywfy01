# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：Agent 卡片、技能安装与 Hermes 聊天
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。



def hermes_exe():
    configured = os.environ.get("HERMES_COMMAND")
    if configured:
        return configured
    bundled = Path("__pdca_no_bundled_hermes__")  # HERMES_COMMAND/PATH only; no hard-coded user path
    if bundled.exists():
        return str(bundled)
    discovered = shutil.which("hermes")
    return discovered or "hermes"


def agent_by_key(key):
    return next((agent for agent in AGENT_CARDS if agent["key"] == key), None)


def agent_profile_dir(agent):
    return HERMES_HOME / agent["profile"]


def agent_soul_path(agent):
    return agent_profile_dir(agent) / "SOUL.md"


def agent_core_file_path(agent, filename):
    safe_file = filename if filename in AGENT_CORE_FILES else "SOUL.md"
    return agent_profile_dir(agent) / safe_file


def ensure_agent_soul(agent):
    path = agent_soul_path(agent)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    source_path = WORKSPACE / "agents" / f"{agent['key']}.md"
    source_text = read_text(source_path)
    content = source_text or f"# {agent['key']}\n\n{agent['desc']}\n"
    write_text(path, content)
    return path


def ensure_agent_core_file(agent, filename):
    if filename == "SOUL.md":
        return ensure_agent_soul(agent)
    path = agent_core_file_path(agent, filename)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        title = filename.replace(".md", "")
        write_text(path, f"# {title}\n\n")
    return path


def list_agent_skills(agent):
    skills_dir = agent_profile_dir(agent) / "skills"
    if not skills_dir.exists():
        return []
    return sorted(
        [path.parent.name for path in skills_dir.glob("*/SKILL.md")],
        key=str.lower,
    )


def skill_name_from_content(filename, content):
    for line in content.splitlines()[:20]:
        if line.lower().startswith("name:"):
            return safe_name(line.split(":", 1)[1].strip())
    stem = Path(filename or "uploaded-skill").stem
    return safe_name(stem if stem.upper() != "SKILL" else "uploaded-skill")


def install_skill_to_agent(agent_key, filename, content_bytes):
    agent = agent_by_key(agent_key)
    if not agent:
        raise ValueError("未知 Agent。")
    text = content_bytes.decode("utf-8-sig", errors="replace")
    skill_name = skill_name_from_content(filename, text)
    target = agent_profile_dir(agent) / "skills" / skill_name
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(text, encoding="utf-8")
    return target


def data_access_agent_prompt(query: str) -> str:
    """与 scripts/invoke-data-access-agent.ps1 保持一致的只读取数提示词。"""
    return f"""
You are acting as the data-access-agent for the Dealer PDCA workspace.

User data request:
{query}

Follow the data-access-agent rules in AGENTS.md.
Use installed Hermes Odoo skills when needed.

Rules:
1. Read-only only. Do not approve, reject, send messages, write, delete, or import data.
2. If VPS/Odoo data is needed, use the Vertu/Odoo skill or the vertu CLI.
3. Return these sections: user question, query scope, skill or command used, data source, result summary, data quality issues, next step.
4. If you cannot query, explain why and what information is needed next.
""".strip()



def run_hermes_chat(query):
    if not query.strip():
        return {"ok": False, "content": "请输入要问 Hermes 的内容。", "path": None}
    try:
        if is_vps_cli_query(query):
            return run_vps_cli_query(query)
    except Exception as exc:
        return {"ok": False, "content": f"VPS-CLI 路由失败：{exc}", "path": None}
    try:
        if is_research_query(query):
            return run_research_chat(query)
    except Exception as exc:
        return {"ok": False, "content": f"调研 Agent 执行失败：{exc}", "path": None}
    try:
        if is_sales_data_query(query):
            return run_sales_data_query(query)
    except Exception as exc:
        return {"ok": False, "content": f"业绩出表失败：{exc}", "path": None}
    try:
        if is_logistics_query(query):
            return run_logistics_chat(query)
    except Exception as exc:
        return {"ok": False, "content": f"物流核查失败：{exc}", "path": None}
    topic = "pdca-workbench-chat"
    started_at = datetime.now().timestamp()
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(REPO_ROOT / "scripts" / "invoke-data-access-agent.ps1"),
        "-Query",
        query,
        "-Topic",
        topic,
    ]
    if os.name != "nt":
        command = [
            hermes_exe(),
            "chat",
            "-q",
            data_access_agent_prompt(query),
            "-Q",
            "--max-turns",
            "15",
        ]

    try:
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "content": "Hermes 执行超过 120 秒，已自动终止。演示时可改成更明确的数据出表或调研问题。", "path": None}
    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part).strip()
    if completed.returncode != 0:
        if "No inference provider configured" in output:
            return {"ok": False, "content": (
                "Hermes 模型还没有配置好。\n\n"
                "已知修复方式：把 Hermes 配置为 custom provider，并使用 DashScope OpenAI 兼容地址：\n"
                "hermes config set model.provider custom\n"
                "hermes config set model.default qwen-plus\n"
                "hermes config set model.base_url https://dashscope.aliyuncs.com/compatible-mode/v1\n"
            ), "path": None}
        return {"ok": False, "content": f"Hermes 调用失败：{output}", "path": None}
    path = resolve_hermes_output_path(output, topic, started_at)
    if path and path.exists():
        if path.suffix.lower() not in {".md", ".txt", ".json", ".csv", ".html", ".htm"}:
            return {"ok": True, "content": f"Hermes 已生成文件：{path.name}", "path": str(path), "filename": path.name}
        content = read_text(path).strip()
        if content:
            return {"ok": True, "content": content[-4000:], "path": str(path), "filename": path.name}
    if output:
        return {"ok": True, "content": output, "path": None}
    return {"ok": True, "content": "Hermes 已成功运行，但没有返回文本。模型已配置，可继续重试更明确的指令。", "path": None}
