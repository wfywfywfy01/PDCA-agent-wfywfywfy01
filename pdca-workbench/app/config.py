# -*- coding: utf-8 -*-
"""应用配置：环境变量与路径解析。"""
from __future__ import annotations

import os
import json
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
        # Vemory 全量拉取（经销商部门会议列表/详情/音频直链 API）
        self.vemory_dept_ids = os.environ.get(
            "PDCA_VEMORY_DEPT_IDS", "2231,2227,2223,2230"
        ).strip()
        try:
            self.vemory_page_size = int(os.environ.get("PDCA_VEMORY_PAGE_SIZE", "50"))
        except ValueError:
            self.vemory_page_size = 50
        try:
            self.vemory_max_pages = int(os.environ.get("PDCA_VEMORY_MAX_PAGES", "20"))
        except ValueError:
            self.vemory_max_pages = 20
        try:
            self.vemory_audio_cache_ttl = int(
                os.environ.get("PDCA_VEMORY_AUDIO_CACHE_TTL", "1800")
            )
        except ValueError:
            self.vemory_audio_cache_ttl = 1800
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
        # 海外日报群总结（默认 08:00，前 24 小时总分结构）；文案确认前默认关闭
        self.daily_digest_enabled = (
            os.environ.get("PDCA_DAILY_DIGEST_ENABLED", "0") == "1"
        )
        self.daily_digest_time = os.environ.get("PDCA_DAILY_DIGEST_TIME", "08:00").strip()
        # 督战证据日报（每天一份 HTML 落 data/exports/evidence，08:00 前生成）
        self.evidence_report_enabled = (
            os.environ.get("PDCA_EVIDENCE_REPORT_ENABLED", "1") == "1"
        )
        self.evidence_report_time = os.environ.get(
            "PDCA_EVIDENCE_REPORT_TIME", "07:30"
        ).strip()
        self.evidence_report_images = int(
            os.environ.get("PDCA_EVIDENCE_REPORT_IMAGES", "24") or 24
        )
        # 所有「早上固定输出」的 HTML（证据日报 / 三策略简报）共用这一份收件人名单
        self.mgmt_html_user_ids = [
            int(item.strip())
            for item in os.environ.get(
                "PDCA_MGMT_HTML_USER_IDS", "13365,13102,12564"
            ).split(",")
            if item.strip().isdigit()
        ]
        # 证据日报私聊收件人（默认不发；.env 里配 user_id）
        self.evidence_report_user_ids = [
            int(item.strip())
            for item in os.environ.get("PDCA_EVIDENCE_REPORT_USER_IDS", "").split(",")
            if item.strip().isdigit()
        ]
        # 证据日报是否也发某个群（默认空 = 不发群）
        self.evidence_report_channel_id = os.environ.get(
            "PDCA_EVIDENCE_REPORT_CHANNEL_ID", ""
        ).strip()
        # 海外渠道督战官：独立机器人，按群时区推 10:00/15:00/20:00。
        self.duzhan_enabled = os.environ.get("PDCA_DUZHAN_ENABLED", "0") == "1"
        self.duzhan_bot_app_id = os.environ.get("PDCA_DUZHAN_BOT_APP_ID", "").strip()
        self.duzhan_bot_app_secret = os.environ.get(
            "PDCA_DUZHAN_BOT_APP_SECRET", ""
        ).strip()
        self.duzhan_times = [
            item.strip()
            for item in os.environ.get("PDCA_DUZHAN_TIMES", "10:00,15:00,20:00").split(",")
            if item.strip()
        ]
        # 10/15/20 是推送整点；提前这么多分钟跑采集组表。
        try:
            lead = int(os.environ.get("PDCA_DUZHAN_LEAD_MINUTES", "15"))
        except ValueError:
            lead = 15
        self.duzhan_lead_minutes = min(60, max(5, lead))
        # @海外渠道督战官 才回；默认跟督战开关走，1 分钟轮询。
        # 三档只出总结性内容（明细走每天 08:00 的证据 HTML）；=0 回到长版
        self.duzhan_compact = os.environ.get("PDCA_DUZHAN_COMPACT", "1") == "1"
        self.duzhan_reply_enabled = os.environ.get(
            "PDCA_DUZHAN_REPLY_ENABLED",
            "1" if self.duzhan_enabled else "0",
        ) == "1"
        # C转B 跟进群：与达标群同结构（10:00 定任务 / 15:00 追变化 / 20:00 验兑现）。
        self.ctob_enabled = os.environ.get(
            "PDCA_CTOB_ENABLED",
            "1" if self.duzhan_enabled else "0",
        ) == "1"
        # C转B 三档同样只出总结性内容；=0 回到长版
        self.ctob_compact = os.environ.get("PDCA_CTOB_COMPACT", "1") == "1"
        self.ctob_times = [
            item.strip()
            for item in os.environ.get("PDCA_CTOB_TIMES", "10:00,15:00,20:00").split(",")
            if item.strip()
        ]
        self.aisales_mcp_url = os.environ.get(
            "PDCA_AISALES_MCP_URL",
            "https://aisales-report.vertu.cn/mcp",
        ).strip()
        self.aisales_mcp_token = os.environ.get("PDCA_AISALES_MCP_TOKEN", "").strip()
        # MTO 报价图：服务器 OCR，读完删文件。密钥只走环境变量。
        self.qwen_base_url = os.environ.get(
            "PDCA_QWEN_BASE_URL",
            "https://qwen3.vertu.cn:8443",
        ).strip()
        self.qwen_api_key = os.environ.get("PDCA_QWEN_API_KEY", "").strip()
        self.qwen_model = os.environ.get("PDCA_QWEN_MODEL", "qwen3.8-27b").strip()
        self.vemory_api_url = os.environ.get("PDCA_VEMORY_API_URL", "").strip()
        self.duzhan_agent_im_html = os.environ.get("PDCA_DUZHAN_AGENT_IM_HTML", "").strip()
        # ── 多智能体督战运行时（migrations 011；规格 docs/多智能体督战系统实施规格.md）──
        # 部署默认全部关闭/影子：模型故障与 Agent 异常绝不阻断现有三追。
        self.agent_enabled = os.environ.get("PDCA_AGENT_ENABLED", "0") == "1"
        self.agent_shadow_mode = os.environ.get("PDCA_AGENT_SHADOW_MODE", "1") == "1"
        self.agent_outbox_enabled = os.environ.get("PDCA_AGENT_OUTBOX_ENABLED", "0") == "1"
        self.agent_auto_template_push = (
            os.environ.get("PDCA_AGENT_AUTO_TEMPLATE_PUSH", "0") == "1"
        )
        self.agent_task_write = os.environ.get("PDCA_AGENT_TASK_WRITE", "0") == "1"
        self.agent_llm_draft = os.environ.get("PDCA_AGENT_LLM_DRAFT", "0") == "1"
        self.agent_healthcheck_enabled = (
            os.environ.get("PDCA_AGENT_HEALTHCHECK_ENABLED", "1") == "1"
        )
        try:
            self.agent_healthcheck_delay_minutes = int(
                os.environ.get("PDCA_AGENT_HEALTHCHECK_DELAY_MINUTES", "5")
            )
        except ValueError:
            self.agent_healthcheck_delay_minutes = 5
        # MTO 图片下载残留隔日清理（默认开启；只清理 temp/mto-ocr-* 前缀）。
        self.mto_temp_cleanup_enabled = (
            os.environ.get("PDCA_MTO_TEMP_CLEANUP_ENABLED", "1") == "1"
        )
        try:
            self.mto_temp_max_age_hours = float(
                os.environ.get("PDCA_MTO_TEMP_MAX_AGE_HOURS", "24")
            )
        except ValueError:
            self.mto_temp_max_age_hours = 24.0
        # 主 Agent（Supervisor）：供应商无关，参数由环境变量配置。
        self.supervisor_enabled = os.environ.get("PDCA_SUPERVISOR_ENABLED", "0") == "1"
        # 豆包 ASR：默认关闭；模式 fallback/verify/always 由适配层消费。
        self.asr_enabled = os.environ.get("PDCA_ASR_ENABLED", "0") == "1"
        try:
            self.asr_timeout_seconds = int(
                os.environ.get("PDCA_DOUBAO_ASR_TIMEOUT_SECONDS", "180")
            )
        except ValueError:
            self.asr_timeout_seconds = 180
        # MTO 视觉能力：复用现有 Qwen 配置。
        self.mto_vision_enabled = os.environ.get("PDCA_MTO_VISION_ENABLED", "1") == "1"
        self.sync_cron = os.environ.get("PDCA_SYNC_CRON", "0 6 * * *")
        # 待办催办（提醒跟进）：VPS IM 私聊本人。
        # PDCA_TODO_REMIND_TIMES 为逗号分隔的 HH:MM 列表，默认上午/下午各一轮。
        self.todo_remind_enabled = os.environ.get("PDCA_TODO_REMIND_ENABLED", "1") == "1"
        # 派生写任务独立关闭：生产首次启用前必须完成 dry-run 与目标核验。
        self.todo_scoring_enabled = os.environ.get("PDCA_TODO_SCORING_ENABLED", "0") == "1"
        self.todo_ledger_sync_enabled = (
            os.environ.get("PDCA_TODO_LEDGER_SYNC_ENABLED", "0") == "1"
        )
        self.todo_remind_times = [
            item.strip()
            for item in os.environ.get("PDCA_TODO_REMIND_TIMES", "09:30,16:30").split(",")
            if item.strip()
        ]
        # 催办排除名单：逗号分隔的负责人姓名；同时引擎会自动跳过
        # 当前登录 IM 身份本人（机器人不能与自己创建私聊）。
        self.todo_remind_skip_owners = [
            item.strip()
            for item in os.environ.get("PDCA_TODO_REMIND_SKIP_OWNERS", "").split(",")
            if item.strip()
        ]
        # 负责人 → VPS user_id 静态映射（JSON 字符串）：im +users 组织搜索
        # 查不到的人（如外部经销商）在这里兜底，催办/认领直接按 user_id 发送。
        # 例：PDCA_TODO_USER_ID_OVERRIDES={"徐华俊":13102,"徐豪":12665}
        raw_overrides = os.environ.get("PDCA_TODO_USER_ID_OVERRIDES", "").strip()
        overrides: dict[str, int] = {}
        if raw_overrides:
            try:
                parsed_overrides = json.loads(raw_overrides)
                if isinstance(parsed_overrides, dict):
                    for name, user_id in parsed_overrides.items():
                        if isinstance(user_id, int) and user_id > 0:
                            overrides[str(name).strip()] = user_id
            except (ValueError, TypeError):
                pass
        self.todo_user_id_overrides = overrides
        # 负责人别名 → HR 姓名（JSON 字符串，键统一小写）：日报证据与群认领
        # 按 HR 口径匹配（如 Sissi → 丁晓茜）。例：
        # PDCA_TODO_OWNER_ALIASES={"Sissi":"丁晓茜"}
        raw_aliases = os.environ.get("PDCA_TODO_OWNER_ALIASES", "").strip()
        aliases: dict[str, str] = {}
        if raw_aliases:
            try:
                parsed_aliases = json.loads(raw_aliases)
                if isinstance(parsed_aliases, dict):
                    for alias, target in parsed_aliases.items():
                        alias_name = str(alias).strip().casefold()
                        target_name = str(target).strip()
                        if alias_name and target_name:
                            aliases[alias_name] = target_name
            except (ValueError, TypeError):
                pass
        self.todo_owner_aliases = aliases
        # 催办发送通道：配置机器人 App ID 后走 im +bot-send-user（机器人身份
        # 发私聊，不再用登录账号本人身份）；留空则回退 im +send-user。
        self.todo_bot_app_id = os.environ.get("PDCA_TODO_BOT_APP_ID", "").strip()
        # 群知会（每天把待办丢到工作大群让大家认领，再进入私聊跟进）：
        # 启用开关 + 群会话 id + 发送时刻（默认 09:00，早于 09:30 私聊轮）。
        self.todo_group_notice_enabled = (
            os.environ.get("PDCA_TODO_GROUP_NOTICE_ENABLED", "0") == "1"
        )
        self.todo_group_channel_id = os.environ.get(
            "PDCA_TODO_GROUP_CHANNEL_ID", ""
        ).strip()
        self.todo_group_notice_time = os.environ.get(
            "PDCA_TODO_GROUP_NOTICE_TIME", "09:00"
        ).strip()
        # 群知会公示范围：只公示该日期及之后到期的待办（如 2026-09-01 = 只看
        # 9 月新任务，8 月积压不进公示、仍走私聊跟进）；留空 = 全部。
        self.todo_group_notice_min_date = os.environ.get(
            "PDCA_TODO_GROUP_NOTICE_MIN_DATE", ""
        ).strip()
        # 台账（VPS 智能表格）：待办闭环状态同步目标文档 ID；留空则首次同步时
        # 自动创建「PDCA 待办台账」并写回 todo_group_state。
        self.todo_ledger_doc_id = os.environ.get("PDCA_TODO_LEDGER_DOC_ID", "").strip()
        # 每日催收简报接收人（user_id，默认付汪阳 13365）：18:20 机器人发送
        # 已完成/有进度/无回复 分类 + 升级链名单。
        self.todo_report_user_id = int(
            os.environ.get("PDCA_TODO_REPORT_USER_ID", "13365")
        )
        # 每日催收简报开关（显式启用，默认关，与打分/台账一致）。
        self.todo_brief_enabled = os.environ.get("PDCA_TODO_BRIEF_ENABLED", "0") == "1"
        # 待办/项目 ↔ 个人 OKR 挂接（显式启用，默认关）。
        self.todo_okr_link_enabled = os.environ.get("PDCA_TODO_OKR_LINK_ENABLED", "0") == "1"
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
        # 督战官/会议中心：经销商一部/二部/三部/新部 hr.department id。
        self.vemory_dept_ids = os.environ.get(
            "PDCA_VEMORY_DEPT_IDS", "2231,2227,2223,2230"
        ).strip()
        try:
            self.vemory_page_size = int(os.environ.get("PDCA_VEMORY_PAGE_SIZE", "50"))
        except ValueError:
            self.vemory_page_size = 50
        try:
            self.vemory_max_pages = int(os.environ.get("PDCA_VEMORY_MAX_PAGES", "20"))
        except ValueError:
            self.vemory_max_pages = 20
        try:
            self.vemory_audio_cache_ttl = int(
                os.environ.get("PDCA_VEMORY_AUDIO_CACHE_TTL", "1800")
            )
        except ValueError:
            self.vemory_audio_cache_ttl = 1800
        # Vemory 无截止待办：会议满该小时数后才进入催办（对齐 todo-tracker 语义）。
        self.todo_remind_grace_hours = float(
            os.environ.get("PDCA_TODO_REMIND_GRACE_HOURS", "48")
        )
        self.log_level = os.environ.get("PDCA_LOG_LEVEL", "INFO")
        self.environment = os.environ.get("PDCA_ENV", "development").strip().lower()
        # 独立 logistics-track 运营台的私网地址。留空时不启用同源挂载；
        # 地址只能来自部署环境，用户请求不会参与拼接，避免形成 SSRF 代理。
        raw_logistics_admin = os.environ.get("PDCA_LOGISTICS_ADMIN_UPSTREAM", "").strip().rstrip("/")
        parsed_logistics_admin = urlparse(raw_logistics_admin)
        valid_logistics_admin = bool(
            parsed_logistics_admin.scheme in {"http", "https"}
            and parsed_logistics_admin.netloc
            and not parsed_logistics_admin.username
            and not parsed_logistics_admin.password
            and parsed_logistics_admin.query == ""
            and parsed_logistics_admin.fragment == ""
            and parsed_logistics_admin.path in {"", "/"}
        )
        self.logistics_admin_upstream = (
            raw_logistics_admin if valid_logistics_admin else ""
        )
        try:
            self.logistics_admin_timeout_seconds = float(
                os.environ.get("PDCA_LOGISTICS_ADMIN_TIMEOUT_SECONDS", "15")
            )
        except ValueError:
            self.logistics_admin_timeout_seconds = 15.0
        if self.logistics_admin_timeout_seconds <= 0:
            self.logistics_admin_timeout_seconds = 15.0
        self.knowledge_hub_enabled = os.environ.get("PDCA_KNOWLEDGE_HUB_ENABLED", "0") == "1"
        raw_knowledge_url = os.environ.get(
            "PDCA_KNOWLEDGE_HUB_URL", "http://127.0.0.1:8080"
        ).strip().rstrip("/")
        parsed_knowledge = urlparse(raw_knowledge_url)
        private_docker_knowledge_url = (
            parsed_knowledge.scheme == "http"
            and parsed_knowledge.hostname == "dealer-knowledge-api"
            and parsed_knowledge.port == 8080
        )
        knowledge_url_allowed = (
            parsed_knowledge.scheme in {"http", "https"}
            if self.environment != "production"
            else parsed_knowledge.scheme == "https" or private_docker_knowledge_url
        )
        self.knowledge_hub_url = (
            raw_knowledge_url
            if knowledge_url_allowed and parsed_knowledge.netloc
            else ""
        )
        self.knowledge_hub_token_key_file = os.environ.get(
            "PDCA_KNOWLEDGE_HUB_TOKEN_KEY_FILE", ""
        ).strip()
        self.knowledge_hub_token_secret = os.environ.get(
            "PDCA_KNOWLEDGE_HUB_TOKEN_SECRET", ""
        ).strip()
        self.knowledge_hub_timeout_seconds = float(
            os.environ.get("PDCA_KNOWLEDGE_HUB_TIMEOUT_SECONDS", "45")
        )
        try:
            team_map = json.loads(os.environ.get(
                "PDCA_KNOWLEDGE_HUB_TEAM_MAP", '{"overseas":"overseas-sales"}'
            ))
            self.knowledge_hub_team_map = {
                str(key).strip(): str(value).strip()
                for key, value in team_map.items()
                if str(key).strip() and str(value).strip()
            }
        except (TypeError, ValueError, AttributeError):
            self.knowledge_hub_team_map = {}
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
        parsed_odoo = urlparse(os.environ.get("PDCA_ODOO_BASE_URL", "https://admin.vertu.cn").strip())
        self.odoo_base_url = (
            f"{parsed_odoo.scheme}://{parsed_odoo.netloc}"
            if parsed_odoo.scheme == "https" and parsed_odoo.netloc
            else "https://admin.vertu.cn"
        )
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
