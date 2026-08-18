# -*- coding: utf-8 -*-
"""PDCA 数据岗位工作台（按域拆分）。

原 pdca_workbench.py（4400+ 行单文件）按域拆分为本包：
  - _header
  - web
  - dashboard
  - vps_api
  - core
  - sales
  - hermes
  - logistics
  - csvutil
  - agents
  - vertu
  - identity
  - delivery
  - im
  - questionnaire
  - pipeline
  - ui
  - page
  - routes
  - home
  - views
  - server

加载机制：所有部分以【同一个共享命名空间】按原文件顺序 exec——
这个命名空间就是本包模块自己的 __dict__。因此：
- 函数互相可见、常量共享、无导入环，行为与拆分前单文件完全一致；
- 函数 __globals__ 与模块属性读写是同一个 dict，运行期对
  `wb.PORT = ...`、`wb.webbrowser.open = ...` 这类 monkeypatch 依然生效。
这是刻意的兼容选择：legacy 脚本没有直接测试覆盖，先保证行为零变化；
后续可逐步把各部分迁移为真正的模块 import。
"""
from pathlib import Path

_PARTS = ("_header.py", "web.py", "dashboard.py", "vps_api.py", "core.py", "sales.py", "hermes.py", "logistics.py", "csvutil.py", "agents.py", "vertu.py", "identity.py", "delivery.py", "im.py", "questionnaire.py", "pipeline.py", "ui.py", "page.py", "routes.py", "home.py", "views.py", "server.py")

_here = Path(__file__).resolve().parent
_g = globals()
_original_file = _g.get("__file__")
# _header.py 用 __file__ 推导 _SCRIPTS_DIR；exec 不会自动注入，这里显式提供
_g["__file__"] = str(_here / "_header.py")
try:
    for _part in _PARTS:
        _source = (_here / _part).read_text(encoding="utf-8")
        exec(compile(_source, str(_here / _part), "exec"), _g)
finally:
    if _original_file is not None:
        _g["__file__"] = _original_file
    for _internal in ("_PARTS", "_here", "_part", "_source", "_original_file", "_internal"):
        _g.pop(_internal, None)
    del _g
