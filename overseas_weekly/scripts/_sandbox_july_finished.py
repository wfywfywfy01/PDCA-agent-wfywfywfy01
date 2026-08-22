# 7月产成品大类图数据 → 写 UTF-8 JSON
# JOIN: odoo_sale.产品编码 = mv_product.default_code
# 过滤: mv_product."产品" = '产成品'

dealer_filter = """(
  s."客户名称" ILIKE '%Billionaire%'
  OR s."客户名称" ILIKE '%AI-SARAF%' OR s."客户名称" ILIKE '%AI SARAF%'
  OR s."客户名称" ILIKE '%Behzadi%'
  OR s."客户名称" ILIKE '%CLICK TECH%'
  OR s."客户名称" ILIKE '%Dar Al Sabaek%' OR s."客户名称" ILIKE '%Sabaek%'
  OR s."客户名称" ILIKE '%HASSIB%'
  OR s."客户名称" ILIKE '%Luxem%'
  OR s."客户名称" ILIKE '%Mkateb%'
  OR s."客户名称" ILIKE '%My Shops%' OR s."客户名称" ILIKE '%MyShops%'
  OR s."客户名称" ILIKE '%Rashid lukman%'
  OR s."客户名称" ILIKE '%Safiranhamrah%' OR s."客户名称" ILIKE '%Safiran%'
  OR s."客户名称" ILIKE '%TIVAL%' OR s."客户名称" ILIKE '%Tivali%'
  OR s."客户名称" ILIKE '%Veysel%'
  OR s."客户名称" ILIKE '%Bestcom%'
  OR s."客户名称" ILIKE '%FRONTANA%'
  OR s."客户名称" ILIKE '%IQ-QUEST%' OR s."客户名称" ILIKE '%IQ QUEST%'
  OR s."客户名称" ILIKE '%Optimizers%'
  OR s."客户名称" ILIKE '%Robo Trading%'
  OR s."客户名称" ILIKE '%VERTU LONDON%'
  OR s."客户名称" ILIKE '%vipconnect%'
  OR s."客户名称" ILIKE '%Quantum Reserve%'
  OR s."客户名称" ILIKE '%ECN GmbH%'
  OR s."客户名称" ILIKE '%GURU ELECTRONICS%'
  OR s."客户名称" ILIKE '%LZB INDIA%'
  OR s."客户名称" ILIKE '%Sidd Senthil%' OR s."客户名称" ILIKE '%Senthil%'
  OR s."客户名称" ILIKE '%Parth Kamlesh%'
  OR s."客户名称" ILIKE '%Sun International%'
  OR s."客户名称" ILIKE '%BIN BIN%'
  OR s."客户名称" ILIKE '%VMG Communication%'
  OR s."客户名称" ILIKE '%VST ECS%'
  OR s."客户名称" ILIKE '%Zmc automotive%' OR s."客户名称" ILIKE '%Zmc%'
  OR s."客户名称" ILIKE '%Altyn Zaman%'
  OR s."客户名称" ILIKE '%Bizcon%'
  OR s."客户名称" ILIKE '%CONTINENTAL PLUS%'
  OR s."客户名称" ILIKE '%Azimut%'
  OR s."客户名称" ILIKE '%LYZHINA%'
  OR s."客户名称" ILIKE '%reStore%'
  OR s."客户名称" ILIKE '%VERTU AZIA%' OR s."客户名称" ILIKE '%AZIA KZ%'
)"""

sql = """
SELECT
  COALESCE(s."商品大类", '未分类') AS major,
  COALESCE(s."商品细类", '未分类') AS series,
  SUM(COALESCE(s."实际金额", 0)) AS amount,
  COUNT(*) AS lines
FROM odoo_sale s
INNER JOIN mv_product vp ON s."产品编码" = vp.default_code
WHERE s."销售日期" >= '2026-07-01'
  AND s."销售日期" <= '2026-07-12 23:59:59'
  AND vp."产品" = '产成品'
  AND COALESCE(vp."定金", '') IS DISTINCT FROM '是'
  AND """ + dealer_filter + """
GROUP BY 1, 2
ORDER BY amount DESC
"""

rows = sql_read(sql)

by_major = {}
presale = 0.0
other_rest = 0.0
series_list = []
for r in rows:
    major = r.get("major") or "未分类"
    series = (r.get("series") or "未分类").replace("<br>", " ").replace("<br/>", " ")
    amt = float(r.get("amount") or 0)
    series_list.append({
        "major": major,
        "series": series,
        "amount": round(amt, 2),
        "lines": int(r.get("lines") or 0),
    })
    if major == "其他":
        if ("预售" in series) or ("虚拟" in series):
            presale += amt
        else:
            other_rest += amt
    else:
        by_major[major] = by_major.get(major, 0.0) + amt

# 对齐截图：主图用「其他（预售虚拟类）」；权益等归「其他（其余）」备查
chart = []
for k, v in sorted(by_major.items(), key=lambda x: -x[1]):
    if v > 0:
        chart.append({"label": k, "amount": round(v, 2)})
if presale > 0:
    chart.append({"label": "其他（预售虚拟类）", "amount": round(presale, 2)})
chart.sort(key=lambda x: -x["amount"])

# 主图：仅金额>0 的大类（截图风格，不含权益服务）
chart_main = [c for c in chart if c["amount"] > 0]

ai["result"] = {
    "period": "2026-07-01 ~ 2026-07-12",
    "filter": "产成品 + 非定金",
    "total_main": round(sum(c["amount"] for c in chart_main), 2),
    "other_rest": round(other_rest, 2),
    "chart": chart_main,
    "series_top": series_list[:10],
}
