# -*- coding: utf-8 -*-
"""清理品牌直营店 -> 交付 Excel：Sheet1 剩余名单（已清理），Sheet2 清理说明与拓客策略。"""
import sys, re
from collections import Counter
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

sys.stdout = open(r"D:\经销商PDCA\.tmp_xlsx\bc2.log", "w", encoding="utf-8")
SRC = r"D:\经销商PDCA\.dsh-uploads\session-d315aa5f-ed73-43bb-a652-08d5223aa253\b78b98fb6b0144a0-02_本轮未分配剩余名单.xlsx"
OUT = r"D:\经销商PDCA\deliverables\未分配剩余名单_已清理品牌直营_2026-09-16.xlsx"

NAVY = "FF233649"; BAND = "FFEAF0F6"; GREEN = "FF1E6B3A"; MUTED = "FF6B7C8F"

def F(sz=10, bold=False, color=NAVY):
    return Font(name="Arial", size=sz, bold=bold, color=color)

def FL(color):
    return PatternFill(fill_type="solid", fgColor=color)

AC = Alignment(horizontal="center", vertical="center", wrap_text=True)
AL = Alignment(horizontal="left", vertical="center", wrap_text=True)
ALT = Alignment(horizontal="left", vertical="top", wrap_text=True)


def norm(v):
    if v is None: return ""
    s = " ".join(str(v).split())
    return "" if s.lower() in ("none", "nan", "-", "n/a", "na", "null") else s

def rows_of(ws): return [[norm(c) for c in r] for r in ws.iter_rows(values_only=True)]


wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
raw = rows_of(wb["剩余名单"]); H = raw[0]; BODY = [r for r in raw[1:] if any(r)]
wb.close()
I = {h: j for j, h in enumerate(H)}
def g(r, n):
    j = I.get(n, -1); return r[j] if 0 <= j < len(r) else ""

BRAND = (r"Gucci|Louis Vuitton|Herm[eè]s|Dior|CHANEL|Chanel|Prada|Balenciaga|Bottega Veneta|C[eé]line|CELINE|"
 r"Fendi|Givenchy|LOEWE|Loewe|Saint Laurent|Burberry|Valentino|Versace|Armani|A\|X Armani|Balmain|Chlo[eé]|"
 r"Miu Miu|Berluti|Loro Piana|Moncler|Max Mara|BOSS|HUGO BOSS|BOGGI|Boggi|Zegna|Canali|Brioni|Blackberrys|"
 r"Acne Studios|Coach|Michael Kors|Tory Burch|Kate Spade|Longchamp|Delvaux|MCM|Mulberry|Jimmy Choo|"
 r"Manolo Blahnik|Bally|TUMI|Tumi|RIMOWA|Rimowa|Samsonite|LOJEL|Lojel|ECHOLAC|Echolac|Sacoor Brothers|Sacoor|"
 r"Bonia|Soch|ALDO|Rolex|Cartier|Omega|OMEGA|Patek Philippe|Audemars Piguet|Vacheron Constantin|"
 r"Jaeger-LeCoultre|IWC|Panerai|Hublot|Breitling|TAG Heuer|Tag Heuer|Longines|Rado|Tissot|Swatch|Blancpain|"
 r"Breguet|Chopard|Piaget|Chaumet|Franck Muller|Bell & Ross|Zenith|Oris|Tudor|TUDOR|Seiko|Citizen|Casio|Garmin|"
 r"Bvlgari|Bulgari|Van Cleef|Tiffany & Co\.|Tiffany|APM Monaco|Swarovski|Pandora|Poh Kong|HABIB|Tomei|DeGem|"
 r"Sincere|Hour Glass|Watatime|Cortina|Red Army|Ethos|Lukfook|Gold Boutique|Diamond & Gold|Excella|Swisphy|"
 r"Watch Clinic|Apple|Samsung|HUAWEI|Huawei|Xiaomi|OPPO|vivo|HONOR|Honor|OnePlus|Realme|Sony|Lenovo|Asus|Acer|"
 r"Dell|Microsoft|Leica|Canon|Nikon|Fujifilm|GoPro|DJI|Dyson|Mi Store|MI Store|Fust|Globus")
