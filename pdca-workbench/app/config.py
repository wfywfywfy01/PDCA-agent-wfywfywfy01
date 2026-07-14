# -*- coding: utf-8 -*-
"""应用配置：环境变量与路径解析。"""
from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

APP_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(APP_ROOT / ".env")
DEFAULT_MVP = APP_ROOT.parent / "data_platform" / "data_role_pdca_mvp"
DEFAULT_REPO = APP_ROOT.parent


class Settings:
    """运行时配置。"""

    def __init__(self) -> None:
        self.app_root = APP_ROOT
        self.host = os.environ.get("PDCA_HOST", "0.0.0.0")
        self.port = int(os.environ.get("PDCA_WORKBENCH_PORT", "8767"))
        self.secret_key = os.environ.get(
            "PDCA_SECRET_KEY",
            "pdca-dev-secret-change-in-production",
        )
        self.algorithm = "HS256"
        self.access_token_expire_minutes = int(
            os.environ.get("PDCA_TOKEN_EXPIRE_MINUTES", "480"),
        )
        mvp = os.environ.get("PDCA_MVP_ROOT", str(DEFAULT_MVP))
        repo = os.environ.get("PDCA_REPO_ROOT", str(DEFAULT_REPO))
        self.mvp_root = Path(mvp).resolve()
        self.repo_root = Path(repo).resolve()
        self.scripts_dir = self.mvp_root / "scripts"
        self.modules_dir = self.mvp_root / "modules"
        self.config_dir = self.mvp_root / "config"
        self.outputs_dir = self.mvp_root / "outputs"
        self.data_dir = APP_ROOT / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_url = self._resolve_database_url()
        self.vertu_command = self._resolve_vertu_command()
        self.require_vertu = os.environ.get(
            "PDCA_REQUIRE_VERTU",
            "1" if os.environ.get("PDCA_ENV", "development").strip().lower() == "production" else "0",
        ) == "1"
        self.include_demo_data = os.environ.get("PDCA_INCLUDE_DEMO_DATA", "0") == "1"
        self.max_reported_revenue_usd = float(
            os.environ.get("PDCA_MAX_REPORTED_REVENUE_USD", "5000000")
        )
        self.scheduler_enabled = os.environ.get("PDCA_SCHEDULER_ENABLED", "1") == "1"
        self.sync_cron = os.environ.get("PDCA_SYNC_CRON", "0 6 * * *")
        self.log_level = os.environ.get("PDCA_LOG_LEVEL", "INFO")
        self.environment = os.environ.get("PDCA_ENV", "development").strip().lower()
        self.workers = int(os.environ.get("PDCA_WORKERS", "2"))
        self.secure_cookies = os.environ.get("PDCA_SECURE_COOKIES", "0") == "1"
        raw_mode = os.environ.get("PDCA_AUTH_MODE", "local").strip().lower()
        if raw_mode not in ("local", "vps", "hybrid"):
            raw_mode = "local"
        self.auth_mode = raw_mode
        self.vps_login_url = os.environ.get(
            "PDCA_VPS_LOGIN_URL",
            "https://vps.vertu.cn",
        ).strip()
        # 信任反向代理注入的 X-VPS-User-* / X-Forwarded-User（多用户生产）
        self.trust_proxy_headers = os.environ.get("PDCA_TRUST_PROXY_HEADERS", "0") == "1"
        # 每次 VPS 同步是否覆盖本地 role（默认 0，保留手工调权）
        self.vps_sync_role = os.environ.get("PDCA_VPS_SYNC_ROLE", "0") == "1"
        cors = os.environ.get("PDCA_CORS_ORIGINS", "").strip()
        self.cors_origins = [o.strip() for o in cors.split(",") if o.strip()] if cors else []
        self.ssl_cert = os.environ.get("PDCA_SSL_CERT", "")
        self.ssl_key = os.environ.get("PDCA_SSL_KEY", "")
        self.pg_host = os.environ.get("PDCA_PG_HOST", "")
        self.pg_port = os.environ.get("PDCA_PG_PORT", "5432")
        self.pg_user = os.environ.get("PDCA_PG_USER", "")
        self.pg_password = os.environ.get("PDCA_PG_PASSWORD", "")
        self.pg_database = os.environ.get("PDCA_PG_DATABASE", "")
        self.pg_dump_command = os.environ.get("PDCA_PG_DUMP_COMMAND", "").strip()
        self.bootstrap_admin_username = os.environ.get("PDCA_BOOTSTRAP_ADMIN_USERNAME", "").strip()
        self.bootstrap_admin_password = os.environ.get("PDCA_BOOTSTRAP_ADMIN_PASSWORD", "")
        self.bootstrap_admin_display_name = os.environ.get(
            "PDCA_BOOTSTRAP_ADMIN_DISPLAY_NAME", "系统管理员"
        ).strip()

    def _resolve_vertu_command(self) -> str:
        """解析 vertu-cli 可执行文件完整路径（Windows 需 .cmd 绝对路径）。"""
        configured = os.environ.get("VERTU_COMMAND", "vertu-cli").strip()
        if Path(configured).name.lower() in {"vertu", "vertu.cmd", "vertu.ps1"}:
            configured = "vertu-cli"
        configured_path = Path(configured)
        if configured_path.exists():
            return str(configured_path.resolve())
        discovered = shutil.which(configured)
        if discovered:
            return discovered
        npm_cmd = Path.home() / "AppData" / "Roaming" / "npm" / "vertu-cli.cmd"
        if npm_cmd.exists():
            return str(npm_cmd)
        return configured

    def _resolve_database_url(self) -> str:
        """解析 PostgreSQL 连接串。"""
        url = os.environ.get("PDCA_DATABASE_URL", "").strip()
        if url:
            if url.startswith("postgresql://") and "+psycopg2" not in url:
                return url.replace("postgresql://", "postgresql+psycopg2://", 1)
            return url
        return "postgresql+psycopg2://pdca:pdca@localhost:5432/pdca"

    @property
    def is_postgresql(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def pg_connection_info(self) -> dict[str, str]:
        """供 pg_dump 使用的连接信息。"""
        if self.pg_host and self.pg_user and self.pg_database:
            return {
                "host": self.pg_host,
                "port": self.pg_port,
                "user": self.pg_user,
                "password": self.pg_password,
                "database": self.pg_database,
            }
        parsed = urlparse(self.database_url.replace("+psycopg2", ""))
        return {
            "host": parsed.hostname or "localhost",
            "port": str(parsed.port or 5432),
            "user": parsed.username or "",
            "password": parsed.password or "",
            "database": (parsed.path or "/pdca").lstrip("/"),
        }

    @property
    def home_dashboard_dir(self) -> Path:
        return self._module_dir("home_dashboard")

    @property
    def walkin_cockpit_dir(self) -> Path:
        return self._module_dir("walkin_cockpit")

    @property
    def meeting_center_dir(self) -> Path:
        return self._module_dir("meeting_center")

    @property
    def logistics_center_dir(self) -> Path:
        return self._module_dir("logistics_center")

    @property
    def onboarding_center_dir(self) -> Path:
        return self._module_dir("onboarding_center")

    @property
    def signalseller_center_dir(self) -> Path:
        return self._module_dir("signalseller_center")

    def _module_dir(self, name: str) -> Path:
        """解析模块目录，并兼容整仓部署时误配的 MVP 根目录。"""
        primary = self.modules_dir / name
        if (primary / "index.html").is_file():
            return primary

        candidates = (
            self.repo_root / "data_platform" / "data_role_pdca_mvp" / "modules" / name,
            DEFAULT_MVP / "modules" / name,
        )
        for candidate in candidates:
            if candidate != primary and (candidate / "index.html").is_file():
                return candidate.resolve()
        return primary

    @property
    def team_dir(self) -> Path:
        return self.repo_root / "teams" / "yang-jingjing"

    @property
    def frontend_dir(self) -> Path:
        return APP_ROOT / "frontend"


@lru_cache
def get_settings() -> Settings:
    """获取单例配置。"""
    return Settings()
