rows = sql_read("""
    SELECT
        sale_order_number,
        sale_date::date AS sale_date,
        sale_state,
        sale_type,
        is_apportionment,
        performance,
        unit_price,
        quantity,
        financial_reconciliation,
        cny_currency_rate,
        currency_id,
        remark
    FROM sale_order_line_report
    WHERE partner_name ILIKE '%TC Azimut%'
      AND sale_date >= '2026-05-19'
      AND sale_date < '2026-06-01'
      AND sale_state IN ('sale', 'done')
    ORDER BY sale_date
""")
ai['result'] = rows
