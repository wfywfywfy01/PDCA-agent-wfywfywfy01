# -*- coding: utf-8 -*-
"""督战官积木：配置 JSON 的唯一事实来源（配置页、API、运行时共用）。

一个子 Agent 的配置就是一份 JSON：{"blocks": [{"type": "...", ...}, ...]}，
blocks 是**有序数组**，渲染按顺序拼装。这里只做解析与校验，不碰网络与推送。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from loguru import logger

#: 支持的积木类型（顺序即前端面板展示顺序）
BLOCK_TYPES: tuple[str, ...] = (
    "group",
    "times",
    "people",
    "source",
    "rule",
    "strategy",
    "recipient",
    "condition",
    "style",
)

#: 每节取什么数
SOURCE_KEYS: dict[str, str] = {
    "wa_summary": "WhatsApp 日汇总（触达/回复/新增）",
    "mto_ocr": "MTO 报价图 OCR 识别",
    "im_trace": "VPS IM 留痕",
    "daily_report": "日报提交情况",
    "vemory": "Vemory 会议/纪要",
}

#: 只能出现一次的块（运行时只读第一块，多出来的会被校验挡下）
SINGLETON_BLOCKS: tuple[str, ...] = ("group", "times", "people", "style")

#: 可以出现多次的块（按顺序生效）
REPEATABLE_BLOCKS: tuple[str, ...] = ("source", "rule", "strategy", "recipient", "condition")

#: 发送前置条件
CONDITION_KEYS: dict[str, str] = {
    "workday": "普通工作日（含调休）",
    "holiday": "长假照常推送日",
    "has_data": "群内有可确认数据",
}

#: 规则块生效范围
RULE_WHEN: tuple[str, ...] = ("always", "workday", "holiday", "missing_report")

#: 规则块生成方式：确定性文案 / AI 语义生成（AI 块更慢且产生费用）
RULE_MODES: tuple[str, ...] = ("text", "ai")

RECIPIENT_KINDS: tuple[str, ...] = ("channel", "user")

LANGS: dict[str, str] = {"zh": "中文", "en": "English"}

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Block:
    """一个积木块：type + 其余字段。"""

    type: str
    data: dict

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def as_dict(self) -> dict:
        return {"type": self.type, **self.data}


def parse_blocks(raw: Any) -> list[Block]:
    """把库里的 JSON（或 dict / list）解析成积木列表；坏数据按空配置处理并记日志。"""
    payload: Any = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("督战官积木 JSON 解析失败，按空配置处理: {}", exc)
            return []
    if isinstance(payload, dict):
        items = payload.get("blocks")
    elif isinstance(payload, list):
        items = payload
    else:
        items = None
    if not isinstance(items, list):
        return []
    blocks: list[Block] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        block_type = str(item.get("type") or "").strip()
        data = {key: value for key, value in item.items() if key != "type"}
        blocks.append(Block(type=block_type, data=data))
    return blocks


def dump_blocks(blocks: Iterable[Block]) -> str:
    """积木列表 → 落库 JSON（紧凑、保留中文）。"""
    body = {"blocks": [block.as_dict() for block in blocks]}
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def blocks_dict(blocks: Iterable[Block]) -> dict:
    """积木列表 → 给前端/接口用的 dict。"""
    return {"blocks": [block.as_dict() for block in blocks]}


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def as_str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def normalize_time_slot(value: Any) -> str | None:
    """返回规范的 HH:MM；非法值返回 None。"""
    text = _text(value)
    match = _TIME_RE.fullmatch(text)
    if not match:
        return None
    return f"{int(match.group(1)):02d}:{int(text[-2:]):02d}"


def split_time_slot(value: Any) -> tuple[int, int] | None:
    """把合法 HH:MM 拆成 APScheduler 使用的时、分。"""
    slot = normalize_time_slot(value)
    if slot is None:
        return None
    hour, minute = slot.split(":", 1)
    return int(hour), int(minute)


def time_slot_stage(value: Any) -> int | None:
    """把合法时刻映射到最近的 10/15/20 点业务阶段；平局取较晚阶段。"""
    clock = split_time_slot(value)
    if clock is None:
        return None
    total = clock[0] * 60 + clock[1]
    return min((10, 15, 20), key=lambda anchor: (abs(total - anchor * 60), -anchor))


def _check_one(
    index: int,
    block: Block,
    *,
    strategies: Optional[list[str]],
    owners: Optional[list[str]],
    today: str,
) -> list[str]:
    """校验单块，返回错误文案列表。"""
    where = f"第 {index} 块 {block.type or '(缺 type)'}"
    errors: list[str] = []
    if block.type not in BLOCK_TYPES:
        return [f"{where}：不支持的积木类型"]

    if block.type == "group":
        channel_id = _text(block.get("channel_id"))
        if not channel_id:
            errors.append(f"{where}：channel_id 不能为空")
        elif not _UUID_RE.match(channel_id):
            errors.append(f"{where}：channel_id 必须是群 UUID，当前为 {channel_id}")

    elif block.type == "times":
        slots = as_str_list(block.get("slots"))
        if not slots:
            errors.append(f"{where}：slots 不能为空")
        seen: set[str] = set()
        seen_stages: dict[int, str] = {}
        for slot in slots:
            if slot in seen:
                errors.append(f"{where}：档位 {slot} 重复")
                continue
            seen.add(slot)
            normalized = normalize_time_slot(slot)
            if normalized is None:
                errors.append(f"{where}：时刻格式应为 HH:MM，当前为 {slot}")
                continue
            stage = time_slot_stage(normalized)
            if stage in seen_stages:
                label = {10: "早追", 15: "中追", 20: "晚追"}[stage]
                errors.append(
                    f"{where}：{label}阶段只能配置一个发送时间，"
                    f"当前为 {seen_stages[stage]}、{normalized}"
                )
            elif stage is not None:
                seen_stages[stage] = normalized

    elif block.type == "people":
        # 空名单 = 该群全员；想限定人员才填 names
        names = as_str_list(block.get("names"))
        if owners is not None:
            unknown = [name for name in names if name not in owners]
            if unknown:
                errors.append(f"{where}：不在督战名单内 {'、'.join(unknown)}")

    elif block.type == "source":
        key = _text(block.get("key"))
        if key not in SOURCE_KEYS:
            errors.append(f"{where}：未知数据源 {key or '(空)'}")

    elif block.type == "rule":
        mode = _text(block.get("mode")) or "text"
        if mode not in RULE_MODES:
            errors.append(f"{where}：mode 只能是 text/ai，当前为 {mode}")
        if mode == "ai":
            if not _text(block.get("prompt")):
                errors.append(f"{where}：AI 规则必须填 prompt")
        elif not _text(block.get("text")):
            errors.append(f"{where}：规则文案不能为空")
        when = _text(block.get("when")) or "always"
        if when not in RULE_WHEN:
            errors.append(f"{where}：when 只能是 {'/'.join(RULE_WHEN)}，当前为 {when}")

    elif block.type == "strategy":
        strategy_id = _text(block.get("id"))
        if not strategy_id:
            errors.append(f"{where}：策略 id 不能为空")
        elif strategies is not None and strategy_id not in strategies:
            errors.append(f"{where}：策略 {strategy_id} 不在当前策略清单内")
        until = _text(block.get("until"))
        if until and not _DAY_RE.match(until):
            errors.append(f"{where}：until 应为 YYYY-MM-DD，当前为 {until}")
        elif until and until < today:
            errors.append(f"{where}：策略 {strategy_id} 已于 {until} 到期，这块永远不会命中，请改期或删掉")

    elif block.type == "recipient":
        kind = _text(block.get("kind"))
        if kind not in RECIPIENT_KINDS:
            errors.append(f"{where}：kind 只能是 channel/user，当前为 {kind or '(空)'}")
        target = _text(block.get("id"))
        if not target:
            errors.append(f"{where}：id 不能为空")
        elif not _UUID_RE.match(target):
            errors.append(f"{where}：id 必须是 UUID，当前为 {target}")

    elif block.type == "condition":
        key = _text(block.get("key"))
        if key not in CONDITION_KEYS:
            errors.append(f"{where}：未知条件 {key or '(空)'}")
        if not isinstance(block.get("value"), bool):
            errors.append(f"{where}：value 必须是 true/false")
        elif key == "has_data" and block.get("value") is False:
            errors.append(f"{where}：目前只支持「有数据才发送」，不能把取数失败当作无数据")

    elif block.type == "style":
        lang = _text(block.get("lang")) or "zh"
        if lang not in LANGS:
            errors.append(f"{where}：lang 只能是 zh/en，当前为 {lang}")
        if block.get("title") is not None and not _text(block.get("title")):
            errors.append(f"{where}：title 不能为空字符串（不需要就删掉该字段）")
    return errors


def today_in_shanghai() -> str:
    """今天的日期（Asia/Shanghai），用来判断策略是不是已经过期。"""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    return datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()


def is_valid_day(text: str) -> bool:
    """只校验 YYYY-MM-DD 形状。"""
    return bool(_DAY_RE.match(text or ""))


def validate_blocks(
    blocks: list[Block],
    *,
    strategies: Optional[list[str]] = None,
    owners: Optional[list[str]] = None,
    today: Optional[str] = None,
) -> list[str]:
    """校验整份配置，返回错误文案列表（不抛异常）。

    有错误也能存草稿，但**不允许启用**：坏配置一旦启用，到点推不出去。
    """
    if not blocks:
        return ["至少需要一个积木块（至少要有 group + times）"]
    errors: list[str] = []
    reference_day = today or today_in_shanghai()
    for index, block in enumerate(blocks, start=1):
        errors.extend(_check_one(index, block, strategies=strategies, owners=owners, today=reference_day))
    if not any(block.type == "group" for block in blocks):
        errors.append("缺少 group 块：不知道发到哪个群")
    for kind in SINGLETON_BLOCKS:
        found = [block for block in blocks if block.type == kind]
        if len(found) > 1:
            tail = "：一个子 Agent 追一个群" if kind == "group" else "：同类块只有第一个生效，多出来的会被忽略"
            errors.append(f"只能有一个 {kind} 块（当前 {len(found)} 个）{tail}")
    if not any(block.type == "times" for block in blocks):
        errors.append("缺少 times 块：不知道一天推哪几档")
    return errors


def block_schema() -> list[dict]:
    """给前端积木面板用的字段定义（面板与校验同源，避免两边漂移）。"""
    return [
        {
            "type": "group",
            "label": "目标群",
            "hint": "选择已接入消息采集和闭环判断的督战群（只能一块）",
            "multiple": False,
            "fields": [
                {"key": "channel_id", "label": "群 ID", "kind": "uuid", "required": True},
                {"key": "label", "label": "群名称", "kind": "text"},
            ],
        },
        {
            "type": "times",
            "label": "推送档位",
            "hint": "可自定义早追、中追、晚追各一个时刻；按最近的 10/15/20 点匹配阶段（只能一块）",
            "multiple": False,
            "fields": [
                {
                    "key": "slots",
                    "label": "档位",
                    "kind": "slots",
                    "required": True,
                }
            ],
        },
        {
            "type": "people",
            "label": "覆盖人员",
            "hint": "留空 = 该群全员；要限定人员就填名字（必须在本群名单内）",
            "multiple": False,
            "fields": [{"key": "names", "label": "姓名", "kind": "names"}],
        },
        {
            "type": "source",
            "label": "数据源",
            "multiple": True,
            "hint": "这一节取什么数",
            "fields": [
                {
                    "key": "key",
                    "label": "来源",
                    "kind": "select",
                    "required": True,
                    "options": list(SOURCE_KEYS.keys()),
                    "option_labels": SOURCE_KEYS,
                }
            ],
        },
        {
            "type": "rule",
            "label": "提醒重点",
            "multiple": True,
            "hint": "只覆盖消息里的“本档动作”；其余检查提醒仍由系统自动生成",
            "fields": [
                {
                    "key": "mode",
                    "label": "重点来源",
                    "kind": "select",
                    "options": list(RULE_MODES),
                    "option_labels": {"text": "固定提醒重点", "ai": "AI 生成重点（慢·有费用，失败回落默认重点）"},
                    "default": "text",
                },
                {"key": "text", "label": "本档动作", "kind": "textarea", "show_when": {"mode": "text"}},
                {"key": "prompt", "label": "告诉 AI 本档重点", "kind": "textarea", "show_when": {"mode": "ai"}},
                {
                    "key": "when",
                    "label": "什么时候使用",
                    "kind": "select",
                    "options": list(RULE_WHEN),
                    "option_labels": {
                        "always": "每档都用",
                        "workday": "普通工作日",
                        "holiday": "长假照常推送日",
                        "missing_report": "有人未交日报",
                    },
                    "default": "always",
                },
            ],
        },
        {
            "type": "strategy",
            "label": "策略核查",
            "multiple": True,
            "hint": "挂一条触达策略检查",
            "fields": [
                {"key": "id", "label": "策略 ID", "kind": "text", "required": True},
                {"key": "until", "label": "到期日", "kind": "date"},
            ],
        },
        {
            "type": "recipient",
            "label": "额外收件人",
            "multiple": True,
            "hint": "除群以外再抄送给谁",
            "fields": [
                {
                    "key": "kind",
                    "label": "类型",
                    "kind": "select",
                    "options": list(RECIPIENT_KINDS),
                    "option_labels": {"channel": "群", "user": "个人"},
                    "default": "channel",
                },
                {"key": "id", "label": "ID", "kind": "uuid", "required": True},
            ],
        },
        {
            "type": "condition",
            "label": "提醒条件",
            "multiple": True,
            "hint": "默认每档都提醒；这里用于筛选是否发送整条检查结果",
            "fields": [
                {
                    "key": "key",
                    "label": "检查条件",
                    "kind": "select",
                    "required": True,
                    "options": list(CONDITION_KEYS.keys()),
                    "option_labels": CONDITION_KEYS,
                },
                {"key": "value", "label": "取值", "kind": "bool", "default": True},
            ],
        },
        {
            "type": "style",
            "label": "样式",
            "hint": "语言、标题、落款（只能一块）",
            "multiple": False,
            "fields": [
                {
                    "key": "lang",
                    "label": "语言",
                    "kind": "select",
                    "options": list(LANGS.keys()),
                    "option_labels": LANGS,
                    "default": "zh",
                },
                {"key": "title", "label": "标题", "kind": "text"},
                {"key": "footer", "label": "落款", "kind": "text"},
            ],
        },
    ]
