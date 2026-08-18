# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：vertu-cli 命令桥接、IM、Odoo 检索
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。


def extract_json_payload(text):
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
            return payload
        except json.JSONDecodeError:
            continue
    raise ValueError("VPS 返回内容不是 JSON")


def _flag_value(args, flag, default=""):
    try:
        return args[args.index(flag) + 1]
    except (ValueError, IndexError):
        return default


def translate_vertu_cli_args(args):
    """把工作台仍在使用的旧 Odoo 参数映射为 vertu-cli 2.x 快捷命令。"""
    if args[:2] == ["odoo", "me"]:
        return ["hr", "+me"]
    if args[:3] == ["odoo", "daily-report", "user-summary"]:
        mapped = ["report", "+user-summary"]
        for flag in ("--user-id", "--start-time", "--end-time"):
            value = _flag_value(args, flag)
            if value:
                mapped.extend([flag, value])
        return mapped
    if args[:4] == ["odoo", "project", "todo", "list"]:
        return ["task", "+tc-todos", "--limit", _flag_value(args, "--limit", "100")]
    if args[:4] == ["odoo", "project", "todo", "create"]:
        mapped = ["task", "+tc-todo-create"]
        for flag in ("--title", "--remark", "--deadline"):
            value = _flag_value(args, flag)
            if value:
                mapped.extend([flag, value])
        return mapped
    if args[:4] == ["odoo", "project", "todo", "update"]:
        mapped = ["task", "+tc-todo-update"]
        for flag in ("--todo-id", "--remark", "--deadline"):
            value = _flag_value(args, flag)
            if value:
                mapped.extend([flag, value])
        status = _flag_value(args, "--status")
        if status:
            mapped.extend(["--status", "done" if status in ("已完成", "completed") else status])
        return mapped
    if args[:4] == ["odoo", "project", "todo", "complete"]:
        return ["task", "+tc-todo-update", "--todo-id", _flag_value(args, "--todo-id"), "--status", "done"]
    if args[:3] == ["odoo", "im", "channels"]:
        return ["im", "+channels", "--limit", _flag_value(args, "--limit", "20")]
    if args[:3] == ["odoo", "im", "search"]:
        return [
            "im",
            "+history",
            "--channel-id",
            _flag_value(args, "--channel-id"),
            "--limit",
            _flag_value(args, "--limit", "20"),
        ]
    return args


def normalize_vertu_cli_payload(cache_key, payload):
    """为旧页面保留 items/results 等字段，底层数据来自 vertu-cli 2.x。"""
    if not isinstance(payload, dict):
        return payload
    result = dict(payload)
    if cache_key.startswith("im_") and "channels" in result:
        result.setdefault("items", result.get("channels") or [])
        result.setdefault("total", result.get("count") or len(result["items"]))
    if cache_key.startswith("im_latest_") and "messages" in result:
        result.setdefault("items", result.get("messages") or [])
    if "todos" in result:
        result.setdefault("items", result.get("todos") or [])
        result.setdefault("results", result.get("todos") or [])
    return result


def vertu_process_command(args):
    """构造可跨平台执行的 vertu-cli 命令；Windows 的 .cmd 需经 cmd /c。"""
    executable = vertu_command()
    command = [executable, *translate_vertu_cli_args(args)]
    if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", *command]
    return command


def run_vertu_json(cache_key, args, timeout=8):
    now = datetime.now().timestamp()
    cached = _VPS_CACHE.get(cache_key)
    if cached and now - cached["time"] < VPS_CACHE_SECONDS:
        return cached["payload"], ""
    command = vertu_process_command(args)
    try:
        completed = subprocess.run(
            command,
            cwd=str(WORKSPACE),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        if cached:
            return cached["payload"], ""
        raise RuntimeError("VPS 请求超时，请稍后刷新。")
    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
    if completed.returncode != 0:
        if cached:
            return cached["payload"], output
        raise RuntimeError(output.strip() or f"vertu-cli 命令失败：{completed.returncode}")
    try:
        payload = normalize_vertu_cli_payload(cache_key, extract_json_payload(output))
    except ValueError:
        if cached:
            return cached["payload"], output
        raise
    _VPS_CACHE[cache_key] = {"time": now, "payload": payload}
    return payload, output


def run_vertu_write_json(args, timeout=60):
    command = vertu_process_command(args)
    completed = subprocess.run(
        command,
        cwd=str(WORKSPACE),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
    if completed.returncode != 0:
        raise RuntimeError(output.strip() or f"vertu-cli 写入失败：{completed.returncode}")
    _VPS_CACHE.clear()
    return extract_json_payload(output), output


def compact_text(value, limit=120):
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[:limit]}..."


def im_channel_url(channel_id):
    template = os.environ.get(
        "PDCA_IM_CHANNEL_URL_TEMPLATE",
        "https://vps-im.vertu.cn/web#action=mail.action_discuss&active_id=discuss.channel_{channel_id}",
    )
    return template.format(channel_id=channel_id)


def fetch_im_latest_message(channel_id):
    payload, _ = run_vertu_json(
        f"im_latest_{channel_id}",
        ["odoo", "im", "search", "--channel-id", str(channel_id), "--role", "any", "--limit", "1"],
    )
    items = payload.get("items") or []
    return items[0] if items else {}


def fetch_vps_im_unread(with_latest=True):
    try:
        payload, _ = run_vertu_json(
            "im_unread_latest" if with_latest else "im_unread",
            ["odoo", "im", "channels", "--has-unread", "--limit", "20"],
        )
        items = payload.get("items") or []
        if with_latest:
            for item in items[:5]:
                try:
                    item["latest_message"] = fetch_im_latest_message(item.get("id"))
                except Exception:
                    item["latest_message"] = {}
        unread_count = sum(int(item.get("unread_count") or 0) for item in items)
        return {
            "ok": True,
            "channels": items,
            "channel_count": int(payload.get("total") or len(items)),
            "unread_count": unread_count,
            "error": "",
        }
    except Exception as exc:
        return {"ok": False, "channels": [], "channel_count": 0, "unread_count": 0, "error": str(exc)}


def fetch_vps_today_todos():
    try:
        payload, _ = run_vertu_json(
            "today_todos",
            ["odoo", "project", "todo", "list", "--for-me", "--due-within-days", "0", "--limit", "20"],
        )
        rows = payload.get("results") or payload.get("items") or []
        return {"ok": True, "rows": rows, "count": int(payload.get("count") or len(rows)), "error": ""}
    except Exception as exc:
        return {"ok": False, "rows": [], "count": 0, "error": str(exc)}


def quote_odoo_domain_value(value: str) -> str:
    """转义 Odoo domain 字符串字面量。"""
    return str(value or "").replace("\\", "\\\\").replace("'", "\\'")


def many2one_name(value):
  """@param value Odoo many2one [id, name]"""
  return value[1] if isinstance(value, list) and len(value) > 1 else ""


def odoo_data_search(model: str, domain: str, fields: str, limit: int = 5) -> tuple[list[dict], str]:
    """
    通过 vertu odoo data search 查询记录。

    @returns (rows, error)
    """
    cache_key = f"odoo_search_{model}_{domain}_{fields}_{limit}"
    try:
        payload, output = run_vertu_json(
            cache_key,
            [
                "odoo",
                "data",
                "search",
                "--model-name",
                model,
                "--domain",
                domain,
                "--fields",
                fields,
                "--limit",
                str(limit),
            ],
            timeout=20,
        )
        if isinstance(payload, list):
            return payload, ""
        return [], output or "unexpected odoo search payload"
    except Exception as exc:
        return [], str(exc)
