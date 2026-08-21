# 7月达成度分析（收紧口径）
# - 产成品 + 非定金
# - 排除订单状态 Inpayment / partial_payment
# - 二级部门 IN 经销商一部/二部/三部
# - 新品=ALPHAFOLD；IOT=腕表+钢笔+耳机+戒指

dept_filter = """
  s."二级部门" IN ('经销商一部', '经销商二部', '经销商三部')
"""

status_filter = """
  AND COALESCE(s."订单状态", '') NOT ILIKE '%Inpayment%'
  AND COALESCE(s."订单状态", '') NOT ILIKE '%in_payment%'
  AND COALESCE(s."订单状态", '') <> 'partial_payment'
"""

base = """
FROM odoo_sale s
INNER JOIN mv_product vp ON s."产品编码" = vp.default_code
WHERE s."销售日期" >= '2026-07-01'
  AND s."销售日期" <= '2026-07-12 23:59:59'
  AND vp."产品" = '产成品'
  AND COALESCE(vp."定金", '') IS DISTINCT FROM '是'
  AND """ + dept_filter + status_filter

def one(sql):
    rows = sql_read(sql)
    return rows[0] if rows else {}

qty_col = None
for c in ["数量", "销售数量", "产品数量"]:
    try:
        sql_read('SELECT SUM(COALESCE(s."' + c + '",0)) AS q ' + base)
        qty_col = c
        break
    except Exception:
        pass

qty_expr = ('SUM(COALESCE(s."' + qty_col + '",0)) AS qty') if qty_col else "NULL AS qty"

total = one(
    "SELECT SUM(COALESCE(s.\"实际金额\",0)) AS amount, COUNT(*) AS lines, " + qty_expr + base
)
phone = one(
    "SELECT SUM(COALESCE(s.\"实际金额\",0)) AS amount, COUNT(*) AS lines, " + qty_expr
    + base + " AND s.\"商品大类\" = '手机'"
)
alpha = one(
    "SELECT SUM(COALESCE(s.\"实际金额\",0)) AS amount, COUNT(*) AS lines, " + qty_expr
    + base + " AND s.\"商品细类\" ILIKE '%ALPHAFOLD%'"
)
iot_rows = sql_read(
    "SELECT s.\"商品大类\" AS major, SUM(COALESCE(s.\"实际金额\",0)) AS amount, COUNT(*) AS lines, "
    + qty_expr
    + base
    + " AND s.\"商品大类\" IN ('腕表','钢笔','耳机','戒指') GROUP BY 1 ORDER BY amount DESC"
)

# 状态分布校验
st_rows = sql_read(
    "SELECT s.\"订单状态\" AS st, COUNT(*) AS cnt, SUM(COALESCE(s.\"实际金额\",0)) AS amt "
    + base.replace(status_filter, "")  # 含全部状态看排除前
    + " GROUP BY 1 ORDER BY amt DESC"
)

iot_amount = sum(float(r.get("amount") or 0) for r in iot_rows)
iot_lines = sum(int(r.get("lines") or 0) for r in iot_rows)
iot_qty = sum(float(r.get("qty") or 0) for r in iot_rows) if qty_col else None

okr_target = 6950000.0
total_amt = float(total.get("amount") or 0)

ai["result"] = {
    "period": "2026-07-01 ~ 2026-07-12",
    "filter": "产成品+非定金+排除Inpayment/partial_payment+二级部门经销商一二三部",
    "qty_field": qty_col,
    "okr_target": okr_target,
    "status_before_exclude": [
        {"st": r.get("st"), "cnt": int(r.get("cnt") or 0), "amt": round(float(r.get("amt") or 0), 2)}
        for r in st_rows
    ],
    "total": {
        "amount": round(total_amt, 2),
        "lines": int(total.get("lines") or 0),
        "qty": float(total["qty"]) if total.get("qty") is not None else None,
        "rate": round(total_amt / okr_target * 100, 1),
    },
    "phone": {
        "amount": round(float(phone.get("amount") or 0), 2),
        "lines": int(phone.get("lines") or 0),
        "qty": float(phone["qty"]) if phone.get("qty") is not None else None,
    },
    "alphafold": {
        "amount": round(float(alpha.get("amount") or 0), 2),
        "lines": int(alpha.get("lines") or 0),
        "qty": float(alpha["qty"]) if alpha.get("qty") is not None else None,
    },
    "iot": {
        "amount": round(iot_amount, 2),
        "lines": iot_lines,
        "qty": iot_qty,
        "breakdown": [
            {
                "major": r.get("major"),
                "amount": round(float(r.get("amount") or 0), 2),
                "lines": int(r.get("lines") or 0),
                "qty": float(r["qty"]) if r.get("qty") is not None else None,
            }
            for r in iot_rows
        ],
    },
}
