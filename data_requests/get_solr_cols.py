rows = sql_read("SELECT column_name FROM information_schema.columns WHERE table_name = 'sale_order_line_report' AND column_name ILIKE '%amount%' OR table_name = 'sale_order_line_report' AND column_name ILIKE '%perf%' OR table_name = 'sale_order_line_report' AND column_name ILIKE '%cny%' ORDER BY ordinal_position")
ai['result'] = rows
