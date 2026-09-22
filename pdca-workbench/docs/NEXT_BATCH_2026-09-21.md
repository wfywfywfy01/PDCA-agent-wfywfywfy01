# 下一批改动（老板 2026-09-21 拍板）· 队列

全速做完 1-6 后一起合并部署。每项都要：先本地跑真数据出草稿 → 老板确认 → 合并 → 部署。

1. **C转B 也恢复长版**：`scripts/deploy_remote_docker.ps1` 的白名单只有 `PDCA_DUZHAN_COMPACT`，补上 `PDCA_CTOB_COMPACT`（.env 已写 0）。
2. **`vertu-cli` → `vps-work`**：命令探测优先 `vps-work`、回退 `vertu-cli`；覆盖本机脚本/文档；**`mto_ocr._vps_auth` 的 `x-vertu-auth-channel: vertu-cli` 协议头不动**（待确认服务端）。
3. **三档各加一行 MTO 摘要**：`MTO：N 款达标（型号 金额 达标/未满30万）`；读不出写「待确认」；明细图仍只在 08:00 证据 HTML。
4. **调休日工时照常评价**：豁免只给长假（中秋 9/25-27、国庆 10/1-7）。
5. **第 8 节「今日早会待办」**：见 `docs/MEETING_TODOS_SPEC.md`；`scope=group` 只发给对应达标群，`scope=mgmt` 只进 08:00 管理版。
6. **查 `strategy_wa_brief:2026-09-21 failed`**（另一个会话并入 main 的功能）：只诊断、不擅自改其业务逻辑。

已验证现状（2026-09-21）：三追已恢复长版（`duzhan_compact False`）；今天 10:00/15:00 三追 + C转B + 巴黎 10:00 全部 sent；每周备份提醒 W39 已发。
