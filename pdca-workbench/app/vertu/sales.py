# -*- coding: utf-8 -*-
"""通过 vertu CLI 从 Odoo 实时拉取 sell-in / sell-out 数据。

sell-in  (经销商提货) → sale.order ORM _read_group（Frank 的 Personal Orders）
sell-out (经销商终销) → dealer.sale.order ORM search_read（海外经销商终销）
sellin-summary        → sale.order ORM 按 partner_id 分组 + 6 个月趋势
"""
from __future__ import annotations

from datetime import date as _date, timedelta

from app.vertu.client import run_vertu_sandbox

_SELL_IN_CODE = """
start = params['start']
end = params['end']
recs = env['sale.order']._read_group(
    [('date_order', '>=', start + ' 00:00:00'),
     ('date_order', '<=', end + ' 23:59:59'),
     ('state', 'in', ['sale', 'done'])],
    [],
    ['amount_total:sum']
)
total = float(recs[0][0] or 0) if recs else 0.0
ai['result'] = {
    'amount': total,
    'wan': round(total / 10000, 2),
    'note': 'Odoo实时 · sale.order',
}
"""

_SELL_OUT_CODE = """
start = params['start']
end = params['end']
records = env['dealer.sale.order'].search_read(
    [('date', '>=', start), ('date', '<=', end),
     ('state', 'in', ['done', 'confirm'])],
    ['total']
)
total = sum(float(r.get('total') or 0) for r in records)
ai['result'] = {'amount': total, 'count': len(records)}
"""

_SELLIN_SUMMARY_CODE = """
month = params['month']
trend_months = params['trend_months']
curr = trend_months[-1]

groups = env['sale.order']._read_group(
    [('date_order', '>=', curr['start'] + ' 00:00:00'),
     ('date_order', '<',  curr['end']   + ' 00:00:00'),
     ('state', 'in', ['sale', 'done'])],
    ['partner_id'],
    ['amount_total:sum']
)
sorted_groups = sorted(groups, key=lambda r: -(float(r[1] or 0)))

dealers = []
total = 0.0
for i, row in enumerate(sorted_groups):
    partner = row[0]
    amount = float(row[1] or 0)
    total += amount
    dealers.append({
        'rank': i + 1,
        'name': partner.name if partner else '',
        'wan': round(amount / 10000, 2),
        'quantity': 0,
    })

trend = []
for mo in trend_months:
    t_groups = env['sale.order']._read_group(
        [('date_order', '>=', mo['start'] + ' 00:00:00'),
         ('date_order', '<',  mo['end']   + ' 00:00:00'),
         ('state', 'in', ['sale', 'done'])],
        [],
        ['amount_total:sum']
    )
    mo_total = float(t_groups[0][0] or 0) if t_groups else 0.0
    trend.append({'month': mo['label'], 'wan': round(mo_total / 10000, 2)})

ai['result'] = {
    'month': month,
    'total_wan': round(total / 10000, 2),
    'dealers': dealers[:50],
    'has_data': bool(dealers),
    'trend': trend,
}
"""


def _exec_result(data):
    """从 vertu JSON 响应中提取 execution.result。

    sandbox 返回 {validation, execution} (直接结构)；
    skills execute 返回 {ok, result:{ok, result:{validation, execution}}} (双层嵌套)。
    两种结构都支持。
    """
    if not isinstance(data, dict):
        return None

    # 尝试直接结构 (sandbox 命令格式)
    if "execution" in data:
        block = data["execution"]
    # 尝试双层嵌套 (skills execute 格式)
    elif "result" in data:
        inner = data.get("result", {})
        if isinstance(inner, dict) and "result" in inner:
            inner = inner.get("result", {})
        if isinstance(inner, dict) and "execution" in inner:
            block = inner["execution"]
        else:
            return None
    else:
        return None

    if not isinstance(block, dict):
        return None

    err = block.get("error")
    if err:
        raise RuntimeError(
            f"vertu sandbox error [{err.get('phase')}]: {err.get('message')}"
        )
    return block.get("result")


def _date_range(date_text: str, period: str) -> tuple[str, str]:
    today = _date.fromisoformat(date_text) if date_text else _date.today()
    if period in ("day", "today"):
        return str(today), str(today)
    if period == "week":
        start = today - timedelta(days=today.weekday())
        return str(start), str(today)
    if period == "month":
        return str(today.replace(day=1)), str(today)
    if period == "quarter":
        qm = ((today.month - 1) // 3) * 3 + 1
        return str(today.replace(month=qm, day=1)), str(today)
    return str(today), str(today)


def _trend_months(month: str) -> list[dict]:
    """生成最近 6 个月的日期区间（含当月）。"""
    y, m = int(month[:4]), int(month[5:7])
    result = []
    for i in range(5, -1, -1):
        mm, yy = m - i, y
        while mm <= 0:
            mm += 12
            yy -= 1
        m_next = mm + 1 if mm < 12 else 1
        y_next = yy if mm < 12 else yy + 1
        result.append({
            "label": f"{yy:04d}-{mm:02d}",
            "start": f"{yy:04d}-{mm:02d}-01",
            "end": f"{y_next:04d}-{m_next:02d}-01",
        })
    return result


async def fetch_sell_in(date_text: str, period: str = "day") -> dict:
    """Sell-in KPI via sale.order ORM（无 SQL 超时风险）。"""
    start, end = _date_range(date_text, period)
    data = await run_vertu_sandbox(_SELL_IN_CODE, {"start": start, "end": end})
    result = _exec_result(data)
    if result is None:
        raise RuntimeError("vertu sell-in returned no result")
    return result


async def fetch_sell_out(date_text: str, period: str = "day") -> dict:
    """Sell-out KPI 汇总 dealer.sale.order。"""
    start, end = _date_range(date_text, period)
    data = await run_vertu_sandbox(_SELL_OUT_CODE, {"start": start, "end": end})
    result = _exec_result(data)
    if result is None:
        raise RuntimeError("vertu sell-out returned no result")
    return {"amount": result.get("amount", 0)}


async def fetch_sellin_summary(month: str | None = None) -> dict:
    """按经销商汇总当月 sell-in + 6 个月趋势。"""
    if not month:
        month = _date.today().strftime("%Y-%m")
    months = _trend_months(month)
    data = await run_vertu_sandbox(
        _SELLIN_SUMMARY_CODE, {"month": month, "trend_months": months}
    )
    result = _exec_result(data)
    if result is None:
        raise RuntimeError("vertu sellin-summary returned no result")
    return result
