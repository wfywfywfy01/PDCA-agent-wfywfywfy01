monthly = sql_read("""
    SELECT
        TO_CHAR(sale_date, 'YYYY-MM') AS month,
        SUM(performance) AS performance_cny,
        COUNT(*) AS line_count
    FROM sale_order_line_report
    WHERE partner_name ILIKE '%TC Azimut%'
      AND sale_date >= '2026-01-01'
      AND sale_date < '2027-01-01'
    GROUP BY TO_CHAR(sale_date, 'YYYY-MM')
    ORDER BY month
""")
total = sql_read("""
    SELECT SUM(performance) AS total_performance
    FROM sale_order_line_report
    WHERE partner_name ILIKE '%TC Azimut%'
      AND sale_date >= '2026-01-01'
      AND sale_date < '2027-01-01'
""")
ai['result'] = {'monthly': monthly, 'total': total}
