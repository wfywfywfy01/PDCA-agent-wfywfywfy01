# -*- coding: utf-8 -*-
"""通过 vertu CLI 从 Odoo 实时拉取 sell-in / sell-out 数据。

sell-in  (各销售业绩，如杨晶晶/何海文等) → odoo_sale SQL 视图，按销售日期区间求和
                「一级部门」='海外渠道' AND 「二级部门」LIKE '经销商%'
sell-out (代理商终端销售，卖给最终消费者) → dealer.sale.order ORM search_read（经销商自行
                录入的终端销售单，数据量天然偏少——多数经销商并未持续在此录入）
sellin-summary        → sale.order ORM 按 partner_id 分组 + 6 个月趋势（另一独立指标，未改）

排错记录（2026-07-11）：曾误判 sql_read 对 odoo_sale 有行级权限阻塞（付汪阳只能看自己），
实测账号对「海外渠道」部门树有完整读权限（792 条/¥617万，覆盖全体销售）。真正原因是部门
命名变更：「海外事业部」→「海外渠道」，「经销商」→「经销商一/二/三部」，旧的精确匹配
WHERE 条件（pull_dealer_sales_odoo_sale.py / dealer_monthly_overseas.py 用的旧名）从此
静默匹配 0 行，导致每日 20:00 的 sync_dealer_sales_from_vps 定时同步任务实际失效多日而
无人察觉。sell-in 已按新部门名重写；sell-out 语义上就是不同的表（dealer.sale.order），与
部门改名无关。
"""
from __future__ import annotations

from datetime import date as _date, timedelta

from app.vertu.client import run_vertu_sandbox

_SELL_IN_CODE = """
start = params['start']
end = params['end']
rows = sql_read('''
    SELECT SUM("实际金额") AS total, COUNT(*) AS cnt
    FROM odoo_sale
    WHERE "销售日期" >= %(start)s
      AND "销售日期" <= %(end)s
      AND "一级部门" = '海外渠道'
      AND "二级部门" LIKE '经销商%%'
''', {'start': start, 'end': end})
total = float(rows[0]['total'] or 0) if rows else 0.0
count = int(rows[0]['cnt'] or 0) if rows else 0
ai['result'] = {'amount': total, 'count': count}
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


_PERIOD_LABEL = {"day": "今日", "today": "今日", "week": "本周", "month": "本月", "quarter": "本季度"}


async def fetch_sell_in(date_text: str, period: str = "day") -> dict:
    """Sell-in KPI：海外渠道/经销商各部销售业绩汇总，按 day/week/month/quarter 区分区间。"""
    start, end = _date_range(date_text, period)
    data = await run_vertu_sandbox(_SELL_IN_CODE, {"start": start, "end": end})
    result = _exec_result(data)
    if result is None:
        raise RuntimeError("vertu sell-in returned no result")
    amount = float(result.get("amount", 0) or 0)
    label = _PERIOD_LABEL.get(period, "今日")
    return {
        "amount": amount,
        "wan": round(amount / 10000, 2),
        "note": f"{label} Odoo实时 · odoo_sale",
    }


async def fetch_sell_out(date_text: str, period: str = "day") -> dict:
    """Sell-out KPI 汇总 dealer.sale.order（代理商终端销售，经销商自行录入），
    按 day/week/month/quarter 区分区间。数据天然偏少，见模块顶部说明。
    """
    start, end = _date_range(date_text, period)
    data = await run_vertu_sandbox(_SELL_OUT_CODE, {"start": start, "end": end})
    result = _exec_result(data)
    if result is None:
        raise RuntimeError("vertu sell-out returned no result")
    amount = float(result.get("amount", 0) or 0)
    label = _PERIOD_LABEL.get(period, "今日")
    return {
        "amount": amount,
        "wan": round(amount / 10000, 2),
        "note": f"{label} Odoo实时 · dealer.sale.order",
    }


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
