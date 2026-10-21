"""Bilibili danmaku XML parser and local window aggregation."""

from __future__ import annotations

import re
import statistics
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Iterable

REACTION_PATTERNS = (
    ("lol", re.compile(r"(草+|艹+|笑死|笑不活|绷不住|蚌埠住|哈哈哈+|hhhh+|www+|awsl|233+|lol+|lmao|乐子|节目效果)", re.I)),
    ("shock", re.compile(r"(卧槽|我去|我靠+|离谱|逆天|破防|名场面|啊\?+|这什么|不是吧|？{2,}|\?{2,})", re.I)),
    ("question", re.compile(r"(为什么|啥情况|怎么|什么意思|？|\?)")),
    ("hype", re.compile(r"(牛+|厉害|太强|无敌|封神|yyds|绝了|可以|冲|切片|录下来)", re.I)),
    ("sad", re.compile(r"(泪目|哭了|心疼|呜呜+|寄了|g了|gg|完了)", re.I)),
)

FUNNY_PATTERNS = ("哈哈", "笑死", "笑不活", "绷不住", "蚌埠住", "草", "艹", "乐", "典", "急了", "乐子", "节目效果")
CHAOS_PATTERNS = ("?", "？", "啊？", "逆天", "破防", "名场面", "切片", "录下来", "离谱", "寄", "完了")
STOPWORDS = {"哈哈", "哈哈哈", "啊", "吗", "了", "的", "是", "不是", "主播"}
PROMOTIONAL_PATTERNS = ("点点关注", "参与天选福袋", "加入粉丝团", "抽奖啦", "福袋啦")
ROUTINE_PATTERNS = ("拜拜", "886", "下播了", "下播啦", "晚安")


@dataclass(frozen=True)
class DanmakuEvent:
    time_ms: int
    text: str
    mode: int = 1


@dataclass
class DanmakuDocument:
    path: str
    events: list[DanmakuEvent] = field(default_factory=list)
    duration_ms: int = 0

    @property
    def count(self) -> int:
        return len(self.events)


@dataclass
class DanmakuWindow:
    start_ms: int
    end_ms: int
    count: int
    unique: int
    baseline: float
    spike: float
    top_texts: list[tuple[str, int]]
    reactions: dict[str, int]
    growth: float
    funny_hits: int = 0
    chaos_hits: int = 0
    # 2026-09-19 P1：hits 是模式命中次数（一条弹幕可重复计数、单字符
    # 模式如"?"极易膨胀——卡片"惊叹93"实为 93 次命中而非 93 条弹幕）。
    # count_* 是真实条数（一条弹幕至多计 1），用于展示与簇级统计。
    funny_count: int = 0
    chaos_count: int = 0
    keywords: list[str] = field(default_factory=list)
    representative_comments: list[str] = field(default_factory=list)
    raw_score: float = 0.0
    promotional_hits: int = 0
    usable_count: int = 0
    routine_hits: int = 0

    @property
    def effective_count(self) -> int:
        """Count of comments retained after fixed/promotional-message filtering."""
        return self.usable_count if self.usable_count else max(0, self.count - self.promotional_hits)


def parse_danmaku_xml(path: str | Path) -> DanmakuDocument:
    target = Path(path)
    text = target.read_text(encoding="utf-8-sig", errors="replace")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"不是有效的弹幕 XML：{target.name}: {exc}") from exc
    events: list[DanmakuEvent] = []
    for node in root.iter("d"):
        payload = str(node.get("p") or "")
        parts = payload.split(",")
        if not parts:
            continue
        try:
            seconds = float(parts[0])
        except (TypeError, ValueError):
            continue
        try:
            mode = int(float(parts[1])) if len(parts) > 1 else 1
        except (TypeError, ValueError):
            mode = 1
        body = unescape((node.text or "").strip())
        if not body:
            continue
        events.append(DanmakuEvent(time_ms=max(0, round(seconds * 1000)), text=body, mode=mode))
    events.sort(key=lambda item: (item.time_ms, item.text))
    duration = events[-1].time_ms if events else 0
    return DanmakuDocument(path=str(target), events=events, duration_ms=duration)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def _reactions(texts: Iterable[str]) -> dict[str, int]:
    scores = {name: 0 for name, _pattern in REACTION_PATTERNS}
    for text in texts:
        for name, pattern in REACTION_PATTERNS:
            if pattern.search(text):
                scores[name] += 1
    return {key: value for key, value in scores.items() if value}


def _pattern_hits(text: str, patterns: Iterable[str]) -> int:
    return sum(text.count(pattern) for pattern in patterns)


def _is_promotional(text: str) -> bool:
    return any(pattern in text for pattern in PROMOTIONAL_PATTERNS)


def _is_routine(text: str) -> bool:
    return any(pattern in text for pattern in ROUTINE_PATTERNS)


def _keywords(texts: Iterable[str], limit: int = 8) -> list[str]:
    counter: Counter[str] = Counter()
    for text in texts:
        if _is_promotional(text):
            continue
        for token in re.findall(r"[\u4e00-\u9fff]{2,6}|[A-Za-z0-9_]{2,}", text):
            if token not in STOPWORDS:
                counter[token] += 1
    return [word for word, _count in counter.most_common(limit)]


