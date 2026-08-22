rows = sql_read("""
SELECT *
FROM odoo_sale
WHERE "客户名称" ILIKE '%VMG%'
LIMIT 1
""")
cols = list(rows[0].keys()) if rows else []
ai["result"] = {"cols": cols, "sample": rows[0] if rows else {}}
