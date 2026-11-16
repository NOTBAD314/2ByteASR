"""Term-library sources from DeepSeek's Search / Fetch API (2026-11-16).

User (2026-11-16): people keep saying the term library's AI search is poor and they have to fill it
in by hand or have another AI harness do it. With a DeepSeek key the app could already search the
web (``providers.deepseek_tools``), but only 「名称与译名」 used it: 「补上最近版本的新词」 was locked
(「🔒 需换 AI」) and 「从零整理一整个词库」 looked for pages through Bing RSS.

Here the application does the searching, so the receipts are its own: a fixed set of queries per
content type, results kept only when the subject is named in their title, address or summary,
ranked by DeepSeek's own scores, and the best few pages read whole with Fetch. A model only reads
what was found; a term counts as sourced only when its spelling is in the text of a page it cites
(``verify_terms``). No Qt.
"""
from __future__ import annotations

import re
import time
from datetime import date, timedelta
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

RESULTS_PER_QUERY = 10
MAX_RESULTS = 30            # results handed to the model, best first
MAX_PAGES = 3               # pages read whole with Fetch
PAGE_LIMIT = 60000          # characters kept per fetched page (verification uses all of it)
SOURCE_BYTES = 36000        # UTF-8 bytes of results + page text in one request (glossary_update budget)
SUMMARY_CHARS = 220
RECENT_DAYS = 180
_VIDEO = re.compile(r'(youtube\.com|youtu\.be|douyin\.com|tiktok\.com|kuaishou\.com|ixigua\.com|'
                    r'bilibili\.com/video|v\.qq\.com|huya\.com|douyu\.com)', re.I)

_TOPICS = {
    'game': ('角色 一览', '技能 机制 术语', '地图 地区 Boss', '道具 装备 货币', 'wiki 图鉴', '玩家 黑话 简称'),
    'event': ('嘉宾 出场 名单', '赛程 战队 选手', '活动 介绍 项目'),
    'series': ('角色 一览', '设定 名词 组织', '作品 列表'),
    'creator': ('主播 简介 粉丝 昵称', '梗 口头禅', '常玩 游戏 合作 主播'),
    'other': ('专有名词', '介绍 wiki'),
}
_CATEGORY_TOPICS = {'character': '角色 一览', 'skill': '技能', 'location': '地图 地点', 'mechanic': '机制',
                    'equipment': '装备', 'item': '道具 物品', 'boss': 'Boss', 'community': '玩家 昵称 黑话',
                    'faction': '阵营 组织', 'currency': '货币', 'event': '活动'}


def _subject(game: str) -> str:
    return ' '.join(str(game or '').replace('"', ' ').split())[:60]


def queries(game: str, content_type: str = 'game', *, categories: Iterable[str] = (), today: date | None = None,
            recent: bool = True) -> list[str]:
    """The searches for one subject: its topics (or only the named categories) and recent changes."""
    subject = _subject(game)
    if not subject:
        return []
    picked = [_CATEGORY_TOPICS[key] for key in (str(c).strip().casefold() for c in categories) if key in _CATEGORY_TOPICS]
    topics = list(dict.fromkeys(picked)) or list(_TOPICS.get(str(content_type), _TOPICS['other']))
    rows = [f'{subject} {topic}' for topic in topics]
    if recent and not picked and str(content_type) in {'game', 'series'}:
        since = (today or date.today()) - timedelta(days=RECENT_DAYS)
        rows.insert(1, f'{subject} 版本更新 新角色 after:{since.isoformat()}')
    return [row[:128] for row in rows]


def relevant(game: str, row: dict) -> bool:
    from .glossary_fullflow import source_relevance
    return source_relevance(game, dict(url=row.get('url', ''), title=row.get('title', ''),
                                       description=row.get('summary') or row.get('snippet') or ''))[0]


def _rank(row: dict) -> tuple:
    score = row.get('rerank_score')
    authority = row.get('authority')
    score = float(score) if isinstance(score, (int, float)) else 0.0
    authority = float(authority) if isinstance(authority, (int, float)) else -1.0
    return (score >= 1.5, authority, score)


def gather(api_key: str, game: str, query_list: list[str], *, search=None, cancel_check=None,
           on_query: Callable[[str, int], Any] | None = None, workers: int = 6) -> tuple[list[dict], int, list[str]]:
    """Run the searches. Returns (relevant results best first, searches made, rejected urls).

    A key or balance problem stops the run (``DeepSeekToolError``); any other failed query is skipped."""
    from concurrent.futures import ThreadPoolExecutor
    from ..providers import deepseek_tools
    search = search or deepseek_tools.search
    subject = _subject(game)

    def run(query):
        try:
            return query, search(api_key, query, count=RESULTS_PER_QUERY, ori_question=f'《{subject}》的专有名词',
                                 cancel_check=cancel_check)
        except deepseek_tools.DeepSeekToolError as exc:
            if exc.category in {'auth', 'balance'}:
                raise
            return query, []

    found: dict[str, dict] = {}
    rejected: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(query_list) or 1))) as pool:
        for query, rows in pool.map(run, query_list):
            if on_query is not None:
                on_query(query, len(rows))
            for row in rows:
                url = str(row.get('url') or '')
                if not url.startswith('https://') or url in found:
                    continue
                if relevant(game, row):
                    found[url] = dict(row, query=query)
                elif url not in rejected:
                    rejected.append(url)
    ranked = sorted(found.values(), key=_rank, reverse=True)
    return ranked, len(query_list), rejected


