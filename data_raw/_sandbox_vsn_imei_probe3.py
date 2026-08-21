
vsn = 'V23009735'
models = [
    'vsn.index',
    'vsn.product.manufacture.info',
    'vsn.activation',
    'production.serial.number.line',
    'sale.order.line.report.small',
    'transit.logistics.report',
]
out = []
for model in models:
    try:
        fg = env[model].fields_get()
    except Exception as e:
        out.append({'model': model, 'error': str(e)[:160]})
        continue
    keys = sorted(fg.keys())
    vsn_keys = [k for k in keys if 'vsn' in k.lower() or k in ('name','default_code','imei','imei1','imei2')]
    # build domain
    domain = None
    for vk in ['vsn', 'name', 'vsn_code', 'serial_number']:
        if vk in fg:
            domain = [(vk, '=', vsn)]
            break
    rows = []
    err = None
    if domain:
        try:
            fields = [k for k in keys if 'imei' in k.lower() or 'vsn' in k.lower() or k in ('name','product_id','partner_id','display_name')][:25]
            rows = env[model].search_read(domain, fields, limit=3)
        except Exception as e:
            err = str(e)[:200]
    out.append({
        'model': model,
        'vsn_keys': vsn_keys,
        'imei_keys': [k for k in keys if 'imei' in k.lower()],
        'domain': domain,
        'rows': rows,
        'err': err,
        'field_sample': keys[:40],
    })

ai['result'] = out