NAME_IS_BRAND = re.compile(rf"^({BRAND})\b", re.I)
NAME_EQ_BRAND = re.compile(rf"^({BRAND})[\s\-—–|/、]*(Boutique|Store|Shop|Salon|旗舰店|专卖店|精品店|专营店|店)?\s*$", re.I)
STRONG_EXCL = re.compile(
 r"Genius Bar|品牌(工坊|售后|维修评估|服务中心|护理／维修|维修送修|产品售后|保养维修|维修、保养送修|"
 r"维修及送修|官方服务中心|产品维修评估|产品维修咨询|产品售后评估)|本品牌|自有(服饰|品牌|高端礼服)|"
 r"所购|本店(购买|购买)|购买的|品牌及授权渠道购入|品牌官网购买|品牌政策|官方腕表维修|Rolex官方服务中心|"
 r"门店售出|需购买凭证|按购买|保修适用条件按购买|保养送修受理|腕表保养及维修受理|保养咨询|店内售后工坊|品牌授权")
MULTI = re.compile(
 r"独立多品牌|多品牌|非品牌授权|接受其他品牌|依维修品牌及故障评估|具体品牌需评估|品牌需询问|"
 r"接受品牌需询问|适用品牌.*询问|维修品牌评估|不限品牌|具体品牌、材质及型号须评估|具体品牌／型号需评估|"
 r"品牌及型号逐件评估|各品类按门店评估|具体型号需询问|依物品评估|按材质及破损状况评估|"
 r"门店受理的|店铺支持的|适用手机|适用智能手机|按诊断受理|按故障|现场维修|多个品牌|品牌均")
BRANDS_LIST = [b.strip() for b in BRAND.split("|") if b.strip()]

def brand_hits(t):
    tl = (t or "").lower()
    return {b for b in BRANDS_LIST if b.lower().replace("\\", "") in tl}

# 品牌名出现在店名中（词首），如 "TUMI Repair Centre"、"Tiffany & Co."、"Rolex Boutique at Raffi"
BRAND_IN_NAME = re.compile(rf"\b({BRAND})\b", re.I)
def name_has_brand(name):
    """店名里是否含品牌名。用分词精确匹配，避免 ALDO/Aldoby 这类子串误报。"""
    nm = name or ""
    bl = {b.lower().replace("\\", ""): b for b in BRANDS_LIST}
    # 1) 逐词精确
    parts = re.split(r"[\s\-—–|/、（）()]+", nm)
    for p in parts:
        k = p.lower().strip(".,")
        if k in bl:
            return bl[k]
    # 2) 「by 品牌」结构，如 Signature by Tomei — IOI City Mall
    m = re.search(r"\bby\s+([A-Za-z&\.\' ]{2,24}?)(?=\s*[-—–|/、（(]|$)", nm.strip())
    if m and m.group(1).strip().lower() in bl:
        return bl[m.group(1).strip().lower()]
    # 3) 品牌名作为完整词出现在店名任意位置（含括号内）
    low = nm.lower()
    for k, orig in bl.items():
        if len(k) < 4:
            continue
        if re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", low):
            return orig
    # 4) 兜底：店名任意位置含品牌名（处理「Signature by Tomei — IOI City Mall」这类）
    low = nm.lower()
    for k, orig in bl.items():
        if len(k) >= 4 and k in low:
            return orig
    return None

# 人工补充：抓取时店名未带品牌后缀，但实为品牌专营/单一品牌售后的门店
BRAND_OWNED_STORES = re.compile(
 r"^(Montblanc|TUMI|RIMOWA|LOJEL|ECHOLAC|Tiffany|Rolex|Omega|OMEGA|Panerai|Hublot|Breitling|Longines|"
 r"Tissot|Swatch|Chopard|IWC|Rado|Cartier|Breguet|Blancpain|Piaget|Franck Muller|Bell & Ross|"
 r"Signature by Tomei|Poh Kong|HABIB|Tomei|DeGem|Lukfook|Swarovski|Pandora|APM Monaco)", re.I)

