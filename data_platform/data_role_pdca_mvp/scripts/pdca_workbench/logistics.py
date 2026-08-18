# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：物流单号解析与承运商官网查询
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。


def is_logistics_query(query):
    text = query.lower()
    return any(token in text for token in ["物流", "快递", "单号", "tracking", "ups", "fedex", "dhl", "顺丰"])


def extract_tracking_numbers(query):
    numbers = []
    text = query.upper()
    for match in re.finditer(r"1Z(?:[\s\-_:：]*[A-Z0-9]){16}", text):
        value = re.sub(r"[^A-Z0-9]", "", match.group(0))
        if value not in numbers:
            numbers.append(value)
    for match in re.finditer(r"[A-Z0-9][A-Z0-9\s\-_:：]{8,40}[A-Z0-9]", text):
        value = re.sub(r"[^A-Z0-9]", "", match.group(0))
        if "1Z" in value and not value.startswith("1Z"):
            value = value[value.index("1Z"):]
        if 10 <= len(value) <= 30 and any(char.isdigit() for char in value) and value not in numbers:
            numbers.append(value)
    return numbers


def infer_carrier(tracking_number):
    value = tracking_number.upper()
    if value.startswith("1Z"):
        return "UPS"
    if re.fullmatch(r"\d{12,15}", value):
        return "FedEx"
    if re.fullmatch(r"\d{10}", value):
        return "DHL"
    if value.startswith("SF"):
        return "SF"
    return "未知"


def carrier_tracking_url(carrier, tracking_number):
    carriers = read_json(WORKSPACE / "config" / "carriers.json")
    info = carriers.get(carrier) or {}
    template = info.get("tracking_url", "")
    return template.replace("{tracking_number}", tracking_number) if template else ""


def browser_executable_path():
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    return next((str(path) for path in candidates if path.exists()), None)


def parse_dhl_tracking_text(text, tracking_number):
    cleaned = re.sub(r"[ \t]+", " ", text or "")
    status = ""
    for candidate in ["Delivered", "Out for Delivery", "In Transit", "Shipment information received", "Exception"]:
        if re.search(rf"\b{re.escape(candidate)}\b", cleaned, re.I):
            status = candidate
            break
    last_update = ""
    match = re.search(r"Last Update:\s*(.+?)(?:\n|Origin:|Destination:|Authenticate|Sign up)", cleaned, re.S)
    if match:
        last_update = " ".join(match.group(1).split())
    origin = ""
    match = re.search(r"Origin:\s*(.+?)(?:\n|Destination:|Authenticate|Sign up)", cleaned, re.S)
    if match:
        origin = " ".join(match.group(1).split())
    destination = ""
    match = re.search(r"Destination:\s*(.+?)(?:\n|Authenticate|Sign up|Shipment Details)", cleaned, re.S)
    if match:
        destination = " ".join(match.group(1).split())
    service = ""
    match = re.search(r"Service\s*\n\s*(.+?)(?:\n|1 Piece ID|Waybill Number)", cleaned, re.S)
    if match:
        service = " ".join(match.group(1).split())
    return {
        "tracking_number": tracking_number,
        "carrier": "DHL",
        "status": status or "官网已打开，未识别到状态",
        "last_update": last_update,
        "origin": origin,
        "destination": destination,
        "service": service,
        "source": "DHL 官网浏览器抓取",
    }


def track_dhl_with_browser(tracking_number):
    executable = browser_executable_path()
    if not executable:
        raise RuntimeError("未找到 Chrome 或 Edge，无法启动浏览器核查。")
    step_count = 0

    def step(label):
        nonlocal step_count
        step_count += 1
        if step_count > 15:
            raise RuntimeError(f"浏览器核查超过 15 步，已强制终止：{label}")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        step("启动浏览器")
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=executable,
            args=["--disable-http2", "--disable-blink-features=AutomationControlled"],
        )
        try:
            step("打开页面")
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
            url = "https://www.dhl.com/global-en/home/tracking.html"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                # DHL 偶发 HTTP2/加载超时，页面主体已渲染时继续后续步骤。
                pass

      

      
            step("等待页面加载")
            page.wait_for_timeout(4000)
            popup_errors = []
            for selector in ["#onetrust-accept-btn-handler", 'button:has-text("Accept All")', 'button:has-text("Stay on this site")']:
                step(f"处理弹窗 {selector}")
                try:
                    page.locator(selector).first.click(timeout=3000, force=True)
                    page.wait_for_timeout(800)
                except Exception as exc:
                    popup_errors.append(f"{selector}: {exc}")
            step("输入单号")
            page.locator('input[name="tracking-id"]').fill(tracking_number, timeout=8000)
            step("点击 Track")
            page.locator('button:has-text("Track")').first.click(timeout=8000, force=True)
            step("等待官网结果")
            page.wait_for_timeout(12000)
            step("读取页面文本")
            text = page.locator("body").inner_text(timeout=10000)
            result = parse_dhl_tracking_text(text, tracking_number)
            if popup_errors:
                result["note"] = "部分弹窗选择器未命中，不影响已读取页面文本。"
            return result
        finally:
            browser.close()


def run_logistics_chat(query):
    tracking_numbers = extract_tracking_numbers(query)
    if not tracking_numbers:
        return {"ok": False, "content": "我识别到这是物流任务，但没有识别出快递单号。请直接输入 UPS/FedEx/DHL/SF 单号。", "path": None}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = DATA_REPORTS / f"{stamp}_logistics-tracking_summary.md"
    lines = [
        "# 物流核查 Agent 结果",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 用户问题",
        "",
        query,
        "",
        "## 识别结果",
        "",
        "已识别为物流查询，并优先通过官网浏览器核查读取页面状态。浏览器核查最多 15 步，超过即强制终止。",
        "",
        "| 单号 | 承运商 | 官网核查入口 | 当前判断 | 更新时间 | 始发地 | 目的地 |",
        "|---|---|---|---|---|---|---|",
    ]
    links = []
    tracking_results = []
    for number in tracking_numbers:
        carrier = infer_carrier(number)
        url = carrier_tracking_url(carrier, number)
        if url:
            links.append({"label": f"打开 {carrier} 官网核查 {number}", "url": url})
        link = f"[打开官网]({url})" if url else "未识别承运商，需补充"
        result = {
            "tracking_number": number,
            "carrier": carrier,
            "status": "待官网核查",
            "last_update": "",
            "origin": "",
            "destination": "",
            "source": "官网入口",
        }
        if carrier == "DHL":
            try:
                result = track_dhl_with_browser(number)
            except Exception as exc:
                result["status"] = f"官网浏览器核查失败：{exc}"
        tracking_results.append(result)
        lines.append(
            f"| {number} | {carrier} | {link} | {result.get('status', '')} | "
            f"{result.get('last_update', '')} | {result.get('origin', '')} | {result.get('destination', '')} |"
        )
    lines.extend([
        "",
        "## 下一步",
        "",
        "- 弹窗中会直接显示官网核查卡片。",
        "- 点“查看结果”可看到 Markdown 明细。",
        "- 点“用本机软件打开”会打开 Markdown 报告。",
        "- DHL 已接入浏览器官网核查；UPS/FedEx 后续可按同样方式接入。",
    ])
    write_text(path, "\n".join(lines))
    content = read_text(path).strip()
    return {
        "ok": True,
        "content": content,
        "path": str(path),
        "filename": path.name,
        "kind": "logistics",
        "links": links,
        "tracking_results": tracking_results,
    }
