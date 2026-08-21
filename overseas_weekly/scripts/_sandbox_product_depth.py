# 产品深度：AF/AQ/Meta2/IOT/清库存 · 按组与代理商（自动窗口由外层写入）
# 口径：dealers CASE 命中 + 实际金额；数量字段=数量

CASE_SQL = """__CASE_SQL__"""
START = "__MTD_START__"
END = "__MTD_END__"
WEEK_START = "__WEEK_START__"
WEEK_END = "__WEEK_END__"

PHONE_SERIES = {
    "af": "%ALPHAFOLD%",
    "aq": "%AGENT Q%",
    "meta2": "%METAVERTU 2%",
    "meta1": "%METAVERTU%",
    "ivertu": "%iVERTU%",
}
IOT_MAJORS = ("腕表", "钢笔", "耳机", "戒指", "手链")
CLEAR_SERIES = ("iVERTU", "METAVERTU")  # 清库存：iVertu + Meta1（排除 Meta2）


def rows_for(start, end):
    sql = (
        "SELECT (" + CASE_SQL + ") AS dealer_name, "
        "COALESCE(\"销售人员\", '') AS salesperson, "
        "COALESCE(\"商品大类\", '未分类') AS major, "
        "COALESCE(\"商品细类\", '未分类') AS series, "
        "SUM(COALESCE(\"实际金额\", 0)) AS amount, "
        "SUM(COALESCE(\"数量\", 0)) AS qty, "
        "COUNT(*) AS lines, "
        "COUNT(DISTINCT \"原订单号\") AS orders "
        "FROM odoo_sale "
        "WHERE \"销售日期\" >= '" + start + "' "
        "AND \"销售日期\" <= '" + end + " 23:59:59' "
        "AND (" + CASE_SQL + ") IS NOT NULL "
        "GROUP BY 1, 2, 3, 4"
    )
    return sql_read(sql)


def pack(rows):
    out = []
    for r in rows:
        out.append({
            "dealer": r.get("dealer_name"),
            "salesperson": r.get("salesperson") or "",
            "major": (r.get("major") or "未分类").replace("<br>", " "),
            "series": (r.get("series") or "未分类").replace("<br>", " "),
            "amount": float(r.get("amount") or 0),
            "qty": float(r.get("qty") or 0),
            "lines": int(r.get("lines") or 0),
            "orders": int(r.get("orders") or 0),
        })
    return out


ai["result"] = {
    "mtd": pack(rows_for(START, END)),
    "week": pack(rows_for(WEEK_START, WEEK_END)),
}