# 明确是品牌自营店的服务描述
BRAND_OWNED_DESC = re.compile(
 r"品牌维修受理|品牌售后|品牌授权售后|官方服务中心|官方腕表|RIMOWA旅行箱维修|TUMI箱包维修|"
 r"品牌保养维修|品牌维修、零件及售后服务|授权售后咨询及维修受理|腕表保养维修咨询及送修|"
 r"珠宝及腕表售后咨询|珠宝清洁及维修|珠宝清洁维修及腕表|珠宝清洁、修改及维修|珠宝清洁与维修|"
 r"品牌产品售后|品牌产品维修")

def classify(r):
    name = g(r, "店铺"); svc = g(r, "服务类型"); brand = g(r, "适用品牌／物品")
    blob = f"{name} {svc} {brand}"
    multi = bool(MULTI.search(svc) or MULTI.search(brand))
    strong = bool(STRONG_EXCL.search(svc) or STRONG_EXCL.search(brand))
    nb = brand_hits(brand)
    if BRAND_OWNED_STORES.match(name):
        return "A"
    # 店名含品牌名 且 该店在品牌列/服务描述里围绕该品牌 → 品牌自营/专卖
    hb = name_has_brand(name)
    if hb and (hb.lower() in brand.lower() or BRAND_OWNED_DESC.search(svc)
               or re.search(r"维修|售后|保养|护理|送修", svc)):
        return "A"
    if (NAME_IS_BRAND.match(name) or NAME_EQ_BRAND.match(name)) and not multi:
        return "A"
    if len(nb) == 1 and strong:
        return "A"
    if BRAND_OWNED_DESC.search(svc) and len(nb) <= 1:
        return "A"
    if len(nb) >= 3:
        return "C"
    if len(nb) == 0 and not strong:
        return "C"
    if len(nb) in (1, 2):
        if multi and not strong:
            return "C"
        if NAME_IS_BRAND.match(name) or NAME_EQ_BRAND.match(name):
            return "A"
        return "B"
    if strong and not multi:
        return "A"
    return "C"

tagged = [(classify(r), r) for r in BODY]
A = [r for k, r in tagged if k == "A"]
B = [r for k, r in tagged if k == "B"]
C = [r for k, r in tagged if k == "C"]
print(f"原始 {len(BODY)} | 剔除A {len(A)} | 待定B {len(B)} | 保留C {len(C)}")

wbo = openpyxl.Workbook()
st = wbo.active
st.title = "剩余名单（已清理）"
st.sheet_view.showGridLines = False
KEEP_H = H + ["拓客类型"]
for c, t in enumerate(KEEP_H, 1):
    cell = st.cell(row=1, column=c, value=t)
    cell.font = F(10, True, "FFFFFFFF"); cell.fill = FL(NAVY); cell.alignment = AC
for i, r in enumerate(C):
    for c, v in enumerate(r, 1):
        if v == "": continue
        cell = st.cell(row=2 + i, column=c, value=v)
        cell.font = F(); cell.alignment = ALT
    cell = st.cell(row=2 + i, column=len(KEEP_H), value="多品牌服务商 · 可拓")
    cell.font = F(10, True, GREEN); cell.alignment = AC
st.row_dimensions[1].height = 30
for j, h in enumerate(KEEP_H, 1):
    w = 30
    if h in ("店铺", "适用品牌／物品", "来源链接"): w = 42
    if h in ("综合背调分", "优先级分档", "证据等级", "可触达性", "商场档位", "业务线", "风险扣分",
             "全表名次", "区域归属", "拓客类型"): w = 13
    if h in ("地址", "服务类型", "证据状态（评级依据）", "核验备注"): w = 46
    if h in ("电话", "WhatsApp", "公开邮箱"): w = 26
    st.column_dimensions[get_column_letter(j)].width = w
st.freeze_panes = "C2"
st.auto_filter.ref = f"A1:{get_column_letter(len(KEEP_H))}{len(C) + 1}"

# ---------------- Sheet2 ----------------
sp = wbo.create_sheet("清理说明与拓客策略")
sp.sheet_view.showGridLines = False
row = 1

def put(col, val, font=None, align=None, fill=None, numfmt=None, ws=sp, r=None):
    rr = r if r is not None else row
    c = ws.cell(row=rr, column=col, value=val)
    c.font = font or F()
    c.alignment = align or AL
    if fill: c.fill = FL(fill)
    if numfmt: c.number_format = numfmt
    return c

