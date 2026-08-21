channels = sql_read("""
    SELECT "渠道", "二级部门", "销售人员", COUNT(*) AS cnt, SUM(COALESCE("数量", 0)) AS qty
    FROM odoo_sale
    WHERE "销售人员" = 'DEHDAHOUMAIMA'
    GROUP BY "渠道", "二级部门", "销售人员"
    ORDER BY COUNT(*) DESC
""", {})
return_types = sql_read("""
    SELECT "退换货类型", "渠道", COUNT(*) AS cnt, SUM(COALESCE("数量", 0)) AS qty
    FROM odoo_sale
    WHERE "销售人员" = 'DEHDAHOUMAIMA'
    GROUP BY "退换货类型", "渠道"
    ORDER BY COUNT(*) DESC
""", {})
sample_cols = sql_read("SELECT * FROM odoo_sale WHERE \"销售人员\" = 'DEHDAHOUMAIMA' LIMIT 1", {})
ai["result"] = {
    "channels": channels,
    "return_types": return_types,
    "columns": list(sample_cols[0].keys()) if sample_cols else [],
}
