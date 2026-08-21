# 于冰组 W2 明细：找与 PPT 47.58万 的差额
CASE_SQL = """
CASE
WHEN ("客户名称" ILIKE '%BIN BIN%') THEN 'BIN BIN'
WHEN ("客户名称" ILIKE '%VMG Communication%' OR "客户名称" ILIKE '%VMG%') THEN 'VMG'
WHEN ("客户名称" ILIKE '%VST ECS%' OR "客户名称" ILIKE '%VST%') THEN 'VST'
WHEN ("客户名称" ILIKE '%Zmc automotive%' OR "客户名称" ILIKE '%Zmc%') THEN 'Zmc'
ELSE NULL
END
"""

def rows(start, end):
    sql = (
        "SELECT "
        "(" + CASE_SQL + ") AS dealer, "
        "\"销售日期\"::date AS d, "
        "COALESCE(\"商品大类\",'') AS major, "
        "COALESCE(\"商品细类\",'') AS series, "
        "COALESCE(\"商品名称\",'') AS sku, "
        "COALESCE(\"实际金额\",0) AS amount, "
        "COALESCE(\"原订单号\",'') AS order_no, "
        "COALESCE(\"销售人员\",'') AS salesperson "
        "FROM odoo_sale "
        "WHERE \"销售日期\" >= '" + start + "' "
        "AND \"销售日期\" <= '" + end + " 23:59:59' "
        "AND (" + CASE_SQL + ") IS NOT NULL "
        "ORDER BY amount DESC"
    )
    return sql_read(sql)

week = rows("2026-07-06", "2026-07-12")
mtd = rows("2026-07-01", "2026-07-12")
ai["result"] = {
    "week": [{
        "dealer": r.get("dealer"),
        "d": str(r.get("d")),
        "major": r.get("major"),
        "series": (r.get("series") or "").replace("<br>", " ")[:40],
        "sku": (r.get("sku") or "")[:50],
        "amount": float(r.get("amount") or 0),
        "order_no": r.get("order_no"),
        "salesperson": r.get("salesperson"),
    } for r in week],
    "week_sum": sum(float(r.get("amount") or 0) for r in week),
    "mtd_sum": sum(float(r.get("amount") or 0) for r in mtd),
}