def section(text, span=6):
    global row
    for c in range(1, span + 1):
        put(c, text if c == 1 else None, F(12, True, "FFFFFFFF"), AL, NAVY)
    sp.merge_cells(start_row=row, start_column=1, end_row=row, end_column=span)
    sp.row_dimensions[row].height = 22
    row += 1

def thead(labels, span=6):
    global row
    for i, t in enumerate(labels, 1):
        put(i, t, F(10, True, "FFFFFFFF"), AC, NAVY)
    for c in range(len(labels) + 1, span + 1):
        put(c, None, F(10, True, "FFFFFFFF"), AC, NAVY)
    sp.row_dimensions[row].height = 19
    row += 1

put(1, "未分配剩余名单 · 品牌直营清理说明与拓客策略", F(15, True), AL)
sp.merge_cells(f"A{row}:F{row}"); sp.row_dimensions[row].height = 30; row += 1
put(1, f"来源：02_本轮未分配剩余名单.xlsx「剩余名单」页 {len(BODY)} 条　｜　清理对象：品牌直营店／品牌专卖店（只服务自家产品，不可能转做 VERTU 经销）", F(9, False, MUTED), AL)
sp.merge_cells(f"A{row}:F{row}"); row += 2

section("一、清理结果")
for i, (lab, val) in enumerate([("原始条数", len(BODY)), ("剔除·品牌直营", len(A)),
                                ("保留·可拓", len(C)), ("待定·单品牌授权", len(B))], 1):
    put(i, lab, F(9, False, MUTED), AC)
    put(i, val, F(20, True, GREEN if i == 3 else NAVY), AC, r=row + 1)
sp.row_dimensions[row].height = 17; sp.row_dimensions[row + 1].height = 32
row += 2
thead(["分类", "条数", "占比", "处置", "原因"])
for i, (tag, n, act, why) in enumerate([
    ("A 品牌直营／品牌专卖店", len(A), "直接剔除",
     "Gucci／LV／Rolex／Apple Store 等品牌自营门店，只受理本品牌商品，供货与售后体系闭环，无经销可能"),
    ("B 单品牌授权服务商", len(B), "建议剔除（可复核）",
     "Apple Premium Reseller、Samsung 授权中心、OPPO／vivo 体验店等，主营单一品牌，转做 VERTU 概率低但非绝对"),
    ("C 多品牌服务商", len(C), "保留·重点拓客",
     "独立维修商、跨品牌服务商、百货／连锁售后柜台，本身已在做多品牌生意，是最优转化对象"),
]):
    fill = BAND if i % 2 else None
    put(1, tag, F(), AL, fill); put(2, n, F(), AC, fill)
    put(3, n / len(BODY), F(), AC, fill, "0.0%")
    put(4, act, F(11, True), AC, fill)
    put(5, why, F(9, False, MUTED), ALT, fill)
    sp.merge_cells(start_row=row, start_column=5, end_row=row, end_column=6)
    sp.row_dimensions[row].height = 32; row += 1
put(1, "合计", F(11, True), AC); put(2, len(BODY), F(11, True), AC)
put(3, 1.0, F(11, True), AC, None, "0.0%")
for c in (4, 5, 6): put(c, None, F(11, True), AC)
row += 2

section("二、为什么品牌直营店必须剔除")
for i, t in enumerate([
    "只修自家：Gucci／LV／Hermès／Dior 等门店的服务是「品牌维修送修接收」——收件后送回品牌工坊或指定售后点，不从外部采购零件、不与第三方分单。",
    "不卖别家：品牌专卖店的商品结构由总部锁定，门店没有引入 VERTU 的采购权与陈列权，店长无权决策。",
    "直接竞品：VERTU 与其母公司产品同属高端手机，属正面竞争，总部不会允许门店代销。",
    "投入产出为零：店长到店员都无决策权，触达等于无效动作，只会消耗线索池和销售的触达次数指标。",
    "为什么会混进来：抓取规则把「商场内提供维修受理的门店」都收录了，未区分品牌自营与第三方。本次按「店名／服务描述／适用品牌」三个字段做了区分。",
]):
    fill = BAND if i % 2 else None
    put(1, f"{i+1}", F(), AC, fill)
    put(2, t, F(9, False, MUTED), ALT, fill)
    sp.merge_cells(start_row=row, start_column=2, end_row=row, end_column=6)
    sp.row_dimensions[row].height = 30; row += 1
