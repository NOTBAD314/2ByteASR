"""DeepSeek Search / Fetch API (2026-10-17, api-docs.deepseek.com/guides/search).

2026-11-13 (user): DeepSeek can search the web through its own read-only JSON
APIs on the same API key, so the term library can look up official names with
it. The chat endpoint does not search by itself: the application calls Search,
hands the results to the model and keeps only names whose source URL Search
actually returned.

Search: POST /v1/tools/search {query (1-128 chars), count 1-50, ori_question,
need_content} -> {results: [{title, url, snippet, summary, rerank_score,
authority, date, site_name, ...}]}. Fetch: POST /v1/tools/fetch {url} ->
{title, content (Markdown)}. $0.75 per 1,000 successful requests each;
account QPS 100 (Search) / 25 (Fetch); errors use the OpenAI envelope.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

HOST = "api.deepseek.com"
SEARCH_URL = f"https://{HOST}/v1/tools/search"
FETCH_URL = f"https://{HOST}/v1/tools/fetch"
PRICE_PER_1000_USD = 0.75
MAX_QUERY = 128
RETRYABLE = {408, 429, 500, 502, 503, 504}


class DeepSeekToolError(RuntimeError):
    def __init__(self, message: str, *, status: int = 0, category: str = "deepseek_tool_error"):
        super().__init__(message)
        self.status = status
        self.category = category


_MESSAGES = {
    401: ("DeepSeek API Key 无效或缺失，请在设置里检查。", "auth"),
    402: ("DeepSeek 账户余额不足，充值后再查。", "balance"),
    403: ("这个网页被 DeepSeek 的安全策略拒绝抓取。", "blocked"),
    404: ("这个网页抓不到可用内容。", "not_found"),
}


def supports(endpoint: Mapping[str, Any] | None) -> bool:
    """The endpoint is DeepSeek's own API (a key for its Search API)."""
    endpoint = endpoint or {}
    if str(endpoint.get("provider") or "") != "deepseek" or not str(endpoint.get("api_key") or "").strip():
        return False
    host = urlsplit(str(endpoint.get("base_url") or endpoint.get("url") or "")).hostname or ""
    return host == HOST


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text[:limit]


def _post(url: str, api_key: str, body: dict, *, timeout: float, retries: int,
          cancel_check: Callable[[], Any] | None, post=None) -> dict:
    if post is None:
        from .network_policy import post
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for attempt in range(retries + 1):
        if cancel_check is not None:
            cancel_check()
        try:
            response = post(url, headers=headers, json=body, timeout=timeout)
        except Exception as exc:  # network error: retry, then report
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise DeepSeekToolError(f"连接 DeepSeek 搜索失败：{exc}", category="network") from exc
        status = int(getattr(response, "status_code", 0) or 0)
        if status == 200:
            try:
                payload = response.json()
            except ValueError as exc:
                raise DeepSeekToolError("DeepSeek 搜索返回了无法解析的内容。", status=status) from exc
            return payload if isinstance(payload, dict) else {}
        if status in RETRYABLE and attempt < retries:
            time.sleep(0.8 * (attempt + 1))
            continue
        message, category = _MESSAGES.get(status, (f"DeepSeek 搜索请求失败（HTTP {status}）。", "http"))
        try:
            detail = str((response.json().get("error") or {}).get("message") or "")
        except Exception:
            detail = ""
        raise DeepSeekToolError(message + (f" {detail}" if detail and status not in _MESSAGES else ""),
                                status=status, category=category)
    raise DeepSeekToolError("DeepSeek 搜索请求失败。")


def search(api_key: str, query: str, *, count: int = 5, ori_question: str = "", timeout: float = 20,
           retries: int = 2, cancel_check=None, post=None) -> list[dict]:
    """Search results as plain dicts (title, url, snippet, summary, authority, date, site_name)."""
    query = _clip(query, MAX_QUERY)
    if not query:
        return []
    body: dict[str, Any] = {"query": query, "count": max(1, min(50, int(count))), "need_content": False}
    if ori_question:
        body["ori_question"] = _clip(ori_question, MAX_QUERY)
    payload = _post(SEARCH_URL, api_key, body, timeout=timeout, retries=retries, cancel_check=cancel_check, post=post)
    rows = []
    for row in payload.get("results") or ():
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        if not url.startswith(("https://", "http://")):
            continue
        rows.append(dict(title=_clip(row.get("title"), 160), url=url, snippet=_clip(row.get("snippet"), 240),
                         summary=_clip(row.get("summary"), 800), site_name=str(row.get("site_name") or ""),
                         date=str(row.get("date") or ""), authority=row.get("authority"),
                         rerank_score=row.get("rerank_score")))
    return rows


def fetch(api_key: str, url: str, *, timeout: float = 30, retries: int = 1, cancel_check=None, post=None) -> dict:
    """One page as {title, content (Markdown)}."""
    payload = _post(FETCH_URL, api_key, {"url": str(url)[:8192]}, timeout=timeout, retries=retries,
                    cancel_check=cancel_check, post=post)
    return dict(title=str(payload.get("title") or ""), content=str(payload.get("content") or ""))


def estimate_cost_usd(requests: int) -> float:
    return round(max(0, int(requests)) * PRICE_PER_1000_USD / 1000, 2)
