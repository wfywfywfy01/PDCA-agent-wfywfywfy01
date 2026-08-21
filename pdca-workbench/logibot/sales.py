"""按订单号补录单人，再对 IM user_id。"""

from __future__ import annotations

from cli import vertu_cli
from db import list_all, upsert


def pick_salesperson(payload: dict) -> dict | None:
    """从 sales +orders JSON 取销售人员。
    @param {dict} payload
    @returns {dict|None}
    """
    rows = payload.get("rows") or []
    if not rows:
        return None
    row = rows[0]
    name = (row.get("销售人员") or "").strip()
    if not name:
        return None
    ordered = (row.get("下单时间") or "")[:10]
    return {
        "销售人员": name,
        "部门": (row.get("匹配部门") or "").strip(),
        "销售单录单日期": ordered,
    }


def pick_im_user(payload: dict, name: str) -> str | None:
    """姓名精确匹配一条 IM 用户。多名则放弃。
    @param {dict} payload
    @param {str} name
    @returns {str|None}
    """
    users = payload.get("users") or []
    exact = [u for u in users if (u.get("employee_name") or "") == name]
    pool = exact or users
    if len(pool) != 1:
        return None
    uid = pool[0].get("user_id")
    return str(uid) if uid not in (None, "") else None


def lookup_salesperson(order_no: str) -> dict | None:
    """vertu-cli sales +orders。
    @param {str} order_no
    @returns {dict|None}
    """
    data = vertu_cli(
        "sales",
        "+orders",
        "--order-no",
        order_no,
        "--period",
        "this_year",
        "--limit",
        "3",
        "--no-json",
    )
    return pick_salesperson(data)


def lookup_im_user(name: str) -> str | None:
    """vertu-cli im +users。
    @param {str} name
    @returns {str|None}
    """
    data = vertu_cli("im", "+users", "--query", name, "--limit", "10", "--no-json")
    return pick_im_user(data, name)


def match_sales() -> list[dict]:
    """给缺销售人员 / im_user_id 的票补全。同订单只查一次。
    @returns {list}
    """
    order_cache: dict[str, dict | None] = {}
    user_cache: dict[str, str | None] = {}
    out = []
    for row in list_all():
        order = (row.get("订单号") or "").strip()
        if not order:
            continue
        patch = {"顺丰单号": row["顺丰单号"]}
        if not row.get("销售人员"):
            if order not in order_cache:
                try:
                    order_cache[order] = lookup_salesperson(order)
                except Exception as exc:
                    print("sales", order, exc)
                    order_cache[order] = None
            info = order_cache[order]
            if info:
                patch["销售人员"] = info["销售人员"]
                if info.get("部门"):
                    patch["部门"] = info["部门"]
                if info.get("销售单录单日期"):
                    patch["销售单录单日期"] = info["销售单录单日期"]
        name = patch.get("销售人员") or row.get("销售人员") or ""
        if name and not row.get("im_user_id"):
            if name not in user_cache:
                try:
                    user_cache[name] = lookup_im_user(name)
                except Exception as exc:
                    print("im user", name, exc)
                    user_cache[name] = None
            uid = user_cache[name]
            if uid:
                patch["im_user_id"] = uid
        if len(patch) > 1:
            upsert(patch)
            out.append(patch)
    return out
