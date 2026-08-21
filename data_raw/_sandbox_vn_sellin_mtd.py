# 越南 Sell-in MTD：总体（经销商名单匹配）vs VMG
# 越南代理名单对齐 overseas_weekly/config/dealers.json 东南亚越南 + VMG/VST等
start_date = params.get("start_date") or "2026-07-01"
end_date = params.get("end_date") or "2026-07-23"
end_ts = end_date + " 23:59:59"

# 越南相关客户：VMG 为主；若有其他越南经销商一并纳入总体
dealer_filter = """(
  "客户名称" ILIKE '%VMG%'
  OR "客户名称" ILIKE '%VST ECS%'
  OR "客户名称" ILIKE '%BIN BIN%'
  OR "客户名称" ILIKE '%Zmc automotive%'
  OR "客户名称" ILIKE '%Zmc%'
)"""

# 注意：越南总体若仅用国家字段不可用，则用东南亚越南经销商名单近似；
# 用户问「越南总体」——以客户名匹配越南市场代理为准。

rows = sql_read("""
SELECT
  COALESCE("客户名称", '') AS partner,
  SUM(COALESCE("实际金额", 0)) AS amount,
  SUM(COALESCE("数量", 0)) AS qty,
  COUNT(*) AS lines,
  COUNT(DISTINCT "原订单号") AS orders
FROM odoo_sale
WHERE "销售日期" >= %(start)s
  AND "销售日期" <= %(end)s
  AND "一级部门" = '海外渠道'
  AND "二级部门" LIKE '经销商%%'
  AND """ + dealer_filter + """
GROUP BY 1
ORDER BY amount DESC
""", {"start": start_date, "end": end_ts})

# 仅越南 VMG vs 越南总体（上述名单）
phone_rows = sql_read("""
SELECT
  CASE WHEN "客户名称" ILIKE '%VMG%' THEN 'VMG' ELSE 'OTHER_SEA_VN_LIST' END AS bucket,
  SUM(COALESCE("实际金额", 0)) AS amount,
  SUM(COALESCE("数量", 0)) AS qty
FROM odoo_sale
WHERE "销售日期" >= %(start)s
  AND "销售日期" <= %(end)s
  AND "一级部门" = '海外渠道'
  AND "二级部门" LIKE '经销商%%'
  AND "商品大类" = '手机'
  AND """ + dealer_filter + """
GROUP BY 1
""", {"start": start_date, "end": end_ts})

all_rows = sql_read("""
SELECT
  CASE WHEN "客户名称" ILIKE '%VMG%' THEN 'VMG' ELSE 'OTHER_SEA_VN_LIST' END AS bucket,
  SUM(COALESCE("实际金额", 0)) AS amount,
  SUM(COALESCE("数量", 0)) AS qty
FROM odoo_sale
WHERE "销售日期" >= %(start)s
  AND "销售日期" <= %(end)s
  AND "一级部门" = '海外渠道'
  AND "二级部门" LIKE '经销商%%'
  AND """ + dealer_filter + """
GROUP BY 1
""", {"start": start_date, "end": end_ts})

# 纯 VMG 全量（不限大类）
vmg_only = sql_read("""
SELECT
  SUM(COALESCE("实际金额", 0)) AS amount,
  SUM(COALESCE("数量", 0)) AS qty,
  COUNT(DISTINCT "原订单号") AS orders
FROM odoo_sale
WHERE "销售日期" >= %(start)s
  AND "销售日期" <= %(end)s
  AND "一级部门" = '海外渠道'
  AND "二级部门" LIKE '经销商%%'
  AND "客户名称" ILIKE '%VMG%'
""", {"start": start_date, "end": end_ts})

# 越南：尝试用客户地址/来源含 Vietnam / 越南
vn_geo = sql_read("""
SELECT
  COALESCE("客户名称", '') AS partner,
  SUM(COALESCE("实际金额", 0)) AS amount,
  SUM(COALESCE("数量", 0)) AS qty
FROM odoo_sale
WHERE "销售日期" >= %(start)s
  AND "销售日期" <= %(end)s
  AND "一级部门" = '海外渠道'
  AND "二级部门" LIKE '经销商%%'
  AND (
    "客户名称" ILIKE '%VMG%'
    OR COALESCE("客户地址",'') ILIKE '%Vietnam%'
    OR COALESCE("客户地址",'') ILIKE '%越南%'
    OR COALESCE("客户来源",'') ILIKE '%Vietnam%'
    OR COALESCE("客户来源",'') ILIKE '%越南%'
  )
GROUP BY 1
ORDER BY amount DESC
""", {"start": start_date, "end": end_ts})

ai["result"] = {
    "period": {"start": start_date, "end": end_date},
    "by_partner_sea_list": [{
        "partner": r.get("partner"),
        "amount": float(r.get("amount") or 0),
        "qty": float(r.get("qty") or 0),
        "lines": int(r.get("lines") or 0),
        "orders": int(r.get("orders") or 0),
    } for r in rows],
    "phone_bucket": [{
        "bucket": r.get("bucket"),
        "amount": float(r.get("amount") or 0),
        "qty": float(r.get("qty") or 0),
    } for r in phone_rows],
    "all_bucket": [{
        "bucket": r.get("bucket"),
        "amount": float(r.get("amount") or 0),
        "qty": float(r.get("qty") or 0),
    } for r in all_rows],
    "vmg_only": {
        "amount": float(vmg_only[0].get("amount") or 0) if vmg_only else 0,
        "qty": float(vmg_only[0].get("qty") or 0) if vmg_only else 0,
        "orders": int(vmg_only[0].get("orders") or 0) if vmg_only else 0,
    },
    "by_partner_vn_geo": [{
        "partner": r.get("partner"),
        "amount": float(r.get("amount") or 0),
        "qty": float(r.get("qty") or 0),
    } for r in vn_geo],
}
