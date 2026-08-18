# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：导入、路径与全局常量
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。
import csv
import html
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse


_SCRIPTS_DIR = Path(__file__).resolve().parent.parent  # 包内 _header.py 的上一级 = scripts/
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
WORKSPACE = _SCRIPTS_DIR.parent
# Docker 部署下 /mvp 与 /repo 是两个独立 bind mount（不再是同一棵目录树的父子关系），
# 优先信任 PDCA_REPO_ROOT；否则按源码仓库里 WORKSPACE 的实际嵌套深度回退。
_env_repo_root = os.environ.get("PDCA_REPO_ROOT", "").strip()
if _env_repo_root:
    REPO_ROOT = Path(_env_repo_root)
else:
    _parents = WORKSPACE.parents
    REPO_ROOT = _parents[1] if len(_parents) > 1 else _parents[0]
