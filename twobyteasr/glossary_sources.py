"""术语库来源层（v3，2026-09-19）：来源健康状态机 + MediaWiki API 客户端 + 词表直导源。

设计原则（来自 VII 轮取证：模型抽名调用占整轮 79-85%）：
- **程序负责收集，模型负责整理**——MediaWiki 站的分类成员（categorymembers）
  一次调用 500 条页面名，就是带来源的确定名单，不排队等模型。
- 来源级共享健康状态：同一 host 的页面/api.php/词表共享冷却与重试预算；
  明确被拦即冷却+切换，绝不同域反复试错（VII 轮"交替重试×3 间隔 20s"教训）。
- 退避可取消：所有 sleep 分片检查 cancel_check，用户取消立即生效。
- 事件可解释：每次网络动作回报给调用方（emit），区分 blocked/限流/空壳/正常。

日志不记录密钥/Cookie；UA 如实标识应用。
"""

from __future__ import annotations

from . import network_policy

import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping
from urllib.parse import quote, urlparse

import requests

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 2ByteASR/1.0"
_REQUESTS_TIMEOUT = (6, 20)

# 冷却策略：无 Retry-After 时的 capped backoff（秒）。一次冷却后探测恢复，
# 连续被拦升级冷却时长，封顶 COOLDOWN_MAX——同域绝不再试错式轰炸。
_COOLDOWN_STEPS = (30, 90, 180)
_COOLDOWN_MAX = 300


