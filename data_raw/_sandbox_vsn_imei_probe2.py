
# stock.lot fields + sample by VSN; search models mentioning imei via ir.model.fields if allowed
fg = env['stock.lot'].fields_get()
lot_fields = sorted(fg.keys())
imei_like = [k for k,v in fg.items() if 'imei' in k.lower() or 'meid' in k.lower() or 'eid' in k.lower() or 'sn' in k.lower() or 'vsn' in k.lower()]

# sample one of our VSNs
vsn = 'V23009735'
lots = env['stock.lot'].search_read(
    ['|', ('name', '=', vsn), ('ref', '=', vsn)] if 'ref' in fg else [('name', '=', vsn)],
    list(fg.keys()),
    limit=3,
)

# try serial_mark related
sm_info = None
if 'serial_mark' in fg:
    sm_info = fg['serial_mark']
    # read serial_mark record if many2one
    if lots and lots[0].get('serial_mark'):
        sm_id = lots[0]['serial_mark'][0] if isinstance(lots[0]['serial_mark'], (list,tuple)) else lots[0]['serial_mark']
        # discover model
        sm_model = sm_info.get('relation')
        if sm_model:
            sm_fg = env[sm_model].fields_get()
            sm_hits = sorted([k for k in sm_fg if 'imei' in k.lower() or 'vsn' in k.lower() or k in ('name','ref')])
            sm_row = env[sm_model].search_read([('id','=',sm_id)], list(sm_fg.keys())[:50], limit=1)
            sm_info = {'model': sm_model, 'hits': sm_hits, 'all_fields': sorted(sm_fg.keys())[:80], 'row': sm_row}

# search ir.model.fields for imei
field_hits = []
try:
    field_hits = env['ir.model.fields'].search_read(
        [('name', 'ilike', 'imei')],
        ['model', 'name', 'field_description', 'ttype', 'relation'],
        limit=40,
    )
except Exception as e:
    field_hits = [{'error': str(e)[:200]}]

ai['result'] = {
    'lot_field_count': len(lot_fields),
    'lot_imei_like': imei_like,
    'lot_fields': lot_fields,
    'lots_for_vsn': lots,
    'serial_mark': sm_info,
    'ir_fields_imei': field_hits,
}
