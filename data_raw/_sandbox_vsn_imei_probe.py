
# probe models/fields for vsn <-> imei
cands = []
for model in ['stock.lot', 'stock.production.lot', 'mobile.activation.report', 'serial.mark', 'mobile.serial']:
    try:
        fg = env[model].fields_get()
    except Exception as e:
        cands.append({'model': model, 'error': str(e)[:120]})
        continue
    hits = sorted([k for k in fg if 'imei' in k.lower() or k.lower()=='vsn' or 'serial' in k.lower() or 'name'==k])
    sample = None
    if 'vsn' in fg or any('imei' in k.lower() for k in fg):
        fields = [k for k in ['name','vsn','imei','imei1','imei2','ref','x_imei'] if k in fg][:8]
        try:
            domain = [('vsn','!=',False)] if 'vsn' in fg else []
            if not domain and 'name' in fg:
                domain = [('name','ilike','V')]
            rows = env[model].search_read(domain, fields, limit=2)
            sample = rows
        except Exception as e:
            sample = {'err': str(e)[:160]}
    cands.append({'model': model, 'field_count': len(fg), 'hits': hits[:40], 'sample': sample})

# also sql probe lot tables if available
sql_hits = []
try:
    rows = sql_read("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name IN ('stock_lot','stock_production_lot','mobile_activation_report')
          AND (column_name ILIKE '%imei%' OR column_name ILIKE '%vsn%')
        ORDER BY table_name, column_name
    """)
    sql_hits = rows
except Exception as e:
    sql_hits = [{'error': str(e)[:160]}]

ai['result'] = {'cands': cands, 'sql_hits': sql_hits}
