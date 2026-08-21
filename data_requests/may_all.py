rows = sql_read("""
    SELECT
        sale_date::date AS sale_date,
        sale_state,
        sale_type,
        SUM(performance) AS performance_cny,
        COUNT(*) AS line_count
    FROM sale_order_line_report
    WHERE partner_name ILIKE '%TC Azimut%'
      AND sale_date >= '2026-05-01'
      AND sale_date < '2026-06-01'
    GROUP BY sale_date::date, sale_state, sale_type
    ORDER BY sale_date
""")
total = sql_read("""
    SELECT SUM(performance) AS total_may
    FROM sale_order_line_report
    WHERE partner_name ILIKE '%TC Azimut%'
      AND sale_date >= '2026-05-01'
      AND sale_date < '2026-06-01'
""")
ai['result'] = {'detail': rows, 'total': total}
