# -*- coding: utf-8 -*-
"""页面 HTML 辅助：共享顶栏注入。"""
from __future__ import annotations

import re

from fastapi.responses import HTMLResponse


def inject_vue_shell(html: str) -> str:
    """将公共顶栏注入任意合法的 body 起始标签之后。"""
    if "pdca-shell-root" in html:
        return html
    shell = (
        '<div id="pdca-shell-root"></div>'
        '<link rel="stylesheet" href="/shared/shell.css" />'
        '<script type="module" src="/shared/shell.js?v=3"></script>'
    )
    return re.sub(r"(<body\b[^>]*>)", lambda match: match.group(1) + shell, html, count=1, flags=re.IGNORECASE)


_NO_CACHE_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate"}


def html_page(content: str) -> HTMLResponse:
    """返回注入顶栏后的 HTML 页面，禁止浏览器缓存（页面内容会随部署更新）。"""
    return HTMLResponse(inject_vue_shell(content), headers=_NO_CACHE_HEADERS)
