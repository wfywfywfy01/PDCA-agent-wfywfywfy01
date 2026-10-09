# -*- coding: utf-8 -*-
"""筛掉「无可用联系方式」的 66 条，产出最终可派名单。

- 主表「剩余名单」：只留 806 条（原 29 列不变）
- 新增「排除_无联系方式」sheet：留痕 66 条，便于回溯补号
- 「剩余概览」页追加本次筛选说明
"""
import sys, re, shutil
from collections import Counter
import openpyxl
from openpyxl.styles import Font

sys.stdout = open(r"D:\经销商PDCA\.tmp_xlsx\filter.log", "w", encoding="utf-8")

SRC = r"C:\Users\frank\Desktop\02_本轮未分配剩余名单_已清理品牌直营.xlsx"
OUT = r"C:\Users\frank\Desktop\02_本轮未分配剩余名单_可派名单.xlsx"
PKF = ("国家／地区", "商场", "店铺", "服务类型", "电话")


def norm(v):
    if v is None: return ""
    s = " ".join(str(v).split())
    return "" if s.lower() in ("none", "nan", "-", "n/a", "na", "null") else s
def dialable(t): return bool(t) and len(re.sub(r"\D", "", t)) >= 7


wb = openpyxl.load_workbook(SRC)
ws = wb["剩余名单"]
H = [norm(ws.cell(row=1, column=c).value) for c in range(1, ws.max_column + 1)]
I = {h: j + 1 for j, h in enumerate(H)}
total = ws.max_row - 1
print(f"输入：{SRC}")
print(f"  数据行 {total} / 列 {len(H)}")

# 判定：三字段全空 + 或标签为无可用联系方式
drop_rows, keep_rows = [], []
for r in range(2, ws.max_row + 1):
    tel = norm(ws.cell(row=r, column=I["电话"]).value)
    wa = norm(ws.cell(row=r, column=I["WhatsApp"]).value)
    ml = norm(ws.cell(row=r, column=I["公开邮箱"]).value)
    tag = norm(ws.cell(row=r, column=I["可触达性"]).value)
    if (not dialable(tel) and not dialable(wa) and not ml) or tag.startswith("无可用联系方式"):
        drop_rows.append(r)
    else:
        keep_rows.append(r)
print(f"  待排除 {len(drop_rows)} 行 / 保留 {len(keep_rows)} 行")

# 先把要排除的行内容抓出来（删除后就没法读了）
drop_data = [[ws.cell(row=r, column=c).value for c in range(1, len(H) + 1)] for r in drop_rows]

# 删除排除行（倒序）
for r in reversed(drop_rows):
    ws.delete_rows(r, 1)
print(f"  删除后数据行 = {ws.max_row - 1}")
ws.auto_filter.ref = f"A1:{openpyxl.utils.get_column_letter(len(H))}{ws.max_row}"

# ---- 新增排除页 ----
if "排除_无联系方式" in wb.sheetnames:
    del wb["排除_无联系方式"]
ps = wb.create_sheet("排除_无联系方式")
for j, h in enumerate(H, 1):
    c = ps.cell(row=1, column=j, value=h)
    c.font = Font(bold=True)
for i, row in enumerate(drop_data):
    for j, v in enumerate(row, 1):
        ps.cell(row=2 + i, column=j, value=v)
ps.freeze_panes = "A2"
for j, w in enumerate((10, 12, 10, 40, 16, 12, 12, 10, 8, 10, 12, 14, 30, 30, 34, 16, 30, 28, 22, 16, 20, 40, 40, 40, 22, 30, 14, 20, 24), 1):
    ps.column_dimensions[openpyxl.utils.get_column_letter(j)].width = w

# ---- 概览页追加说明 ----
ov = wb["剩余概览"]
r = ov.max_row + 2
ov.cell(row=r, column=1, value="本轮可派名单筛选（无联系方式剔除）").font = Font(bold=True)
r += 1
for lab, val in [
    ("筛选规则", "电话 / WhatsApp / 公开邮箱 三个字段全空的记录，不派销售"),
    ("筛选前", f"{total} 条"),
    ("筛选后", f"{len(keep_rows)} 条（本表「剩余名单」页）"),
    ("已移出", f"{len(drop_rows)} 条（见「排除_无联系方式」页，可回溯补号）"),
    ("说明", f"被移出的 {len(drop_rows)} 条全部为 P4 低优先，均无可用联系方式（含 0800 PHONEZONE 这类字母号码），触达无从下手"),
]:
    ov.cell(row=r, column=1, value=lab)
    ov.cell(row=r, column=2, value=val)
    r += 1
ov.auto_filter.ref = f"A1:B{ov.max_row}"

wb.save(OUT)
print(f"\n已保存：{OUT}")
print("sheets =", openpyxl.load_workbook(OUT, read_only=True).sheetnames)

# ---- 复核 ----
wb2 = openpyxl.load_workbook(OUT, read_only=True, data_only=True)
w2 = wb2["剩余名单"]
rows2 = [[norm(c) for c in r] for r in w2.iter_rows(values_only=True)]
H2 = [h for h in rows2[0] if h]
B2 = [r[:len(H2)] for r in rows2[1:] if any(r)]
I2 = {h: j for j, h in enumerate(H2)}
w3 = wb2["排除_无联系方式"]
rows3 = [[norm(c) for c in r] for r in w3.iter_rows(values_only=True)]
B3 = [r for r in rows3[1:] if any(r)]
wb2.close()

print("\n" + "=" * 70); print("复核"); print("=" * 70)
print(f"  表头一致 = {H == H2}  （{len(H2)} 列）")
print(f"  剩余名单 = {len(B2)} 行")
print(f"  排除页  = {len(B3)} 行")
print(f"  两页相加 = {len(B2)+len(B3)} （原 {total}）")
bad = [r for r in B2 if not (dialable(r[I2['电话']]) or dialable(r[I2['WhatsApp']]) or r[I2['公开邮箱']])]
print(f"  剩余名单里仍有空联系方式的 = {len(bad)}")
print("\n  剩余名单 可触达性分布:")
for k, v in Counter(r[I2["可触达性"]] for r in B2).most_common():
    print(f"     {v:>4}  {k}")
print("\n  剩余名单 优先级分布:")
for k, v in Counter(r[I2["优先级分档"]] for r in B2).most_common():
    print(f"     {v:>4}  {k}")
print("\n  剩余名单 区域分布:")
for k, v in Counter(r[I2["区域归属"]] for r in B2).most_common():
    print(f"     {v:>4}  {k}")
print("\n  剩余名单 国家 Top10:")
for k, v in Counter(r[I2["国家／地区"]] for r in B2).most_common(10):
    print(f"     {v:>4}  {k}")
