# 海外经销客流分析台（含线上经营）

对标文件：`桌面\海外PDCA\对标\线下事业部walk in模块驾驶舱.html`（`index.html`）。

**线上驾驶舱**（OKR 表、各渠道线索、区域堆叠）已并入本页「全局洞察」→ `客流转化总览` 下方；原 `/online-cockpit/` 自动跳转至此。

## 访问

- http://127.0.0.1:8767/walkin-cockpit/?date=2026-06-05
- 线上经营锚点：http://127.0.0.1:8767/walkin-cockpit/#oi-merged

## 数据

- 实时：`/api/walkin?month=YYYY-MM`（工作台暂未接 walkin:api，会回退）
- 静态：本目录 `data/walkin-YYYY-MM.json`（**推荐**）
- 兜底：页面内置 demo 门店/店员数据

### 数据文件（不读 Excel）

| 文件 | 作用 |
|------|------|
| `data/dealer_distribution_reference.json` | **代理商终销表**经销商清单（33 家，已固化） |
| `data/vietnam_store_metrics.json` | 越南 walk-in 参考指标 |
| `data/walkin-YYYY-MM.json` | 驾驶舱加载的数据包 |
| `data/online_channel_reference.json` | 内地门店 OKR + 渠道线索（结构与 Excel 表一致，不读 xlsx） |
| `data/vn_data_collect_reference.json` | 越南四店区域/门店数（来自 Data collecet(5).xlsx，已固化） |

重新生成各月 JSON：

```powershell
python D:\经销商PDCA\data_platform\data_role_pdca_mvp\scripts\build_walkin_bundle.py
```

更新线上渠道/OKR 参考（从 `online_cockpit` 导出，可选）：

```powershell
python D:\经销商PDCA\data_platform\data_role_pdca_mvp\scripts\build_online_channel_reference_once.py
```

更新越南四店区域汇总（可选，一次性读 xlsx）：

```powershell
python D:\经销商PDCA\data_platform\data_role_pdca_mvp\scripts\import_vn_data_collect_reference_once.py
```

若代理商 Excel 有更新，**一次性**导入（可选）：

```powershell
python D:\经销商PDCA\data_platform\data_role_pdca_mvp\scripts\import_dealer_distribution_once.py
python D:\经销商PDCA\data_platform\data_role_pdca_mvp\scripts\build_walkin_bundle.py
```

## 重新同步对标 HTML

```powershell
python D:\经销商PDCA\data_platform\data_role_pdca_mvp\scripts\_copy_walkin_cockpit_once.py
```

复制后重启 `pdca_workbench.py`。
