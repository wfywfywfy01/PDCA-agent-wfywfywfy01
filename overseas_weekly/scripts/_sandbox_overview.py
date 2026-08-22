# 海外经销商周报取数（自动生成，含销售人员）
CASE_SQL = """CASE
WHEN ("客户名称" ILIKE '%AI-SARAF%' OR "客户名称" ILIKE '%AI SARAF%') THEN 'AI-SARAF CO'
WHEN ("客户名称" ILIKE '%Behzadi%') THEN 'Behzadi Boutique'
WHEN ("客户名称" ILIKE '%Billionaire%') THEN 'Billionaire Collections'
WHEN ("客户名称" ILIKE '%CLICK TECH%') THEN 'CLICK TECH SERVICES'
WHEN ("客户名称" ILIKE '%Dar Al Sabaek%' OR "客户名称" ILIKE '%Sabaek%') THEN 'Dar Al Sabaek'
WHEN ("客户名称" ILIKE '%HASSIB%') THEN 'HASSIB ABDALLAH AMIR ALLAH'
WHEN ("客户名称" ILIKE '%Taher Jasem%' OR "客户名称" ILIKE '%Taher%') THEN 'Taher Jasem'
WHEN ("客户名称" ILIKE '%Luxem%') THEN 'Luxem Store'
WHEN ("客户名称" ILIKE '%Mkateb%') THEN 'Mkateb for e-commerce'
WHEN ("客户名称" ILIKE '%My Shops%' OR "客户名称" ILIKE '%MyShops%') THEN 'My Shops Electronics Trading LLC'
WHEN ("客户名称" ILIKE '%Rashid lukman%' OR "客户名称" ILIKE '%Rashid%') THEN 'Rashid lukman rashid'
WHEN ("客户名称" ILIKE '%Safiranhamrah%' OR "客户名称" ILIKE '%Safiran%') THEN 'Safiranhamrah'
WHEN ("客户名称" ILIKE '%TIVAL%' OR "客户名称" ILIKE '%TİVALİ%' OR "客户名称" ILIKE '%Tivali%') THEN 'TİVALİ Commercial Broker LLC'
WHEN ("客户名称" ILIKE '%Veysel%') THEN 'Veysel Sevis Ltd'
WHEN ("客户名称" ILIKE '%Bestcom%') THEN 'Bestcom'
WHEN ("客户名称" ILIKE '%FRONTANA%') THEN 'FRONTANA GIDA DIS TICARET LIMITED'
WHEN ("客户名称" ILIKE '%IQ-QUEST%' OR "客户名称" ILIKE '%IQ QUEST%') THEN 'IQ-QUEST SP. Z O.O.'
WHEN ("客户名称" ILIKE '%Optimizers%') THEN 'Optimizers d.o.o.'
WHEN ("客户名称" ILIKE '%Robo Trading%') THEN 'Robo Trading Ltd'
WHEN ("客户名称" ILIKE '%VERTU LONDON%') THEN 'VERTU LONDON LTD'
WHEN ("客户名称" ILIKE '%vipconnect%') THEN 'vipconnect.de'
WHEN ("客户名称" ILIKE '%Quantum Reserve%') THEN 'Quantum Reserve'
WHEN ("客户名称" ILIKE '%ECN GmbH%' OR "客户名称" ILIKE '%ECN%') THEN 'ECN GmbH'
WHEN ("客户名称" ILIKE '%GURU ELECTRONICS%') THEN 'GURU ELECTRONICS SINGAPORE PTE LTD'
WHEN ("客户名称" ILIKE '%LZB INDIA%') THEN 'LZB INDIA ELECTRIC PRIVATE LIMITED'
WHEN ("客户名称" ILIKE '%Sidd Senthil%' OR "客户名称" ILIKE '%Senthil%') THEN 'Sidd Senthil'
WHEN ("客户名称" ILIKE '%Parth Kamlesh%' OR "客户名称" ILIKE '%Parth%') THEN 'Parth Kamlesh Doshi'
WHEN ("客户名称" ILIKE '%Sun International%') THEN 'Sun International General Trading'
WHEN ("客户名称" ILIKE '%BIN BIN%') THEN 'BIN BIN INVESTMENT(CAMBODIA) COLTD'
WHEN ("客户名称" ILIKE '%VMG Communication%' OR "客户名称" ILIKE '%VMG%') THEN 'VMG Communication and Technology Joint Stock Company'
WHEN ("客户名称" ILIKE '%VST ECS%' OR "客户名称" ILIKE '%VST%') THEN 'VST ECS (Thailand) Co., Ltd.'
WHEN ("客户名称" ILIKE '%Zmc automotive%' OR "客户名称" ILIKE '%Zmc%') THEN 'Zmc automotive Pte Ltd'
WHEN ("客户名称" ILIKE '%Altyn Zaman%') THEN 'Altyn Zaman H.J.'
WHEN ("客户名称" ILIKE '%Bizcon%') THEN 'Bizcon Group'
WHEN ("客户名称" ILIKE '%CONTINENTAL PLUS%') THEN 'CONTINENTAL PLUS LLC.'
WHEN ("客户名称" ILIKE '%Azimut%' OR "客户名称" ILIKE '%TC Azimut%') THEN 'LLC "TC Azimut"'
WHEN ("客户名称" ILIKE '%LYZHINA%') THEN 'LYZHINA OLGA'
WHEN ("客户名称" ILIKE '%reStore%' OR "客户名称" ILIKE '%restore%') THEN 'reStore'
WHEN ("客户名称" ILIKE '%VERTU AZIA%' OR "客户名称" ILIKE '%AZIA KZ%') THEN 'ТОО "VERTU AZIA KZ"'
ELSE NULL
END"""

def attributed_rows(start, end):
    sql = (
        "SELECT (" + CASE_SQL + ") AS dealer_name, "
        "COALESCE(\"销售人员\", '') AS salesperson, "
        "COALESCE(\"商品大类\", '未分类') AS major, "
        "COALESCE(\"商品细类\", '未分类') AS series, "
        "SUM(COALESCE(\"实际金额\", 0)) AS amount, "
        "COUNT(*) AS lines, "
        "COUNT(DISTINCT \"原订单号\") AS orders "
        "FROM odoo_sale "
        "WHERE \"销售日期\" >= '" + start + "' "
        "AND \"销售日期\" <= '" + end + " 23:59:59' "
        "AND (" + CASE_SQL + ") IS NOT NULL "
        "GROUP BY 1, 2, 3, 4 "
        "ORDER BY amount DESC"
    )
    return sql_read(sql)

result = {}
windows = {
  "week": ("2026-07-20", "2026-07-26"),
  "mtd": ("2026-07-01", "2026-07-26"),
  "prev_month": ("2026-06-01", "2026-06-26"),
  "yoy_mtd": ("2025-07-01", "2025-07-26"),
}
for key, pair in windows.items():
    rows = attributed_rows(pair[0], pair[1])
    result[key] = [{
        "dealer": r.get("dealer_name"),
        "salesperson": r.get("salesperson") or "",
        "major": r.get("major") or "未分类",
        "series": r.get("series") or "未分类",
        "amount": float(r.get("amount") or 0),
        "lines": int(r.get("lines") or 0),
        "orders": int(r.get("orders") or 0),
    } for r in rows]

ai["result"] = result
