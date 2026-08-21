# 腕表/钢笔/耳机/手链 · 产成品明细（用于分析文案；汇总以用户数为准）

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
  s."商品大类" AS major,
  COALESCE(s."商品细类", '未分类') AS series,
  COALESCE(s."商品名称", '') AS product_name,
  SUM(COALESCE(s."数量", 0)) AS qty,
  SUM(COALESCE(s."实际金额", 0)) AS amount,
  COUNT(*) AS lines
FROM odoo_sale s
INNER JOIN mv_product vp ON s."产品编码" = vp.default_code
WHERE s."销售日期" >= '2026-07-01'
  AND s."销售日期" <= '2026-07-31 23:59:59'
  AND vp."产品" = '产成品'
  AND COALESCE(vp."定金", '') IS DISTINCT FROM '是'
  AND s."商品大类" IN ('腕表', '钢笔', '耳机', '手链')
  AND """ + dealer_filter + """
GROUP BY 1, 2, 3
ORDER BY major, amount DESC
"""

rows = sql_read(sql)

by_major = {}
detail = []
for r in rows:
    major = r.get("major")
    series = (r.get("series") or "").replace("<br>", " ")
    name = r.get("product_name") or ""
    qty = float(r.get("qty") or 0)
    amt = float(r.get("amount") or 0)
    detail.append({
        "major": major,
        "series": series,
        "product_name": name,
        "qty": qty,
        "amount": round(amt, 2),
    })
    if major not in by_major:
        by_major[major] = {"qty": 0.0, "amount": 0.0, "series": {}}
    by_major[major]["qty"] += qty
    by_major[major]["amount"] += amt
    ser = by_major[major]["series"]
    if series not in ser:
        ser[series] = {"qty": 0.0, "amount": 0.0}
    ser[series]["qty"] += qty
    ser[series]["amount"] += amt

summary = {}
for k, v in by_major.items():
    series_list = [
        {"series": sk, "qty": round(sv["qty"], 2), "amount": round(sv["amount"], 2)}
        for sk, sv in sorted(v["series"].items(), key=lambda x: -x[1]["amount"])
    ]
    summary[k] = {
        "qty": round(v["qty"], 2),
        "amount": round(v["amount"], 2),
        "series": series_list,
    }

ai["result"] = {"summary": summary, "detail": detail[:40]}
