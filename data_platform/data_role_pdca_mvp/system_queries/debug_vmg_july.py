# 看 VMG 七月销售明细 — 按商品大类拆分
rows = sql_read("""
    SELECT
        "客户名称"   AS dealer_name,
        "商品大类"   AS category,
        SUM("数量")  AS qty,
        SUM("实际金额") AS sell_out_yuan
    FROM odoo_sale
    WHERE "销售日期" >= '2026-07-01'
      AND "销售日期" <= '2026-07-05'
      AND "二级部门" = '经销商'
      AND ("退换货类型" IS NULL OR "退换货类型" = '')
      AND "客户名称" LIKE '%VMG%'
    GROUP BY "客户名称", "商品大类"
    ORDER BY "客户名称", SUM("实际金额") DESC
""")
ai["result"] = {"rows": rows}
