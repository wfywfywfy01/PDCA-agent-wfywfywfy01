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
        self.revenue_review_threshold_usd = float(
            os.environ.get("PDCA_REVENUE_REVIEW_THRESHOLD_USD", "1000000")
        )
        self.scheduler_enabled = os.environ.get("PDCA_SCHEDULER_ENABLED", "1") == "1"
        # 每日经营日报推送（08:30，服务器自跑）；走 VPS IM 机器人通道
        self.daily_report_enabled = os.environ.get("PDCA_DAILY_REPORT_ENABLED", "1") == "1"
        self.sync_cron = os.environ.get("PDCA_SYNC_CRON", "0 6 * * *")
        # 待办催办（提醒跟进）：VPS IM 私聊本人。
        # PDCA_TODO_REMIND_TIMES 为逗号分隔的 HH:MM 列表，默认上午/下午各一轮。
        self.todo_remind_enabled = os.environ.get("PDCA_TODO_REMIND_ENABLED", "1") == "1"
        self.todo_remind_times = [
            item.strip()
            for item in os.environ.get("PDCA_TODO_REMIND_TIMES", "09:30,16:30").split(",")
            if item.strip()
        ]
        self.workbench_base_url = os.environ.get(
            "PDCA_WORKBENCH_URL",
            "https://pdca-workbench-teams.vertu.cn/app/",
        ).strip().rstrip("/") + "/"
        # Vemory 会议待办（事实源）：OpenAPI 地址、查询人员名单、催办宽限。
        # 名单为 JSON 字符串：[{"name","vemoryUserId","vpsUserId"}, ...]；
        # 密钥走环境变量 VEMORY_OPENAPI_KEY（X-API-Key），不落入配置对象。
        self.vemory_openapi_url = os.environ.get(
            "PDCA_VEMORY_OPENAPI_URL",
            "https://vemory-meet.vemory.io",
        ).strip().rstrip("/")
        self.vemory_todo_users_json = os.environ.get("PDCA_VEMORY_TODO_USERS", "").strip()
        # Vemory 无截止待办：会议满该小时数后才进入催办（对齐 todo-tracker 语义）。
        self.todo_remind_grace_hours = float(
            os.environ.get("PDCA_TODO_REMIND_GRACE_HOURS", "48")
        )
        self.log_level = os.environ.get("PDCA_LOG_LEVEL", "INFO")
        self.environment = os.environ.get("PDCA_ENV", "development").strip().lower()
        acquisition_url = os.environ.get(
            "PDCA_ACQUISITION_URL",
            "https://global-autoleads.vertu.cn",
        ).strip().rstrip("/")
        parsed_acquisition = urlparse(acquisition_url)
        valid_acquisition_url = bool(
            parsed_acquisition.scheme in ({"https"} if self.environment == "production" else {"http", "https"})
            and parsed_acquisition.netloc
        )
        self.acquisition_url = acquisition_url if valid_acquisition_url else ""
        self.acquisition_enabled = (
            os.environ.get("PDCA_ACQUISITION_ENABLED", "1").strip() == "1"
            and bool(self.acquisition_url)
        )
        self.acquisition_frame_origin = (
            f"{parsed_acquisition.scheme}://{parsed_acquisition.netloc}"
            if valid_acquisition_url else ""
        )
        # 允许把本站嵌进 iframe 的来源。未设时默认 admin.vertu.cn；显式空字符串则只允许同源。
        raw_frame_ancestors = os.environ.get("PDCA_FRAME_ANCESTORS")
        if raw_frame_ancestors is None:
            raw_frame_ancestors = "https://admin.vertu.cn"
        ancestor_schemes = {"https"} if self.environment == "production" else {"http", "https"}
        self.frame_ancestors: list[str] = []
        for item in raw_frame_ancestors.split(","):
            parsed = urlparse(item.strip().rstrip("/"))
            if parsed.scheme in ancestor_schemes and parsed.netloc:
                origin = f"{parsed.scheme}://{parsed.netloc}"
                if origin not in self.frame_ancestors:
                    self.frame_ancestors.append(origin)
        self.workers = int(os.environ.get("PDCA_WORKERS", "2"))
        self.secure_cookies = os.environ.get("PDCA_SECURE_COOKIES", "0") == "1"
        raw_mode = os.environ.get("PDCA_AUTH_MODE", "local").strip().lower()
        if raw_mode not in ("local", "vps", "hybrid"):
            raw_mode = "local"
        self.auth_mode = raw_mode
        # 部署形态：workbench（内部工作台，dealer 禁止登录）/ walkin（门店五件套门户）
        raw_portal = os.environ.get("PDCA_PORTAL_MODE", "workbench").strip().lower()
        self.portal_mode = raw_portal if raw_portal in ("workbench", "walkin") else "workbench"
        self.vps_login_url = os.environ.get(
            "PDCA_VPS_LOGIN_URL",
            "https://vps.vertu.cn",
        ).strip()
        # 信任反向代理注入的 X-VPS-User-* / X-Forwarded-User（多用户生产）
        self.trust_proxy_headers = os.environ.get("PDCA_TRUST_PROXY_HEADERS", "0") == "1"
        self.trusted_proxy_ips = {
            item.strip()
            for item in os.environ.get("PDCA_TRUSTED_PROXY_IPS", "").split(",")
            if item.strip()
        }
        self.trust_proxy_role_header = (
            os.environ.get("PDCA_TRUST_PROXY_ROLE_HEADER", "0") == "1"
        )
        self.allow_sqlite_fallback = (
            os.environ.get("PDCA_ALLOW_SQLITE_FALLBACK", "0") == "1"
        )
        # 每次 VPS 同步是否覆盖本地 role（默认 0，保留手工调权）
        self.vps_sync_role = os.environ.get("PDCA_VPS_SYNC_ROLE", "0") == "1"
        # 精简部署（如五件套录入独立容器）没有经营首页数据时，把 "/" 重定向到指定路径，
        # 而不是显示"功能不可用"兜底页。留空则保持原有的经营首页行为。
        self.home_redirect = os.environ.get("PDCA_HOME_REDIRECT", "").strip()
        cors = os.environ.get("PDCA_CORS_ORIGINS", "").strip()
        self.cors_origins = [o.strip() for o in cors.split(",") if o.strip()] if cors else []
        self.odoo_sso_secret = os.environ.get("PDCA_ODOO_SSO_SECRET", "").strip()
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
        self.using_default_database_url = not bool(url)
        if url:
            if url.startswith("postgresql://") and "+psycopg2" not in url:
                return url.replace("postgresql://", "postgresql+psycopg2://", 1)
            return url
        # 生产环境默认弱口令连接串在 bootstrap_database() 中拦截。

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

    @property
    def spa_dist_dir(self) -> Path:
        """Vue3 SPA 构建产物目录（P1）。

        优先级：PDCA_SPA_DIST 环境变量 > 镜像内 pdca-workbench/spa-dist
        > 仓库 apps/web/dist（本地开发）。
        """
        configured = os.environ.get("PDCA_SPA_DIST", "").strip()
        if configured:
            return Path(configured).resolve()
        in_image = APP_ROOT / "spa-dist"
        if in_image.is_dir():
            return in_image
        return APP_ROOT.parent / "apps" / "web" / "dist"


@lru_cache
def get_settings() -> Settings:
    """获取单例配置。"""
    return Settings()