def clean_markdown(text: str) -> str:
    """Fetched Markdown without pictures, link targets and empty runs (names stay)."""
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', ' ', str(text or ''))
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'[ \t　]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text)
    return text.strip()


def pick_pages(results: list[dict], limit: int = MAX_PAGES) -> list[dict]:
    """The best results to read whole: no video pages, one per site."""
    hosts, picked = set(), []
    for row in results:
        url = str(row.get('url') or '')
        host = urlsplit(url).hostname or ''
        if not host or host in hosts or _VIDEO.search(url):
            continue
        hosts.add(host)
        picked.append(row)
        if len(picked) >= limit:
            break
    return picked


def fetch_pages(api_key: str, game: str, rows: list[dict], *, fetch=None, cancel_check=None,
                on_page: Callable[[str, bool], Any] | None = None) -> tuple[list[dict], int]:
    """Read pages with DeepSeek Fetch. Returns (documents, fetches made); a page that fails is skipped."""
    from ..providers import deepseek_tools
    from .smart_glossary import is_safe_web_url
    fetch = fetch or deepseek_tools.fetch
    documents, made = [], 0
    for row in rows:
        url = str(row.get('url') or '')
        if not url.startswith('https://') or not is_safe_web_url(url)[0]:
            continue
        made += 1
        try:
            page = fetch(api_key, url, cancel_check=cancel_check)
        except deepseek_tools.DeepSeekToolError as exc:
            if exc.category in {'auth', 'balance'}:
                raise
            if on_page is not None:
                on_page(url, False)
            continue
        text = clean_markdown(page.get('content', ''))[:PAGE_LIMIT]
        document = dict(url=url, title=str(page.get('title') or row.get('title') or '')[:160], text=text,
                        fetched_at=time.time(), method='deepseek_fetch')
        ok = bool(text) and relevant(game, dict(document, summary=text[:2000]))
        if on_page is not None:
            on_page(url, ok)
        if ok:
            documents.append(document)
    return documents, made


def _size(value) -> int:
    import json
    return len(json.dumps(value, ensure_ascii=False).encode('utf8'))


def model_material(results: list[dict], documents: list[dict], budget: int = SOURCE_BYTES) -> dict:
    """Results (best first) and page text that fit in ``budget`` bytes, for the model's input."""
    shown, used = [], 0
    for row in results[:MAX_RESULTS]:
        item = dict(url=row['url'], title=str(row.get('title') or '')[:80],
                    summary=str(row.get('summary') or row.get('snippet') or '')[:SUMMARY_CHARS])
        size = _size(item)
        if used + size > budget * 0.45:
            break
        shown.append(item)
        used += size
    pages = []
    left = max(0, budget - used)
    for index, document in enumerate(documents):
        share = left // max(1, len(documents) - index)
        text = document['text']
        while text and _size(text) > share - 200:
            text = text[:int(len(text) * 0.8)]
        if text:
            pages.append(dict(url=document['url'], title=document.get('title', ''), text=text))
            left -= _size(pages[-1])
    return dict(search_results=shown, pages=pages)


def _norm(value: str) -> str:
    from .glossary_skill import quote_normalize_term
    return ''.join(quote_normalize_term(value).split()).casefold()


def evidence_texts(results: list[dict], documents: list[dict]) -> dict[str, str]:
    """url -> everything read from it (title, summary, whole page), for spelling checks."""
    texts: dict[str, str] = {}
    for row in results:
        texts[row['url']] = ' '.join(str(row.get(key) or '') for key in ('title', 'summary', 'snippet'))
    for document in documents:
        texts[document['url']] = texts.get(document['url'], '') + ' ' + document.get('title', '') + ' ' + document['text']
    return {url: ''.join(text.split()).casefold() for url, text in texts.items()}


def verify_terms(terms, texts: dict[str, str], titles: dict[str, str] | None = None):
    """Keep a source only when the term's spelling is in that page; else find a page that has it.

    A term no page contains becomes ``unverified`` (shown, never checked by default)."""
    titles = titles or {}
    for term in terms:
        key = _norm(term.term)
        cited = [s for s in term.sources if key and key in texts.get(str(s.get('url', '')), '')]
        if not cited and key:
            cited = [dict(url=url, title=titles.get(url, '')) for url, text in texts.items() if key in text][:2]
        if cited:
            # The application read these pages itself (Search summary or Fetch text) and the spelling is in
            # them: the same evidence level as a page the collector parsed.
            term.sources = tuple(cited[:3])
            term.verification = 'community' if term.formality == 'community' else 'page_verified'
        else:
            term.sources = ()
            term.verification = 'unverified'
        term.aliases = tuple(a for a in term.aliases if _norm(a) and any(_norm(a) in texts.get(str(s.get('url', '')), '')
                                                                        for s in term.sources))
    return terms


def cost_usd(searches: int, fetches: int) -> float:
    from ..providers.deepseek_tools import estimate_cost_usd
    return estimate_cost_usd(searches + fetches)


def planned_requests(content_type: str = 'game') -> int:
    """Searches + page reads one 「补上最近版本的新词」 run makes at most (shown before it starts)."""
    return len(queries('x', content_type)) + MAX_PAGES


__all__ = ['MAX_PAGES', 'clean_markdown', 'cost_usd', 'evidence_texts', 'fetch_pages', 'gather', 'model_material',
           'pick_pages', 'planned_requests', 'queries', 'relevant', 'verify_terms']
