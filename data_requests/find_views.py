rows = sql_read("SELECT viewname FROM pg_views WHERE viewname ILIKE '%sale%' OR viewname ILIKE '%odoo%' ORDER BY viewname")
ai['result'] = rows
