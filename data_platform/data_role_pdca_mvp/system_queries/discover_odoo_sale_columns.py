# 探查 odoo_sale 所有列名及一行样本
rows = sql_read("""
    SELECT *
    FROM odoo_sale
    WHERE "二级部门" = '经销商'
    LIMIT 2
""")
ai["result"] = {"sample": rows}