row += 1

section("三、这类客户怎么拓：从「门店」转向「同一商场里的其他人」")
put(1, "核心思路：品牌店不是客户，但它所在的商场里，有 5 类人既接触同一批高净值客群、又有决策权或分单权。", F(11, True), ALT)
sp.merge_cells(f"A{row}:F{row}"); row += 1
thead(["拓客对象", "为什么能成", "怎么切入", "优先级"])
for i, (a, b, c, d) in enumerate([
    ("① 多品牌独立维修商", "本身就是多品牌生意，已把「接别家品牌的活」当日常；缺的是高客单价的活儿和高端形象背书。",
     "让他成为 VERTU 指定维修／保养点：给高端机型维修授权＋配件供应＋培训，换取门店陈列位与客户转介绍。", "P0"),
    ("② 奢侈腕表／珠宝服务中心", "客群完全重叠（买百达翡丽的人就是买 VERTU 的人），已有高端服务话术、私密接待间与预约制流程。",
     "联合会员权益：他的 VIP 客户享 VERTU 专属礼遇，VERTU 客户享腕表保养权益，互相导流。", "P0"),
    ("③ 商场方（招商／VIP 客服台）", "商场掌握全部高端租户与 VIP 客户数据，是唯一能一次触达多个品牌的入口，且有招商 KPI。",
     "谈「商场级合作」：VERTU 快闪／专柜＋商场 VIP 活动赞助＋联名礼遇，用商场客户名单做定向邀约。", "P0"),
    ("④ 单品牌授权服务商（本地加盟商）", "很多 Apple Premium Reseller／Samsung 授权中心是本地公司加盟、非品牌直营，老板有决策权、有维修坪效压力。",
     "谈「多品牌柜台」：在他现有店里加一个 VERTU 高端维修／以旧换新柜台，用他现成人流与工位，零租金试跑。", "P1"),
    ("⑤ 品牌店的店员与店长（做 C 端转介绍）", "他们每天接触已成交的高净值客户，本人有转介绍动机；不作 B 端客户，作转介绍人。",
     "设「转介绍激励」：成交一台给固定佣金，走个人渠道。注意：需法务确认合规性后再执行。", "P1"),
]):
    fill = BAND if i % 2 else None
    put(1, a, F(11, True), ALT, fill); put(2, b, F(9, False, MUTED), ALT, fill)
    put(3, c, F(9, False, MUTED), ALT, fill); put(4, d, F(11, True), AC, fill)
    put(5, None, F(9, False, MUTED), ALT, fill); put(6, None, F(9, False, MUTED), ALT, fill)
    sp.merge_cells(start_row=row, start_column=5, end_row=row, end_column=6)
    sp.row_dimensions[row].height = 52; row += 1
row += 1

section("四、清理后的名单怎么用")
for i, t in enumerate([
    f"保留的 {len(C)} 条（C 类）按原「综合背调分」顺序不变，直接在「剩余名单（已清理）」页使用，已加「拓客类型」列。",
    f"B 类 {len(B)} 条建议单独存放、不派销售。若某区域线索实在稀缺，可挑「本地公司运营、非品牌直营」的授权服务商做二次甄别。",
    "触达前必须做两件事：① 拨号验证号码真实性（母表自述未实联）；② 确认该店是否真接非本品牌业务（大量店只做送修接收，不实际维修）。",
    "「服务类型」字段是判断能否合作的关键：出现「送修接收／受理／转送」的多为中间商，出现「现场维修／屏幕电池维修」的才有真维修能力。",
]):
    fill = BAND if i % 2 else None
    put(1, f"{i+1}", F(), AC, fill)
    put(2, t, F(9, False, MUTED), ALT, fill)
    sp.merge_cells(start_row=row, start_column=2, end_row=row, end_column=6)
    sp.row_dimensions[row].height = 32; row += 1

for col, wd in zip("ABCDEF", (26, 40, 40, 10, 22, 22)):
    sp.column_dimensions[col].width = wd

wbo.save(OUT)
print("saved:", OUT)
print("sheets:", wbo.sheetnames)
print("保留:", len(C), "行")
