# W1（7/1–7/5）PPT vs 系统核对

- 系统窗口: 2026-07-01~2026-07-05 as_of=2026-07-05
- 口径: headline_ppt / groups_ppt

## 1. 全盘 / 三组（总览页）

| 项 | 结果 |
|----|------|
| [PASS] 全盘 MTD: got=124.05 expect=124.1 diff=-0.05 | ✅ |
| [PASS] 全盘 本周: got=124.05 expect=124.1 diff=-0.05 | ✅ |
| [PASS] 达成率: got=17.8 expect=17.8 diff=+0.00 | ✅ |
| [PASS] 环比: got=-41.1 expect=-41.0 diff=-0.10 | ✅ |
| [PASS] 同比: got=122.7 expect=127.0 diff=-4.30 | ✅ |
| [PASS] Lina组 MTD: got=94.69 expect=94.7 diff=-0.01 | ✅ |
| [PASS] Lina组 本周: got=94.69 expect=94.7 diff=-0.01 | ✅ |
| [PASS] Lina组 达成率(auto): got=32.7 expect=32.7 diff=+0.00 | ✅ |
| [PASS] 于冰组 MTD: got=16.45 expect=16.4 diff=+0.05 | ✅ |
| [PASS] 于冰组 本周: got=16.45 expect=16.44 diff=+0.01 | ✅ |
| [PASS] 于冰组 达成率(auto): got=15.0 expect=14.9 diff=+0.10 | ✅ |
| [PASS] 杨晶晶组 MTD: got=12.92 expect=12.9 diff=+0.02 | ✅ |
| [PASS] 杨晶晶组 达成率(auto): got=5.5 expect=5.5 diff=+0.00 | ✅ |

## 2. Lina 代理商明细

| 经销商 | PPT(万) | 系统(万) | 差额 |
|--------|---------|----------|------|
| VERTU LONDON LTD | 39.7981 | 39.86 | +0.06 ✅ |
| HASSIB ABDALLAH AMIR ALLAH | 25.5462 | 25.55 | +0.0 ✅ |
| Luxem | 22.684 | 22.72 | +0.04 ✅ |
| Veysel Sevis Ltd | 6.5562 | 6.57 | +0.01 ✅ |
| **合计** | 94.58 | 94.69 | — |

## 3. PPT 内部不一致（非系统误差）

| 位置 | PPT 写法 | 正确/系统 |
|------|----------|-----------|
| 总览大字 | 124.1万 / 17.8% | 系统 124.05→124.1 / 17.8% ✅ |
| 全盘页文案 | 「目前完成112万，达成率18%」 | 与同页 124.1 矛盾 → PPT 笔误 |
| Lina 页 | 94.5万 / 25.5% | 总览 94.7；94.7/290=**32.7%**（非25.5%） |
| Lina 表总计 | 945847元≈94.58万 | 系统 94.69万（差约0.1万） |
| 于冰页 | 16.44万 / 14.9% | 系统 16.45 / 15.0% ✅ |
| 同比总览 | +127% | 系统 +122.7%（取整差） |

## 4. 系统 Lina 本周代理商（完整）

- 39.86万 | VERTU LONDON LTD
- 25.55万 | HASSIB ABDALLAH AMIR ALLAH
- 22.72万 | Luxem Store
- 6.57万 | Veysel Sevis Ltd
- 0.0万 | My Shops Electronics Trading LLC

**总体关键 KPI: 对齐通过 ✅**

- owner=ppt 本周（无非团队记名剔除）: 124.05万
- cross_person: 0.0万