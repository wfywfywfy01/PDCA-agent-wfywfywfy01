# VPS/Odoo sandbox script — 经销商 Sell-In 汇总（odoo_sale 表）
# 替代 pull_dealer_sales_month_to_date.py（sale_order_line_report 已被白名单限制）
#
# Run with:
# vertu odoo data sandbox --code-file pull_dealer_sales_odoo_sale.py --params '{"run_date":"2026-06-25"}'

_today = fields.Date.today().strftime("%Y-%m-%d")
run_date = params.get("run_date") or _today
month_start = params.get("start_date") or (run_date[:8] + "01")

dept_where = """
    "一级部门" = '海外渠道'
    AND "二级部门" LIKE '经销商%%'
    AND "订单状态" IN ('sale', 'done')
"""

month_params = {"month_start": month_start, "run_date": run_date}
week_params = {"run_date": run_date}
day_params = {"run_date": run_date}

salesperson_summary = sql_read("""
    SELECT
        COALESCE("销售人员", '(空)') AS salesperson,
        SUM("实际金额") AS performance,
        SUM(COALESCE("数量", 0)) AS quantity,
        COUNT(*) AS line_count
    FROM odoo_sale
    WHERE """ + dept_where + """
      AND "销售日期" >= %(month_start)s
      AND "销售日期" <= %(run_date)s
    GROUP BY "销售人员"
    ORDER BY SUM("实际金额") DESC
""", month_params)

customer_summary = sql_read("""
    SELECT
        COALESCE("客户名称", '(空)') AS partner_name,
        SUM("实际金额") AS performance,
        SUM(COALESCE("数量", 0)) AS quantity,
        COUNT(*) AS line_count
    FROM odoo_sale
    WHERE """ + dept_where + """
      AND "销售日期" >= %(month_start)s
      AND "销售日期" <= %(run_date)s
    GROUP BY "客户名称"
    ORDER BY SUM("实际金额") DESC
""", month_params)

product_summary = sql_read("""
    SELECT
        COALESCE("商品名称", '(空)') AS product_name,
        SUM("实际金额") AS performance,
        SUM(COALESCE("数量", 0)) AS quantity,
        COUNT(*) AS line_count
    FROM odoo_sale
    WHERE """ + dept_where + """
      AND "销售日期" >= %(month_start)s
      AND "销售日期" <= %(run_date)s
    GROUP BY "商品名称"
    ORDER BY SUM("实际金额") DESC
""", month_params)

daily_salesperson_summary = sql_read("""
    SELECT
        COALESCE("销售人员", '(空)') AS salesperson,
        SUM("实际金额") AS performance,
        SUM(COALESCE("数量", 0)) AS quantity,
        COUNT(*) AS line_count
    FROM odoo_sale
    WHERE """ + dept_where + """
      AND "销售日期"::date = %(run_date)s::date
    GROUP BY "销售人员"
    ORDER BY SUM("实际金额") DESC
""", day_params)

week_salesperson_summary = sql_read("""
    SELECT
        COALESCE("销售人员", '(空)') AS salesperson,
        SUM("实际金额") AS performance,
        SUM(COALESCE("数量", 0)) AS quantity,
        COUNT(*) AS line_count
    FROM odoo_sale
    WHERE """ + dept_where + """
      AND "销售日期" >= date_trunc('week', %(run_date)s::date)::date
      AND "销售日期" <= %(run_date)s
    GROUP BY "销售人员"
    ORDER BY SUM("实际金额") DESC
""", week_params)

daily_team_summary = sql_read("""
    SELECT
        COALESCE("三级部门", '(空)') AS team,
        SUM("实际金额") AS performance,
        SUM(COALESCE("数量", 0)) AS quantity,
        COUNT(*) AS line_count
    FROM odoo_sale
    WHERE """ + dept_where + """
      AND "销售日期"::date = %(run_date)s::date
    GROUP BY "三级部门"
    ORDER BY SUM("实际金额") DESC
""", day_params)

week_team_summary = sql_read("""
    SELECT
        COALESCE("三级部门", '(空)') AS team,
        SUM("实际金额") AS performance,
        SUM(COALESCE("数量", 0)) AS quantity,
        COUNT(*) AS line_count
    FROM odoo_sale
    WHERE """ + dept_where + """
      AND "销售日期" >= date_trunc('week', %(run_date)s::date)::date
      AND "销售日期" <= %(run_date)s
    GROUP BY "三级部门"
    ORDER BY SUM("实际金额") DESC
""", week_params)

daily_trend_by_salesperson = sql_read("""
    SELECT
        to_char("销售日期", 'MM-DD') AS day_label,
        COALESCE("销售人员", '(空)') AS salesperson,
        SUM("实际金额") AS performance,
        SUM(COALESCE("数量", 0)) AS quantity
    FROM odoo_sale
    WHERE """ + dept_where + """
      AND "销售日期" >= %(month_start)s
      AND "销售日期" <= %(run_date)s
    GROUP BY to_char("销售日期", 'MM-DD'), "销售人员"
    ORDER BY to_char("销售日期", 'MM-DD'), SUM("实际金额") DESC
""", month_params)

ai["result"] = {
    "source": "vps-cli / odoo_sale / 经销商 sell-in",
    "table": "odoo_sale",
    "run_date": run_date,
    "month_start": month_start,
    "period_start": month_start,
    "scope": "海外渠道 / 经销商",
    "filters": {
        "一级部门": "海外渠道",
        "二级部门": "经销商%",
        "订单状态": ["sale", "done"],
    },
    "summary_mode": True,
    "salesperson_summary": salesperson_summary,
    "customer_summary": customer_summary,
    "product_summary": product_summary,
    "daily_salesperson_summary": daily_salesperson_summary,
    "week_salesperson_summary": week_salesperson_summary,
    "daily_team_summary": daily_team_summary,
    "week_team_summary": week_team_summary,
    "daily_trend_by_salesperson": daily_trend_by_salesperson,
}
