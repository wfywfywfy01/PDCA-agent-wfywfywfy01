# -*- coding: utf-8 -*-
"""
工作台数据解析：VPS(vertu CLI) > Excel 固化 JSON > mock。

供 pdca_workbench /api/walkin 与 sync_workbench_data 使用。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
REPO_ROOT = WORKSPACE.parents[1]
DATA_SOURCES = WORKSPACE / "config" / "data_sources.json"
DATA_RAW = REPO_ROOT / "data_raw"
WALKIN_DATA = WORKSPACE / "modules" / "walkin_cockpit" / "data"
BUILD_WALKIN = WORKSPACE / "scripts" / "build_walkin_bundle.py"
VN_METRICS = WALKIN_DATA / "vietnam_store_metrics.json"
VN_COLLECT = WALKIN_DATA / "vn_data_collect_reference.json"
DEFAULT_VN_XLSX = Path(r"c:\Users\frank\Desktop\越南门店数据.xlsx")
DEFAULT_COLLECT_XLSX = Path(r"c:\Users\frank\Desktop\Data collecet(5).xlsx")
DEALERS_CFG_JSON = WORKSPACE / "config" / "dealers.json"
ONLINE_CHANNEL_JSON = WALKIN_DATA / "online_channel_reference.json"
REGION_ORDER_DEFAULT = ["中东", "欧洲", "南亚", "东南亚", "中亚"]
TIER_OKR_WAN = {"S": 120.0, "A": 65.0, "B": 35.0, "C": 28.0}
DEFAULT_OKR_WAN = 120.0


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None


def load_data_sources() -> dict:
    payload = _read_json(DATA_SOURCES)
    return payload if isinstance(payload, dict) else {}


def resolve_vps_sales_json(date_text: str) -> tuple[Path | None, str]:
    """按检查日匹配 data_raw 下 VPS 经销商业绩 JSON。"""
    cfg = load_data_sources()
    configured = (cfg.get("sales_json") or "").strip()
    if configured:
        p = Path(configured)
        if p.is_file():
            return p, "config/data_sources.json"

    if not DATA_RAW.is_dir():
        return None, ""

    ym = date_text[:7] if date_text else ""
    candidates = sorted(
        DATA_RAW.glob(f"dealer_sales_month_to_date_*{date_text}*.json"),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    if not candidates and ym:
        candidates = sorted(
            DATA_RAW.glob(f"dealer_sales_month_to_date_{ym}*.json"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
    if not candidates:
        candidates = sorted(
            DATA_RAW.glob("dealer_sales_month_to_date_*.json"),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
    if candidates:
        return candidates[0], candidates[0].name
    return None, ""


def vps_performance_wan(date_text: str) -> tuple[float | None, str]:
    path, label = resolve_vps_sales_json(date_text)
    if not path:
        return None, ""
    payload = _read_json(path)
    if not payload:
        return None, label
    result = (payload.get("execution") or {}).get("result") or payload
    teams = result.get("team_summary") or []
    total = sum(float(t.get("performance") or 0) for t in teams)
    if total <= 0:
        return None, label
    return round(total / 10000, 2), label


def walkin_bundle_path(month: str) -> Path:
    return WALKIN_DATA / f"walkin-{month}.json"


def ensure_walkin_bundle(month: str) -> Path | None:
    out = walkin_bundle_path(month)
    if out.is_file():
        return out
    if not BUILD_WALKIN.is_file():
        return None
    try:
        subprocess.run(
            [sys.executable, str(BUILD_WALKIN), "--month", month],
            cwd=str(WORKSPACE),
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None
    return out if out.is_file() else None


def excel_reference_flags() -> list[str]:
    flags = []
    if VN_METRICS.is_file():
        flags.append("excel_vietnam_store")
    if VN_COLLECT.is_file():
        flags.append("excel_data_collect")
    return flags


def format_source_detail(sources: list[str], month: str, date_text: str, vps_file: str) -> str:
    parts = []
    if "vps" in sources:
        parts.append(f"VPS 业绩（{vps_file or 'data_raw'}）")
    if "excel_vietnam_store" in sources or "excel_data_collect" in sources:
        parts.append("Excel 固化（越南门店数据 + Data collecet(5)）")
    if "walkin_json" in sources:
        parts.append(f"客流包 walkin-{month}.json")
    if "mock" in sources:
        parts.append("部分指标 mock")
    if not parts:
        parts.append("演示 mock")
    return "数据优先级：vertu CLI → Excel 参考 JSON → mock · " + " · ".join(parts) + f" · 检查日 {date_text}"


def build_walkin_api_payload(month: str, date_text: str) -> dict:
    """
    @param month YYYY-MM
    @param date_text YYYY-MM-DD
    """
    sources: list[str] = []
    excel_flags = excel_reference_flags()
    sources.extend(excel_flags)

    path = ensure_walkin_bundle(month) or walkin_bundle_path(month)
    bundle = _read_json(path) if path and path.is_file() else None

    vps_wan, vps_file = vps_performance_wan(date_text)
    if vps_wan is not None:
        sources.insert(0, "vps")

    if bundle:
        if "walkin_json" not in sources:
            sources.append("walkin_json")
    else:
        sources.append("mock")
        bundle = {
            "meta": {"month": month, "periodLabel": month, "storeCount": 0},
            "stores": [],
            "staff": [],
        }

    meta = bundle.setdefault("meta", {})
    meta["dataSources"] = sources
    meta["dataSourcePriority"] = ["vps", "excel_vietnam_store", "excel_data_collect", "walkin_json", "mock"]
    meta["dataSourceDetail"] = format_source_detail(sources, month, date_text, vps_file)
    if vps_wan is not None:
        meta["vpsMonthPerformanceWan"] = vps_wan
    meta["generatedAt"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    meta["checkDate"] = date_text
    return bundle


def _vps_sales_result(date_text: str) -> tuple[dict | None, str]:
    path, label = resolve_vps_sales_json(date_text)
    if not path:
        return None, label
    payload = _read_json(path)
    if not payload:
        return None, label
    result = (payload.get("execution") or {}).get("result") or payload
    if not isinstance(result, dict):
        return None, label
    return result, label


def norm_dealer_name(value: str) -> str:
    """与 data_role_pdca_daily.dashboard_store_data 同名口径。"""
    return re.sub(r"[\s\-'\"“”\.，,()（）]+", "", str(value or "")).upper()


def load_dealers_config() -> list[dict]:
    payload = _read_json(DEALERS_CFG_JSON)
    if not isinstance(payload, dict):
        return []
    dealers = payload.get("dealers") or []
    return dealers if isinstance(dealers, list) else []


def vps_customer_perf_map(date_text: str) -> dict[str, dict]:
    result, _ = _vps_sales_result(date_text)
    perf_map: dict[str, dict] = {}
    if not result:
        return perf_map
    for row in result.get("customer_summary") or []:
        key = norm_dealer_name(row.get("partner_name"))
        if key:
            perf_map[key] = row
    return perf_map


def dealer_display_label(dealer: dict) -> str:
    name = (dealer.get("name") or "").strip()
    nick = (dealer.get("nickname") or "").strip()
    if nick:
        return f"{name}（{nick}）"
    return name or "未命名门店"


def okr_target_wan(dealer: dict) -> float:
    level = (dealer.get("level") or "").strip().upper()
    if level in TIER_OKR_WAN:
        return TIER_OKR_WAN[level]
    if level and level[0] in TIER_OKR_WAN:
        return TIER_OKR_WAN[level[0]]
    return DEFAULT_OKR_WAN


def build_dealer_region_tree(dealers: list[dict], perf_map: dict[str, dict]) -> list[dict]:
    """与数据看板 DEALER_REGION 结构一致，供大区门店分析展示。"""
    region_map: dict[str, dict[str, list]] = {}
    for dealer in dealers:
        region = dealer.get("region") or "其他"
        country = dealer.get("country") or "未分组"
        row = perf_map.get(norm_dealer_name(dealer.get("name")), {})
        perf = round(float(row.get("performance") or 0) / 10000, 2)
        qty = int(float(row.get("quantity") or 0))
        entry = {
            "name": dealer.get("name", ""),
            "nickname": dealer.get("nickname", ""),
            "salesperson": dealer.get("salesperson", ""),
            "perf": perf,
            "qty": qty,
            "pickupAmount": perf if row else None,
            "pickupQty": qty if row else None,
            "vpsUsage": None,
            "inboundQty": None,
            "activationQty": None,
            "walkinQty": None,
            "orderPerformance": perf if row else None,
            "inTransitPerformance": None,
        }
        region_map.setdefault(region, {}).setdefault(country, []).append(entry)

    dealer_region = []
    for region, countries in region_map.items():
        country_list = []
        region_perf = 0.0
        region_qty = 0
        for country, entries in countries.items():
            entries = sorted(entries, key=lambda item: item.get("perf", 0), reverse=True)
            country_perf = round(sum(item.get("perf", 0) for item in entries), 2)
            country_qty = sum(item.get("qty", 0) for item in entries)
            region_perf += country_perf
            region_qty += country_qty
            country_list.append(
                {
                    "country": country,
                    "perf": country_perf,
                    "qty": country_qty,
                    "dealers": entries,
                }
            )
        dealer_region.append(
            {
                "region": region,
                "perf": round(region_perf, 2),
                "qty": region_qty,
                "countries": country_list,
            }
        )
    dealer_region.sort(key=lambda item: item.get("perf", 0), reverse=True)
    return dealer_region


def load_vietnam_channel_leads(month: str) -> dict | None:
    """各渠道线索：来自越南门店 Excel（TK / Ins / Facebook 列汇总）。"""
    vn = _read_json(VN_METRICS)
    if not isinstance(vn, dict):
        return None
    by_month = vn.get("channelByMonth") or {}
    if not by_month:
        return None

    def _has_leads(ch: dict) -> bool:
        return bool(ch.get("shortVideo") or ch.get("live") or ch.get("other"))

    channel = by_month.get(month)
    if isinstance(channel, dict) and _has_leads(channel):
        return channel
    for ym in sorted(by_month.keys(), reverse=True):
        alt = by_month[ym]
        if isinstance(alt, dict) and _has_leads(alt):
            merged = dict(alt)
            merged["displayMonth"] = ym
            merged["requestedMonth"] = month
            return merged
    if isinstance(channel, dict):
        return channel
    return None


def _mock_channel_leads(sal_wan: float, seed: str) -> tuple[int, int, int]:
    """渠道线索条数：VPS 无渠道明细时用销售额稳定派生（演示）。"""
    sal_wan = max(0.0, float(sal_wan or 0))
    if sal_wan <= 0:
        return 0, 0, 0
    h = abs(hash(seed)) % 10000
    ls = max(0, int(sal_wan * (6 + h % 5)))
    ll = max(0, int(sal_wan * (2 + (h >> 3) % 4)))
    lo = max(0, int(sal_wan * (1 + (h >> 5) % 3)))
    return ls, ll, lo


def build_online_channel_payload(date_text: str) -> dict:
    """
    全量门店来自 config/dealers.json；真实销售/件数来自 vertu 经销商业绩 customer_summary。
    与数据看板「大区门店分析」同源。
    """
    month = (date_text or datetime.now().strftime("%Y-%m-%d"))[:7]
    dealers = load_dealers_config()
    _, vps_file = _vps_sales_result(date_text)
    perf_map = vps_customer_perf_map(date_text)
    stores: list[dict] = []
    okr_month: dict[str, float] = {}

    for dealer in dealers:
        row = perf_map.get(norm_dealer_name(dealer.get("name")), {})
        sal_wan = round(float(row.get("performance") or 0) / 10000, 2)
        qty = int(float(row.get("quantity") or 0))
        nm = dealer_display_label(dealer)
        rg = dealer.get("region") or "其他"
        ls, ll, lo = _mock_channel_leads(sal_wan, f"{dealer.get('name')}|{month}")
        stores.append(
            {
                "rg": rg,
                "nm": nm,
                "mgr": dealer.get("salesperson") or "",
                "hk": 0,
                "Ls": ls,
                "Ll": ll,
                "Lo": lo,
                "sal": sal_wan,
                "qty": qty,
                "partner": dealer.get("name") or "",
                "country": dealer.get("country") or "",
            }
        )
        okr_month[nm] = okr_target_wan(dealer)

    order_idx = {name: idx for idx, name in enumerate(REGION_ORDER_DEFAULT)}
    stores.sort(
        key=lambda item: (
            order_idx.get(item["rg"], 99),
            item.get("country") or "",
            -float(item.get("sal") or 0),
            item["nm"],
        )
    )
    region_order = [r for r in REGION_ORDER_DEFAULT if any(s["rg"] == r for s in stores)]
    dealer_region = build_dealer_region_tree(dealers, perf_map)
    channel_leads = load_vietnam_channel_leads(month)

    return {
        "note": "门店清单=config/dealers.json；真实销售/提货件数=vertu odoo data sandbox customer_summary。",
        "source": "vps",
        "vpsFile": vps_file,
        "checkDate": date_text,
        "storeCount": len(stores),
        "estRatio": 4,
        "channelLabels": (channel_leads or {}).get("labels") or ["短视频", "直播", "其他"],
        "channelLeads": channel_leads,
        "regionOrder": region_order,
        "dealerRegion": dealer_region,
        "okrByMonth": {month: okr_month},
        "stores": stores,
        "scaleByMonth": {month: 1},
    }


def write_online_channel_reference(date_text: str) -> Path:
    payload = build_online_channel_payload(date_text)
    ONLINE_CHANNEL_JSON.parent.mkdir(parents=True, exist_ok=True)
    ONLINE_CHANNEL_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return ONLINE_CHANNEL_JSON
