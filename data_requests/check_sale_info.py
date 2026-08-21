rows = sql_read("SELECT column_name FROM information_schema.columns WHERE table_name = 'sale_info_report' ORDER BY ordinal_position")
ai['result'] = rows
