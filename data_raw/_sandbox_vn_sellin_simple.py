start_date = params.get("start_date") or "2026-07-01"
end_date = params.get("end_date") or "2026-07-23"
end_ts = end_date + " 23:59:59"

rows = sql_read(
    "SELECT COALESCE(\"客户名称\", '') AS partner, "
    "SUM(COALESCE(\"实际金额\", 0)) AS amount, "
    "SUM(COALESCE(\"数量\", 0)) AS qty, "
    "COUNT(DISTINCT \"原订单号\") AS orders "
    "FROM odoo_sale "
    "WHERE \"销售日期\" >= '" + start_date + "' "
    "AND \"销售日期\" <= '" + end_ts + "' "
    "AND \"一级部门\" = '海外渠道' "
    "AND \"二级部门\" LIKE '经销商%' "
    "AND ("
    "\"客户名称\" ILIKE '%VMG%' "
    "OR COALESCE(\"客户地址\",'') ILIKE '%Vietnam%' "
    "OR COALESCE(\"客户地址\",'') ILIKE '%越南%'"
    ") "
    "GROUP BY 1 ORDER BY amount DESC"
)

phone = sql_read(
    "SELECT COALESCE(\"客户名称\", '') AS partner, "
    "SUM(COALESCE(\"实际金额\", 0)) AS amount, "
    "SUM(COALESCE(\"数量\", 0)) AS qty "
    "FROM odoo_sale "
    "WHERE \"销售日期\" >= '" + start_date + "' "
    "AND \"销售日期\" <= '" + end_ts + "' "
    "AND \"一级部门\" = '海外渠道' "
    "AND \"二级部门\" LIKE '经销商%' "
    "AND \"商品大类\" = '手机' "
    "AND ("
    "\"客户名称\" ILIKE '%VMG%' "
    "OR COALESCE(\"客户地址\",'') ILIKE '%Vietnam%' "
    "OR COALESCE(\"客户地址\",'') ILIKE '%越南%'"
    ") "
    "GROUP BY 1 ORDER BY amount DESC"
)

ai["result"] = {
    "period": {"start": start_date, "end": end_date},
    "all": [{
        "partner": r.get("partner"),
        "amount": float(r.get("amount") or 0),
        "qty": float(r.get("qty") or 0),
        "orders": int(r.get("orders") or 0),
    } for r in rows],
    "phone": [{
        "partner": r.get("partner"),
        "amount": float(r.get("amount") or 0),
        "qty": float(r.get("qty") or 0),
    } for r in phone],
}
