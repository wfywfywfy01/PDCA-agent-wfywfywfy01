# VPS/Odoo sandbox script — 海外经销商手机 Sell-out 汇总
# Run with: vertu odoo data sandbox --code-file dealer_monthly_overseas.py --params-file params.json
# params: {"run_date": "2026-07-05", "start_date": "2026-07-01", "end_date": "2026-07-05"}
#
# sell_out / qty / 本月激活 / 累计库存未激活
#
# 本月激活（month_act）与累计激活（all_act）都改用 mobile.activation.report ORM 查询
# （同 dealer_activation_stats.py），替换原来两条 odoo_sale JOIN stock_lot 的慢查询——
# 部门改名修好过滤条件后，这两条 JOIN 因行级权限过滤器叠加，均超过服务端 30 秒查询
# 上限，daily 20:00 同步任务持续超时失败（不止全历史那条，本月区间那条也一样超时）。

DEALER_DEPT_ID = 1569  # 海外渠道（含 经销商一/二/三/新部等子部门，child_of 覆盖全部）

_today = fields.Date.today().strftime("%Y-%m-%d")

run_date   = params.get("run_date")   or _today
start_date = params.get("start_date") or run_date[:8] + "01"
end_date   = params.get("end_date")   or run_date

if end_date > _today:
    end_date = _today

# ── 手机 Sell-out（本月区间） ──────────────────────────────────────────────────
rows = sql_read("""
    SELECT
        "客户名称"      AS dealer_name,
        SUM("实际金额") AS sell_out_yuan,
        SUM("数量")     AS qty
    FROM odoo_sale
    WHERE "销售日期" >= %(start_date)s
      AND "销售日期" <= %(end_date)s
      AND "一级部门"   = '海外渠道'
      AND "二级部门"   LIKE '经销商%%'
      AND "商品大类"   = '手机'
      AND ("退换货类型" IS NULL OR "退换货类型" = '')
    GROUP BY "客户名称"
    ORDER BY SUM("实际金额") DESC
""", {"start_date": start_date, "end_date": end_date})

# ── 本月激活 + 累计激活，一次 ORM 查询算出两口径（替代原本两条 odoo_sale JOIN stock_lot
#    的慢查询——即便本月区间已限定日期，JOIN 仍因行级权限过滤器叠加导致超过 30 秒上限）───
_activation_records = env['mobile.activation.report'].search_read(
    [('department_id', 'child_of', [DEALER_DEPT_ID])],
    ['partner_name', 'activation_state', 'sale_date', 'vsn'],
)
_all_shipped, _all_activated = {}, {}
_month_shipped, _month_activated = {}, {}
for _r in _activation_records:
    _name = (_r.get('partner_name') or '').strip()
    _vsn = _r.get('vsn')
    if not _name or not _vsn:
        continue
    _sd_raw = _r.get('sale_date')
    _sd = _sd_raw.isoformat() if hasattr(_sd_raw, 'isoformat') else (_sd_raw or '')
    _activated = _r.get('activation_state') == 'activated'

    _all_shipped.setdefault(_name, set()).add(_vsn)
    if _activated:
        _all_activated.setdefault(_name, set()).add(_vsn)

    if start_date <= _sd <= end_date:
        _month_shipped.setdefault(_name, set()).add(_vsn)
        if _activated:
            _month_activated.setdefault(_name, set()).add(_vsn)

month_act = [
    {'dealer_name': name, 'month_shipped': len(vsns), 'month_activated': len(_month_activated.get(name, set()))}
    for name, vsns in _month_shipped.items()
]
all_act = [
    {'dealer_name': name, 'total_shipped': len(vsns), 'total_activated': len(_all_activated.get(name, set()))}
    for name, vsns in _all_shipped.items()
]

month_map = {a["dealer_name"]: a for a in month_act}
all_map   = {a["dealer_name"]: a for a in all_act}

for row in rows:
    name = row["dealer_name"]
    ma = month_map.get(name, {})
    aa = all_map.get(name, {})

    ms  = ma.get("month_shipped", 0)   or 0
    mac = ma.get("month_activated", 0) or 0
    ts  = aa.get("total_shipped", 0)   or 0
    tac = aa.get("total_activated", 0) or 0

    row["month_shipped"]        = ms
    row["month_activated"]      = mac
    row["month_not_activated"]  = ms - mac
    row["month_act_rate"]       = round(mac / ms * 100, 1) if ms else 0

    row["total_shipped"]        = ts
    row["total_activated"]      = tac
    row["total_not_activated"]  = ts - tac          # 累计库存未激活
    row["activation_rate"]      = round(tac / ts * 100, 1) if ts else 0

ai["result"] = {
    "start_date": start_date,
    "end_date":   end_date,
    "month":      start_date[:7],
    "total":      len(rows),
    "dealers":    rows,
}
