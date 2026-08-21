# -*- coding: utf-8 -*-
"""把三部 Vemory JSON 整理成可读纪要。"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

SRC = Path(__file__).with_name("overseas_123_vemory_liu_2026-07-01.json")
OUT = Path(__file__).with_name("overseas_123_vemory_本月纪要_2026-07.md")

JUNK_TITLE = ("录音连线", "内容极少", "转录内容不足", "简短开场", "输入法切换", "未形成有效")


def week_label(day: str) -> str:
    if not day:
        return "?"
    if day <= "2026-07-05":
        return "W1"
    if day <= "2026-07-12":
        return "W2"
    if day <= "2026-07-19":
        return "W3"
    return "W4"


def is_junk(title: str, summary: str, dur: int) -> bool:
    if dur >= 400:
        return True
    if any(k in title for k in JUNK_TITLE):
        return True
    if dur <= 1 and len(summary) < 80:
        return True
    return False


def themes(title: str, summary: str) -> list[str]:
    text = f"{title} {summary[:400]}".lower()
    mapping = [
        ("马来/东南亚开店", ("马来", "云顶", "pavilion", "klcc", "东南亚", "选址", "开店", "trx")),
        ("印度渠道", ("印度", "india", "thakral", "kerala", "潮汕", "古吉拉特", "brc", "zimson")),
        ("俄语区/俄罗斯", ("俄罗", "俄语", "russia", "圣彼得堡", "metrogroup")),
        ("回款/订单交付", ("回款", "收款", "订单", "付款", "尾款", "发货", "collection")),
        ("代理政策/价格", ("代理标准", "价格策略", "policy", "rebate", "返利", "代理商对外")),
        ("售后/补偿", ("售后", "维修", "换新", "补偿", "黑金")),
        ("招聘/BD薪酬", ("面试", "招聘", "bd", "薪酬", "compensation")),
        ("培训/AI工具", ("培训", "cursor", "mars", "miles", "contactout", "五件套", "ai 工具", "ai工具")),
        ("VPS/SOP/流程", ("vps", "sop", "日报", "系统录入", "流程")),
        ("出差/物料规范", ("出差", "物料", "礼赠", "报销")),
        ("印尼/澳洲", ("印尼", "澳洲", "澳大利亚", "ti/v2", "time international")),
    ]
    tags = [name for name, kws in mapping if any(k in text for k in kws)]
    return tags or ["其他"]


def first_para(summary: str, n: int = 160) -> str:
    s = (summary or "").strip().split("\n")[0].strip()
    return s[:n] + ("…" if len(s) > n else "")


def todo_text(t) -> str:
    if isinstance(t, dict):
        return (t.get("content") or t.get("text") or t.get("title") or "").strip()
    return str(t).strip()


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    window = data["window"]
    rows = []
    for r in data["results"]:
        if not r.get("ok"):
            continue
        for m in r.get("meetings") or []:
            st = m.get("start_time") or ""
            day = st[:10]
            dur = int(m.get("duration_seconds") or 0) // 60
            title = m.get("name") or ""
            summary = (m.get("summary") or "").strip()
            if is_junk(title, summary, dur):
                continue
            rows.append(
                {
                    "dept": r["dept"],
                    "person": r.get("name") or "",
                    "day": day,
                    "week": week_label(day),
                    "dur": dur,
                    "title": title,
                    "summary": summary,
                    "todos": [todo_text(t) for t in (m.get("todos") or []) if todo_text(t)],
                    "tags": themes(title, summary),
                }
            )

    denied = [r for r in data["results"] if not r.get("ok")]
    zero = [
        r
        for r in data["results"]
        if r.get("ok") and int(r.get("total_meetings") or 0) == 0
    ]

    lines: list[str] = []
    lines += [
        f"# 海外经销商一部/二部/新部 · Vemory 本月纪要",
        "",
        f"> **窗口**：{window['from']} ~ {window['to']}  ",
        f"> **账号**：刘春梅（13281878861）  ",
        f"> **有效会议**：{len(rows)} 场（已剔除空转写/异常时长）  ",
        f"> **可查人员**：于冰、杨晶晶、何海文、新部 9 人；其余 19 人无权限",
        "",
        "---",
        "",
        "## 1. 一句话总览",
        "",
        "- **一部（于冰）**：本月重心在马来西亚双店（云顶 + Pavilion/KLCC）与东南亚渠道；W3 密集客户会，越南/泰国门店运营与回款同步。",
        "- **二部（杨晶晶 / 何海文）**：印度（Thakral、潮汕/喀拉拉、BRC）+ 俄语区售后/BD 薪酬 + 经销商 VPS/SOP/出差物料规范。",
        "- **新部**：以培训与获客工具为主（门店五件套、AI 调研、ContactOut）；业务成交类会议很少。",
        "",
        "## 2. 覆盖与权限",
        "",
        "| 部门 | 花名册 | 可查 | 有效会议 | 说明 |",
        "|------|--------|------|----------|------|",
    ]

    for dept in ("一部", "二部", "新部"):
        roster = [r for r in data["results"] if r.get("dept") == dept]
        ok = [r for r in roster if r.get("ok")]
        meet = [x for x in rows if x["dept"] == dept]
        lines.append(
            f"| {dept} | {len(roster)} | {len(ok)} | {len(meet)} | "
            f"{'、'.join(r.get('name','') for r in ok if int(r.get('total_meetings') or 0)>0) or '无可拉会议人员'} |"
        )

    lines += [
        "",
        f"**无权限（{len(denied)}）**："
        + "、".join(r.get("name") or "?" for r in denied),
        "",
        f"**可查但本月 0 场（{len(zero)}）**："
        + ("、".join(r.get("name") or "?" for r in zero) if zero else "无"),
        "",
        "## 3. 主题热力（有效会议打标，可多标）",
        "",
        "| 主题 | 场次 | 主要归属 |",
        "|------|------|----------|",
    ]

    theme_bucket: dict[str, list] = defaultdict(list)
    for x in rows:
        for t in x["tags"]:
            theme_bucket[t].append(x)
    for theme, arr in sorted(theme_bucket.items(), key=lambda kv: -len(kv[1])):
        depts = "、".join(
            sorted({a["dept"] for a in arr}, key=["一部", "二部", "新部"].index)
        )
        lines.append(f"| {theme} | {len(arr)} | {depts} |")

    lines += ["", "## 4. 分部门纪要", ""]

    dept_focus = {
        "一部": [
            "马来：云顶赌场店 + 吉隆坡 Pavilion/KLCC，倾向低成本 pop-up 试水，直营/代理未拍板。",
            "东南亚：越南/泰国门店 sell-out 与回款、发布会节点并行。",
            "新市场：印尼 TI 约会、澳洲拒免费样机并推进零售商会议。",
        ],
        "二部": [
            "印度：Thakral 三轮视频、潮汕/喀拉拉网络、北方市场测算、BRC 认证咨询。",
            "俄语区：售后问题与黑金会员补偿；BD/PR 角色与可追溯业绩挂钩的薪酬方案未定稿。",
            "管理：经销商 VPS/SOP、出差报销留痕、礼赠物料申请、代理对外价格口径统一。",
        ],
        "新部": [
            "培训：门店运营与销售五件套；Cursor/Mars 海外调研与选址测算（须人工核验）。",
            "获客：ContactOut API 试用（邮箱/职位/电话）。",
            "业务会议很少，本月尚处工具与能力建设阶段。",
        ],
    }

    for dept in ("一部", "二部", "新部"):
        arr = [x for x in rows if x["dept"] == dept]
        people = sorted({x["person"] for x in arr})
        mins = sum(x["dur"] for x in arr)
        lines += [
            f"### {dept}",
            "",
            f"- 有效会议 **{len(arr)}** 场 · 约 **{mins}** 分钟 · 人员：{'、'.join(people) or '—'}",
            "",
            "**工作重心**",
            "",
        ]
        for b in dept_focus[dept]:
            lines.append(f"- {b}")
        lines.append("")

        by_week: dict[str, list] = defaultdict(list)
        for x in arr:
            by_week[x["week"]].append(x)
        for w in ("W1", "W2", "W3"):
            items = sorted(by_week.get(w, []), key=lambda z: z["day"], reverse=True)
            if not items:
                continue
            lines.append(f"**{w}**（{len(items)} 场）")
            lines.append("")
            for x in items:
                lines.append(
                    f"- `{x['day']}` · {x['dur']}min · **{x['person']}** · {x['title']}"
                )
                brief = first_para(x["summary"], 140)
                if brief:
                    lines.append(f"  - {brief}")
            lines.append("")

    # Key actions from todos + inferred from W3
    lines += [
        "## 5. 待办与跟进（从会议 todos / 结论提炼）",
        "",
    ]
    todos = []
    for x in rows:
        for t in x["todos"]:
            todos.append((x["dept"], x["person"], x["day"], t))
    if todos:
        lines += ["| 部门 | 人 | 日期 | 待办 |", "|------|----|------|------|"]
        for dept, person, day, t in todos[:40]:
            lines.append(f"| {dept} | {person} | {day} | {t[:120]} |")
        if len(todos) > 40:
            lines.append(f"| … | | | 另有 {len(todos)-40} 条见 JSON |")
    else:
        lines += [
            "接口返回的结构化 todos 较少，按各部门结论整理如下：",
            "",
            "| 优先级 | 事项 | 责任侧 |",
            "|--------|------|--------|",
            "| P0 | 马来双店：SWAP/SWITCH 测算定案；KLCC/Pavilion 商务条件 | 于冰 |",
            "| P0 | 印度 Thakral 反馈跟进；BRC 资料补充后再决策 | 何海文 / 杨晶晶 |",
            "| P0 | 俄语区售后闭环 + 黑金会员补偿落地 | 杨晶晶组 |",
            "| P1 | 俄语区 BD 薪酬与业绩归因方案定稿 | 杨晶晶 |",
            "| P1 | 越南发货/到账；泰国运营与本月 PO | 于冰 |",
            "| P1 | 代理对外价格/政策口径统一并群同步 | 二部 |",
            "| P2 | 出差标准、礼赠物料、VPS 录入规范落地 | 全组 |",
            "| P2 | 新部完成 AI 调研区域分工与人工核验 | 新部 |",
        ]

    lines += [
        "",
        "## 6. 第三周（7/13–7/19）重点（对齐业务周报）",
        "",
        "### 一部 · 于冰",
        "",
        "1. 马来密集会议：SWAP 定调、云顶参观、SWITCH/KLCC 洽谈 → 与 PDF《26.7.13-26.7.17工作》一致。",
        "2. 系统 SI 本周 0、在途约 49 万；会议侧重心在新客/选址而非当周入账。",
        "",
        "### 二部 · 杨晶晶 / 何海文",
        "",
        "1. 印度：Thakral 第三次视频；北方市场测算；BRC 认证咨询。",
        "2. 俄语区：售后与黑金补偿；BD 薪酬方案讨论。",
        "3. 管理：海外物料/出差规范、VPS 推进、代理价格口径。",
        "",
        "### 新部",
        "",
        "1. 门店五件套培训 + AI 调研工具培训为主。",
        "2. 尚无明显经销商成交类会议沉淀。",
        "",
        "## 7. 资料来源",
        "",
        f"- 原始 JSON：`{SRC.name}`",
        f"- 清单版：`overseas_123_vemory_liu_2026-07-01.md`",
        "- 口径：按会议 owner（被查询销售）归属；同一场多方录音可能重复出现。",
        "",
    ]

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT} meetings={len(rows)}")


if __name__ == "__main__":
    main()
