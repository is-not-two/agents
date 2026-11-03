"""Outbound web search with a fixed provider allowlist and normalized results.

No user-supplied URL is ever fetched: only the configured provider endpoint is
called. Results are untrusted text and must never change agent permissions.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from rag_tech_retriever.domains.life_planning import DomainError
from rag_tech_retriever.platform.http_tools import is_private_host

TAVILY_URL = "https://api.tavily.com/search"
DUCKDUCKGO_URL = "https://html.duckduckgo.com/html/"
BING_URL = "https://cn.bing.com/search"
USER_AGENT = "Mozilla/5.0 (compatible; ShilieResearch/1.0; +local-operator)"
MAX_RESPONSE_BYTES = 1_048_576


class SearchError(Exception):
    """Safe, user-facing failure without provider bodies or credentials."""


class _NoRedirect(HTTPRedirectHandler):
    """Do not follow redirects; a provider must stay on its fixed endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _DuckDuckGoParser(HTMLParser):
    """Tolerant parser for the public HTML result page; no JavaScript required."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict] = []
        self.snippets: list[str] = []
        self._link: dict | None = None
        self._snippet: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag not in {"a", "div", "span"}:
            return
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if tag == "a" and "result__a" in classes and values.get("href"):
            self._link = {"href": values["href"], "title": []}
        elif "result__snippet" in classes:
            self._snippet = []

    def handle_data(self, data):
        if self._link is not None:
            self._link["title"].append(data)
        if self._snippet is not None:
            self._snippet.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._link is not None:
            title = " ".join("".join(self._link["title"]).split())
            href = self._link["href"]
            if title and href:
                self.links.append({"title": title, "href": href})
            self._link = None
        if self._snippet is not None and tag in {"a", "div", "span"}:
            text = " ".join("".join(self._snippet).split())
            if text:
                self.snippets.append(text)
            self._snippet = None


def _decode_duckduckgo_url(href: str) -> str | None:
    """DuckDuckGo wraps outbound links in /l/?uddg=; return the real target."""
    if href.startswith("//"):
        href = "https:" + href
    parts = urlsplit(href)
    if parts.netloc in {"duckduckgo.com", "html.duckduckgo.com"} and parts.path.startswith("/l/"):
        target = parse_qs(parts.query).get("uddg", [""])[0]
        return target or None
    return href


def _safe_url(url: object) -> str | None:
    """Only absolute public HTTP(S) results without credentials or fragments."""
    if not isinstance(url, str) or len(url) > 2048:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if (parts.scheme not in {"http", "https"} or not parts.hostname
            or parts.username or parts.password or is_private_host(parts.hostname)):
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


class WebSearch:
    """Provider adapter + bounded cache. Disabled by default until configured."""

    def __init__(self, config: dict | None, env: Callable[..., str | None]) -> None:
        config = config or {}
        if not isinstance(config, dict):
            raise DomainError("联网搜索配置必须为对象")
        self.enabled = config.get("enabled", False)
        self.provider = config.get("provider", "duckduckgo")
        self.api_key_env = config.get("api_key_env", "TAVILY_API_KEY")
        self.timeout = config.get("timeout_seconds", 10)
        self.max_results = config.get("max_results", 5)
        if not isinstance(self.enabled, bool):
            raise DomainError("联网搜索 enabled 必须为布尔值")
        if self.provider not in {"duckduckgo", "tavily", "bing"}:
            raise DomainError("联网搜索只支持 bing、duckduckgo 或 tavily")
        if type(self.timeout) is not int or not 3 <= self.timeout <= 30:
            raise DomainError("联网搜索超时必须在 3–30 秒")
        if type(self.max_results) is not int or not 1 <= self.max_results <= 10:
            raise DomainError("联网搜索返回条数必须在 1–10")
        if not isinstance(self.api_key_env, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", self.api_key_env):
            raise DomainError("联网搜索密钥环境变量名不合法")
        self.env = env
        self._cache: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
        self._lock = threading.Lock()

    def public(self) -> dict:
        """Never expose the API key; configured tells the UI whether it can run."""
        key = self.env(self.api_key_env, "") if self.provider == "tavily" else ""
        configured = self.provider != "tavily" or bool(key)
        return {"enabled": self.enabled, "provider": self.provider, "configured": configured,
                "max_results": self.max_results, "timeout_seconds": self.timeout}

    def _request(self, url: str, *, data: dict | None = None, headers: dict | None = None) -> bytes:
        request = Request(url, data=json.dumps(data).encode() if data is not None else None,
                          headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/html",
                                   **({"Content-Type": "application/json"} if data is not None else {}),
                                   **(headers or {})})
        try:
            with build_opener(_NoRedirect()).open(request, timeout=self.timeout) as response:
                return response.read(MAX_RESPONSE_BYTES + 1)
        except (HTTPError, URLError, OSError, ValueError) as exc:
            raise SearchError("联网搜索服务不可达或超时，未返回结果") from exc

    def search(self, query: str, max_results: int | None = None) -> dict:
        """Return normalized results; cache is bounded and never persists queries."""
        if not isinstance(query, str) or not query.strip() or len(query) > 1000:
            raise DomainError("搜索关键词必须为 1–1000 字")
        if not self.enabled:
            raise SearchError("联网搜索未启用；请管理员在 agent-tools.yaml 配置")
        limit = self.max_results if max_results is None else max_results
        if type(limit) is not int or not 1 <= limit <= 10:
            raise DomainError("搜索返回条数必须为 1–10")
        key = f"{self.provider}\0{limit}\0{query.strip()}"
        with self._lock:
            cached = self._cache.get(key)
            if cached and time.time() - cached[0] < 300:
                return {"query": query.strip(), "provider": self.provider,
                        "results": cached[1][:limit], "cached": True}
        try:
            results = {
                "tavily": self._tavily,
                "duckduckgo": self._duckduckgo,
                "bing": self._bing,
            }[self.provider](query.strip(), limit)
        except SearchError:
            raise
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise SearchError("联网搜索返回格式无法解析") from exc
        with self._lock:
            self._cache[key] = (time.time(), results)
            self._cache.move_to_end(key)
            while len(self._cache) > 64:
                self._cache.popitem(last=False)
        return {"query": query.strip(), "provider": self.provider, "results": results[:limit], "cached": False}

    def _tavily(self, query: str, limit: int) -> list[dict]:
        key = self.env(self.api_key_env, "")
        if not key:
            raise SearchError("Tavily 搜索密钥未配置")
        raw = self._request(TAVILY_URL, data={
            "api_key": key, "query": query, "max_results": limit,
            "search_depth": "basic", "include_answer": False, "include_raw_content": False,
        })
        if len(raw) > MAX_RESPONSE_BYTES:
            raise SearchError("搜索响应超过大小限制")
        payload = json.loads(raw)
        rows = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise SearchError("Tavily 未返回结果列表")
        results = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = _safe_url(row.get("url"))
            title = row.get("title") if isinstance(row.get("title"), str) else ""
            snippet = row.get("content") if isinstance(row.get("content"), str) else ""
            if url:
                results.append({"title": title.strip()[:300], "url": url,
                                "snippet": snippet.strip()[:1000], "score": row.get("score")})
        return results

    def _duckduckgo(self, query: str, limit: int) -> list[dict]:
        raw = self._request(DUCKDUCKGO_URL + "?q=" + quote_plus(query))
        if len(raw) > MAX_RESPONSE_BYTES:
            raise SearchError("搜索响应超过大小限制")
        parser = _DuckDuckGoParser()
        parser.feed(raw.decode("utf-8", "replace"))
        results = []
        for index, link in enumerate(parser.links[:limit]):
            target = _decode_duckduckgo_url(link["href"])
            url = _safe_url(target)
            if not url:
                continue
            snippet = parser.snippets[index] if index < len(parser.snippets) else ""
            results.append({"title": link["title"][:300], "url": url,
                            "snippet": snippet[:1000], "score": None})
        if not results:
            raise SearchError("搜索服务未返回可解析结果")
        return results

    def _bing(self, query: str, limit: int) -> list[dict]:
        """Bing CN is reachable from the deployment network; markup is bounded."""
        raw = self._request(BING_URL + "?q=" + quote_plus(query) + "&setlang=zh-CN",
                            headers={"Accept-Language": "zh-CN,zh;q=0.9"})
        if len(raw) > MAX_RESPONSE_BYTES:
            raise SearchError("搜索响应超过大小限制")
        html = raw.decode("utf-8", "replace")
        results = []
        for block in re.findall(r'<li class="b_algo".*?</li>', html, re.DOTALL):
            link = re.search(r'<h2[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
            if not link:
                continue
            url = _safe_url(unescape(link.group(1)))
            if not url:
                continue
            title = re.sub(r"<[^>]+>", "", unescape(link.group(2)))
            snippet_match = re.search(r"<p[^>]*>(.*?)</p>", block, re.DOTALL)
            snippet = re.sub(r"<[^>]+>", "", unescape(snippet_match.group(1))) if snippet_match else ""
            results.append({"title": " ".join(title.split())[:300], "url": url,
                            "snippet": " ".join(snippet.split())[:1000], "score": None})
            if len(results) >= limit:
                break
        if not results:
            raise SearchError("搜索服务未返回可解析结果")
        return results
