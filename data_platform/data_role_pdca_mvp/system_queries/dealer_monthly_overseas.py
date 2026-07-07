# VPS/Odoo sandbox script — 海外经销商手机 Sell-out 汇总
# Run with: vertu odoo data sandbox --code-file dealer_monthly_overseas.py --params-file params.json
# params: {"run_date": "2026-07-05", "start_date": "2026-07-01", "end_date": "2026-07-05"}
#
# sell_out / qty / 本月激活 / 累计库存未激活

_today = fields.Date.today().strftime("%Y-%m-%d")

run_date   = params.get("run_date")   or _today
start_date = params.get("start_date") or run_date[:8] + "01"
end_date   = params.get("end_date")   or run_date

if end_date > _today:
    end_date = _today

# ── 手机 Sell-out（本月区间） ──────────────────────────────────────────────────
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

# ── 本月售出 VSN 的激活情况 ────────────────────────────────────────────────────
month_act = sql_read("""
    SELECT
        s."客户名称" AS dealer_name,
        COUNT(DISTINCT s.vsn)                                             AS month_shipped,
        COUNT(DISTINCT CASE WHEN sl.serial_mark = true THEN s.vsn END)   AS month_activated
    FROM odoo_sale s
    LEFT JOIN stock_lot sl ON sl.name = s.vsn
    WHERE s."销售日期" >= %(start_date)s
      AND s."销售日期" <= %(end_date)s
      AND s."二级部门" = '经销商'
      AND s."商品大类" = '手机'
      AND s.vsn IS NOT NULL AND s.vsn != ''
      AND (s."退换货类型" IS NULL OR s."退换货类型" = '')
    GROUP BY s."客户名称"
""", {"start_date": start_date, "end_date": end_date})

# ── 累计库存激活情况（all-time，不限日期） ─────────────────────────────────────
all_act = sql_read("""
    SELECT
        s."客户名称" AS dealer_name,
        COUNT(DISTINCT s.vsn)                                             AS total_shipped,
        COUNT(DISTINCT CASE WHEN sl.serial_mark = true THEN s.vsn END)   AS total_activated
    FROM odoo_sale s
    LEFT JOIN stock_lot sl ON sl.name = s.vsn
    WHERE s."二级部门" = '经销商'
      AND s."商品大类" = '手机'
      AND s.vsn IS NOT NULL AND s.vsn != ''
      AND s."退换货类型" IS NULL
    GROUP BY s."客户名称"
""", {})

month_map = {a["dealer_name"]: a for a in month_act}
all_map   = {a["dealer_name"]: a for a in all_act}

for row in rows:
    name = row["dealer_name"]
    ma = month_map.get(name, {})
    aa = all_map.get(name, {})

    ms  = ma.get("month_shipped", 0)   or 0
    mac = ma.get("month_activated", 0) or 0
    ts  = aa.get("total_shipped", 0)   or 0
    tac = aa.get("total_activated", 0) or 0

    row["month_shipped"]        = ms
    row["month_activated"]      = mac
    row["month_not_activated"]  = ms - mac
    row["month_act_rate"]       = round(mac / ms * 100, 1) if ms else 0

    row["total_shipped"]        = ts
    row["total_activated"]      = tac
    row["total_not_activated"]  = ts - tac          # 累计库存未激活
    row["activation_rate"]      = round(tac / ts * 100, 1) if ts else 0

ai["result"] = {
    "start_date": start_date,
    "end_date":   end_date,
    "month":      start_date[:7],
    "total":      len(rows),
    "dealers":    rows,
}
