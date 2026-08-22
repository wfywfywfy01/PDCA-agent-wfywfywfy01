# -*- coding: utf-8 -*-
"""经销商 PDCA 驾驶舱 v1 — 静态前端 + snapshot API。"""
import json
import subprocess
import sys
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Timer
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
SNAPSHOT_DIR = ROOT / "snapshots"
BUILD_SCRIPT = ROOT / "jobs" / "build_dealer_snapshot.py"
HOST = "127.0.0.1"
PORT = 8766


def read_snapshot(date_text=None):
    if date_text:
        path = SNAPSHOT_DIR / f"dealer-{date_text}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8")), "snapshot", str(path.name)
    latest = SNAPSHOT_DIR / "dealer-latest.json"
    if latest.exists():
        return json.loads(latest.read_text(encoding="utf-8")), "snapshot", "dealer-latest.json"
    return None, "missing", ""


def rebuild_snapshot(date_text):
    cmd = [sys.executable, str(BUILD_SCRIPT), "--date", date_text]
    completed = subprocess.run(cmd, cwd=str(ROOT.parent), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return completed.returncode == 0, (completed.stdout or "") + (completed.stderr or "")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, data, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/snapshot":
            qs = parse_qs(parsed.query)
            date_text = (qs.get("date") or [None])[0]
            data, kind, fname = read_snapshot(date_text)
            if data is None:
                self.send_json({"ok": False, "error": "snapshot 不存在，请先 POST /api/rebuild"}, 404)
                return
            self.send_json({"ok": True, "file": fname, "data": data})
            return
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "port": PORT, "time": datetime.now().isoformat()})
            return

        file_map = {
            "/": WEB / "index.html",
            "/index.html": WEB / "index.html",
            "/app.js": WEB / "app.js",
            "/styles.css": WEB / "styles.css",
        }
        path = file_map.get(parsed.path)
        if not path or not path.exists():
            self.send_response(404)
            self.end_headers()
            return
        suffix = path.suffix.lower()
        ctype = "text/html; charset=utf-8"
        if suffix == ".js":
            ctype = "application/javascript; charset=utf-8"
        elif suffix == ".css":
            ctype = "text/css; charset=utf-8"
        self.send_bytes(path.read_bytes(), ctype)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/rebuild":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else "{}"
        try:
            body = json.loads(raw or "{}")
        except json.JSONDecodeError:
            body = {}
        date_text = body.get("date") or datetime.now().strftime("%Y-%m-%d")
        ok, log = rebuild_snapshot(date_text)
        if not ok:
            self.send_json({"ok": False, "error": log[-500:]}, 500)
            return
        data, _, fname = read_snapshot(date_text)
        self.send_json({"ok": True, "file": fname, "data": data})


def main():
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    latest = SNAPSHOT_DIR / "dealer-latest.json"
    if not latest.exists():
        rebuild_snapshot("2026-05-26")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}/"
    print(f"经销商 PDCA 驾驶舱 v1: {url}")
    Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
