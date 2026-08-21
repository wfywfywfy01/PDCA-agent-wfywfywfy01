# -*- coding: utf-8 -*-
"""Assemble Yu Bing Malaysia full dossier for Desktop."""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(r"d:\经销商PDCA")
DESKTOP = Path(r"C:\Users\frank\Desktop")
OUT = DESKTOP / "于冰_马来西亚_全量资料与数据.md"
VEMORY = ROOT / "overseas_weekly" / "outputs" / "_tmp_yubing_vemory.md"
CSV_PATH = ROOT / "overseas_weekly" / "inputs" / "malaysia" / "2026-07-23_马来西亚3C与腕表渠道_批量获客导入.csv"
KDOCS_PATH = ROOT / "overseas_weekly" / "inputs" / "malaysia" / "2026-08-13_kdocs_过往名单总表_Malaysia.csv"


def extract_vemory_block(text: str, title: str) -> str:
    start = text.find("## " + title)
    if start < 0:
        return f"（未找到纪要：{title}）\n"
    rest = text[start + 3 :]
    nxt = rest.find("\n## 2026-")
    if nxt < 0:
        return text[start:].rstrip() + "\n\n"
    return text[start : start + 3 + nxt].rstrip() + "\n\n"


def main() -> None:
    vemory = VEMORY.read_text(encoding="utf-8") if VEMORY.exists() else ""
    csv_rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8"))) if CSV_PATH.exists() else []
    kdocs_rows = list(csv.DictReader(KDOCS_PATH.open(encoding="utf-8"))) if KDOCS_PATH.exists() else []

    meeting_order = [
        ("2026-07-14 马来西亚高端手机渠道与门店布局讨论", "SWAP 门店布局 · 分享 1d939024 · audio 54min / JSON 57min"),
        ("2026-07-14 东南亚零售渠道与电动车市场机会讨论", "SWAP 零售/电动车 · 分享 4c58a03d · audio 24min / JSON 32min"),
        ("2026-07-14 东南亚门店选址与高定手机销售合作讨论", "分享标题 DirectD 选址 · 6cc96a48 · audio 48min / JSON 60min · 纪要是商场选址+越南销售，未见 Amy 本人承诺"),
        ("2026-07-15 马来西亚商场选址与东南亚开店策略沟通", "Pavilion · d8ca9b58 · audio 54min / JSON 55min"),
        ("2026-07-15 东南亚奢侈品与高定业务落位沟通", "Genting 落位 · e547d52e · audio 59min / JSON 59min"),
        ("2026-07-15 云顶赌场与商旅业态合作参观交流", "Genting 参观 · e478833d · audio 65min / JSON 65min"),
        ("2026-07-16 马来西亚门店拓展与代理合作洽谈", "KLCC · d11b354d · audio 68min / JSON 73min"),
        ("2026-07-16 马来西亚门店合作与东南亚渠道拓展讨论", "SWITCH · 997cda36 · audio 95min / JSON 96min"),
        ("2026-07-07 印尼与马来西亚市场进入方案讨论", "出差前内部方案会 · JSON 19min · 无分享链接"),
    ]
    parts: list[str] = []
    parts.append(
        """# 于冰 · 马来西亚全量资料与数据

> **整理日**：2026-08-14  
> **负责人**：于冰 Ivan · 工号 72 · 海外经销商一部  
> **口径**：管线索，不是客户。S7 试铺或签约前不得改口叫客户。  
> **合同/LOI**：不是正式法律意见，需人工复核。  
> **原则**：只写仓库/手册/金山/Vemory 能溯源的内容。未知标「待确认」。不编造 WhatsApp/邮件全文。

---

## 0. 一句话

现在能汇报的不是「马来客户」，是 **62 条可跟进线索的位置**。进行中 6 条。客户 0。马来 SI=0、L2=0、试铺=0、门店五件套=0。于冰 7 月 ¥1,265,468.52、8/1–13 ¥968,982.06 是**越柬存量**。VPS 检索 DirectD / SWITCH / KLCC = 0。H2 stretch 155 万不能用这 220 万 SI 证明。

---

## 1. 硬口径（勿改）

| 规则 | 说明 |
|------|------|
| 管理对象 | 线索（联系人级），不是客户、不是公司 |
| 毕业 | S7 试铺或签约发生，才改口叫客户 |
| 晋级只认 | 发送记录 / 对方回复 / 会议纪要 / 书面。不认「感觉谁好」 |
| 公司有会 ≠ 该人已触达 | Shawn / Chris / Ai Lin / Ezwan / Lawrence / Marcus / Chin 不并入主线阶段 |
| DirectD S4 | 只算 Amy Tan。Ezwan 仍 S1 |
| SWITCH S5 | 只算 John Cheah。Lawrence / Marcus / Chin 仍 S1 |
| SWAP | 内部定调，非签约主体 |
| 三类分池 | 承接方 ≠ 场地方 ≠ 生态。KLCC 书面 ≠ 代理已成 |
| 6/12 Ivan 日报 | API 测试样例，不当业务证据 |
| 出差周 Cursor | 7/14–16 空。Ivan Cursor 最新停 7/24 |
| 金山表内已回 | 不升阶段。Ian lim「暂时没兴趣」未见邮件原文，不升 S4 |
| Red Army Regional | 邮箱在新加坡，不计入马来净增 13 |

---

## 2. 漏斗（2026-08-13 口径）

可跟进 **62** = 手册 32 ∪ 获客净增 13 ∪ 金山净增 17。

| 阶段 | 条 | 对象 | 触达？ |
|------|----|------|--------|
| S1 入库未触达 | 52 | 见 §5。Cc 6 · 本周可发 5 · 冻结 41 | 否 |
| S2 尽调未发 | 3 | Delia Yap · Valiram · Damien Woo | 尽调有，发出记录未入库 |
| S3 已发未回 | 1 | Machines Andrew Cheng | 历史有回复后失联 |
| S4 有效回复 | 1 | 仅 Amy Tan 7/24 邮件 | 是 |
| S5 谈判 | 4 | John Cheah · SWAP · Pavilion Lovell Ho · Genting | 是（会议） |
| S6 书面 | 1 | 仅 KLCC | 是（7/31 书面） |
| S7 转化成客户 | 0 | — | — |

进行中 6 条 = Amy / John / SWAP / Pavilion / Genting / KLCC。

---

## 3. 已触达线索（有会议 / 邮件 / 书面）

### 3.1 Amy Tan · DirectD CEO · S4

| 项 | 内容 |
|----|------|
| 公司 | DirectD Retail & Wholesale Sdn Bhd · 20+ 店 · SS15 HQ |
| 电话 | +60 3-5621 1355；WhatsApp +60 19-694 0000（公司）；Amy +6019 339 1184（金山） |
| 邮箱 | 公司 sales@directd.com.my；Amy amytan@directd.com.my（金山） |
| 触达证据 | 7/24 邮件原文仅存一句：**Kindly send me the relevant info**。邮件全文待确认 |
| 不升 S4 的 | Ezwan Rais、Stacey Lau：名单在册，0 触达 |
| 7/14 分享 | 标题写 DirectD（6cc96a48）。纪要是 Pavilion/Getting/KLCC + 越南销售，**未见 Amy 本人承诺** |
| 下一步 | 资料包 + 线上 MOU 1-pager → 完成后到 S5 |
| CSV 快照 | 7/23 仍写「是否跟进:否」。以 7/24 回邮为准 |

### 3.2 John Cheah · SWITCH GM BD · S5

| 项 | 内容 |
|----|------|
| 公司 | CG Computers Sdn Bhd (Switch) · Apple APR · Erajaya 60% · 80+ 店 |
| 电话 | +60 16-441 1800（公司总机） |
| 邮箱 | feedback@switch.com.my（公司，非 John 个人） |
| 触达证据 | 7/16 现场约 95min · 分享 https://vemory-share.vemory.ai/share?id=997cda36 |
| 对方口径 | 先 pop-up 试水；强调代理商要有利润；可协助认证/海关；关心装修谁出、投入上限 |
| 位置情报 | KLCC 转角 / 宝珀 / 芬迪门口更好；云顶巧克力位对入口 |
| 仍 S1 | Lawrence Seng、Marcus Wong、Chin Ing Heng、Adeline K. |
| 下一步 | 30min ROI 会：先接云顶还是 KLCC → S6 或淘汰 |

### 3.3 SWAP / Brightstar · 内部渠道 · S5（非签约主体）

| 项 | 内容 |
|----|------|
| 触达 | 7/14 两场：布局 1d939024（54min）、零售 4c58a03d（24min） |
| 定调 | 两店 Getin + Pavilion/KLCC |
| 原文 | 「他们利润点多少？」「七八啊。」「所以我们手机大致上如果赚不到的话，我们就不做。」 |
| 原文 | GTO 15%「有点高，其实可以往下谈。」Getin 初步「四千多美金一个月，或者说 GTO 是十五。」 |
| 原文 | premium 不接受「卖了再算」 |
| 金山另条 | William Tan · SWAP LOGISTICS · 60 12-277 9938 · 表写已回 · **不并入 SWAP-S5** |
| 下一步 | 利润点书面。Andy Tan（SWAP CEO，总抓取名单）记着但未进 62 |

### 3.4 Lovell Ho · Pavilion Senior Director · S5

| 项 | 内容 |
|----|------|
| 触达 | 7/15 约 54min · d8ca9b58 |
| 对方 | 暂无铺、不能给平面图、进 waiting list、要公司资料。偏好 2–3 楼腕表区（沛纳海/IWC） |
| 卡点 | 直营/代理未拍。主体不拍材料交不出 |
| 不并入 | Shawn Wong LEASING MANAGER 60176289929 · 金山写已回 · 公司有会 ≠ 该人已触达 |
| 下一步 | 品牌/财务/主体材料 → S6 |

### 3.5 Genting / Sky Avenue · S5

| 项 | 内容 |
|----|------|
| 触达 | 7/15 落位 e547d52e（59min）+ 参观 e478833d（65min） |
| 口头 | USD 4k+/月或 GTO 15%。倾向正对赌场门口 |
| 意向 | 赌场限定款、发布会。自营/代理并行，2–3 天等代理回复 |
| WhatsApp | 参观场纪要写后续 WhatsApp 群。**群原文待确认**，不能当已回复 |
| 不并入 | Melissa Wong VP +6012 218 8631；Chris Yap LEASING 60178804487 |
| 下一步 | 口头转 LOI |

### 3.6 Suria KLCC · S6（场地方，不是代理）

| 项 | 内容 |
|----|------|
| 触达 | 7/16 约 68min · d11b354d |
| 书面 | **7/31 事后文件** RM70k/月或 15% GTO · 进场 10/12。不是 8 场当场签下 |
| 会中 | 口述无店仍「每年两百多台」——VPS 未按国拆，标签=假设 |
| 面积 | boutique 40–50㎡（约 600SF）；pop-up 约 30㎡。手册另记 Ampang Rotunda G · 300SF |
| 不并入 | Ai Lin klcc Casual Mall +60 12-393 3665 · 金山写已回 |
| 下一步 | ROI 一页纸 + 经营主体书面。完成后仍是场地方线索进场筹备 |

### 3.7 Andrew Cheng · Machines CEO · S3 搁置

| 项 | 内容 |
|----|------|
| 邮箱 | andrew.cheng@machines.com.my |
| 电话 | +60 12-311 9922 |
| 证据 | 历史回复了解 presentation 后再无回复。跟进人 Longsion |
| 处置 | 前两家未死不重启 |

### 3.8 尽调未发出（S2，严格说还没触达对方）

| 对象 | 尽调 | 发出？ |
|------|------|--------|
| Delia Yap · TRX Leasing Director | Cursor 7/20、7/30 英文租赁稿 | 发送记录未入库 · 待确认是否已发 |
| Valiram / Swiss Watch Gallery | Cursor 6/17–22 | 0 触达。Ian lim 金山写已回「暂时没兴趣」，未见邮件原文，不升 S4 |
| Damien Woo · Ital Auto COO | Cursor 6/29 · woochunming87@hotmail.com | 0 触达。Zahir 等 Damien 后再发 |

---

## 4. 手册底表 32 条（截止 2026-08-05）

来源：`马来西亚_线索全生命周期.html` LEADS 数组。联系人级。

| 公司 | 联系人 | 池 | 阶段 | P | 下一步 | 证据/备注 |
|------|--------|----|------|---|--------|-----------|
| DirectD | Amy Tan · CEO | 承接方 | S4 | P0 | 资料包+线上 MOU | 7/24 Kindly send me the relevant info |
| DirectD | Ezwan Rais · Head of Product | 承接方 | S1 | P0 | Amy 会 Cc | 0 触达 |
| SWITCH | John Cheah · GM BD | 承接方 | S5 | P0 | ROI 书面或放弃 | 7/16 现场 95min |
| SWITCH | Lawrence Seng · BR GM | 承接方 | S1 | P0 | 与 John 同步发 | 0 触达 |
| SWITCH | Marcus Wong · GM | 承接方 | S1 | P0 | 陈列对接 | 0 触达 |
| SWITCH | Chin Ing Heng · BD | 承接方 | S1 | P1 | 落位协同 | 0 触达 |
| SWAP / Brightstar | 内部渠道 | 承接方 | S5 | P1 | 利润点书面 | 7/14 双店定调 |
| Machines | Andrew Cheng · CEO | 承接方 | S3 | P2 | 冻结 | 历史回复后失联 |
| Suria KLCC | Leasing · Ampang Rotunda G | 场地方 | S6 | P0 | ROI+主体 | 7/31 RM70k 或 15% GTO · 10/12 |
| Pavilion KL | Lovell Ho · Senior Director | 场地方 | S5 | P0 | pop-up 书面 | 7/15 2–3 楼腕表区 |
| Sky Avenue Genting | Leasing | 场地方 | S5 | P0 | 口头转 LOI | 7/15 口头 USD 4k+ 或 GTO 15% |
| The Exchange TRX | Delia Yap · Leasing Director | 场地方 | S2 | P1 | 邮件发出 | Cursor 7/20、7/30 |
| Mid Valley / The Gardens | Leasing Team | 场地方 | S1 | P2 | 冻结 | 双店后再触达 |
| Valiram Group | Swiss Watch Gallery | 生态 | S2 | P0 | VIP probe | Cursor 6/17–22；0 触达 |
| The Hour Glass MY | Corporate / Pavilion 店 | 生态 | S1 | P0 | 本周可发 | 0 触达 |
| Cortina Watch | —（后补 Ming Hon） | 生态 | S1 | P0 | 本周可发 | 0 触达 |
| Sincere Fine Watches | Pavilion L2 | 生态 | S1 | P0 | 冻结至 Pavilion 落位 | 0 触达 |
| Red Army Watches | — | 生态 | S1 | P0 | 双店后再发 | 0 触达 |
| Watatime | — | 生态 | S1 | P0 | 冻结 | 中端非首要 |
| A.D. Time | YY Kwan / Junyi Kwan | 生态 | S1 | P1 | 对接 Junyi | 0 触达 |
| Tomei Consolidated | — | 生态 | S1 | P1 | 可与 ACCCIM 同批 | 0 触达 |
| Ingram Micro MY | Ricky Tan · MD | 生态 | S1 | P1 | 冻结 | 分销模式未选 |
| Senheng Electric | Mobile Category | 生态 | S1 | P2 | 淘汰观察 | 调性不匹配 |
| VSTECS Berhad | — | 生态 | S1 | P2 | 核实 V-STARS 名称 | 名单储备 |
| Ital Auto | Damien Woo · Dealer Principal | 生态 | S2 | P0 | VIP probe | Cursor 6/29；0 触达 |
| Ital Auto | Zahir Kelvin Ong Abdullah | 生态 | S1 | P0 | 等 Damien | 0 触达 |
| SunAgata Supercars | Nicole Perreau | 生态 | S1 | P1 | 双店后再发 | 0 触达 |
| Wearnes / Quest | — | 生态 | S1 | P1 | 补 LinkedIn | 联系人待补 |
| ACCCIM | 秘书处 | 生态 | S1 | P0 | 本周可发 | 0 触达 |
| MCCC | 秘书处 | 生态 | S1 | P0 | 本周可发 | 0 触达 |
| KLSCCCI 隆雪中总 | — | 生态 | S1 | P1 | 可与 ACCCIM 同批 | 0 触达 |
| KLSCAH 隆雪华堂 | — | 生态 | S1 | P1 | 冻结 | 社团非本周 |

本周可发 5：Hour Glass · Cortina Ming Hon · ACCCIM · MCCC（+ Cortina 人名已由金山补上）。

---

## 5. 7/23 获客 CSV 30 行

文件：`overseas_weekly/inputs/malaysia/2026-07-23_马来西亚3C与腕表渠道_批量获客导入.csv`  
腕表 19 + 3C 11。CSV「是否跟进」29 否。净增 13（相对手册不双计）。

"""
    )

    parts.append("| 公司 | 类 | 联系人/岗位 | 电话 | 邮箱 | 跟进 | 回复 | 备注 |\n")
    parts.append("|------|----|-------------|------|------|------|------|------|\n")
    for r in csv_rows:
        reason = r.get("reason") or ""
        contact = ""
        for piece in reason.split("|"):
            piece = piece.strip()
            if piece.startswith("联系人:"):
                contact = piece[4:].strip()
        followed = "是" if "是否跟进:是" in reason else "否"
        replied = "是" if "是否回复:是" in reason else "否"
        note = ""
        if "失联" in reason or "无继续" in reason:
            note = "历史失联"
        if "新加坡" in (r.get("location") or ""):
            note = (note + " · 新加坡不计入马来13").strip(" ·")
        parts.append(
            f"| {r.get('company_name','')} | {r.get('category','').split('/')[0]} | {contact or r.get('job_titles','')} | {r.get('phone','')} | {r.get('email','')} | {followed} | {replied} | {note} |\n"
        )

    parts.append(
        """
获客净增 13（门店级/Habib/Poh Kong/Adeline/Stacey 等本周不群发）。Switch/DirectD/Valiram/Hour Glass/Cortina 已在手册，进度以会议/回邮为准。

---

## 6. 金山过往名单总表 /S/21 · Malaysia

文档：https://www.kdocs.cn/l/chxzet9BUaXO?R=L1MvMjE=  
《东南亚线索盘点 (1)》file_id 501279496653。过往名单总表 1426 行，地区=Malaysia **34**（查找 36），去重净增 **17** 进 S1。  
清洗表：`2026-08-13_kdocs_过往名单总表_Malaysia.csv`

表内「是否跟进/回复」**不升阶段**。

"""
    )
    parts.append("| 行 | 公司 | 姓名 | 职位 | 邮箱 | 电话 | 跟进 | 回复 | owner | 漏斗处置 |\n")
    parts.append("|----|------|------|------|------|------|------|------|-------|----------|\n")
    for r in kdocs_rows:
        parts.append(
            f"| {r.get('row','')} | {r.get('company','')} | {r.get('name','')} | {r.get('title','')} | {r.get('email','')} | {r.get('phone','')} | {r.get('followed','')} | {r.get('replied','')} | {r.get('owner','')} | {r.get('funnel','')} |\n"
        )

    parts.append(
        """
金山净增 17（全 S1）：Ming Hon Leow（Cortina，本周可发补人名）· Mark Seng · Ian lim（不升 S4）· Joseph Boudville · F J Benjamin / Horloger / Infinite（先补人）· William Tan（不并入 SWAP）· Lionel Lee / Jacky / SK Senheng（调性不匹配冻）· Adrian Khoo · Melissa / Chris Genting · Shawn Pavilion · Ai Lin KLCC · 广东企业联合会。

### S0 未进 62

| 批次 | 条数 | 处置 |
|------|------|------|
| 金山总抓取名单 地区=Malaysia | 75（另有「马来西亚」10） | 地产/抓取未分池 · 停 S0 |
| 总抓取记着未进 62 | Andy Tan（SWAP CEO）、Janson Kwan（Zitron 自称已开会）、Sime Darby Azmir | 停 S0 |
| 6/23 渠道 118 | 原件未找到 | 停 S0 |
| 6/26 MY 48 | 原件未找到 | 停 S0 |
| 手册引用 6 月 53 / 7 月 100 | 仓库未找到独立原件 | 可能与金山重叠 · 待确认 |

---

## 7. 会议全量

### 7.1 出差 8 场（7/14–16）

时长两套口径：分享页 `audio_duration` 合计 **467min**；Vemory JSON `duration_seconds` 合计约 **502min**。Deck 用 467。链接形态 `https://vemory-share.vemory.ai/share?id={id}`。

| 日期 | 对象 | audio | JSON | 分享 ID | 事实产出 |
|------|------|-------|------|---------|----------|
| 7/14 | SWAP 门店布局 | 54min | 57min | 1d939024 | 两店 Getin+KLCC。利润七八。非签约主体 |
| 7/14 | SWAP 零售/电动车 | 24min | 32min | 4c58a03d | 小库存试水。premium 不接受卖了再算 |
| 7/14 | DirectD 选址（标题） | 48min | 60min | 6cc96a48 | 纪要是商场选址+越南。Amy 只认 7/24 邮件 |
| 7/15 | Pavilion | 54min | 55min | d8ca9b58 | 暂无铺、waiting list、主体未拍 |
| 7/15 | Genting 落位 | 59min | 59min | e547d52e | 赌场动线。要更优惠商务条件 |
| 7/15 | Genting 参观 | 65min | 65min | e478833d | 定制款意向。WhatsApp 群原文待确认 |
| 7/16 | KLCC | 68min | 73min | d11b354d | 口述 200+ 台/年。书面在 7/31 |
| 7/16 | SWITCH | 95min | 96min | 997cda36 | pop-up 试水。John=S5 |

原始 JSON：`data_raw/overseas_123_vemory_liu_2026-07-01.json`（于冰 7 月 20 场）。  
PDF 业务稿：`overseas_weekly/outputs/_w3_yubing_pdf.md`（`26.7.13-26.7.17工作(1).pdf`）。

### 7.2 出差前 / 其他于冰会（含马来）

| 日期 | 时长 | 标题 | 马来相关 |
|------|------|------|----------|
| 7/02 | 29min | 外贸订单跟进与新人市场调研分工 | 调研分工，非马来专项 |
| 7/02 | 24min | 自动化工作系统培训 | 获客系统方法论 |
| 7/02 | 34min | 东南亚奢侈品与数码渠道落地 | 区域策略 |
| 7/03 | 24min | 东南亚与中东多项目推进 | 含区域跟进 |
| 7/06 | 87min | 海外代理收款与门店体系 | 越柬为主 |
| 7/07 | 19min | **印尼与马来西亚市场进入方案** | 精品路线、本地化、先把马来跑通 |
| 7/07 | 31min | 销售周会 | 推进马来西亚/越南等 |
| 7/07 | 41min | 代理商门店与收款周会 | 含马来出差排期语境 |
| 7/08 | 9min | 客户订单与下半年规划 | H2 语境 |
| 7/09 | 33min | 多国回款周报 | 含马来行程 |
| 7/13 | 待确认 | 手册：马来 4 天行程 SWAP→Pavilion/云顶→KLCC/Switch | 该场未在于冰 20 场 JSON 标题里单独出现 |

于冰 7 月 Vemory 共 20 场。8 月 Vemory **空**（待确认刘春梅账号再拉）。

### 7.3 会议纪要全文（Vemory summary + 章节 + 待办）

以下从 `overseas_123_vemory_liu_2026-07-01.json` 抽出，按出差时间序。JSON 时长与分享 audio 可能差几分钟。

"""
    )

    for i, (title, note) in enumerate(meeting_order, 1):
        parts.append(f"\n### 会议 {i} · {note}\n\n")
        parts.append(extract_vemory_block(vemory, title))

    parts.append(
        """
---

## 8. 对方原文摘录（只引已入库）

| 出处 | 原文 | 标签 |
|------|------|------|
| SWAP 7/14 1d939024 | 「他们利润点多少？」「七八啊。」「所以我们手机大致上如果赚不到的话，我们就不做。」 | 事实：转写 |
| SWAP 7/14 | 「GTO十五有点高，其实可以往下谈。」Getin「四千多美金一个月，或者说GTO是十五。」 | 事实：转写 |
| SWAP 7/14 | 专门店都关。Power 关掉；Valiram 接过老库存 | 事实：会中口述 |
| SWAP 7/14 4c58a03d | premium「不接受先卖再算」 | 事实：转写 |
| Pavilion 7/15 | 暂无铺位、不能给平面图，进 waiting list，要公司资料。直营/代理未拍 | 事实：纪要 |
| KLCC 7/16 | 无正式店仍「每年两百多台」 | 假设：VPS 未按国拆 |
| Amy 7/24 | Kindly send me the relevant info | 事实：邮件一句 |
| KLCC 7/31 | RM70k/月或 15% GTO · 10/12 | 事实：书面；非法务意见 |
| 会中口述 | 越南月均 USD 16–22 万（最好月 34 万 / 峰值约 36 万，口径不一） | 越 sell-in 背书，不是马来 sell-out |
| 会中口述 | 代理净利润约 18%；客单 USD 3.5–5K；高定可达 10 万 USD | 假设直到系统或书面锁定 |

WhatsApp：仅云顶参观场纪要写「后续通过 WhatsApp 群保持沟通」。群原文 **待确认**。

---

## 9. 事前调研时间线

| 日期 | 动作 | 产出 | 标签 |
|------|------|------|------|
| 6/17–29 | Cursor：Switch / Valiram / 云顶 / Ital Auto | 尽调种子 | 事实 |
| 6/23–7/03 | 渠道 118 / 公司种子 / 日报写 1949 | 金山盘点已打开；总抓取 MY75 未分池 | 事实；118/1949 原件待确认 |
| 7/02 | 自动化获客系统培训 | 方法论 | 事实 |
| 7/07 | 印尼+马来进入方案会 | 精品路线、本地化、先跑马来 | 事实 |
| 7/08 | H2 OKR | Genting+Pavilion 155 万 | 目标 |
| 7/13 前 | 4 天行程排期 | SWAP→Pavilion/云顶→KLCC/Switch | 手册 |
| 7/14–16 | 8 场现场 | 见 §7 | 事实 |
| 7/16–28 | KLCC 落位标准分析 | 手册称有 PDF | 原件待确认 |
| 7/20–24 | 话术 · TRX Delia 邮件稿 · DirectD/SWITCH 尽调 | Cursor 有 | 事实 |
| 7/23 | 3C+腕表获客 CSV 30 行 | 原件已找到；净增 13 | 事实 |
| 7/24 | Amy 回邮 | S4 | 事实 |
| 7/30 | TRX 租赁邮件起草 | 发送记录未入库 | 待确认是否已发 |
| 7/31 | KLCC 书面终版 | RM70k 或 15% GTO · 10/12 | 事实 |
| 8/13 | 金山 /S/21 并入 | MY34 净增 17 | 事实 |
| 8/1 后 | Ivan Cursor / Vemory | 空 | 待确认 |

---

## 10. 当地难点（有证据）

| 层 | 难点 | 证据 |
|----|------|------|
| 市场 | 高价机心理门槛；印度裔需「思维教育」 | SWAP 7/14 |
| 市场 | Power/Valiram 专卖店关闭；旧 VR 退出阴影 | SWAP / Pavilion |
| 市场 | 当地手机毛利约 7–8 点 | SWAP 原文 |
| 市场 | 手机不宜与普通 3C 混放 | SWAP |
| 市场 | 本地化/合规（TKDN 等对照） | 7/7 会 |
| 商场 | KLCC 坪效 RM70k/月×面积 | 7/31 书面 |
| 商场 | Pavilion 无现成铺、要主体+材料 | 7/15 |
| 商场 | 云顶仅口头；LV/H 位等租约 | 7/15 |
| 商场 | 提袋率无官方数 | 手册缺口 |
| 谈判 | 装修谁出、premium 不接受长账期 | SWITCH / SWAP |
| 决策 | 经营主体不拍，两条商场线都卡 | 8 月拍板③ |

---

## 11. 本周动作与 8 月拍板

| P | 线索 | 动作 | 完成后 |
|---|------|------|--------|
| P0 | Amy Tan | 资料包 + 线上 MOU 1-pager | S5 |
| P0 | KLCC | ROI 一页纸 + 经营主体书面 | 进场筹备（仍是线索） |
| P0 | Delia Yap | 租赁邮件发出并记日志 | S3 |
| P1 | John Cheah | 30min ROI 会 | S6 或淘汰 |
| P1 | Lovell / Genting | Pavilion 材料 · 口头转 LOI | S6 |
| P1 | Damien / Valiram | probe 发出 | S3 |

不要做：52 条群发。Zahir 等 Damien。Wearnes 先补人。Machines 不重启。

8 月拍板：① DirectD 线上先行 vs SWITCH 双店　② 市区以 KLCC 已锁为准、Pavilion 并行　③ 经营主体。

---

## 12. 越柬系统数据（勿算进马来）

| 指标 | 数值 | 来源 |
|------|------|------|
| 于冰 7 月 SI | ¥1,265,468.52 | 系统；越柬 |
| 于冰 8/1–13 SI | ¥968,982.06 | 系统；越柬 |
| 7 月中（7/17 自报） | ¥640,347 / 58.2% · 在途约 ¥489,787 | PDF |
| 7/26 MTD | 113.21 万 / 102.9% | W30 一部 |
| 核心客户 | VMG、BIN BIN | 非马来 |
| 马来 SI / L2 / 五件套 | 0 | VPS 无马来经销商 |
| 越泰店 7/1–16 | Saigon $8,292；Siam 金额漏报 | PDF · 马来无店 |

`pdca-workbench` store_seed / dealers.json：**无马来正式经销商**。

---

## 13. 仍缺（待确认）

| 缺口 | 影响 |
|------|------|
| WhatsApp 群原文（云顶参观场约定） | 不能当已回复 |
| Amy 以外邮件全文；Amy 邮件除一句外的全文 | 意愿无法完整举证 |
| TRX 邮件是否已发出 | Delia 可能仍停 S2 |
| 总抓取 MY75 未分池 | 不能当已触达 |
| 6/23 118、6/26 MY48、手册 53/100 原件 | 池总量只能写 62+S0 |
| 200+ 台/年无法按国复核 | 标签=假设 |
| 8 月 Cursor / Vemory | 出差后跟进无会议层 |
| KLCC floor plan PDF | 7/13 会称已提供 |
| 评分草案未计入 WhatsApp/财务尽调/90 天 sell-out | 旧稿 78/76 分勿当终审 |

---

## 14. 源文件

| 路径 | 内容 |
|------|------|
| `C:\\Users\\frank\\Desktop\\马来西亚_线索全生命周期_Humanize.html` | 6 页 AST 汇报 |
| `C:\\Users\\frank\\Desktop\\马来西亚_线索全生命周期_BossDeck.html` | 9 页老板稿 |
| 桌面手册（截止 8/5） | `马来西亚市场拓展_客户池与行动手册.html` · 本次桌面未检出，以仓库 HTML LEADS 为准 |
| `overseas_weekly/outputs/马来西亚_线索全生命周期.html` | 32 条看板 |
| `overseas_weekly/outputs/马来西亚_全量数据整理_2026-08-13.md` | 旧稿（S1=22，已被本文更新） |
| `overseas_weekly/inputs/malaysia/2026-07-23_马来西亚3C与腕表渠道_批量获客导入.csv` | 30 行 |
| `overseas_weekly/inputs/malaysia/2026-08-13_kdocs_过往名单总表_Malaysia.csv` | 金山 MY |
| `data_raw/overseas_123_vemory_liu_2026-07-01.json` | 于冰 20 场 |
| `overseas_weekly/outputs/_w3_yubing_pdf.md` | 7/13–17 PDF |
| `overseas_weekly/outputs/_w3_work_from_vemory.json` | W3 8 条 brief |
| `overseas_weekly/outputs/2026-W29_第三周周报_含业务稿.md` | §F |
| `overseas_weekly/outputs/_cursor_ivan_pull.json` | 出差周 Ivan Cursor 空 |

---

*整理：仓库可验证文件。未知标待确认。合同/LOI 需人工复核。*
"""
    )

    OUT.write_text("".join(parts), encoding="utf-8")
    print(f"wrote {OUT} bytes={OUT.stat().st_size} chars={len(''.join(parts))}")


if __name__ == "__main__":
    main()