@dataclass
class SourceHealth:
    """per-host 共享健康状态（页面抓取、api.php、词表页全部走这里）。"""

    host: str
    state: str = "ok"                      # ok / cooldown / blocked
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    last_error: str = ""
    total_requests: int = 0
    total_failures: int = 0

    def in_cooldown(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return self.cooldown_until > now

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.state = "ok"
        self.last_error = ""

    def record_failure(self, kind: str, retry_after: float | None = None) -> float:
        """登记失败并进入/加深冷却；返回冷却秒数（0=不冷却的普通失败）。"""
        self.total_failures += 1
        self.consecutive_failures += 1
        self.last_error = kind
        now = time.time()
        if retry_after is not None and retry_after > 0:
            seconds = min(retry_after, _COOLDOWN_MAX)
        elif self.consecutive_failures >= 2:
            index = min(self.consecutive_failures - 2, len(_COOLDOWN_STEPS) - 1)
            seconds = _COOLDOWN_STEPS[index]
        else:
            seconds = _COOLDOWN_STEPS[0]
        self.cooldown_until = now + seconds
        self.state = "blocked" if self.consecutive_failures >= 4 else "cooldown"
        return seconds


class HealthBoard:
    """所有来源的共享看板：按 host 取状态；blocked host 的请求直接跳过。"""

    def __init__(self):
        self._hosts: dict[str, SourceHealth] = {}
        self.deadline = None
        self.cancel_check = None
        self.receipts = []

    def request_timeout(self):
        if self.cancel_check is not None:
            self.cancel_check()
        if self.deadline is None:
            return _REQUESTS_TIMEOUT
        from urllib3.util import Timeout
        left = max(.01, self.deadline-time.monotonic())
        return Timeout(total=left, connect=min(6,left), read=min(20,left))

    def for_host(self, host: str) -> SourceHealth:
        host = (host or "").lower()
        if host not in self._hosts:
            self._hosts[host] = SourceHealth(host=host)
        return self._hosts[host]

    def snapshot(self) -> list[dict]:
        return [
            {
                "host": h.host, "state": h.state,
                "consecutive_failures": h.consecutive_failures,
                "cooldown_seconds_left": max(0, round(h.cooldown_until - time.time())),
                "last_error": h.last_error,
                "requests": h.total_requests, "failures": h.total_failures,
            }
            for h in self._hosts.values()
        ]

    def any_available(self, hosts: list[str]) -> bool:
        return any(not self.for_host(h).in_cooldown() for h in hosts)


def cancellable_sleep(seconds: float, cancel_check: Callable[[], bool] | None,
                      *, slice_seconds: float = 0.5) -> bool:
    """分片等待：被取消立即返回 True（已取消）。"""
    deadline = time.time() + max(0.0, seconds)
    while time.time() < deadline:
        if cancel_check is not None and cancel_check():
            return True
        time.sleep(min(slice_seconds, max(0.0, deadline - time.time())))
    return bool(cancel_check is not None and cancel_check())


def classify_response(status: int, content_type: str, body_head: str) -> str:
    """把 HTTP 响应归类为健康语义：ok / blocked / throttled / empty_shell / bad_format。

    结合状态码与响应内容判断：HTTP 200 但 HTML 空壳（BWIKI 无卡片变体）或
    api.php 返回 HTML（限流页）都不是"正常空词库"。
    """
    if status in (403, 401 + 428,) or status == 403:
        return "blocked"
    if status == 429:
        return "throttled"
    if status >= 500 or status == 567:
        return "throttled"
    body_head = (body_head or "").lstrip()[:400].lower()
    is_json = "json" in (content_type or "").lower() or body_head.startswith(("{", "["))
    is_html = "html" in (content_type or "").lower() or body_head.startswith("<!doctype")
    if is_json:
        return "ok"
    if is_html:
        # api.php 期待 JSON 却给 HTML = 限流/挑战页
        if "captcha" in body_head or "verify" in body_head or "访问过于频繁" in body_head:
            return "blocked"
        return "empty_shell" if len(body_head) < 40 else "ok_html"
    return "bad_format"


# ---------------------------------------------------------------- MediaWiki 客户端

@dataclass
class WikiSite:
    """一个 MediaWiki 站点：api 端点 + 已探测能力。"""

    api_url: str
    site_label: str = ""
    # 分类名 → 我们的类别 key（站点运营惯例，如 BWIKI zzz 的"分类:代理人"）
    category_hints: dict[str, str] = field(default_factory=dict)


def mediawiki_api_url(page_url: str) -> str:
    parsed = urlparse(str(page_url))
    if not parsed.netloc:
        return ""
    # BWIKI hosts many independent wikis below /<game>/. Their API is not
    # the domain root. Preserve explicit api.php / index.php installations.
    parts = parsed.path.strip('/').split('/')
    prefix = '/' + parts[0] if parsed.hostname == 'wiki.biligame.com' and parts[0] else ''
    if parts[-1] in {'api.php', 'index.php'}:
        prefix = parsed.path.rsplit('/', 1)[0]
    return f"{parsed.scheme}://{parsed.netloc}{prefix}/api.php"


_HOST_LAST_REQUEST: dict[str, float] = {}
_HOST_MIN_GAP = 1.5  # 同 host api 请求最小间隔（BWIKI 对零间隔连发非确定性降级实测）


def _api_get(site: WikiSite, params: dict, board: HealthBoard,
             emit=None, label: str = "") -> dict | None:
    """单次 api.php GET，走健康看板；失败/被拦返回 None 并登记。

    同 host 最小间隔 _HOST_MIN_GAP（进程级），避免 discovery+members+harvest
    零间隔连发触发站点降级。
    """
    host = urlparse(site.api_url).netloc.lower()
    health = board.for_host(host)
    if health.in_cooldown():
        return None
    gap = time.time() - _HOST_LAST_REQUEST.get(host, 0.0)
    if gap < _HOST_MIN_GAP:
        cancellable_sleep(_HOST_MIN_GAP - gap, board.cancel_check)
    _HOST_LAST_REQUEST[host] = time.time()
    health.total_requests += 1
    try:
        response = network_policy.get(
            site.api_url, params=params, headers={"User-Agent": _UA},
            timeout=board.request_timeout(), allow_redirects=False,
        )
    except requests.RequestException as exc:
        seconds = health.record_failure("network:" + type(exc).__name__)
        if emit:
            emit("资料抓取", f"{site.site_label or host} 网络失败进入冷却 {seconds}s")
        return None
    body_head = response.text[:400] if response.text else ""
    def record_response(response):
        import hashlib
        board.receipts.append({'url':site.api_url, 'params':dict(params),
            'status':response.status_code, 'content_type':response.headers.get('content-type',''),
            'body_chars':len(response.text), 'fetched_at':time.time(),
            'body_sha256':hashlib.sha256(response.text.encode('utf8')).hexdigest()})
    record_response(response)
    kind = classify_response(response.status_code, response.headers.get("content-type", ""), body_head)
    retry_after = None
    if response.headers.get("Retry-After"):
        try:
            retry_after = float(response.headers["Retry-After"])
        except ValueError:
            pass
    if kind == "ok":
        health.record_success()
        try:
            return response.json()
        except ValueError:
            kind = "bad_format"
    if kind in {"blocked", "throttled"}:
        # 明确被拦：立即冷却切换，不重试（同域绝不反复试错）
        seconds = health.record_failure(kind, retry_after)
        if emit:
            emit("资料抓取", f"{site.site_label or host} 被限（{kind}），冷却 {seconds}s 并切换其他来源")
        return None
    # 可重试类（api_not_json/bad_format/ok_html）：滑动窗口随机降级，3s 后受控重试一次
    for _attempt in range(1):
        cancellable_sleep(3.0, board.cancel_check)
        health.total_requests += 1
        _HOST_LAST_REQUEST[host] = time.time()
        try:
            response = network_policy.get(
                site.api_url, params=params, headers={"User-Agent": _UA},
                timeout=board.request_timeout(), allow_redirects=False,
            )
        except requests.RequestException:
            break
        record_response(response)
        body_head = response.text[:400] if response.text else ""
        kind = classify_response(response.status_code, response.headers.get("content-type", ""), body_head)
        if kind == "ok":
            health.record_success()
            try:
                return response.json()
            except ValueError:
                continue
        if kind in {"blocked", "throttled"}:
            break
    seconds = health.record_failure(kind or "api_not_json", retry_after)
    if emit:
        emit("资料抓取", f"{site.site_label or host} api 不可用（{kind or 'api_not_json'}），冷却 {seconds}s")
    return None


class CategoryMembers(list):
    complete = False
    verified = False


def category_members(site: WikiSite, category_title: str, *, board: HealthBoard,
                     emit=None, max_pages: int = 3, cancel_check: Callable[[], bool] | None = None,
                     per_request: int = 500, on_page=None, cursor=None) -> list[str]:
    """枚举一个分类下的全部页面名（categorymembers + continue 分页）。

    返回按出现序去重的页面标题；被拦/冷却返回已拿到的部分（可为空）。
    参考 https://www.mediawiki.org/wiki/API:Categorymembers / API:Continue。
    """
    names = CategoryMembers()
    state=cursor if cursor is not None else {}
    state.setdefault('queue',[{'title':category_title,'depth':0}])
    state.setdefault('visited',[]);state.setdefault('names',[])
    # A previous bounded run may have deferred deeper categories. Keep them
    # resumable; the request/page and wall-clock budgets bound each invocation.
    for row in state.pop('remaining_subcategories',[]):
        row=row if isinstance(row,dict) else {'title':row,'depth':0}
        if row['title'] not in state['visited'] and row['title'] not in {r['title'] for r in state['queue']}:
            state['queue'].append(row)
    names.extend(state['names']);seen=set(names)
    if state.get('complete'):
        names.complete=True
        names.verified=True
        return names
    for _page in range(max(1, max_pages)):
        if cancel_check is not None and cancel_check():
            break
        if not state.get('current'):
            if not state['queue']:break
            state['current']=state['queue'].pop(0)
            state['visited'].append(state['current']['title'])
        current=state['current']
        params = {
            "action": "query", "list": "categorymembers", "format": "json",
            "cmtitle": current['title'], "cmlimit": str(per_request),
            "cmtype": "page|subcat", "cmnamespace": "0|14",
        }
        if state.get('continue'):
            params['cmcontinue']=state['continue']
        data = _api_get(site, params, board, emit, label=category_title)
        if data is None:
            break
        if data.get('error') or not isinstance((data.get('query') or {}).get('categorymembers'),list):
            state['error']=str((data.get('error') or {}).get('code') or 'invalid_categorymembers')
            if emit:emit('资料抓取',f'分类枚举未完成：{state["error"]}；游标已保留')
            break
        state.pop('error',None)
        names.verified = True
        query = data.get("query") or {}
        for member in query.get("categorymembers") or ():
            title = str(member.get("title") or "").strip()
            if member.get('ns')==14 and title:
                queued={r['title'] for r in state['queue']}|set(state['visited'])
                if title not in queued:
                    state['queue'].append({'title':title,'depth':current['depth']+1})
                continue
            if member.get('ns',0) != 0 or not title or title.startswith(("分类:", "Category:", "模板:", "Template:", "文件:", "File:", "帮助:", "Help:", "预设:")):
                continue
            if title not in seen:
                seen.add(title)
                names.append(title)
        state['continue']=str((data.get('continue') or {}).get('cmcontinue') or '')
        state['names']=list(names)
        if not state['continue']:state['current']=None
        names.complete=not state['current'] and not state['queue'] and not state.get('remaining_subcategories')
        state['complete']=names.complete
        if on_page is not None:
            on_page(list(names), dict(params), names.complete)
        if names.complete:
            break
    return names


def guess_site_from_catalog(catalog_url: str, catalog_title: str = "", covers: str = "") -> WikiSite:
    """从目录页 URL/标题构造 WikiSite（host 即身份；分类提示由 covers 推导）。"""
    host = urlparse(str(catalog_url)).netloc.lower()
    return WikiSite(
        api_url=mediawiki_api_url(catalog_url),
        site_label=host.removeprefix("www."),
        category_hints={},
    )


# ---------------------------------------------------------------- 词表直导源（候选补充）

def fetch_text_wordlist(url: str, *, board: HealthBoard, emit=None,
                        max_bytes: int = 2_000_000) -> str | None:
    """抓取纯文本词表（GitHub raw .txt/.csv/.json、其它直链文本）。

    走健康看板；只收公共直链文本，不解析二进制格式（scel 等）。
    """
    host = urlparse(url).netloc.lower()
    health = board.for_host(host)
    if health.in_cooldown():
        return None
    health.total_requests += 1
    try:
        response = network_policy.get(
            url, headers={"User-Agent": _UA}, timeout=_REQUESTS_TIMEOUT, stream=True,
        )
        chunks: list[bytes] = []
        received = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            received += len(chunk)
            if received > max_bytes:
                break
            chunks.append(chunk)
        body = b"".join(chunks).decode("utf-8", errors="replace")
    except requests.RequestException as exc:
        seconds = health.record_failure("network:" + type(exc).__name__)
        if emit:
            emit("资料抓取", f"{host} 词表抓取失败，冷却 {seconds}s")
        return None
    kind = classify_response(response.status_code, response.headers.get("content-type", ""), body[:400])
    if kind.startswith("ok"):
        health.record_success()
        return body
    seconds = health.record_failure(kind)
    if emit:
        emit("资料抓取", f"{host} 词表不可用（{kind}），跳过")
    return None


def parse_wordlist_text(text: str, *, max_terms: int = 2000) -> list[str]:
    """解析文本词表：每行一个词（兼容 CSV 首列、JSON 数组、词+tab+词频格式）。"""
    text = str(text or "").lstrip()
    terms: list[str] = []
    seen: set[str] = set()
    if text.startswith(("[", "{")):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                for item in data:
                    value = item if isinstance(item, str) else (
                        item.get("term") or item.get("word") or item.get("name") or ""
                        if isinstance(item, dict) else ""
                    )
                    value = str(value).strip()
                    if value and value not in seen:
                        seen.add(value)
                        terms.append(value)
                return terms[:max_terms]
        except ValueError:
            pass
    for line in text.splitlines():
        cell = line.split("\t")[0].split(",")[0].strip()
        if not cell or cell.startswith("#"):
            continue
        if cell not in seen:
            seen.add(cell)
            terms.append(cell)
        if len(terms) >= max_terms:
            break
    return terms


_SOGOU_DICT_URL = "https://pinyin.sogou.com/dict/cate/index/436/default/{page}"


def sogou_game_dict_terms(game_name: str, *, board: HealthBoard, emit=None,
                          requests_module=requests) -> list[str]:
    """搜狗电子游戏词库分类页里匹配游戏名的词表条目（候选来源，不保证命中）。

    该站分类页为分页 HTML：每页列出词表名与预览词。只做一次浅枚举
    （前 2 页），把命中游戏名的词表预览词并起来；被拦立即放弃该源。
    """
    host = "pinyin.sogou.com"
    health = board.for_host(host)
    if health.in_cooldown():
        return []
    terms: list[str] = []
    for page in (1, 2):
        health.total_requests += 1
        try:
            response = requests_module.get(
                _SOGOU_DICT_URL.format(page=page), headers={"User-Agent": _UA},
                timeout=_REQUESTS_TIMEOUT,
            )
        except requests.RequestException:
            health.record_failure("network")
            return terms
        kind = classify_response(response.status_code, response.headers.get("content-type", ""), response.text[:400])
        if not kind.startswith("ok"):
            health.record_failure(kind)
            if emit:
                emit("资料抓取", f"搜狗词库不可用（{kind}），跳过该来源")
            return terms
        health.record_success()
        # 词表预览词在 detail 块里；宽松提取中文词序列，仅当页面提到该游戏
        if game_name not in response.text:
            continue
        for match in re.findall(r'>([\u4e00-\u9fffA-Za-z0-9·]{2,12})<', response.text):
            if match not in terms:
                terms.append(match)
    return terms[:400]


# 主体分类同义词：站点运营各自叫法不同（终末地=干员/绝区零=代理人/原神=角色），
# 按 covers 类别给候选前缀，站内 allcategories 前缀搜索找真实分类名。
_CATEGORY_SYNONYMS = {
    "character": ("干员", "角色", "代理人", "干员娘", "角色列表", "人物"),
    "equipment": ("音擎", "武器", "装备", "驱动盘"),
    "item": ("道具", "物品", "材料"),
    "skill": ("技能", "天赋"),
    "boss": ("敌人", "敌方", "BOSS", "Boss", "boss"),
    "location": ("地点", "区域", "地图"),
    "mechanic": ("机制", "玩法", "系统"),
}
# 分类名里的运营/维护词——不是主体名单
_CATEGORY_JUNK = ("模板", "导航", "页面", "培养", "素材", "攻略", "列表模板", "分类", "一览图", "未实装", "需要", " lacking", "缺少")


def discover_category_names(site: WikiSite, category_key: str, *, board: HealthBoard,
                            emit=None, cancel_check: Callable[[], bool] | None = None,
                            extra_hints: list[str] | None = None) -> list[str]:
    """站内分类发现：allcategories 前缀搜索把 covers 词映射到站内真实分类名。

    返回按优先序的分类名（不含 Category: 前缀）；被拦/无命中返回空。
    每站只需成功一次（调用方缓存）。
    """
    hints: list[str] = []
    for hint in (extra_hints or []):
        if hint and hint not in hints:
            hints.append(hint)
    for hint in _CATEGORY_SYNONYMS.get(category_key, ()):
        if hint not in hints:
            hints.append(hint)
    found: list[str] = []
    for hint in hints[:8]:
        if cancel_check is not None and cancel_check():
            break
        if board.for_host(urlparse(site.api_url).netloc.lower()).in_cooldown():
            break
        data = _api_get(site, {
            "action": "query", "list": "allcategories", "format": "json",
            "acprefix": hint, "aclimit": 20,
        }, board, emit, label=hint)
        if data is None:
            break  # 被拦/冷却：不再对同站试探
        raw = [str(c.get("*") or "").strip() for c in (data.get("query") or {}).get("allcategories") or ()]
        good = [
            name for name in raw
            if 1 <= len(name) <= 8 and not any(junk in name for junk in _CATEGORY_JUNK)
        ]
        # 精确等于 hint 的优先；其次短的
        good.sort(key=lambda name: (name != hint, len(name)))
        found.extend(good[:2])
        if found:
            break
    return list(dict.fromkeys(found))[:3]
