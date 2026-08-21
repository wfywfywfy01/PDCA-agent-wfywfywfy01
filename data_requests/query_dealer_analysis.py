rows = sql_read("SELECT * FROM dealer_sale_analysis WHERE \"客户名称\" ILIKE '%TC Azimut%' AND \"销售日期\" >= '2026-01-01' AND \"销售日期\" < '2027-01-01' LIMIT 5")
ai['result'] = rows
