# 海外经销商门店周报取数（自动生成）
# 区间：2026-07-06 ~ 2026-07-12

WEEK_START = "2026-07-06"
WEEK_END = "2026-07-12"
DEALER_DEPT_ID = 1569

CASE_SQL = """CASE
WHEN ("客户名称" ILIKE '%Billionaire%') THEN 'Billionaire Collections'
WHEN ("客户名称" ILIKE '%AI-SARAF%' OR "客户名称" ILIKE '%AI SARAF%') THEN 'AI-SARAF CO'
WHEN ("客户名称" ILIKE '%Behzadi%') THEN 'Behzadi Boutique'
WHEN ("客户名称" ILIKE '%CLICK TECH%') THEN 'CLICK TECH SERVICES'
WHEN ("客户名称" ILIKE '%Dar Al Sabaek%' OR "客户名称" ILIKE '%Sabaek%') THEN 'Dar Al Sabaek'
WHEN ("客户名称" ILIKE '%HASSIB%') THEN 'HASSIB ABDALLAH AMIR ALLAH'
WHEN ("客户名称" ILIKE '%Luxem%') THEN 'Luxem Store'
WHEN ("客户名称" ILIKE '%Mkateb%') THEN 'Mkateb for e-commerce'
WHEN ("客户名称" ILIKE '%My Shops%' OR "客户名称" ILIKE '%MyShops%') THEN 'My Shops Electronics Trading LLC'
WHEN ("客户名称" ILIKE '%Rashid lukman%') THEN 'Rashid lukman rashid'
WHEN ("客户名称" ILIKE '%Safiranhamrah%' OR "客户名称" ILIKE '%Safiran%') THEN 'Safiranhamrah'
WHEN ("客户名称" ILIKE '%TIVAL%' OR "客户名称" ILIKE '%Tivali%') THEN 'TİVALİ Commercial Broker LLC'
WHEN ("客户名称" ILIKE '%Veysel%') THEN 'Veysel Sevis Ltd'
WHEN ("客户名称" ILIKE '%Bestcom%') THEN 'Bestcom'
WHEN ("客户名称" ILIKE '%FRONTANA%') THEN 'FRONTANA GIDA DIS TICARET LIMITED'
WHEN ("客户名称" ILIKE '%IQ-QUEST%' OR "客户名称" ILIKE '%IQ QUEST%') THEN 'IQ-QUEST SP. Z O.O.'
WHEN ("客户名称" ILIKE '%Optimizers%') THEN 'Optimizers d.o.o.'
WHEN ("客户名称" ILIKE '%Robo Trading%') THEN 'Robo Trading Ltd'
WHEN ("客户名称" ILIKE '%VERTU LONDON%') THEN 'VERTU LONDON LTD'
WHEN ("客户名称" ILIKE '%vipconnect%') THEN 'vipconnect.de'
WHEN ("客户名称" ILIKE '%Quantum Reserve%') THEN 'Quantum Reserve'
WHEN ("客户名称" ILIKE '%ECN GmbH%' OR "客户名称" ILIKE '%ECN%') THEN 'ECN GmbH'
WHEN ("客户名称" ILIKE '%GURU ELECTRONICS%') THEN 'GURU ELECTRONICS SINGAPORE PTE LTD'
WHEN ("客户名称" ILIKE '%LZB INDIA%') THEN 'LZB INDIA ELECTRIC PRIVATE LIMITED'
WHEN ("客户名称" ILIKE '%Sidd Senthil%' OR "客户名称" ILIKE '%Senthil%') THEN 'Sidd Senthil'
WHEN ("客户名称" ILIKE '%Parth Kamlesh%') THEN 'Parth Kamlesh Doshi'
WHEN ("客户名称" ILIKE '%Sun International%') THEN 'Sun International General Trading'
WHEN ("客户名称" ILIKE '%BIN BIN%') THEN 'BIN BIN INVESTMENT(CAMBODIA) COLTD'
WHEN ("客户名称" ILIKE '%VMG Communication%' OR "客户名称" ILIKE '%VMG%') THEN 'VMG Communication and Technology Joint Stock Company'
WHEN ("客户名称" ILIKE '%VST ECS%') THEN 'VST ECS (Thailand) Co., Ltd.'
WHEN ("客户名称" ILIKE '%Zmc automotive%' OR "客户名称" ILIKE '%Zmc%') THEN 'Zmc automotive Pte Ltd'
WHEN ("客户名称" ILIKE '%Altyn Zaman%') THEN 'Altyn Zaman H.J.'
WHEN ("客户名称" ILIKE '%Bizcon%') THEN 'Bizcon Group'
WHEN ("客户名称" ILIKE '%CONTINENTAL PLUS%') THEN 'CONTINENTAL PLUS LLC.'
WHEN ("客户名称" ILIKE '%Azimut%') THEN 'LLC "TC Azimut"'
WHEN ("客户名称" ILIKE '%LYZHINA%') THEN 'LYZHINA OLGA'
WHEN ("客户名称" ILIKE '%reStore%' OR "客户名称" ILIKE '%restore%') THEN 'reStore'
WHEN ("客户名称" ILIKE '%VERTU AZIA%' OR "客户名称" ILIKE '%AZIA KZ%') THEN 'ТОО "VERTU AZIA KZ"'
ELSE NULL
END"""