def _representatives(texts: Iterable[str], limit: int = 3) -> list[str]:
    scored: list[tuple[float, str]] = []
    for original in texts:
        clean = original.replace("\n", " ").strip()
        if not clean or _is_promotional(clean):
            continue
        value = _pattern_hits(clean, FUNNY_PATTERNS) * 3 + _pattern_hits(clean, CHAOS_PATTERNS) * 2
        scored.append((value + min(len(clean), 40) / 40.0, clean))
    picked: list[str] = []
    for _score, text in sorted(scored, reverse=True):
        if text not in picked:
            picked.append(text)
        if len(picked) >= limit:
            break
    return picked


def aggregate_danmaku(
    document: DanmakuDocument,
    *,
    window_ms: int = 30000,
    top_n: int = 6,
    context: int = 1,
) -> list[DanmakuWindow]:
    if window_ms <= 0:
        raise ValueError("window_ms must be positive")
    duration = max(document.duration_ms, 0)
    if duration <= 0 and not document.events:
        return []
    buckets: dict[int, list[DanmakuEvent]] = defaultdict(list)
    for event in document.events:
        index = event.time_ms // window_ms
        buckets[index].append(event)
    last_index = max(duration // window_ms, max(buckets) if buckets else 0)
    counts = [
        sum(
            1 for item in buckets.get(index, ())
            if not _is_promotional(item.text) and not _is_routine(item.text)
        )
        for index in range(last_index + 1)
    ]
    median = float(statistics.median(counts)) if counts else 0.0
    windows: list[DanmakuWindow] = []
    previous = 0
    for index in range(last_index + 1):
        events = buckets.get(index, [])
        retained_events = [
            item for item in events
            if not _is_promotional(item.text) and not _is_routine(item.text)
        ]
        texts = [_normalize_text(item.text) or item.text for item in retained_events]
        unique = len(set(texts))
        top = Counter(item.text.strip() for item in retained_events).most_common(top_n)
        count = len(events)
        usable_count = len(retained_events)
        neighbor_counts = [
            counts[neighbor]
            for neighbor in range(max(0, index - context), min(len(counts), index + context + 1))
            if neighbor != index
        ]
        baseline = max(1.0, float(statistics.mean(neighbor_counts)) if neighbor_counts else median)
        original_texts = [item.text for item in retained_events]
        promotional_hits = sum(1 for item in events if _is_promotional(item.text))
        routine_hits = sum(1 for item in events if _is_routine(item.text))
        funny_hits = sum(_pattern_hits(text, FUNNY_PATTERNS) for text in original_texts)
        chaos_hits = sum(_pattern_hits(text, CHAOS_PATTERNS) for text in original_texts)
        funny_count = sum(1 for text in original_texts if any(p in text for p in FUNNY_PATTERNS))
        chaos_count = sum(1 for text in original_texts if any(p in text for p in CHAOS_PATTERNS))
        positive_spike = max(0.0, usable_count - baseline)
        growth = (usable_count - previous) / max(1.0, float(previous)) if index else 0.0
        windows.append(
            DanmakuWindow(
                start_ms=index * window_ms,
                end_ms=(index + 1) * window_ms,
                count=count,
                unique=unique,
                baseline=baseline,
                spike=usable_count / baseline,
                top_texts=top,
                reactions=_reactions(item.text for item in events),
                growth=growth,
                funny_hits=funny_hits,
                chaos_hits=chaos_hits,
                funny_count=funny_count,
                chaos_count=chaos_count,
                keywords=_keywords(original_texts),
                representative_comments=_representatives(original_texts),
                raw_score=max(0.0, usable_count + funny_hits * 4 + chaos_hits * 3 + positive_spike * 1.5),
                promotional_hits=promotional_hits,
                usable_count=usable_count,
                routine_hits=routine_hits,
            )
        )
        previous = usable_count
    return windows


def local_spike_windows(
    windows: list[DanmakuWindow],
    *,
    min_spike: float = 2.5,
    top_k: int = 50,
    quality_reactions: int = 5,
    fallback_to_top: bool = True,
) -> list[DanmakuWindow]:
    """Admit windows by volume spike OR comment quality.

    quality_reactions: a window whose comments carry at least this many
    reaction-word hits (lol/shock/hype/…) is admitted even at low volume —
    quiet audiences still praise with short, dense reactions.
    fallback_to_top: legacy guarantee that an XML-only analysis never returns
    zero windows; fused recall passes False so a uniform/quiet stream yields
    no danmaku candidate unless nothing else can be recalled.
    """
    ranked = sorted(
        windows,
        key=lambda item: (item.raw_score, item.spike, item.effective_count, item.unique, -item.start_ms),
        reverse=True,
    )
    picked = [
        item for item in ranked
        if item.spike >= min_spike
        or item.effective_count >= item.baseline * 2
        or sum(item.reactions.values()) >= max(0, quality_reactions)
    ]
    if not picked and fallback_to_top:
        picked = ranked[:top_k]
    return picked[:top_k]
