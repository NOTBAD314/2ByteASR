"""智能建词 MVP：Retrieval first, AI optional。

原则：
- 先取已有资料（2ByteASR 游戏词库 / 粘贴文本 / 网页片段），AI 只是增强步骤。
- 任何候选都必须保留 source；AI 建议的词 status=ai_suggested，必须用户确认
  后才进入 user_confirmed（写词库）。
- 不引入爬虫框架：Builtin 读 game_profiles + lexicons JSON，Wiki/文本用
  stdlib html.parser 轻量抽取。

不依赖 twobyteasr.ui（避免 UI 依赖倒挂）；写词库由调用方经
subtitle_core 的 add_learned_mapping / persist_learned_mappings 完成。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol

import requests


_LOG = logging.getLogger(__name__)
_PROXY_FAKE_IP_NETWORK = "198.18.0.0/15"


# ---------------------------------------------------------------- 数据模型

CATEGORY_KEYS = (
    "character",
    "skill",
    "item",
    "weapon",
    "location",
    "enemy",
    "faction",
    "mechanic",
    "quest",
    "common",
    "other",
)
CATEGORY_LABELS = {
    "character": "角色",
    "skill": "技能",
    "item": "物品",
    "weapon": "武器/装备",
    "location": "地点",
    "enemy": "怪物/Boss",
    "faction": "阵营",
    "mechanic": "机制",
    "quest": "任务",
    "common": "常用词",
    "other": "其它",
}
LABEL_TO_CATEGORY = {label: key for key, label in CATEGORY_LABELS.items()}
# game_profiles.json 的 terms.category 现状：game_term 视为通用专名。
_LEGACY_CATEGORY_MAP = {"game_term": "common", "term": "common", "game": "common"}

STATUS_BUILTIN = "builtin"
STATUS_CANDIDATE = "candidate"
STATUS_USER_CONFIRMED = "user_confirmed"
STATUS_AI_SUGGESTED = "ai_suggested"

# 状态优先级（同词去重时胜出）：已确认 > 内置 > AI 建议 > 候选
_STATUS_PRIORITY = {
    STATUS_USER_CONFIRMED: 4,
    STATUS_BUILTIN: 3,
    STATUS_AI_SUGGESTED: 2,
    STATUS_CANDIDATE: 1,
}

# 类别推断关键词（section / 词内命中）；按出现次数计票，取最高票。
_CATEGORY_HINTS = {
    "character": ("角色", "人物", "单位", "干员", "机师", "代理", "角色图鉴"),
    "skill": ("技能", "战技", "秘技", "奥义", "天赋", "招式", "术法", "技能图鉴"),
    "weapon": ("武器", "装备", "专武", "神之眼", "武器图鉴"),
    "item": ("物品", "道具", "材料", "素材", "食物", "物品图鉴"),
    "location": ("地点", "区域", "城市", "地图", "副本", "地点图鉴"),
    "enemy": ("怪物", "boss", "首领", "敌人", "怪物图鉴"),
    "faction": ("阵营", "组织", "势力", "公会", "派系"),
    "mechanic": ("机制", "系统", "玩法", "功能"),
    "quest": ("任务", "剧情", "委托", "任务图鉴"),
    "common": ("简称", "常用", "术语", "名词"),
}
_ALL_HINT_KEYS = tuple(_CATEGORY_HINTS)


@dataclass(frozen=True)
class GlossaryCandidate:
    term: str
    category: str = "other"
    aliases: tuple[str, ...] = ()
    source: str = ""          # builtin / pasted / wiki / ai
    source_url: str = ""
    confidence: float = 0.5
    status: str = STATUS_CANDIDATE
    extra: dict = field(default_factory=dict, compare=False)


def normalize_term(value: str) -> str:
    """去空白与杂标点后的唯一键（不区分全半角，不转小写中文）。"""
    text = str(value or "").strip()
    text = text.replace("（", "(").replace("）", ")").replace("，", ",")
    text = re.sub(r"[,.、。;；:：!?！？·—\-_~～\s]+", "", text)
    return text


def infer_category(term: str, section: str = "") -> str:
    """按 section 与词内关键词计票推断类别；无命中 → other。"""
    votes: dict[str, int] = {}
    for key in _ALL_HINT_KEYS:
        hits = sum(1 for hint in _CATEGORY_HINTS[key] if hint in section or hint in term)
        if hits:
            votes[key] = hits
    if not votes:
        return "other"
    return max(votes, key=votes.get)  # type: ignore[arg-type]


def _merge_sources(urls: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(u for u in urls if u))


def dedupe_candidates(candidates) -> list[GlossaryCandidate]:
    """按 normalize_term 合并：aliases/source 取并集，confidence 取最大，
    status 按优先级保留。"""
    by_key: dict[str, dict] = {}
    order: list[str] = []
    for candidate in candidates:
        key = normalize_term(candidate.term)
        if not key:
            continue
        if key not in by_key:
            by_key[key] = {
                "term": candidate.term,
                "category": candidate.category,
                "aliases": set(candidate.aliases),
                "source": set(candidate.source.split("/")) if candidate.source else set(),
                "urls": {candidate.source_url} if candidate.source_url else set(),
                "confidence": candidate.confidence,
                "status": candidate.status,
            }
            order.append(key)
        else:
            entry = by_key[key]
            entry["aliases"] |= set(candidate.aliases)
            if candidate.source:
                entry["source"] |= set(candidate.source.split("/"))
            if candidate.source_url:
                entry["urls"].add(candidate.source_url)
            entry["confidence"] = max(entry["confidence"], candidate.confidence)
            if _STATUS_PRIORITY.get(candidate.status, 0) > _STATUS_PRIORITY.get(entry["status"], 0):
                entry["status"] = candidate.status
    result = []
    for key in order:
        entry = by_key[key]
        result.append(
            GlossaryCandidate(
                term=entry["term"],
                category=entry["category"],
                aliases=tuple(sorted(entry["aliases"])),
                source="/".join(sorted(entry["source"])),
                source_url="; ".join(sorted(entry["urls"])),
                confidence=round(entry["confidence"], 3),
                status=entry["status"],
            )
        )
    return result


# ---------------------------------------------------------------- 来源适配器

class GlossarySourceAdapter(Protocol):
    name: str

    def collect(self, game_name: str) -> list[GlossaryCandidate]:
        ...


class BuiltinGlossarySource:
    """2ByteASR 游戏词库包：game_profiles.json 的 terms + lexicons/*.json。

    profile terms 的 category（如 game_term）映射到标准类别；lexicons 用
    文件级 category（skill/character/…）。全部 status=builtin，只读参考。
    """

    name = "2ByteASR 游戏词库"

    def __init__(self, profiles_payload: dict, root: Path):
        self._profiles = profiles_payload.get("profiles", {}) if isinstance(profiles_payload, dict) else {}
        self._root = Path(root)

    def _profile_for(self, game_name: str) -> tuple[str, dict] | None:
        from subtitle_core import runtime_game_identity

        identity = runtime_game_identity(game_name)
        for name, profile in self._profiles.items():
            profile_identity = runtime_game_identity(
                str(profile.get("identity", name))
            )
            if profile_identity == identity:
                return name, profile
        return None

    def collect(self, game_name: str) -> list[GlossaryCandidate]:
        found = self._profile_for(game_name)
        candidates: list[GlossaryCandidate] = []
        if found is None:
            return candidates
        _name, profile = found
        for item in profile.get("terms", []):
            if not isinstance(item, dict):
                continue
            source_marker = str(item.get("source", "") or "").strip().lower()
            if (
                "user_verified" in source_marker
                or "user_manual" in source_marker
                or "manual_srt" in source_marker
            ):
                # These rows are migrated into user_confirmed storage. Returning
                # them here would relabel user-owned work as a bundled source.
                continue
            term = str(item.get("canonical", "") or "").strip()
            if not term:
                continue
            raw_category = str(item.get("category", "") or "").strip()
            category = (
                LABEL_TO_CATEGORY.get(raw_category)
                or _LEGACY_CATEGORY_MAP.get(raw_category)
                or infer_category(term, raw_category)
            )
            candidates.append(
                GlossaryCandidate(
                    term=term,
                    category=category,
                    aliases=tuple(
                        str(alias).strip() for alias in item.get("aliases", ()) if str(alias).strip()
                    ),
                    source="builtin",
                    source_url=str(profile.get("source_url", "") or ""),
                    confidence=0.9,
                    status=STATUS_BUILTIN,
                )
            )
        for relative in profile.get("lexicons", []):
            path = (self._root / str(relative)).resolve()
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError, TypeError):
                continue
            file_category = str(payload.get("category", "") or "").strip().lower()
            if file_category in CATEGORY_KEYS:
                category = file_category
            else:
                category = LABEL_TO_CATEGORY.get(file_category) or infer_category(file_category)
            source_url = str(payload.get("source_url", "") or "")
            for entry in payload.get("entries", []):
                if not isinstance(entry, dict):
                    continue
                term = str(entry.get("name", "") or "").strip()
                if not term:
                    continue
                candidates.append(
                    GlossaryCandidate(
                        term=term,
                        category=category,
                        source="builtin",
                        source_url=source_url,
                        confidence=0.9,
                        status=STATUS_BUILTIN,
                    )
                )
        return candidates


class PastedTextSource:
    """粘贴资料文本：逐行术语；支持 `名称（类别）`、`类别：A、B、C`。

    候选 status=candidate，source=pasted。不联网。
    """

    name = "粘贴的文本资料"

    def collect(self, game_name: str, text: str = "") -> list[GlossaryCandidate]:
        del game_name
        candidates: list[GlossaryCandidate] = []
        section = ""
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip().strip("、,，。;；")
            if not line or line.startswith("#"):
                continue
            # 类别段前缀：`角色：xxx` / `技能：xxx`
            prefix_match = re.match(r"^(角色|技能|物品|武器|装备|地点|怪物|敌人|阵营|机制|任务|常用|其它)[：:](.*)$", line)
            if prefix_match:
                section = prefix_match.group(1)
                line = prefix_match.group(2).strip().strip("、,，。;；")
                if not line:
                    continue
            # `名称（类别）` 或 `名称 - 类别`
            paren = re.match(r"^(.*?)[（(](角色|技能|物品|武器|装备|地点|怪物|敌人|阵营|机制|任务|常用|其它)[）)]$", line)
            if paren:
                term = paren.group(1).strip()
                category = LABEL_TO_CATEGORY.get(paren.group(2)) or "other"
            else:
                term = line.strip("、,，。;； ")
                category = infer_category(term, section)
            for chunk in re.split(r"[、,，;；/]+", term):
                chunk = chunk.strip()
                if not (1 <= len(chunk) <= 40):
                    continue
                candidates.append(
                    GlossaryCandidate(
                        term=chunk,
                        category=category,
                        source="pasted",
                        confidence=0.7,
                        status=STATUS_CANDIDATE,
                    )
                )
        return candidates


def build_ai_glossary_prompt(game_name: str) -> str:
    """Return a provider-neutral prompt whose TSV can be reviewed before import."""
    name = str(game_name or "当前游戏").strip() or "当前游戏"
    categories = "角色、技能、物品、武器/装备、地点、怪物/Boss、阵营、机制、任务、常用词、其它"
    return (
        f"请为《{name}》整理字幕识别术语。只输出 TSV 纯文本，不要 Markdown 代码块，"
        "不要解释，也不要虚构不确定名称。\n"
        "第一行固定为：标准词\t分类\t别名或常见错写\n"
        f"分类只能使用：{categories}。\n"
        "每行一个标准词；多个别名或常见错写用 | 分隔；没有别名时第三列留空。\n"
        "优先收录角色、Boss、技能、地点、物品和容易被 ASR 听错的专名。"
    )


def parse_ai_glossary_tsv(text: str, *, limit: int = 1000) -> list[GlossaryCandidate]:
    """Parse external-AI TSV into preview-only candidates; this never writes storage."""
    candidates: list[GlossaryCandidate] = []
    for line_number, raw_line in enumerate(str(text or "").splitlines(), 1):
        line = raw_line.strip().strip("`")
        if not line or line.startswith("#") or line.lower() in {"tsv", "```tsv"}:
            continue
        columns = [part.strip() for part in line.split("\t")]
        if line_number == 1 and columns and columns[0] in {"标准词", "术语", "term", "canonical"}:
            continue
        if len(columns) < 2:
            continue
        term = columns[0]
        if not (1 <= len(term) <= 40):
            continue
        raw_category = columns[1]
        category = (
            LABEL_TO_CATEGORY.get(raw_category)
            or (raw_category if raw_category in CATEGORY_KEYS else None)
            or infer_category(term, raw_category)
        )
        aliases = tuple(
            dict.fromkeys(
                alias.strip()
                for alias in re.split(r"[|｜、,，;；]+", columns[2] if len(columns) > 2 else "")
                if alias.strip() and alias.strip() != term and len(alias.strip()) <= 40
            )
        )
        candidates.append(
            GlossaryCandidate(
                term=term,
                category=category,
                aliases=aliases,
                source="ai",
                confidence=0.65,
                status=STATUS_AI_SUGGESTED,
            )
        )
        if len(candidates) >= max(1, int(limit)):
            break
    return dedupe_candidates(candidates)


class _WikiExtractor(HTMLParser):
    """轻量抽取：h1-h4 标题（section）、表格第一列、列表项、链接文字。"""

    _SECTION_TAGS = {"h1", "h2", "h3", "h4"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections: list[tuple[str, str]] = []      # (section_title, text)
        self._current_section = ""
        self._pending: list[str] = []
        self._in_li = False
        self._in_link = False
        self._link_parts: list[str] = []
        self._table_cell = ""
        self._in_cell = False
        self._cell_index = 0
        self._first_column: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SECTION_TAGS:
            self._current_section = ""
        elif tag == "li":
            self._in_li = True
            self._pending.append("")
        elif tag == "a":
            self._in_link = True
            self._link_parts = []
        elif tag == "tr":
            # 单元格列号按行重置：否则只有整个文档第一个单元格能成为"首列"。
            self._cell_index = 0
        elif tag in ("td", "th"):
            self._in_cell = True
            self._cell_index += 1
            self._table_cell = ""

    def handle_endtag(self, tag):
        if tag in self._SECTION_TAGS:
            if self._current_section.strip():
                self.sections.append((self._current_section.strip(), ""))
        elif tag == "li" and self._pending:
            text = self._pending.pop().strip()
            if text:
                self.sections.append((self._current_section, text))
            self._in_li = False
        elif tag == "a":
            link_text = "".join(self._link_parts).strip()
            if link_text:
                self.sections.append((self._current_section, link_text))
            self._in_link = False
        elif tag in ("td", "th"):
            if self._cell_index == 1 and self._table_cell.strip():
                self._first_column.append(self._table_cell.strip())
            self._in_cell = False

    def handle_data(self, data):
        if self._in_cell:
            self._table_cell += data
            return
        if self._in_link:
            self._link_parts.append(data)
            return
        if self._pending:
            self._pending[-1] += data
        if data.strip() and self._in_li:
            pass
        if not self._in_li and not self._in_link and data.strip():
            self._current_section += data


class StructuredWikiSource:
    """网页/Wiki HTML 片段：标题/表格第一列/列表项/链接文字 + section 推断类别。

    MVP 不主动抓取：调用方传入已取得的 HTML 文本（用户粘贴或简单 requests 获取）。
    """

    name = "Wiki / 网页资料"

    def collect(self, game_name: str, html_text: str = "") -> list[GlossaryCandidate]:
        del game_name
        extractor = _WikiExtractor()
        try:
            extractor.feed(str(html_text or ""))
        except Exception:  # noqa: BLE001 - malformed html must not break collection
            return []
        candidates: list[GlossaryCandidate] = []
        seen: set[str] = set()
        for section, text in extractor.sections:
            for piece in re.split(r"[、,，;；/]+", text):
                piece = piece.strip()
                if not (1 <= len(piece) <= 40) or piece in seen:
                    continue
                seen.add(piece)
                candidates.append(
                    GlossaryCandidate(
                        term=piece,
                        category=infer_category(piece, section),
                        source="wiki",
                        confidence=0.6,
                        status=STATUS_CANDIDATE,
                    )
                )
        for cell in extractor._first_column:
            cell = cell.strip()
            if (1 <= len(cell) <= 40) and cell not in seen:
                seen.add(cell)
                candidates.append(
                    GlossaryCandidate(
                        term=cell,
                        category=infer_category(cell),
                        source="wiki",
                        confidence=0.6,
                        status=STATUS_CANDIDATE,
                    )
                )
        return candidates


def build_candidates(*sources) -> list[GlossaryCandidate]:
    """合并多个来源并去重；保留 source 与最高 confidence。"""
    flattened: list[GlossaryCandidate] = []
    for collected in sources:
        flattened.extend(collected)
    return dedupe_candidates(flattened)


# ---------------------------------------------------------------- AI 增强（可选）

class AiEnhancementError(Exception):
    """AI 增强失败的结构化错误。基础建词不受影响。"""

    def __init__(self, code: str, detail: str, endpoint: str = ""):
        super().__init__(detail)
        self.code = code          # unauthorized / missing_key / unavailable
        self.detail = detail
        self.endpoint = endpoint

    @property
    def user_message(self) -> str:
        if self.code == "unauthorized":
            return "AI 增强不可用：当前 API 密钥无效或未授权。基础建词仍可继续使用。"
        if self.code == "missing_key":
            return "AI 增强不可用：尚未配置 API 密钥。基础建词仍可继续使用。"
        return "AI 增强暂时不可用。基础建词仍可继续使用。"


def classify_ai_error(exc: Exception, endpoint: dict | None = None) -> AiEnhancementError:
    """把网络/HTTP 异常分类为友好错误。401 按 HTTPError.response.status_code 判定。"""
    endpoint = endpoint or {}
    url = str(endpoint.get("url", "") or "")
    if isinstance(exc, AiEnhancementError):
        return exc
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status = getattr(exc.response, "status_code", 0)
        if status == 401:
            return AiEnhancementError("unauthorized", f"HTTP 401：API Key 无效或未授权。", url)
        return AiEnhancementError("unavailable", f"HTTP {status}：{' '.join(str(exc).split())[:160]}", url)
    text = " ".join(str(exc).split())[:160]
    if "密钥" in text or "key" in text.lower():
        return AiEnhancementError("missing_key", text, url)
    return AiEnhancementError("unavailable", text, url)


_AI_ENHANCE_SYSTEM = (
    "你是字幕术语资料整理助手。输入是一批候选游戏专名（可能含噪音）。"
    "只返回 JSON，不要其它文字："
    '{"classify":[{"term":"词","category":"角色|技能|物品|武器/装备|地点|怪物/Boss|阵营|机制|任务|常用词|其它"}],'
    '"aliases":[{"term":"标准词","alias":"常见错字或简称"}],'
    '"noise":["明显不是游戏专名的词"]}。'
    "不得编造输入里不存在的词；alias 只建议真实见过的错字/简称。"
)


def _parse_ai_enhancement(content: str) -> dict:
    text = str(content or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("AI 没有返回可读取的增强 JSON。")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("AI 增强返回格式错误。")
    return payload


def ai_enhance(
    endpoint: dict,
    candidates: list[GlossaryCandidate],
    *,
    requests_module=requests,
    timeout: tuple[int, int] = (10, 60),
) -> tuple[list[GlossaryCandidate], AiEnhancementError | None]:
    """AI 增强（可选）：分类补全 + 别名建议 + 噪音标记。

    返回 (候选列表, 错误)。错误时候选原样返回，调用方继续无 AI 流程。
    AI 建议的别名以 ai_suggested 候选加入，绝不自动 verified。
    """
    if not endpoint.get("api_key"):
        return candidates, AiEnhancementError("missing_key", "未配置 API 密钥")
    prompt_terms = [{"term": c.term} for c in candidates[:120]]
    payload = {
        "model": endpoint["model"],
        "messages": [
            {"role": "system", "content": _AI_ENHANCE_SYSTEM},
            {
                "role": "user",
                "content": f"候选列表（JSON）：{json.dumps(prompt_terms, ensure_ascii=False)}",
            },
        ],
        "temperature": 0.0,
        "max_tokens": 4096,
    }
    try:
        response = requests_module.post(
            endpoint["url"],
            headers={
                "Authorization": f"Bearer {endpoint['api_key']}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001 - any failure must degrade to no-AI flow
        return candidates, classify_ai_error(exc, endpoint)
    try:
        result = _parse_ai_enhancement(content)
    except (ValueError, TypeError, KeyError) as exc:
        return candidates, classify_ai_error(exc, endpoint)

    by_key = {normalize_term(c.term): c for c in candidates}
    updated: list[GlossaryCandidate] = []
    noise: set[str] = set()
    aliases: list[GlossaryCandidate] = []
    for item in result.get("classify", []):
        if not isinstance(item, dict):
            continue
        term = str(item.get("term", "") or "").strip()
        key = normalize_term(term)
        label = str(item.get("category", "") or "").strip()
        category = LABEL_TO_CATEGORY.get(label) or infer_category(label)
        if key in by_key and category != "other":
            old = by_key[key]
            by_key[key] = GlossaryCandidate(
                term=old.term,
                category=category,
                aliases=old.aliases,
                source=old.source,
                source_url=old.source_url,
                confidence=old.confidence,
                status=old.status,
            )
    for item in result.get("noise", []):
        key = normalize_term(str(item))
        if key in by_key:
            noise.add(key)
    for item in result.get("aliases", []):
        if not isinstance(item, dict):
            continue
        term = str(item.get("term", "") or "").strip()
        alias = str(item.get("alias", "") or "").strip()
        key = normalize_term(term)
        if key not in by_key or not alias or alias == term:
            continue
        aliases.append(
            GlossaryCandidate(
                term=term,
                category=by_key[key].category,
                aliases=(alias,),
                source="ai",
                confidence=0.5,
                status=STATUS_AI_SUGGESTED,
            )
        )
    for candidate in candidates:
        key = normalize_term(candidate.term)
        if key in noise:
            continue
        current = by_key.get(key, candidate)
        current = GlossaryCandidate(
            term=current.term,
            category=current.category,
            aliases=current.aliases,
            source=current.source,
            source_url=current.source_url,
            confidence=current.confidence,
            status=current.status,
        )
        updated.append(current)
    # 别名并入对应候选（ai 来源，用户确认后才落盘）
    alias_by_term: dict[str, list[str]] = {}
    for alias_candidate in aliases:
        key = normalize_term(alias_candidate.term)
        alias_by_term.setdefault(key, []).extend(alias_candidate.aliases)
    merged: list[GlossaryCandidate] = []
    for candidate in updated:
        extra_aliases = tuple(alias_by_term.get(normalize_term(candidate.term), ()))
        if extra_aliases:
            candidate = GlossaryCandidate(
                term=candidate.term,
                category=candidate.category,
                aliases=tuple(dict.fromkeys((*candidate.aliases, *extra_aliases))),
                source=candidate.source + "/ai" if "ai" not in candidate.source else candidate.source,
                source_url=candidate.source_url,
                confidence=candidate.confidence,
                status=candidate.status,
            )
        merged.append(candidate)
    return merged, None


def _is_blocked_web_ip(ip, *, allow_proxy_fake_ip: bool) -> bool:
    import ipaddress

    if allow_proxy_fake_ip and ip.version == 4 and ip in ipaddress.ip_network(_PROXY_FAKE_IP_NETWORK):
        return False
    return bool(
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def is_safe_web_url(url: str) -> tuple[bool, str]:
    """MVP 网页来源安全校验：仅 http(s)，拒绝私网/回环/链路本地/metadata IP。

    桌面工具、用户主动输入，但仍是 SSRF 类面：禁止把本地地址喂给
    requests（云 metadata、内网服务等）。
    """
    import ipaddress
    import socket
    from urllib.parse import urlsplit

    text = str(url or "").strip()
    parsed = urlsplit(text)
    if parsed.scheme.lower() not in {"http", "https"}:
        return False, "仅支持 http / https 网页地址。"
    host = str(parsed.hostname or "").strip().rstrip(".")
    if not host:
        return False, "地址缺少主机名。"
    if parsed.username or parsed.password:
        return False, "网页地址不能包含用户名或密码。"
    literal_ip = None
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        try:
            port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except (OSError, ValueError):
            return False, f"无法解析主机 {host!r}。"
        addresses = []
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except (ValueError, IndexError, TypeError):
                continue
            if ip not in addresses:
                addresses.append(ip)
        if not addresses:
            return False, f"无法解析主机 {host!r}。"
    else:
        addresses = [literal_ip]
    rendered = [str(ip) for ip in addresses]
    _LOG.info("Smart Builder URL check host=%s resolved_ips=%s", host, rendered)
    for ip in addresses:
        allow_proxy_fake_ip = literal_ip is None
        if _is_blocked_web_ip(ip, allow_proxy_fake_ip=allow_proxy_fake_ip):
            reason = f"拒绝访问非公网地址 {host!r}（解析到 {ip}）。"
            _LOG.warning(
                "Smart Builder URL rejected host=%s resolved_ips=%s rejected_ip=%s reason=%s",
                host,
                rendered,
                ip,
                reason,
            )
            return False, reason
    return True, ""


def fetch_web_text(
    url: str,
    *,
    requests_module=requests,
    timeout=(8, 30),
    max_redirects: int = 5,
    receipt=None,
    before_request=None,
) -> str:
    from urllib.parse import urljoin

    current = str(url or "").strip()
    for hop in range(max(0, int(max_redirects)) + 1):
        if before_request is not None:
            before_request()
        ok, reason = is_safe_web_url(current)
        if not ok:
            raise ValueError(reason)
        response = requests_module.get(
            current,
            # 浏览器 UA：fandom/wikiwand 等 CDN 对自定义 UA 直接 403。
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 2ByteASR/1.0"},
            timeout=timeout,
            allow_redirects=False,
        )
        status = int(getattr(response, "status_code", 0) or 0)
        if receipt is not None:
            import hashlib
            body = response.text
            receipt({'url':current, 'status':status,
                     'content_type':str(getattr(response, 'headers', {}).get('content-type','')),
                     'body_chars':len(body), 'body_sha256':hashlib.sha256(body.encode('utf8')).hexdigest()})
        if status in {301, 302, 303, 307, 308}:
            location = str(getattr(response, "headers", {}).get("Location", "") or "").strip()
            if not location:
                response.raise_for_status()
            target = urljoin(current, location)
            _LOG.info(
                "Smart Builder redirect hop=%d source=%s target=%s",
                hop + 1,
                current,
                target,
            )
            if hop >= max_redirects:
                raise ValueError("网页重定向次数过多。")
            current = target
            continue
        response.raise_for_status()
        return response.text
    raise ValueError("网页重定向次数过多。")


__all__ = [
    "CATEGORY_KEYS",
    "CATEGORY_LABELS",
    "STATUS_BUILTIN",
    "STATUS_CANDIDATE",
    "STATUS_USER_CONFIRMED",
    "STATUS_AI_SUGGESTED",
    "GlossaryCandidate",
    "normalize_term",
    "infer_category",
    "dedupe_candidates",
    "build_candidates",
    "BuiltinGlossarySource",
    "PastedTextSource",
    "build_ai_glossary_prompt",
    "parse_ai_glossary_tsv",
    "StructuredWikiSource",
    "AiEnhancementError",
    "classify_ai_error",
    "ai_enhance",
    "is_safe_web_url",
    "fetch_web_text",
]
