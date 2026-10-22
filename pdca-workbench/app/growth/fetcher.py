# -*- coding: utf-8 -*-
"""只读抓取 vertu.com 海外站（Shopify）。

国内/阿里云访问 apex `vertu.com` 会被 GeoDNS 解到国内 nginx 跳转 vertu.cn，读不到海外站。
解决：把 TCP 连接钉到 Shopify CDN 的 IP（`www.vertu.com` 解析所得，anycast），
SNI/Host 用主域 `vertu.com`，即可从任意出口直连读海外站全文，无需 VPN 或海外服务器。
"""
from __future__ import annotations

import http.client
import re
import socket
import ssl

HOST = "vertu.com"
FALLBACK_IP = "23.227.38.74"  # Shopify anycast，DNS 不可用时兜底
UA = "Mozilla/5.0 (compatible; VertuGrowthBot/1.0)"
_LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
_MOD_RE = re.compile(r"<lastmod>([^<]+)</lastmod>")
_URL_RE = re.compile(r"<url>(.*?)</url>", re.S)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
_META_RE = re.compile(r'name=["\']description["\'][^>]*content=["\']([^"\']+)', re.I)
_STRIP_RE = re.compile(r"(?is)<(script|style|nav|footer|header|noscript|svg)[^>]*>.*?</\1>")
_TAG_RE = re.compile(r"<[^>]+>")


def _cdn_ip() -> str:
    """取 Shopify CDN IP；DNS 失败时兜底固定 anycast。"""
    try:
        return socket.gethostbyname("www.vertu.com")
    except OSError:
        return FALLBACK_IP


def _path(url: str) -> str:
    """URL → 请求路径（去掉协议与域名）。"""
    return re.sub(r"^https?://[^/]+", "", url) or "/"


def _get(path: str, timeout: int = 20) -> tuple[int, str]:
    """钉 CDN IP + SNI=vertu.com 发起 GET，跟随最多 5 跳同域重定向。"""
    ip = _cdn_ip()
    ctx = ssl.create_default_context()
    status = 0
    for _ in range(5):
        sock = socket.create_connection((ip, 443), timeout)
        tls = ctx.wrap_socket(sock, server_hostname=HOST)
        conn = http.client.HTTPSConnection(HOST, timeout=timeout)
        conn.sock = tls
        try:
            conn.request("GET", path, headers={"User-Agent": UA, "Accept-Language": "en-US,en"})
            resp = conn.getresponse()
            body = resp.read()
            status = resp.status
            if status in (301, 302, 303, 307, 308):
                path = _path(resp.getheader("location") or "") or "/"
                continue
            return status, body.decode("utf-8", "ignore")
        finally:
            conn.close()
    return status, ""


def list_posts(limit: int = 300) -> list[dict]:
    """枚举博客文章与指南，按 lastmod 倒序返回 [{url, lastmod, slug}]。"""
    out: list[dict] = []
    for page in ("/sitemap-posts.xml", "/sitemap-posts.xml?page=2", "/sitemap-seo-guides.xml"):
        _, xml = _get(page)
        for block in _URL_RE.findall(xml):
            loc = _LOC_RE.search(block)
            if not loc:
                continue
            mod = _MOD_RE.search(block)
            url = loc.group(1)
            out.append({"url": url, "lastmod": (mod.group(1)[:10] if mod else ""),
                        "slug": url.rstrip("/").rsplit("/", 1)[-1]})
    out.sort(key=lambda r: r["lastmod"], reverse=True)
    return out[:limit]


def fetch_post(url: str, max_chars: int = 12000) -> dict:
    """抓单篇文章，返回 {url, status, title, meta, words, text}（正文去标签、截断）。"""
    status, html = _get(_path(url))
    title = _TITLE_RE.search(html)
    meta = _META_RE.search(html)
    text = _TAG_RE.sub(" ", _STRIP_RE.sub(" ", html))
    text = re.sub(r"\s+", " ", text).strip()
    return {
        "url": url,
        "status": status,
        "title": (title.group(1).strip() if title else ""),
        "meta": (meta.group(1).strip() if meta else ""),
        "words": len(text.split()),
        "text": text[:max_chars],
    }
