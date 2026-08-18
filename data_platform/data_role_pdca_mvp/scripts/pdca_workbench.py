#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""兼容入口 shim。

实现已按域拆分到同目录的 pdca_workbench/ 包：
- `import pdca_workbench`（app/legacy/bridge.py、build_static_demo_package.py）
  会解析到同名包（包优先于本文件）；
- `python pdca_workbench.py` 直接运行本文件，转发到包入口，行为与原脚本一致。
"""
if __name__ == "__main__":
    from pdca_workbench import main

    main()
