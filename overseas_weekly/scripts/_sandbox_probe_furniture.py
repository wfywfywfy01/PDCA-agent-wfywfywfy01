# probe furniture majors for overseas dealers in July
sql = """
SELECT COALESCE(\"商品大类\",'') AS major, SUM(COALESCE(\"实际金额\",0)) AS amount, COUNT(*) AS n
FROM odoo_sale
WHERE \"销售日期\" >= '2026-07-01' AND \"销售日期\" <= '2026-07-12 23:59:59'
AND (
  \"客户名称\" ILIKE '%GURU%' OR \"客户名称\" ILIKE '%Azimut%' OR \"客户名称\" ILIKE '%Bizcon%'
  OR \"客户名称\" ILIKE '%Sidd%' OR \"客户名称\" ILIKE '%BIN BIN%' OR \"客户名称\" ILIKE '%VMG%'
  OR \"客户名称\" ILIKE '%Perspect%' OR \"客户名称\" ILIKE '%CONTINENTAL%' OR \"客户名称\" ILIKE '%restore%'
  OR \"商品大类\" ILIKE '%家具%' OR \"商品名称\" ILIKE '%家具%'
)
GROUP BY 1 ORDER BY amount DESC
"""
ai["result"] = [{"major": r.get("major"), "amount": float(r.get("amount") or 0), "n": int(r.get("n") or 0)} for r in sql_read(sql)]
