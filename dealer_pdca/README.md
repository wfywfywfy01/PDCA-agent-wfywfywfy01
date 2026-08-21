# 经销商 PDCA 驾驶舱 v1

对标线下事业部 Walk-in 壳（侧栏 + API + snapshot），数据源为 `teams/yang-jingjing` + `scripts/daily-team-check.py`。

## 启动

双击 `启动经销商PDCA驾驶舱.bat`，或：

```powershell
python D:\经销商PDCA\dealer_pdca\api\server.py
```

浏览器打开：**http://127.0.0.1:8766**

## 手动生成 snapshot

```powershell
python D:\经销商PDCA\dealer_pdca\jobs\build_dealer_snapshot.py --date 2026-05-26
```

输出：`dealer_pdca/snapshots/dealer-YYYY-MM-DD.json` 与 `dealer-latest.json`

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/snapshot?date=` | 读取 snapshot |
| POST | `/api/rebuild` body `{"date":"2026-05-26"}` | 重跑 Check 并生成 snapshot |

## 与旧工作台关系

- 旧：`data_platform/.../pdca_workbench.py` → **8765**
- 新：`dealer_pdca/api/server.py` → **8766**（本版重构预览）
