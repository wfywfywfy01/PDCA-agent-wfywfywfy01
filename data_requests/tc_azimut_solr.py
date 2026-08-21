rows = sql_read("""
    SELECT
        TO_CHAR(sale_date, 'YYYY-MM') AS month,
        SUM(performance) AS performance_sum,
        SUM(cny_deal_amount) AS cny_deal_sum,
        SUM(cny_total_amount) AS cny_total_sum,
        COUNT(*) AS line_count
    FROM sale_order_line_report
    WHERE partner_name ILIKE '%TC Azimut%'
      AND sale_date >= '2026-01-01'
      AND sale_date < '2027-01-01'
      AND sale_state IN ('sale', 'done')
    GROUP BY TO_CHAR(sale_date, 'YYYY-MM')
    ORDER BY month
""")
ai['result'] = rows
