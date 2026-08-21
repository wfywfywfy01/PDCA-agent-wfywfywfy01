# 探测 odoo_sale 状态/二级部门字段，并取样本值

# 试状态列
status_cols = []
for col in ["单据状态", "订单状态", "状态", "state", "payment_state", "invoice_status"]:
    try:
        rows = sql_read(
            'SELECT DISTINCT "' + col + '" AS v FROM odoo_sale '
            "WHERE \"销售日期\" >= '2026-07-01' AND \"销售日期\" <= '2026-07-12 23:59:59' "
            "LIMIT 30"
        )
        status_cols.append({"col": col, "values": [str(r.get("v")) for r in rows]})
    except Exception as e:
        status_cols.append({"col": col, "error": str(e)[:120]})

# 试二级部门
dept_cols = []
for col in ["二级部门", "匹配部门", "部门", "销售部门"]:
    try:
        rows = sql_read(
            'SELECT DISTINCT "' + col + '" AS v FROM odoo_sale '
            "WHERE \"销售日期\" >= '2026-07-01' AND \"销售日期\" <= '2026-07-12 23:59:59' "
            'AND "' + col + "\" ILIKE '%经销商%' "
            "LIMIT 50"
        )
        dept_cols.append({"col": col, "values": [str(r.get("v")) for r in rows]})
    except Exception as e:
        dept_cols.append({"col": col, "error": str(e)[:120]})

# Inpayment 命中哪一列
inpay = []
for col in ["单据状态", "订单状态", "状态", "state", "payment_state"]:
    try:
        rows = sql_read(
            'SELECT COUNT(*) AS cnt FROM odoo_sale '
            "WHERE \"销售日期\" >= '2026-07-01' AND \"销售日期\" <= '2026-07-12 23:59:59' "
            'AND CAST("' + col + "\" AS TEXT) ILIKE '%Inpayment%'"
        )
        inpay.append({"col": col, "cnt": rows[0].get("cnt") if rows else 0})
    except Exception as e:
        inpay.append({"col": col, "error": str(e)[:80]})

ai["result"] = {
    "status_cols": status_cols,
    "dept_cols": dept_cols,
    "inpayment_hits": inpay,
}
