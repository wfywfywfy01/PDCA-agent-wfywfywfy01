rows = sql_read("SELECT column_name FROM information_schema.columns WHERE table_name = 'dealer_sale_analysis' ORDER BY ordinal_position")
ai['result'] = rows