# 汇总：SI / 销量 / 订单
summary_sql = (
    "SELECT (" + CASE_SQL + ") AS dealer_name, "
    "SUM(COALESCE(\"实际金额\", 0)) AS amount, "
    "SUM(COALESCE(\"数量\", 0)) AS qty, "
    "COUNT(*) AS lines, "
    "COUNT(DISTINCT \"原订单号\") AS orders "
    "FROM odoo_sale "
    "WHERE \"销售日期\" >= '" + WEEK_START + "' "
    "AND \"销售日期\" <= '" + WEEK_END + " 23:59:59' "
    "AND (" + CASE_SQL + ") IS NOT NULL "
    "GROUP BY 1 ORDER BY amount DESC"
)

# 产品明细
product_sql = (
    "SELECT (" + CASE_SQL + ") AS dealer_name, "
    "COALESCE(\"商品细类\", '未分类') AS series, "
    "SUM(COALESCE(\"数量\", 0)) AS qty, "
    "SUM(COALESCE(\"实际金额\", 0)) AS amount "
    "FROM odoo_sale "
    "WHERE \"销售日期\" >= '" + WEEK_START + "' "
    "AND \"销售日期\" <= '" + WEEK_END + " 23:59:59' "
    "AND (" + CASE_SQL + ") IS NOT NULL "
    "GROUP BY 1, 2 "
    "HAVING SUM(COALESCE(\"实际金额\", 0)) > 0 "
    "ORDER BY dealer_name, amount DESC"
)

summary_rows = sql_read(summary_sql)
product_rows = sql_read(product_sql)

# 本周激活（按 sale_date 落在区间内）
_activation_records = env['mobile.activation.report'].search_read(
    [('department_id', 'child_of', [DEALER_DEPT_ID])],
    ['partner_name', 'activation_state', 'sale_date', 'vsn', 'product_name'],
)
week_act = {}
for _r in _activation_records:
    if _r.get('activation_state') != 'activated':
        continue
    _sd_raw = _r.get('sale_date')
    _sd = _sd_raw.isoformat() if hasattr(_sd_raw, 'isoformat') else (_sd_raw or '')
    if not (_sd and WEEK_START <= _sd <= WEEK_END):
        continue
    _name = (_r.get('partner_name') or '').strip()
    if not _name:
        continue
    week_act[_name] = week_act.get(_name, 0) + 1

ai['result'] = {
    'week_start': WEEK_START,
    'week_end': WEEK_END,
    'summary': [{
        'dealer': r.get('dealer_name'),
        'amount': float(r.get('amount') or 0),
        'qty': float(r.get('qty') or 0),
        'lines': int(r.get('lines') or 0),
        'orders': int(r.get('orders') or 0),
    } for r in summary_rows],
    'products': [{
        'dealer': r.get('dealer_name'),
        'series': (r.get('series') or '').replace('<br>', ' ').replace('<br/>', ' '),
        'qty': float(r.get('qty') or 0),
        'amount': float(r.get('amount') or 0),
    } for r in product_rows],
    'activations_raw': week_act,
}
