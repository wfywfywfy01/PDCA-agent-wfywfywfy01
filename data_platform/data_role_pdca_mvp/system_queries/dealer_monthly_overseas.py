# VPS/Odoo sandbox script — 海外经销商手机 Sell-out 汇总 + 累计激活率
# Run with: vertu odoo data sandbox --code-file dealer_monthly_overseas.py --params-file params.json
# params: {"run_date": "2026-07-05", "start_date": "2026-07-01", "end_date": "2026-07-05"}
#
# 只统计 商品大类=手机，排除退换货；激活率来自 stock_lot 累计数据

_today = fields.Date.today().strftime("%Y-%m-%d")

run_date   = params.get("run_date")   or _today
start_date = params.get("start_date") or run_date[:8] + "01"
end_date   = params.get("end_date")   or run_date

if end_date > _today:
    end_date = _today

# ── 手机 Sell-out（区间） ───────────────────────────────────────────────────────
rows = sql_read("""
    SELECT
        "客户名称"      AS dealer_name,
        SUM("实际金额") AS sell_out_yuan,
        SUM("数量")     AS qty
    FROM odoo_sale
    WHERE "销售日期" >= %(start_date)s
      AND "销售日期" <= %(end_date)s
      AND "二级部门"   = '经销商'
      AND "商品大类"   = '手机'
      AND ("退换货类型" IS NULL OR "退换货类型" = '')
    GROUP BY "客户名称"
    ORDER BY SUM("实际金额") DESC
""", {"start_date": start_date, "end_date": end_date})

# ── 累计激活率（全量，不受日期限制） ──────────────────────────────────────────────
act_rows = sql_read("""
    SELECT
        s."客户名称" AS dealer_name,
        COUNT(DISTINCT s.vsn)                                             AS shipped_vsn,
        COUNT(DISTINCT CASE WHEN sl.serial_mark = true THEN s.vsn END)   AS activated
    FROM odoo_sale s
    LEFT JOIN stock_lot sl ON sl.name = s.vsn
    WHERE s."二级部门" = '经销商'
      AND s."商品大类" = '手机'
      AND s.vsn IS NOT NULL
      AND s.vsn != ''
      AND s."退换货类型" IS NULL
    GROUP BY s."客户名称"
""", {})

act_map = {}
for a in act_rows:
    act_map[a["dealer_name"]] = a

for row in rows:
    a = act_map.get(row["dealer_name"], {})
    shipped   = a.get("shipped_vsn") or 0
    activated = a.get("activated")   or 0
    row["shipped_vsn"]     = shipped
    row["activated"]       = activated
    row["activation_rate"] = round(activated / shipped * 100, 1) if shipped else 0

ai["result"] = {
    "start_date": start_date,
    "end_date":   end_date,
    "month":      start_date[:7],
    "total":      len(rows),
    "dealers":    rows,
}
