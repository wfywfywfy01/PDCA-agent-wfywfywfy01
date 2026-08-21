# 杨晶晶组（杨晶晶+何海文）7月产成品货品结构

dealer_filter = """(
  s."客户名称" ILIKE '%GURU ELECTRONICS%'
  OR s."客户名称" ILIKE '%LZB INDIA%'
  OR s."客户名称" ILIKE '%Sidd Senthil%' OR s."客户名称" ILIKE '%Senthil%'
  OR s."客户名称" ILIKE '%Parth Kamlesh%'
  OR s."客户名称" ILIKE '%Sun International%'
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
  SUM(COALESCE(s."数量", 0)) AS qty,
  SUM(COALESCE(s."实际金额", 0)) AS amount
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
ai["result"] = {
  "rows": [{
    "major": r.get("major"),
    "series": (r.get("series") or "").replace("<br>", " "),
    "qty": float(r.get("qty") or 0),
    "amount": round(float(r.get("amount") or 0), 2),
  } for r in rows],
  "total": round(sum(float(r.get("amount") or 0) for r in rows), 2),
}
