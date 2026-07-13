# VPS/Odoo sandbox script — 海外经销商激活数据汇总（累计，含本地/异地激活、产品明细）
# Run with: vertu odoo data sandbox --code-file dealer_activation_stats.py
#
# 数据源改为 mobile.activation.report（手机激活报表）——比旧版 stock_lot.serial_mark
# JOIN odoo_sale 更准确、更快，且自带 activation_country（实际激活国家）与
# private_country_id（经销商注册国家），可据此判定本地/异地激活；product_name
# 直接给出产品明细，不需要额外查询。
#
# 本地/异地判定：activation_country 与 private_country_id 的国家名一致 → 本地激活；
# 不一致（且 activation_country 非空）→ 异地激活。两侧存在中英文混用（如"土耳其"
# vs "Turkey"），已按 private_country_id 覆盖到的实际国家列表建了别名表做归一化
# （抽样验证过：不做归一化会把印度经销商 17/93 的本地激活误判成异地，偏差很大）。
# 别名表只覆盖当前海外经销商归属的国家；如果以后新增经销商所在国家不在表里，
# 对应的英文写法激活记录会被保守地算作异地，而不是报错。

DEALER_DEPT_ID = 1569  # 海外渠道（含 经销商一/二/三/新部等子部门，child_of 覆盖全部）

# 国家中文名 → 归一化 key；同一 key 下同时收录常见英文写法
_COUNTRY_ALIASES = {
    '中国': 'CN', 'china': 'CN',
    '乌克兰': 'UA', 'ukraine': 'UA',
    '乌兹别克斯坦': 'UZ', 'uzbekistan': 'UZ',
    '伊拉克': 'IQ', 'iraq': 'IQ',
    '伊朗': 'IR', 'iran': 'IR',
    '俄罗斯联邦': 'RU', '俄罗斯': 'RU', 'russia': 'RU', 'russian federation': 'RU',
    '保加利亚': 'BG', 'bulgaria': 'BG',
    '加纳': 'GH', 'ghana': 'GH',
    '卡塔尔': 'QA', 'qatar': 'QA',
    '印度': 'IN', 'india': 'IN',
    '哈萨克斯坦': 'KZ', 'kazakhstan': 'KZ',
    '土库曼斯坦': 'TM', 'turkmenistan': 'TM',
    '土耳其': 'TR', 'turkey': 'TR',
    '德国': 'DE', 'germany': 'DE',
    '斯洛文尼亚': 'SI', 'slovenia': 'SI',
    '新加坡': 'SG', 'singapore': 'SG',
    '柬埔寨': 'KH', 'cambodia': 'KH',
    '波兰': 'PL', 'poland': 'PL',
    '泰国': 'TH', 'thailand': 'TH',
    '瑞士': 'CH', 'switzerland': 'CH',
    '科威特': 'KW', 'kuwait': 'KW',
    '约旦': 'JO', 'jordan': 'JO',
    '英国': 'GB', 'united kingdom': 'GB', 'uk': 'GB',
    '葡萄牙': 'PT', 'portugal': 'PT',
    '越南': 'VN', 'vietnam': 'VN',
    '阿塞拜疆': 'AZ', 'azerbaijan': 'AZ',
    '阿拉伯联合酋长国': 'AE', 'the united arab emirates': 'AE',
    'united arab emirates': 'AE', 'uae': 'AE',
    '阿根廷': 'AR', 'argentina': 'AR',
}

records = env['mobile.activation.report'].search_read(
    [('department_id', 'child_of', [DEALER_DEPT_ID])],
    ['partner_name', 'product_name', 'activation_state', 'activation_country', 'private_country_id'],
)


def _norm(s):
    return (s or '').strip()


def _country_key(name):
    """国家名归一化 key；中英文都能命中同一个 key，未收录的国家原样返回（互不相等即视为不同国家）。"""
    n = _norm(name)
    return _COUNTRY_ALIASES.get(n.lower(), n)


dealers = {}
products = {}
total_shipped = 0
total_activated = 0
total_local = 0
total_remote = 0

for r in records:
    dealer = r.get('partner_name') or '(未知经销商)'
    d = dealers.setdefault(dealer, {
        'dealer_name': dealer, 'shipped': 0, 'activated': 0, 'not_activated': 0,
        'local_activated': 0, 'remote_activated': 0,
    })
    d['shipped'] += 1
    total_shipped += 1

    state = r.get('activation_state')
    pname = r.get('product_name') or '(未知产品)'
    p = products.setdefault(pname, {'product_name': pname, 'shipped': 0, 'activated': 0})
    p['shipped'] += 1

    if state == 'activated':
        d['activated'] += 1
        p['activated'] += 1
        total_activated += 1
        home = r.get('private_country_id')
        home_name = _norm(home[1]) if home else ''
        act_country = _norm(r.get('activation_country'))
        if act_country and home_name and _country_key(act_country) == _country_key(home_name):
            d['local_activated'] += 1
            total_local += 1
        elif act_country:
            d['remote_activated'] += 1
            total_remote += 1
        # act_country 为空但状态是 activated：数据缺失，不计入本地/异地任一边
    else:
        d['not_activated'] += 1

for d in dealers.values():
    d['activation_rate'] = round(d['activated'] / d['shipped'] * 100, 1) if d['shipped'] else 0
    # 分母用"本地+异地"（已归类的），不能用 activated（含 activation_country 缺失、未归类的记录），
    # 否则本地率会被这些既非本地也非异地的记录系统性拉低
    d_classified = d['local_activated'] + d['remote_activated']
    d['local_activation_rate'] = round(d['local_activated'] / d_classified * 100, 1) if d_classified else 0

dealer_list = sorted(dealers.values(), key=lambda x: -x['activated'])
product_list = sorted(products.values(), key=lambda x: -x['activated'])[:30]

inv_rows = sql_read("""
    SELECT SUM(库存数量) AS total_stock
    FROM mv_inventory
    WHERE 门店库存 = '海外库存'
""", {})
total_stock = inv_rows[0]['total_stock'] if inv_rows else 0

ai['result'] = {
    'dealers': dealer_list,
    'products': product_list,
    'total_overseas_stock': int(total_stock) if total_stock else 0,
    'total_shipped': total_shipped,
    'total_activated': total_activated,
    'total_local_activated': total_local,
    'total_remote_activated': total_remote,
    'overall_activation_rate': round(total_activated / total_shipped * 100, 1) if total_shipped else 0,
    # 同上：分母用已归类的 total_local + total_remote，而非 total_activated
    'overall_local_rate': round(total_local / (total_local + total_remote) * 100, 1) if (total_local + total_remote) else 0,
}
