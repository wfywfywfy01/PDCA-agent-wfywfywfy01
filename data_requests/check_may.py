rows = sql_read("""
    SELECT
        sale_date::date AS sale_date,
        SUM(performance) AS performance_cny,
        COUNT(*) AS line_count
    FROM sale_order_line_report
    WHERE partner_name ILIKE '%TC Azimut%'
      AND sale_date >= '2026-05-01'
      AND sale_date < '2026-06-01'
      AND sale_state IN ('sale', 'done')
    GROUP BY sale_date::date
    ORDER BY sale_date
""")
ai['result'] = rows
