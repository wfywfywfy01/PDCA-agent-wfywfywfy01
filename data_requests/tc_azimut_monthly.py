rows = sql_read("""
    SELECT
        TO_CHAR(date_order, 'YYYY-MM') AS month,
        SUM(price_subtotal) AS total_untaxed,
        SUM(price_total) AS total_amount,
        COUNT(DISTINCT id) AS line_count
    FROM sale_info_report
    WHERE partner_name ILIKE '%TC Azimut%'
      AND date_order >= '2026-01-01'
      AND date_order < '2027-01-01'
    GROUP BY TO_CHAR(date_order, 'YYYY-MM')
    ORDER BY month
""")
ai['result'] = rows
