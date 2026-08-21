# 探测是否有其他状态字段 / Inpayment 变体
# 尝试订单状态精确值 + 可能的英文标签字段
sample = sql_read("""
SELECT "订单状态", COUNT(*) AS cnt, SUM(COALESCE("实际金额",0)) AS amt
FROM odoo_sale
WHERE "销售日期" >= '2026-07-01' AND "销售日期" <= '2026-07-12 23:59:59'
  AND "二级部门" IN ('经销商一部','经销商二部','经销商三部')
GROUP BY 1
ORDER BY amt DESC
""")
# partial_payment 金额
pp = sql_read("""
SELECT COUNT(*) AS cnt, SUM(COALESCE("实际金额",0)) AS amt
FROM odoo_sale s
INNER JOIN mv_product vp ON s."产品编码" = vp.default_code
WHERE s."销售日期" >= '2026-07-01' AND s."销售日期" <= '2026-07-12 23:59:59'
  AND s."二级部门" IN ('经销商一部','经销商二部','经销商三部')
  AND vp."产品" = '产成品'
  AND s."订单状态" = 'partial_payment'
""")
ai["result"] = {
    "by_status": [{"st": r.get("订单状态"), "cnt": r.get("cnt"), "amt": float(r.get("amt") or 0)} for r in sample],
    "partial_payment_finished": pp[0] if pp else None,
    "note": "系统可见订单状态仅 sale / partial_payment；Inpayment 若指待付/部分付款，对应 partial_payment",
}
