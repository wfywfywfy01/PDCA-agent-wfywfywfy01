# 7月商品大类销售额（海外经销商映射）
# 口径对齐周报截图：大类横条；「其他」拆出预售虚拟类

dealer_filter = """(
  "客户名称" ILIKE '%Billionaire%'
  OR "客户名称" ILIKE '%AI-SARAF%' OR "客户名称" ILIKE '%AI SARAF%'
  OR "客户名称" ILIKE '%Behzadi%'
  OR "客户名称" ILIKE '%CLICK TECH%'
  OR "客户名称" ILIKE '%Dar Al Sabaek%' OR "客户名称" ILIKE '%Sabaek%'
  OR "客户名称" ILIKE '%HASSIB%'
  OR "客户名称" ILIKE '%Luxem%'
  OR "客户名称" ILIKE '%Mkateb%'
  OR "客户名称" ILIKE '%My Shops%' OR "客户名称" ILIKE '%MyShops%'
  OR "客户名称" ILIKE '%Rashid lukman%'
  OR "客户名称" ILIKE '%Safiranhamrah%' OR "客户名称" ILIKE '%Safiran%'
  OR "客户名称" ILIKE '%TIVAL%' OR "客户名称" ILIKE '%Tivali%'
  OR "客户名称" ILIKE '%Veysel%'
  OR "客户名称" ILIKE '%Bestcom%'
  OR "客户名称" ILIKE '%FRONTANA%'
  OR "客户名称" ILIKE '%IQ-QUEST%' OR "客户名称" ILIKE '%IQ QUEST%'
  OR "客户名称" ILIKE '%Optimizers%'
  OR "客户名称" ILIKE '%Robo Trading%'
  OR "客户名称" ILIKE '%VERTU LONDON%'
  OR "客户名称" ILIKE '%vipconnect%'
  OR "客户名称" ILIKE '%Quantum Reserve%'
  OR "客户名称" ILIKE '%ECN GmbH%'
  OR "客户名称" ILIKE '%GURU ELECTRONICS%'
  OR "客户名称" ILIKE '%LZB INDIA%'
  OR "客户名称" ILIKE '%Sidd Senthil%' OR "客户名称" ILIKE '%Senthil%'
  OR "客户名称" ILIKE '%Parth Kamlesh%'
  OR "客户名称" ILIKE '%Sun International%'
  OR "客户名称" ILIKE '%BIN BIN%'
  OR "客户名称" ILIKE '%VMG Communication%' OR "客户名称" ILIKE '%VMG%'
  OR "客户名称" ILIKE '%VST ECS%'
  OR "客户名称" ILIKE '%Zmc automotive%' OR "客户名称" ILIKE '%Zmc%'
  OR "客户名称" ILIKE '%Altyn Zaman%'
  OR "客户名称" ILIKE '%Bizcon%'
  OR "客户名称" ILIKE '%CONTINENTAL PLUS%'
  OR "客户名称" ILIKE '%Azimut%'
  OR "客户名称" ILIKE '%LYZHINA%'
  OR "客户名称" ILIKE '%reStore%' OR "客户名称" ILIKE '%restore%'
  OR "客户名称" ILIKE '%VERTU AZIA%' OR "客户名称" ILIKE '%AZIA KZ%'
)"""

# 明细：大类 + 细类，便于把「其他」拆成预售虚拟类等
detail_sql = """
SELECT
  COALESCE("商品大类", '未分类') AS major,
  COALESCE("商品细类", '未分类') AS series,
  SUM(COALESCE("实际金额", 0)) AS amount,
  COUNT(*) AS lines
FROM odoo_sale
WHERE "销售日期" >= '2026-07-01'
  AND "销售日期" <= '2026-07-12 23:59:59'
  AND """ + dealer_filter + """
GROUP BY 1, 2
ORDER BY amount DESC
"""

rows = sql_read(detail_sql)

# 聚合大类；对「其他」按截图口径标注预售虚拟类
by_major = {}
presale = 0.0
other_rest = 0.0
series_list = []
for r in rows:
    major = r.get("major") or "未分类"
    series = (r.get("series") or "未分类").replace("<br>", " ").replace("<br/>", " ")
    amt = float(r.get("amount") or 0)
    series_list.append({"major": major, "series": series, "amount": round(amt, 2), "lines": int(r.get("lines") or 0)})
    if major == "其他":
        if "预售" in series or "虚拟" in series:
            presale += amt
        else:
            other_rest += amt
    else:
        by_major[major] = by_major.get(major, 0.0) + amt

# 截图口径：把「其他（预售虚拟类）」作为独立横条；其余其他细类若有金额另列
chart = []
for k, v in by_major.items():
    if v > 0:
        chart.append({"label": k, "amount": round(v, 2)})
if presale > 0:
    chart.append({"label": "其他（预售虚拟类）", "amount": round(presale, 2)})
if other_rest > 0:
    chart.append({"label": "其他（其余）", "amount": round(other_rest, 2)})

chart.sort(key=lambda x: x["amount"], reverse=True)
total = round(sum(c["amount"] for c in chart), 2)

ai["result"] = {
    "period": "2026-07-01 ~ 2026-07-12",
    "total": total,
    "chart": chart,
    "series_top": series_list[:15],
}
