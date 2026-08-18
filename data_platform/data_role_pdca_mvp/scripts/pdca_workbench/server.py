# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：HTTP Handler 与 main() 入口
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。


class WorkbenchHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def date_from_query(self, query):
        return parse_qs(query).get("date", [today_text()])[0] or today_text()

    def read_form(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return parse_qs(raw)

    def read_multipart(self):
        import cgi  # 独立 HTTP 服务模式专用；Python 3.13 移除该模块，故延迟到用到时才导入
        environ = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": self.headers.get("Content-Type", ""),
            "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
        }
        return cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ=environ)

    def send_html(self, content):
        encoded = content.encode("utf-8")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            return

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            return

    def send_file(self, path):
        content_type = "text/html; charset=utf-8"
        self.send_bytes(path.read_bytes(), content_type)

    def send_bytes(self, content, content_type):
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            return

    def serve_cockpit_module(self, mount, parsed_path, resolve_asset, date_text=""):
        """静态驾驶舱模块：/walkin-cockpit/、/online-cockpit/ 等。"""
        if parsed_path == mount:
            self.send_response(302)
            self.send_header("Location", f"{mount}/")
            self.end_headers()
            return
        rel = parsed_path[len(mount) + 1 :]
        asset = resolve_asset(rel)
        if not asset:
            self.send_response(404)
            self.end_headers()
            return
        guessed, _ = mimetypes.guess_type(str(asset))
        content_type = guessed or "application/octet-stream"
        if asset.suffix.lower() in {".js", ".mjs"}:
            content_type = "application/javascript; charset=utf-8"
        elif asset.suffix.lower() == ".json":
            content_type = "application/json; charset=utf-8"
        elif asset.suffix.lower() in {".html", ".htm"}:
            title = "经销商海外客流分析台" if "walkin" in mount else "经销商线上经营"
            html = skin_cockpit_html(asset.read_text(encoding="utf-8"), date_text, title)
            self.send_html(html)
            return
        self.send_bytes(asset.read_bytes(), content_type)

    def serve_walkin_cockpit(self, parsed_path, date_text=""):
        self.serve_cockpit_module("/walkin-cockpit", parsed_path, resolve_walkin_asset, date_text)

    def serve_online_cockpit(self, parsed_path, date_text=""):
        self.serve_cockpit_module("/online-cockpit", parsed_path, resolve_online_asset, date_text)

    def serve_meeting_center(self, parsed_path, date_text=""):
        if parsed_path == "/meeting-center":
            self.send_response(302)
            self.send_header("Location", f"/meeting-center/?date={date_text}")
            self.end_headers()
            return
        rel = parsed_path[len("/meeting-center/") :]
        if not rel:
            rel = "index.html"
        asset = resolve_meeting_center_asset(rel)
        if not asset:
            self.send_response(404)
            self.end_headers()
            return
        if asset.suffix.lower() in {".html", ".htm"}:
            html = skin_cockpit_html(asset.read_text(encoding="utf-8"), date_text, "会议中心")
            self.send_html(html)
            return
        guessed, _ = mimetypes.guess_type(str(asset))
        self.send_bytes(asset.read_bytes(), guessed or "application/octet-stream")

    def send_walkin_api(self, query, date_text):
        """Walk-in 数据：数据库/VPS/已核验参考源；缺失时明确返回不可用。"""
        month = (query.get("month", [""])[0] or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            month = (date_text or today_text())[:7]
        if build_walkin_api_payload is None:
            self.send_json({"error": "workbench_data module missing"}, status=500)
            return
        try:
            payload = build_walkin_api_payload(month, date_text or today_text())
            self.send_json(payload)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def send_online_channel_api(self, date_text):
        """线上 OKR 表：大区东南亚/欧洲，真实销售来自 vertu 经销商业绩 JSON。"""
        if build_online_channel_payload is None:
            self.send_json({"error": "workbench_data module missing"}, status=500)
            return
        try:
            payload = build_online_channel_payload(date_text or today_text())
            self.send_json(payload)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def send_error_page(self, exc):
        try:
            self.send_html(page("工作台异常", f"""
            <section>
              <h2>工作台遇到问题</h2>
              <p>这次请求没有完成，但服务没有崩。请刷新后重试。</p>
              <div class="message">{esc(exc)}</div>
              <div class="actions">{button("返回首页", route_url("/", today_text()), "light")}</div>
            </section>
            """, today_text()))
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            return
        except Exception:
            try:
                self.send_response(500)
                self.end_headers()
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
                return

    def redirect(self, path, date_text, message=""):
        params = {"date": date_text}
        if message:
            params["message"] = message
        self.send_response(303)
        self.send_header("Location", f"{path}?{urlencode(params)}")
        self.end_headers()

    def do_GET(self):
        try:
            self._do_GET()
        except Exception as exc:
            self.send_error_page(exc)

    def _do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        date_text = self.date_from_query(parsed.query)
        message = query.get("message", [""])[0]
        if parsed.path == "/":
            serve_home_dashboard_index(self)
        elif parsed.path == "/home-classic":
            self.send_html(render_home(date_text, message))
        elif parsed.path.startswith("/api/dashboard/") or parsed.path.startswith("/api/todos/") or parsed.path.startswith("/api/hermes-agent/") or parsed.path.startswith("/api/customer-center/") or parsed.path.startswith("/api/hr/") or parsed.path == "/api/exceptions" or parsed.path.startswith("/api/important-matters") or parsed.path.startswith("/api/task-center/") or parsed.path.startswith("/api/meeting-center/"):
            data = dispatch_home_dashboard_api(parsed.path, query)
            if data is None:
                self.send_response(404)
                self.end_headers()
            else:
                self.send_json(data)
        elif parsed.path == "/questionnaire":
            self.send_html(render_questionnaire(date_text, message))
        elif parsed.path == "/todos":
            self.send_html(render_todos(date_text, message))
        elif parsed.path == "/im-unread":
            self.send_html(render_im_unread(date_text, message))
        elif parsed.path == "/pdca-vps":
            self.send_html(render_pdca_vps(date_text, message))
        elif parsed.path == "/meeting-center" or parsed.path.startswith("/meeting-center/"):
            self.serve_meeting_center(parsed.path, date_text)
        elif parsed.path == "/agent-soul":
            agent_key = query.get("agent", [""])[0]
            self.send_html(render_agent_soul(date_text, agent_key, message))
        elif parsed.path == "/agent-edit":
            agent_key = query.get("agent", [""])[0]
            active_file = query.get("file", ["SOUL.md"])[0]
            self.send_html(render_agent_edit(date_text, agent_key, active_file, message))
        elif parsed.path == "/logistics":
            self.send_html(render_logistics(date_text, message))
        elif parsed.path == "/dashboard":
            start_date = query.get("start", [""])[0]
            end_date = query.get("end", [""])[0]
            if start_date and end_date:
                date_text = end_date
                code, stdout, stderr = run_pdca(date_text, push=False, start_date=start_date)
                if code != 0:
                    self.redirect("/", date_text, f"区间看板生成失败：{stderr or stdout}"[:300])
                    return
            dashboard = output_dir(date_text) / "dashboard.html"
            if not dashboard.exists():
                code, stdout, stderr = run_pdca(date_text, push=False)
                if code != 0:
                    self.redirect("/", date_text, f"当天看板生成失败：{stderr or stdout}"[:300])
                    return
            if dashboard.exists():
                serve_dashboard_html(self, dashboard, date_text)
            else:
                self.redirect("/", date_text, "这个日期还没有看板，请先运行当天 PDCA。")
        elif parsed.path == "/dashboard-theme.css":
            if DASHBOARD_THEME_CSS.is_file():
                self.send_bytes(DASHBOARD_THEME_CSS.read_bytes(), "text/css; charset=utf-8")
            else:
                self.send_response(404)
                self.end_headers()
        elif parsed.path == "/workbench-cockpit-shell.css":
            if COCKPIT_SHELL_CSS.is_file():
                self.send_bytes(COCKPIT_SHELL_CSS.read_bytes(), "text/css; charset=utf-8")
            else:
                self.send_response(404)
                self.end_headers()
        elif parsed.path == "/open":
            target = query.get("target", [""])[0]
            self.redirect("/", date_text, open_target(date_text, target))
        elif parsed.path == "/open-path":
            path_text = query.get("path", [""])[0]
            self.redirect("/", date_text, open_path(path_text))
        elif parsed.path == "/view-path":
            path_text = query.get("path", [""])[0]
            back_url = query.get("from", [""])[0]
            self.send_html(render_view_path(date_text, path_text, back_url))
        elif parsed.path == "/customer-mgmt":
            err = ensure_customer_server()
            if err:
                self.redirect("/", date_text, err)
            else:
                self.send_html(render_customer_mgmt_frame(date_text))
        elif parsed.path == "/open-im-channel":
            channel_id = query.get("channel_id", [""])[0]
            self.redirect("/im-unread", date_text, open_im_channel(channel_id))
        elif parsed.path == "/walkin-cockpit" or parsed.path.startswith("/walkin-cockpit/"):
            self.serve_walkin_cockpit(parsed.path, date_text)
        elif parsed.path == "/online-cockpit" or parsed.path.startswith("/online-cockpit/"):
            self.serve_online_cockpit(parsed.path, date_text)
        elif parsed.path == "/api/walkin":
            self.send_walkin_api(query, date_text)
        elif parsed.path == "/api/online-channel":
            self.send_online_channel_api(date_text)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        try:
            self._do_POST()
        except Exception as exc:
            self.send_error_page(exc)

    def _do_POST(self):
        parsed = urlparse(self.path)
        date_text = self.date_from_query(parsed.query)
        if parsed.path == "/api/agent/process-suggestion":
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                payload = {}
            self.send_json({"ok": True, "message": "建议已记录", "id": payload.get("id")})
            return
        if parsed.path == "/api/meeting-center/dispatch":
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                self.send_json({"ok": False, "error": "请求体不是 JSON"}, status=400)
                return
            result = api_meeting_center_dispatch(payload, (payload.get("date") or date_text))
            self.send_json(result)
            return
        if parsed.path == "/agent-skill":
            query = parse_qs(parsed.query)
            agent_key = query.get("agent", [""])[0]
            try:
                fields = self.read_multipart()
                uploaded = fields["skill"] if "skill" in fields else None
                if uploaded is None or not getattr(uploaded, "filename", ""):
                    raise ValueError("没有收到 skill 文件。")
                target = install_skill_to_agent(agent_key, uploaded.filename, uploaded.file.read())
                self.send_response(303)
                self.send_header("Location", f"/agent-edit?{urlencode({'date': date_text, 'agent': agent_key, 'message': f'Skill 已安装：{target}'})}")
                self.end_headers()
            except Exception as exc:
                self.send_response(303)
                self.send_header("Location", f"/agent-edit?{urlencode({'date': date_text, 'agent': agent_key, 'message': f'Skill 安装失败：{exc}'})}")
                self.end_headers()
            return
        form = self.read_form()
        if parsed.path == "/run":
            code, stdout, stderr = run_pdca(date_text, push=False)
            message = "运行成功，结果已刷新。" if code == 0 else f"运行失败：{stderr or stdout}"
            self.redirect("/", date_text, message[:300])
        elif parsed.path == "/hermes-chat":
            query_text = (form.get("query", [""])[0] or "").strip()
            result = run_hermes_chat(query_text)
            self.send_html(render_home(date_text, hermes_result=result))
        elif parsed.path == "/pdca-task":
            task_date = (form.get("date", [date_text])[0] or date_text)
            try:
                message = save_pdca_task_update(form)
            except Exception as exc:
                message = f"保存失败：{exc}"
            self.redirect("/pdca-vps", task_date, message[:300])
        elif parsed.path == "/agent-soul":
            agent_key = parse_qs(parsed.query).get("agent", [""])[0]
            agent = agent_by_key(agent_key)
            if not agent:
                self.redirect("/", date_text, "未知 Agent。")
                return
            write_text(ensure_agent_soul(agent), form.get("content", [""])[0])
            self.send_response(303)
            self.send_header("Location", f"/agent-soul?{urlencode({'date': date_text, 'agent': agent_key, 'message': 'SOUL.md 已保存。'})}")
            self.end_headers()
        elif parsed.path == "/agent-core-file":
            query = parse_qs(parsed.query)
            agent_key = query.get("agent", [""])[0]
            active_file = query.get("file", ["SOUL.md"])[0]
            agent = agent_by_key(agent_key)
            if not agent or active_file not in AGENT_CORE_FILES:
                self.redirect("/", date_text, "未知 Agent 或文件。")
                return
            write_text(ensure_agent_core_file(agent, active_file), form.get("content", [""])[0])
            self.send_response(303)
            self.send_header("Location", f"/agent-edit?{urlencode({'date': date_text, 'agent': agent_key, 'file': active_file, 'message': f'{active_file} 已保存。'})}")
            self.end_headers()
        elif parsed.path == "/questionnaire":
            save_questionnaire(date_text, form)
            self.redirect("/questionnaire", date_text, "问卷已保存。")
        elif parsed.path == "/todos":
            append_todo(date_text, form)
            self.redirect("/todos", date_text, "代办已保存。")
        elif parsed.path == "/logistics":
            append_logistics(date_text, form)
            self.redirect("/logistics", date_text, "物流单号已保存。")
        else:
            self.send_response(404)
            self.end_headers()


def main():
    if os.environ.get("PDCA_ENABLE_LEGACY_HTTP", "0") != "1":
        print(
            "Legacy HTTP server is disabled. "
            "Use the FastAPI workbench (pdca-workbench) or set "
            "PDCA_ENABLE_LEGACY_HTTP=1 only for local development."
        )
        return
    server = ThreadingHTTPServer((HOST, PORT), WorkbenchHandler)
    url = f"http://{HOST}:{PORT}/"
    print(f"数据岗位 PDCA 工作台已启动：{url}")
    threading.Thread(target=warm_identity_cache, daemon=True).start()
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


