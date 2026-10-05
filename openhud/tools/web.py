"""Web tools: search and page fetching.

``web_search`` uses DuckDuckGo's HTML endpoint by default (no API key
required) and can use Brave Search when a key is configured. ``fetch_url``
downloads a page and converts it to readable text.
"""
from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import quote_plus, urljoin

import httpx

from .base import Tool, ToolContext, ToolResult

USER_AGENT = "Mozilla/5.0 (compatible; OpenHUD/1.0; +https://localhost)"


def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?is)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?is)</(p|div|li|h[1-6]|tr)>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    text = html.unescape(raw)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


class WebSearchTool(Tool):
    name = "web_search"
    description = "Pesquisa na internet e retorna resultados (título, URL, resumo)."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    }

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        if not ctx.allow_network:
            return ToolResult(False, "Acesso à internet desativado nas configurações.")
        query = args.get("query", "").strip()
        if not query:
            return ToolResult(False, "Consulta vazia.")
        max_results = min(int(args.get("max_results", 5)), 10)
        brave_key = ctx.secrets.get_or_none("brave") if ctx.secrets else None
        ctx.log("web_search", query)
        try:
            if brave_key:
                return self._brave(query, max_results, brave_key)
            return self._duckduckgo(query, max_results)
        except httpx.RequestError as exc:
            return ToolResult(False, f"Falha de rede na pesquisa: {exc}")

    def _brave(self, query: str, limit: int, key: str) -> ToolResult:
        resp = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": limit},
            headers={"Accept": "application/json", "X-Subscription-Token": key},
            timeout=20,
        )
        if resp.status_code >= 400:
            return ToolResult(False, f"Brave retornou HTTP {resp.status_code}.")
        results = (resp.json().get("web") or {}).get("results") or []
        lines = [
            f"{i}. {r.get('title')}\n   {r.get('url')}\n   {_html_to_text(r.get('description', ''))}"
            for i, r in enumerate(results[:limit], 1)
        ]
        return ToolResult(True, "\n\n".join(lines) or "Nenhum resultado.")

    def _duckduckgo(self, query: str, limit: int) -> ToolResult:
        resp = httpx.get(
            f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
            headers={"User-Agent": USER_AGENT},
            timeout=20,
            follow_redirects=True,
        )
        if resp.status_code >= 400:
            return ToolResult(False, f"DuckDuckGo retornou HTTP {resp.status_code}.")
        blocks = re.findall(
            r'(?is)<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'class="result__snippet"[^>]*>(.*?)</a>',
            resp.text,
        )
        lines = []
        for href, title, snippet in blocks[:limit]:
            lines.append(f"{len(lines) + 1}. {_html_to_text(title)}\n   {html.unescape(href)}\n   {_html_to_text(snippet)}")
        return ToolResult(True, "\n\n".join(lines) or "Nenhum resultado encontrado.")


class FetchUrlTool(Tool):
    name = "fetch_url"
    description = "Baixa uma URL e retorna o conteúdo como texto legível."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "max_chars": {"type": "integer", "default": 12000},
        },
        "required": ["url"],
    }

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        if not ctx.allow_network:
            return ToolResult(False, "Acesso à internet desativado nas configurações.")
        url = args.get("url", "").strip()
        if not url.startswith(("http://", "https://")):
            return ToolResult(False, "URL deve começar com http:// ou https://")
        ctx.log("fetch_url", url)
        try:
            resp = httpx.get(
                url, headers={"User-Agent": USER_AGENT}, timeout=25, follow_redirects=True
            )
        except httpx.RequestError as exc:
            return ToolResult(False, f"Falha de rede: {exc}")
        if resp.status_code >= 400:
            return ToolResult(False, f"HTTP {resp.status_code} ao buscar {url}")
        content_type = resp.headers.get("content-type", "")
        body = resp.text
        text = _html_to_text(body) if "html" in content_type or "<html" in body[:200].lower() else body
        limit = min(int(args.get("max_chars", 12000)), 40000)
        if len(text) > limit:
            text = text[:limit] + "\n...[truncado]"
        return ToolResult(True, text or "(página vazia)")


class HttpRequestTool(Tool):
    name = "http_request"
    description = "Faz uma requisição HTTP (GET/POST/PUT/DELETE) a uma API e retorna a resposta."
    parameters = {
        "type": "object",
        "properties": {
            "method": {"type": "string", "default": "GET"},
            "url": {"type": "string"},
            "headers": {"type": "object"},
            "json_body": {"type": "object"},
            "data": {"type": "string"},
        },
        "required": ["url"],
    }
    requires_confirmation = True

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        if not ctx.allow_network:
            return ToolResult(False, "Acesso à internet desativado nas configurações.")
        method = str(args.get("method", "GET")).upper()
        url = args.get("url", "")
        if not url.startswith(("http://", "https://")):
            return ToolResult(False, "URL deve começar com http:// ou https://")
        ctx.log("http_request", f"{method} {url}")
        try:
            resp = httpx.request(
                method,
                url,
                headers=args.get("headers") or {},
                json=args.get("json_body"),
                content=args.get("data"),
                timeout=30,
                follow_redirects=True,
            )
        except httpx.RequestError as exc:
            return ToolResult(False, f"Falha de rede: {exc}")
        body = resp.text[:15000]
        return ToolResult(
            resp.status_code < 400,
            f"HTTP {resp.status_code}\n{body}",
            {"status_code": resp.status_code},
        )


def build_web_tools() -> list[Tool]:
    return [WebSearchTool(), FetchUrlTool(), HttpRequestTool()]
