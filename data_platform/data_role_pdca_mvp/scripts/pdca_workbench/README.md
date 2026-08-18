# pdca_workbench 包结构说明

原 `scripts/pdca_workbench.py`（约 4400 行单文件）已按域拆分为本包。
同目录的 `pdca_workbench.py` 保留为兼容入口 shim：

- `import pdca_workbench`（如 `pdca-workbench/app/legacy/bridge.py`）解析到本包（同名包优先于同目录 .py 文件）；
- `python pdca_workbench.py` / `python -m pdca_workbench` 均可用，行为不变。

## 拆分方式（刻意的兼容设计）

| 文件 | 职责 |
|---|---|
| `_header.py` | 导入、路径与全局常量 |
| `web.py` | 首页仪表盘 / 驾驶舱 / 走店客流页面与静态资源 |
| `dashboard.py` | 经销商驾驶舱数据聚合 |
| `vps_api.py` | VPS 数据 API（今日计划/待办/会议/任务中心/重要事项） |
| `core.py` | 通用工具：日期、路径、文本读写、转义 |
| `sales.py` | 销售数据查询与研究类查询 |
| `hermes.py` | Hermes 报告路径解析 |
| `logistics.py` | 物流单号解析与承运商官网查询 |
| `csvutil.py` | CSV 读写与公式注入防护（`csv_safe`） |
| `agents.py` | Agent 卡片、技能安装与 Hermes 聊天 |
| `vertu.py` | vertu-cli 命令桥接、IM、Odoo 检索 |
| `identity.py` | VPS 身份解析、日报/待办/OKR 缓存 |
| `delivery.py` | 交付检查、PDCA 待办更新与交付页面渲染 |
| `views.py` | HTML 渲染（问卷、待办、IM、物流、文件浏览） |
| `im.py` | IM 表格渲染 |
| `questionnaire.py` | 每日问卷与待办/物流 CSV 追加 |
| `pipeline.py` | PDCA 日流水线调度 |
| `ui.py` | UI 组件与卡片 |
| `page.py` | 页面外壳 `page()` 与路由参数工具 |
| `routes.py` | Hermes/Agent/输出面板/VPS 页渲染 |
| `home.py` | 首页渲染与 VPS 汇总 |
| `server.py` | HTTP Handler 与 `main()` 入口 |

`__init__.py` 把这些部分以**同一个共享命名空间**（即包模块自身的 `__dict__`）按原文件顺序 exec：

- 函数互相可见、常量共享、无导入环，与拆分前单文件行为逐字节等价（除 `__main__` 守卫移到 shim/`__main__.py`）；
- 运行期 monkeypatch（如 `wb.PORT = ...`）依然生效；
- 后续可逐步把各部分迁移为真正的模块 import，不需要一次性完成。

## 验证方式

拆分时做过以下验证（66/66 测试、API 名称与全局值 100% 对齐、legacy HTTP 服务冒烟 4 个页面 200）。
如需重新拆分，保持本 README 与 `__init__.py` 的 `_PARTS` 顺序一致即可。
