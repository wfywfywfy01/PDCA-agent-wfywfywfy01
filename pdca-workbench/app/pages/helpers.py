# -*- coding: utf-8 -*-
"""页面 HTML 辅助：Vue 顶栏注入。"""
from __future__ import annotations

from fastapi.responses import HTMLResponse


def inject_vue_shell(html: str) -> str:
    """注入 Vue 3 公共顶栏。"""
    if "pdca-shell-root" in html:
        return html
    shell = (
        '<div id="pdca-shell-root"></div>'
        '<link rel="stylesheet" href="/shared/shell.css" />'
        '<script type="module" src="/shared/shell.js?v=2"></script>'
    )
    return html.replace("<body>", "<body>" + shell, 1)


def html_page(content: str) -> HTMLResponse:
    """返回注入顶栏后的 HTML 页面。"""
    return HTMLResponse(inject_vue_shell(content))
