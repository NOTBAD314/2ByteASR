"""Two-pass livestream highlight discovery: local candidates, then LLM rank."""

from __future__ import annotations

import json
import re
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .ai_providers import provider_for_stage
from .studio_danmaku import (
    DanmakuDocument,
    DanmakuWindow,
    aggregate_danmaku,
    local_spike_windows,
    parse_danmaku_xml,
)
from .studio_edit_sequence import HighlightCandidate, _string_list
from .studio_project import StudioCue, SubtitleProject, analysis_transcript_cues


GENERIC_SYSTEM_PROMPT = """你是资深录播切片剪辑师。只对本地分析器召回的窗口排序，不得从整场录播盲找。
不要使用音量、响度或字幕字数作为高能信号。弹幕少不等于不精彩：观众专心观看时往往只有少量短评（牛/泪目/封神/绝了），要靠字幕内容判断铺垫与爆点。

输入证据的边界（2026-09-19 用户规约）：
- transcript 是主播（与队友）说的话；danmaku/quotes 是观众评论。概括事件时区分"主播说了/做了什么"与"观众在猜/在笑什么"，不得混写。
- 你没有看到画面。事件以主播话语与观众反应为据；不要臆测画面里出现了什么怪物/角色/结果，不确定就明说"画面内容待核实"。
- 标题（title/hook）必须概括事件本身；禁止把截断的字幕原句当标题。

核心职责是编辑判断，不是数据罗列。每个候选输出五字段：
- event_summary（发生了什么）：1~2 句、约 25~80 中文字，概括事件本身（谁做了什么、结果如何、情绪如何）。禁止复述或摘录字幕原文——观众已经有字幕了。如果你的答案只是“主播说了X，随后说了Y”或引用原话，视为分析失败。
- clip_reason（为什么值得剪）：1~3 句、约 30~120 中文字，从剪辑师视角说明具体观看价值（预期与结果的反差、翻车/笑点是否完整、紧张过程的释放、能否独立成立），必须尽量涉及：铺垫与 payoff、冲突/反转、情绪转折、节奏、脱离上下文是否可看懂、能否独立成 15~60 秒的段。如果你只写了“弹幕多/弹幕高峰/观众反应集中/字幕显示X”或把统计数字翻译成长句，视为分析失败——统计只属于卡片底部，不进文案。禁止“高能名场面、极具传播价值、情绪价值拉满”等无具体内容的空话。
- hook：6~20 字的钩子，可作章节标题或短视频封面句（例：“50抽直接出了自选五星”“刚说不会翻车就立刻暴毙”）。
- context_required：low | medium | high，表示脱离前文是否还能看懂。
- evidence：danmaku_evidence / subtitle_evidence 等数据只作为辅助证据填这里，不得出现在 event_summary 或 clip_reason 里。

敢于给出保留意见：事件平淡、依赖长前文、只有数据高没有转折的候选，明确写“事件本身较平”“单独剪出可读性一般”并给低分——分数要有区分度，不允许每个候选都“非常值得剪”。窗口内证据不足以判断事件时，明确写“事件待核实”并给低分，绝不编造结局；但不得把所有候选都降级成待核实来回避判断。

其他规则：判断 setup/payoff、反转、翻车、搞笑、失误、clutch、强情绪、争论、故事节点、主播反应和聊天反应。同一事件（哪怕跨越几十分钟）只给一个候选：给出覆盖完整事件的起止范围（含铺垫与收尾），可以超出窗口本身；不要把同一片段拆成多个候选。
title 必须描述事件本身，不要写“搞笑反应高峰”等内部分类名。
只返回 JSON。每个 candidate 必须包含 start_ms、end_ms、score(0-100)、grade、title、hook、event_summary、clip_reason、context_required、reason、danmaku_evidence、subtitle_evidence、edit_direction、subtitle_emphasis、risk_notes、category。
grade 只能是强烈推荐、推荐、可考虑；category 只能是 funny、chaos、reaction、story、clutch、emotional、tutorial、other。
不得让所有候选同分，不得发明窗口摘要中不存在的证据。
"""

# Subtitle-side recall runs in EVERY mode: quiet audiences watch highlights
# without spamming danmaku, so transcript semantics must be able to recall a
# window on its own even when a danmaku XML is bound.
SEMANTIC_SUBTITLE_PATTERN = re.compile(
    r"(翻车|反杀|笑死|不是吧|卧槽|我靠|离谱|破防|逆天|没想到|竟然|完了|成功了|寄了|"
    r"绝了|太强了|好家伙|名场面|封神|泪目|差点|就差一点|最后一波|决战|翻盘|赢了|输了|"
    r"淘汰|出金|抽卡|boss|Boss|BOSS|大招|剧情杀|结局|真相|反转|失误|紧张|手抖)",
    re.I,
)

# Windows closer than this belong to the same event cluster: a 30-minute
# highlight is one candidate, not sixty 30-second ones.
CLUSTER_GAP_MS = 60_000

PREFERRED_SKILL_FOLDERS = (
    "livestream-clip-finder",
    "light-danmaku-clip-ranker",
)
SKILL_SEARCH_NAMES = (
    "SKILL.md",
    "livestream-clip/SKILL.md",
    "live-clip/SKILL.md",
    "highlight/SKILL.md",
)


@dataclass(frozen=True)
class HighlightSkillAdapter:
    path: str = ""
    prompt: str = ""
    found: bool = False

    @classmethod
    def discover(cls, roots: Iterable[str | Path] | None = None) -> "HighlightSkillAdapter":
        preferred: list[Path] = []
        fallback: list[Path] = []
        for root in roots or _default_skill_roots():
            base = Path(root)
            if not base.exists():
                continue
            for name in PREFERRED_SKILL_FOLDERS:
                preferred.append(base / name / "SKILL.md")
                preferred.append(base / "skills" / name / "SKILL.md")
            for name in SKILL_SEARCH_NAMES:
                fallback.append(base / name)
            if base.name.lower() in {"skills", "skill"} and base.is_dir():
                for child in base.iterdir():
                    if child.is_dir():
                        fallback.append(child / "SKILL.md")
        prompts: list[str] = []
        paths: list[str] = []
        seen: set[str] = set()
        for path in preferred + fallback:
            if not path.is_file():
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if _looks_like_clip_skill(text, path):
                paths.append(key)
                prompts.append(f"# {path.parent.name}\n{text[:7000]}")
            preferred_hit = sum(
                1 for item in paths
                if "livestream-clip-finder" in item or "light-danmaku-clip-ranker" in item
            )
            if preferred_hit >= 2:
                break
        if not prompts:
            return cls()
        return cls(path=" | ".join(paths), prompt="\n\n".join(prompts), found=True)


def _default_skill_roots() -> list[Path]:
    home = Path.home()
    project = Path(__file__).resolve().parents[1]
    return [
        project / ".agents" / "skills",
        home / ".agents" / "skills",
        home / ".grok" / "skills",
        home / ".claude" / "skills",
        home / ".codex" / "skills",
        home / ".cursor" / "skills",
        home / "Desktop",
    ]


def _looks_like_clip_skill(text: str, path: Path | None = None) -> bool:
    name = (path.parent.name if path is not None else "").casefold()
    if name in {item.casefold() for item in PREFERRED_SKILL_FOLDERS}:
        return True
    if "title" in name or "标题" in name:
        return False
    lowered = text.casefold()
    if "生成标题" in text or "bilibili-title" in lowered:
        return False
    needles = ("切片候选", "高能时间轴", "爆点", "livestream clip", "highlight clip", "danmaku high-energy")
    return any(item.casefold() in lowered for item in needles)


@dataclass
class LocalCandidate:
    start_ms: int
    end_ms: int
    score: float
    reasons: list[str]
    danmaku: DanmakuWindow | None = None
    quotes: list[str] = None  # type: ignore[assignment]
    # 2026-09-19 P1：弹幕路召回保留整个事件簇（簇级统计的唯一数据源；
    # 此前卡片底部用 best 单窗 raw 计数、"为什么值得剪"却用簇累计，
    # 422 vs 137 / 2.5x vs 1.71x 的口径分裂即源于此）。
    cluster: list[DanmakuWindow] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.quotes is None:
            self.quotes = []
        if self.cluster is None:
            self.cluster = []


def highlight_transcript_project(project: SubtitleProject) -> SubtitleProject:
    """Prefer the non-destructive fast transcript when Clip Assistant has one."""
    analysis_cues = analysis_transcript_cues(project)
    if not analysis_cues:
        return project
    view = copy.deepcopy(project)
    view.cues = analysis_cues
    return view


def _speaker_name(project: SubtitleProject, speaker_id: str) -> str:
    for speaker in project.speakers:
        if speaker.id == speaker_id:
            return speaker.name or speaker.id
    return speaker_id


def _cues_in_range(cues: list[StudioCue], start_ms: int, end_ms: int) -> list[StudioCue]:
    return [cue for cue in cues if cue.end_ms > start_ms and cue.start_ms < end_ms]


def transcript_window(
    project: SubtitleProject,
    start_ms: int,
    end_ms: int,
    *,
    limit: int = 24,
    sample: bool = False,
) -> str:
    cues = _cues_in_range(project.cues, start_ms, end_ms)
    if sample and len(cues) > limit:
        # Even stride across the whole span (endpoints included) so a
        # 30-minute window shows beginning, middle and end instead of only
        # its first 24 cues.
        step = (len(cues) - 1) / float(limit - 1) if limit > 1 else 0.0
        picked = [cues[min(len(cues) - 1, int(round(index * step)))] for index in range(limit)]
    else:
        picked = cues[:limit]
    lines: list[str] = []
    for cue in picked:
        name = _speaker_name(project, cue.speaker_id)
        lines.append(f"{name}: {cue.text.strip()}")
    return "\n".join(lines)


def expand_candidate_context(
    project: SubtitleProject,
    signal_in_ms: int,
    signal_out_ms: int,
    *,
    pad_ms: int = 45_000,
    min_ms: int = 30_000,
    max_ms: int = 180_000,
) -> tuple[int, int]:
    """Expand a short signal window to a cue-aligned editorial range."""
    duration = max(int(project.media.duration_ms or 0), max((cue.end_ms for cue in project.cues), default=0))
    signal_in = max(0, int(signal_in_ms))
    signal_out = max(signal_in + 1, int(signal_out_ms))
    start = max(0, signal_in - max(0, int(pad_ms)))
    end = min(duration or signal_out + pad_ms, signal_out + max(0, int(pad_ms)))
    nearby = _cues_in_range(project.cues, start, end)
    if nearby:
        start = max(0, min(start, nearby[0].start_ms))
        end = max(end, nearby[-1].end_ms)
    if end - start < min_ms:
        missing = min_ms - (end - start)
        start = max(0, start - missing // 2)
        end = min(duration or end + missing, end + (missing - (signal_in - start)))
        if end - start < min_ms and duration:
            start = max(0, end - min_ms)
    if end - start > max_ms:
        center = (signal_in + signal_out) // 2
        start = max(0, center - max_ms // 2)
        end = min(duration or start + max_ms, start + max_ms)
        start = max(0, end - max_ms)
    return int(start), int(max(start + 1, end))


def signal_context_range(
    project: SubtitleProject,
    signal_in_ms: int,
    signal_out_ms: int,
    *,
    pad_ms: int = 45_000,
) -> tuple[int, int]:
    """Broad evidence window retained separately from the edit recommendation."""
    duration = max(
        int(project.media.duration_ms or 0),
        max((cue.end_ms for cue in project.cues), default=0),
    )
    start = max(0, int(signal_in_ms) - max(30_000, int(pad_ms)))
    end = int(signal_out_ms) + max(30_000, int(pad_ms))
    if duration:
        end = min(duration, end)
    return start, max(start + 1, end)


def subtitle_density_windows(project: SubtitleProject, window_ms: int = 10000) -> list[tuple[int, int, int]]:
    if window_ms <= 0:
        return []
    duration = max((cue.end_ms for cue in project.cues), default=0)
    duration = max(duration, int(project.media.duration_ms or 0))
    last = max(0, duration // window_ms)
    buckets = [0] * (last + 1)
    for cue in project.cues:
        index = min(last, max(0, cue.start_ms // window_ms))
        buckets[index] += max(1, len(cue.text.strip()))
    return [
        (index * window_ms, (index + 1) * window_ms, count)
        for index, count in enumerate(buckets)
    ]


def conversation_boundaries(project: SubtitleProject, *, gap_ms: int = 2500) -> list[int]:
    marks = [0]
    previous = None
    for cue in sorted(project.cues, key=lambda item: item.start_ms):
        if previous is not None:
            if cue.start_ms - previous.end_ms >= gap_ms or cue.speaker_id != previous.speaker_id:
                marks.append(cue.start_ms)
        previous = cue
    return marks


def cluster_windows(
    windows: list[DanmakuWindow],
    *,
    gap_ms: int = CLUSTER_GAP_MS,
) -> list[list[DanmakuWindow]]:
    """Group time-adjacent signal windows into one event cluster."""
    clusters: list[list[DanmakuWindow]] = []
    for window in sorted(windows, key=lambda item: item.start_ms):
        if clusters and window.start_ms - clusters[-1][-1].end_ms <= max(0, gap_ms):
            clusters[-1].append(window)
        else:
            clusters.append([window])
    return clusters


def cluster_stats(cluster: list[DanmakuWindow]) -> dict[str, Any]:
    """簇级弹幕统计——卡片底部/详情/文案共享的唯一数据对象。

    2026-09-19 P1 统一口径：raw_total=簇内全部原始事件数；usable_total=
    剔除广告/例行后的有效条数（旧文案"422 条"即此值）；windows=热窗数；
    peak_spike=簇内最高倍数（对 spike 最高的窗，不再与 best-raw 窗混用）；
    funny/chaos_*_count=按条计数（一条弹幕至多 1，替代旧"hits 次数"）。
    """
    if not cluster:
        return {}
    best_spike = max(cluster, key=lambda item: item.spike)
    return {
        "raw_total": int(sum(item.count for item in cluster)),
        "usable_total": int(sum(item.effective_count for item in cluster)),
        "windows": len(cluster),
        "peak_spike": round(best_spike.spike, 2),
        "funny_count": int(sum(getattr(item, "funny_count", 0) for item in cluster)),
        "chaos_count": int(sum(getattr(item, "chaos_count", 0) for item in cluster)),
        "keywords": list(dict.fromkeys(
            keyword
            for window in sorted(cluster, key=lambda item: item.raw_score, reverse=True)
            for keyword in window.keywords
        ))[:8],
    }


def _cluster_evidence(cluster: list[DanmakuWindow]) -> list[str]:
    stats = cluster_stats(cluster)
    if not stats:
        return []
    evidence = [
        # Plain-language only: ratios against a "baseline" read as jargon.
        f"弹幕高峰 {stats['windows']} 段共 {stats['usable_total']} 条（原始 {stats['raw_total']} 条），"
        f"最热时约为平时的 {max(1.0, stats['peak_spike']):.1f} 倍"
    ]
    if stats["funny_count"]:
        evidence.append(f"观众在笑：{stats['funny_count']} 条搞笑弹幕")
    if stats["chaos_count"]:
        evidence.append(f"观众在惊叹：{stats['chaos_count']} 条惊讶弹幕")
    keywords = [str(k).strip() for k in stats["keywords"] if str(k).strip()]
    if keywords:
        evidence.append("观众在说：" + "、".join(keywords[:5]))
    return evidence


def _cluster_quotes(cluster: list[DanmakuWindow], limit: int = 3) -> list[str]:
    quotes: list[str] = []
    for window in sorted(cluster, key=lambda item: item.raw_score, reverse=True):
        for comment in window.representative_comments:
            if comment not in quotes:
                quotes.append(comment)
        if len(quotes) >= limit:
            break
    return quotes[:limit]


def discover_local_candidates(
    project: SubtitleProject,
    danmaku: DanmakuDocument | None,
    *,
    window_ms: int = 10000,
    top_k: int = 50,
) -> list[LocalCandidate]:
    scored: dict[int, LocalCandidate] = {}

    def bump(start: int, end: int, score: float, reason: str, window: DanmakuWindow | None = None, quotes: list[str] | None = None, full_span: bool = False) -> None:
        bucket = max(0, int(start) // 5000 * 5000)
        span = int(end) - int(start)
        if not full_span:
            span = max(10000, min(30000, span))
        key = bucket
        current = scored.get(key)
        if current is None:
            scored[key] = LocalCandidate(bucket, bucket + max(10000, span), score, [reason], window, list(quotes or []))
            return
        current.score = max(current.score, score)
        current.end_ms = max(current.end_ms, bucket + max(10000, span))
        if reason not in current.reasons:
            current.reasons.append(reason)
        if quotes:
            current.quotes.extend(quotes)

    danmaku_windows: list[DanmakuWindow] = []
    if danmaku is not None and danmaku.events:
        # The bundled livestream-clip-finder algorithm uses 10-30 second
        # windows and a nearby-window baseline. Long recordings use 30s.
        analysis_window = 30000 if danmaku.duration_ms >= 45 * 60 * 1000 else max(10000, min(30000, window_ms))
        windows = aggregate_danmaku(danmaku, window_ms=analysis_window, context=1)
        # No top-window fallback here: a uniform/quiet stream must yield no
        # danmaku candidate. The XML-only guarantee is handled below.
        danmaku_windows = local_spike_windows(
            windows, min_spike=1.25, top_k=top_k, fallback_to_top=False
        )
        max_raw = max((item.raw_score for item in danmaku_windows), default=1.0)
        # Adjacent signal windows are one event: a 30-minute highlight must
        # surface as ONE candidate spanning it, not dozens of 30-second ones.
        clusters = cluster_windows(danmaku_windows)
        clusters.sort(
            key=lambda group: (max(item.raw_score for item in group), group[0].start_ms),
            reverse=True,
        )
        for rank, cluster in enumerate(clusters[:top_k]):
            best = max(cluster, key=lambda item: item.raw_score)
            reasons = _cluster_evidence(cluster)
            relative = best.raw_score / max(1.0, max_raw)
            rank_penalty = min(0.12, rank * 0.006)
            score = max(0.45, min(0.96, 0.50 + relative * 0.46 - rank_penalty))
            # First evidence line becomes the card reason; the rest render as
            # structured evidence rows (no duplicated blobs).
            bump(
                cluster[0].start_ms,
                cluster[-1].end_ms,
                score,
                reasons[0],
                best,
                _cluster_quotes(cluster),
                full_span=True,
            )
            current = scored.get(cluster[0].start_ms // 5000 * 5000)
            if current is not None:
                current.cluster = list(cluster)
                for extra in reasons[1:]:
                    if extra not in current.reasons:
                        current.reasons.append(extra)

    # Subtitle semantic recall runs in EVERY mode: quiet highlights rely on it.
    # (No "quiet audience" disclaimer here — NMS merges this line into danmaku
    # reasons and the two narratives contradict each other.)
    semantic = SEMANTIC_SUBTITLE_PATTERN
    for cue in project.cues:
        match = semantic.search(cue.text)
        expressive = cue.text.count("！") + cue.text.count("!") + cue.text.count("？") + cue.text.count("?")
        if match or expressive >= 2:
            score = min(0.82, 0.55 + expressive * 0.04 + (0.12 if match else 0.0))
            bump(max(0, cue.start_ms - 5000), cue.end_ms + 8000, score, "字幕出现强情绪/转折", quotes=[cue.text])
    if not scored:
        if danmaku is not None and danmaku.events:
            # XML-only guarantee: with nothing admitted and no transcript to
            # recall from, still show the busiest windows rather than nothing.
            for window in local_spike_windows(
                aggregate_danmaku(danmaku, window_ms=30_000, context=1), top_k=top_k
            ):
                bump(
                    window.start_ms,
                    window.end_ms,
                    0.45,
                    f"弹幕相对活跃：{window.effective_count} 条（基线 {window.baseline:.1f}）",
                    window,
                    window.representative_comments,
                )
        else:
            for start in conversation_boundaries(project)[1:top_k + 1]:
                bump(max(0, start - 5000), start + 10000, 0.42, "对话场景切换")

    ranked = sorted(scored.values(), key=lambda item: (item.score, -item.start_ms), reverse=True)
    return ranked[:top_k]


def _format_clock(ms: int) -> str:
    seconds = max(0, int(ms)) // 1000
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def window_payload(
    project: SubtitleProject,
    candidate: LocalCandidate,
    *,
    pad_ms: int = 45000,
) -> dict[str, Any]:
    start = max(0, candidate.start_ms - pad_ms)
    end = candidate.end_ms + pad_ms
    span = max(0, end - start)
    # Wide clusters (long events) get a bigger, stride-sampled transcript so
    # the model can see the whole arc instead of the first 24 cues.
    # 2026-09-19 P1 提额：≤120s 全量（≤40 条），>120s 采样提额到 120 条——
    # 事件摘要需要完整前后文，24 条采样稿撑不起"发生了什么"。
    transcript_limit = 40 if span <= 120_000 else 120
    danmaku = candidate.danmaku
    payload = {
        "time": f"{_format_clock(start)}–{_format_clock(end)}",
        "source_in_hint": candidate.start_ms / 1000.0,
        "source_out_hint": candidate.end_ms / 1000.0,
        "local_score": round(candidate.score, 3),
        "reasons": candidate.reasons[:6],
        "transcript": transcript_window(
            project, start, end, limit=transcript_limit, sample=transcript_limit > 40
        ),
    }
    if danmaku is not None:
        payload["danmaku"] = {
            "count": danmaku.count,
            "usable_count": danmaku.effective_count,
            "baseline": round(danmaku.baseline, 2),
            "spike": round(danmaku.spike, 2),
            "funny_hits": danmaku.funny_hits,
            "chaos_hits": danmaku.chaos_hits,
            "keywords": danmaku.keywords[:8],
            "representative_comments": danmaku.representative_comments[:4],
            "promotional_hits": danmaku.promotional_hits,
            "routine_hits": danmaku.routine_hits,
            "top": [{"text": text, "n": n} for text, n in danmaku.top_texts[:6]],
            "reactions": danmaku.reactions,
        }
        # 簇级统计（候选范围内的全热区口径）——模型与卡片底部同源。
        cluster = getattr(candidate, "cluster", None)
        if cluster:
            payload["danmaku_cluster"] = cluster_stats(cluster)
    if candidate.quotes:
        payload["quotes"] = candidate.quotes[:6]
    return payload


def _danmaku_signal(candidate: LocalCandidate | None, window: DanmakuWindow | None = None) -> dict[str, Any]:
    """候选的弹幕统计信号——优先簇级（与卡片底部/详情同源）。"""
    if candidate is not None and getattr(candidate, "cluster", None):
        stats = cluster_stats(candidate.cluster)
        if stats:
            stats["peak_window_raw"] = int(window.count) if window is not None else stats["raw_total"]
            return stats
    if window is None:
        return {}
    return {
        "peak": window.effective_count,
        "raw_count": window.count,
        "raw_total": window.count,
        "usable_total": window.effective_count,
        "windows": 1,
        "baseline": round(window.baseline, 2),
        "spike": round(window.spike, 2),
        "peak_spike": round(window.spike, 2),
        "funny_hits": window.funny_hits,
        "chaos_hits": window.chaos_hits,
        "funny_count": getattr(window, "funny_count", 0),
        "chaos_count": getattr(window, "chaos_count", 0),
        "keywords": list(window.keywords[:8]),
        "promotional_hits": window.promotional_hits,
        "routine_hits": window.routine_hits,
    }


def _danmaku_evidence(window: DanmakuWindow | None) -> list[str]:
    if window is None:
        return []
    evidence = [f"弹幕 {window.effective_count} 条，约为平时的 {max(1.0, window.spike):.1f} 倍"]
    if window.funny_hits:
        evidence.append(f"观众在笑：{window.funny_hits} 条搞笑弹幕")
    if window.chaos_hits:
        evidence.append(f"观众在惊叹：{window.chaos_hits} 条惊讶弹幕")
    return evidence


def _scan_title(clean: str, limit: int = 18) -> str:
    """Humane scan title: short, and cut at a natural pause when possible."""
    if len(clean) <= limit:
        return clean
    cut = clean[:limit]
    for index in range(len(cut) - 1, max(6, len(cut) // 2), -1):
        if cut[index] in "，。！？!?、,；; ":
            return cut[:index].rstrip() + "…"
    # No punctuation in range (raw ASR brick): at least avoid dangling
    # particles/interjection prefixes at the cut.
    while cut and cut[-1] in "了的吗吧呢啊就也我你他她它们个是在和跟很都还又再":
        cut = cut[:-1]
    return cut + "…"


def _local_candidate_title(candidate: LocalCandidate, index: int, project: SubtitleProject | None = None) -> str:
    """本地回退标题（2026-09-19 P1 诚实化）。

    LLM 未参与时本地没有事件理解能力——不再用截断的字幕原句冒充事件
    标题（用户实测"可以了我预感到超怪马上"）。标题=时间范围+信号类型+
    待核实标记；事件内容交给 event_summary 的台词摘录与人工预览。
    """
    start = _format_clock(candidate.start_ms)
    end = _format_clock(candidate.end_ms)
    if candidate.danmaku is not None:
        stats = cluster_stats(candidate.cluster) if candidate.cluster else {}
        if stats:
            return f"{start}–{end} 弹幕热区 · 待核实"
        return f"{start}–{end} 弹幕峰值 · 待核实"
    return f"{start} 语义高亮段 · 待核实"


def _local_candidate_event_summary(candidate: LocalCandidate, project: SubtitleProject | None) -> str:
    """本地回退的"发生了什么"=主播台词摘录（明确标注，不冒充事件概括）。"""
    if project is None:
        return ""
    lines = transcript_window(
        project, candidate.start_ms, candidate.end_ms, limit=3
    ).splitlines()
    cleaned: list[str] = []
    for line in lines:
        text = re.sub(r"^[^:：]{1,20}[:：]\s*", "", line).strip()
        if text and len(re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text)) >= 3:
            cleaned.append(text)
    if not cleaned:
        return ""
    return "本地分析（AI 未参与），该段主播台词摘录：" + "；".join(f"「{item}」" for item in cleaned[:3])


def _local_candidate_reason(candidate: LocalCandidate) -> str:
    """本地回退的"为什么值得剪"=热度证据+待核实声明（不编造看点）。"""
    stats = cluster_stats(candidate.cluster) if getattr(candidate, "cluster", None) else {}
    if stats:
        return (
            f"弹幕热度证据：{stats['windows']} 个热窗共 {stats['usable_total']} 条有效弹幕"
            f"（原始 {stats['raw_total']} 条），峰值约 {max(1.0, stats['peak_spike']):.1f} 倍。"
            "事件内容尚未核实（本地分析无事件理解），建议预览确认触发点后再决定。"
        )
    if candidate.danmaku is not None:
        return (
            f"该窗弹幕峰值约 {max(1.0, candidate.danmaku.spike):.1f} 倍。"
            "事件内容尚未核实，建议预览确认。"
        )
    return "字幕语义命中高亮词。事件内容尚未核实，建议预览确认。"


def parse_highlight_payload(content: str, fallback: list[LocalCandidate]) -> list[HighlightCandidate]:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        payload = json.loads(match.group(0)) if match else {}
    rows = payload.get("candidates", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        rows = []
    results: list[HighlightCandidate] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            continue
        try:
            source_in = float(row.get("source_in", row.get("start_ms", row.get("source_in_ms", 0))) or 0)
            source_out = float(row.get("source_out", row.get("end_ms", row.get("source_out_ms", 0))) or 0)
        except (TypeError, ValueError):
            continue
        if source_in > 1000 and source_out > 1000:
            source_in_ms = int(source_in)
            source_out_ms = int(source_out)
        else:
            source_in_ms = int(source_in * 1000)
            source_out_ms = int(source_out * 1000)
        if source_out_ms - source_in_ms < 1000:
            continue
        try:
            score_value = float(row.get("score") or 60.0)
        except (TypeError, ValueError):
            score_value = 60.0
        score_value = score_value / 100.0 if score_value > 1.0 else score_value
        results.append(
            HighlightCandidate(
                id=f"hl-{index:03d}-{source_in_ms}",
                title=str(row.get("title") or f"候选 {index + 1}"),
                source_in_ms=source_in_ms,
                source_out_ms=source_out_ms,
                score=max(0.0, min(1.0, score_value)),
                reason=str(row.get("reason") or ""),
                danmaku_signal=dict(row.get("danmaku_signal") or {}),
                quotes=_string_list(row.get("quotes")),
                status="suggested",
                origin="ai",
                grade=str(row.get("grade") or ""),
                hook=str(row.get("hook") or ""),
                event_summary=str(
                    row.get("event_summary")
                    or row.get("hook")
                    or row.get("title")
                    or ""
                ),
                clip_reason=str(row.get("clip_reason") or row.get("reason") or ""),
                context_required=str(
                    row.get("context_required")
                    if str(row.get("context_required") or "").lower()
                    in {"low", "medium", "high"}
                    else ""
                ),
                danmaku_evidence=_string_list(row.get("danmaku_evidence")),
                subtitle_evidence=_string_list(row.get("subtitle_evidence")),
                edit_direction=str(row.get("edit_direction") or ""),
                subtitle_emphasis=_string_list(row.get("subtitle_emphasis")),
                risk_notes=_string_list(row.get("risk_notes")),
                category=str(row.get("category") or "other"),
            )
        )
    if results:
        return results
    # Local fallback so the UI still has something if the model returns prose.
    fallback_items = []
    for index, item in enumerate(fallback[:8]):
        fallback_items.append(
            HighlightCandidate(
                id=f"hl-local-{index:03d}",
                title=_local_candidate_title(item, index),
                source_in_ms=item.start_ms,
                source_out_ms=item.end_ms,
                score=item.score,
                reason=_local_candidate_reason(item),
                quotes=item.quotes,
                danmaku_signal=_danmaku_signal(item, item.danmaku),
                danmaku_evidence=_danmaku_evidence(item.danmaku),
                status="suggested",
                origin="ai",
            )
        )
    return fallback_items


def _gap_merge_threshold(span_a_ms: int, span_b_ms: int) -> int:
    """Nearby fragments of one event merge; independent moments stay apart."""
    return max(10_000, min(45_000, int(0.25 * min(span_a_ms, span_b_ms))))


def _range_gap(a_in: int, a_out: int, b_in: int, b_out: int) -> int:
    if a_in < b_out and b_in < a_out:
        return 0
    if b_in >= a_out:
        return b_in - a_out
    return a_in - b_out


def merge_overlapping_candidates(
    candidates: list[HighlightCandidate],
    *,
    overlap_threshold: float = 0.45,
) -> list[HighlightCandidate]:
    """Merge near-duplicate LLM/local ranges using overlap NMS + gap merge."""
    kept: list[HighlightCandidate] = []
    for candidate in sorted(candidates, key=lambda item: (item.score, -item.source_in_ms), reverse=True):
        duplicate = None
        for existing in kept:
            overlap = max(0, min(candidate.source_out_ms, existing.source_out_ms) - max(candidate.source_in_ms, existing.source_in_ms))
            shorter = max(1, min(candidate.source_out_ms - candidate.source_in_ms, existing.source_out_ms - existing.source_in_ms))
            if overlap / shorter >= overlap_threshold:
                duplicate = existing
                break
            gap = _range_gap(
                existing.source_in_ms, existing.source_out_ms,
                candidate.source_in_ms, candidate.source_out_ms,
            )
            threshold = _gap_merge_threshold(
                candidate.source_out_ms - candidate.source_in_ms,
                existing.source_out_ms - existing.source_in_ms,
            )
            if gap <= threshold:
                duplicate = existing
                break
        if duplicate is None:
            kept.append(candidate)
            continue
        duplicate.source_in_ms = min(duplicate.source_in_ms, candidate.source_in_ms)
        duplicate.source_out_ms = max(duplicate.source_out_ms, candidate.source_out_ms)
        duplicate.context_in_ms = min(
            duplicate.context_in_ms or duplicate.source_in_ms,
            candidate.context_in_ms or candidate.source_in_ms,
        )
        duplicate.context_out_ms = max(
            duplicate.context_out_ms or duplicate.source_out_ms,
            candidate.context_out_ms or candidate.source_out_ms,
        )
        duplicate.danmaku_evidence = list(dict.fromkeys(duplicate.danmaku_evidence + candidate.danmaku_evidence))
        duplicate.subtitle_evidence = list(dict.fromkeys(duplicate.subtitle_evidence + candidate.subtitle_evidence))
        duplicate.quotes = list(dict.fromkeys(duplicate.quotes + candidate.quotes))
        if candidate.reason and candidate.reason not in duplicate.reason:
            duplicate.reason = "；".join(filter(None, (duplicate.reason, candidate.reason)))
    kept.sort(key=lambda item: (item.score, -item.source_in_ms), reverse=True)
    return kept


def candidates_from_local(
    project: SubtitleProject,
    locals_: list[LocalCandidate],
    *,
    limit: int,
    max_seconds: int,
) -> list[HighlightCandidate]:
    candidates: list[HighlightCandidate] = []
    for index, item in enumerate(locals_[:max(1, limit)]):
        transcript = transcript_window(project, item.start_ms, item.end_ms, limit=4).splitlines()
        context_lines = transcript_window(project, item.start_ms, item.end_ms, limit=40).splitlines()
        source_in, source_out = expand_candidate_context(
            project,
            item.start_ms,
            min(item.end_ms, item.start_ms + max_seconds * 1000),
            max_ms=max_seconds * 1000,
        )
        context_in, context_out = signal_context_range(
            project,
            item.start_ms,
            min(item.end_ms, item.start_ms + max_seconds * 1000),
        )
        local_reason = _local_candidate_reason(item)
        candidates.append(
            HighlightCandidate(
                id=f"hl-local-{index:03d}-{item.start_ms}",
                title=_local_candidate_title(item, index, project),
                source_in_ms=source_in,
                source_out_ms=source_out,
                signal_in_ms=item.start_ms,
                signal_out_ms=min(item.end_ms, item.start_ms + max_seconds * 1000),
                context_in_ms=context_in,
                context_out_ms=context_out,
                score=max(0.0, min(1.0, item.score)),
                reason=local_reason,
                quotes=list(item.quotes),
                danmaku_signal=_danmaku_signal(item, item.danmaku),
                danmaku_evidence=list(item.reasons[1:]) or _danmaku_evidence(item.danmaku),
                subtitle_evidence=transcript,
                subtitle_context=context_lines,
                status="suggested",
                # 2026-09-19 P1：本地回退诚实标注——没有 LLM 参与就不是
                # AI 事件分析，卡片据此显示"本地·待核实"徽标。
                origin="local",
                context_required="high",
                risk_notes=["事件摘要待核实：本地分析仅弹幕/语义热度，未做事件理解"],
                category=("funny" if item.danmaku and item.danmaku.funny_hits >= item.danmaku.chaos_hits and item.danmaku.funny_hits else
                          "chaos" if item.danmaku and item.danmaku.chaos_hits else "other"),
            )
        )
        # 本地回退没有独立 event_summary 字段入口：写回第一条。
        candidates[-1].event_summary = _local_candidate_event_summary(item, project)
        candidates[-1].clip_reason = local_reason
    return merge_overlapping_candidates(candidates)[:limit]


def _apply_ai_override(
    settings: dict,
    ai_service: str,
    model: str,
) -> dict:
    """Return a call-site copy of settings routed through the chosen service.

    Never mutates the caller's dict: the global Provider Profile stays the
    single source of truth; this override only affects one analysis run.
    """
    service = str(ai_service or "").strip()
    if not service:
        return settings
    from .llm_config import activate_ai_service, update_active_profile

    override = copy.deepcopy(settings)
    activate_ai_service(override, service)
    if str(model or "").strip():
        update_active_profile(override, stage="polish", model=str(model).strip())
    return override


def rank_candidates_with_llm(
    project: SubtitleProject,
    locals_: list[LocalCandidate],
    *,
    runtime_settings: dict | None = None,
    skill: HighlightSkillAdapter | None = None,
    target_count: int = 20,
    min_seconds: int = 30,
    max_seconds: int = 180,
    ai_service: str = "",
    model: str = "",
    post: Callable[..., str] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[HighlightCandidate]:
    settings = runtime_settings if isinstance(runtime_settings, dict) else {}
    if not settings.get("models"):
        from .settings import load_runtime_settings

        loaded = load_runtime_settings()
        settings = loaded[0] if isinstance(loaded, tuple) else loaded
    settings = _apply_ai_override(settings, ai_service, model)
    adapter = skill or HighlightSkillAdapter.discover()
    system = GENERIC_SYSTEM_PROMPT
    windows = [window_payload(project, item) for item in locals_[:50]]
    user = {
        "goal": {"count": int(target_count), "length_seconds": [int(min_seconds), int(max_seconds)]},
        "stream_duration_ms": int(project.media.duration_ms or 0),
        "windows": windows,
        "rule": "只返回 JSON。不要解释。",
    }
    schema = {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "start_ms": {"type": "integer"},
                        "end_ms": {"type": "integer"},
                        "score": {"type": "number"},
                        "grade": {"type": "string"},
                        "title": {"type": "string"},
                        "hook": {"type": "string"},
                        "event_summary": {"type": "string", "minLength": 10, "maxLength": 160},
                        "clip_reason": {"type": "string", "minLength": 12, "maxLength": 240},
                        "context_required": {"type": "string", "enum": ["low", "medium", "high"]},
                        "reason": {"type": "string"},
                        "danmaku_evidence": {"type": "array", "items": {"type": "string"}},
                        "subtitle_evidence": {"type": "array", "items": {"type": "string"}},
                        "edit_direction": {"type": "string"},
                        "subtitle_emphasis": {"type": "array", "items": {"type": "string"}},
                        "risk_notes": {"type": "array", "items": {"type": "string"}},
                        "category": {"type": "string"},
                    },
                    "required": [
                        "start_ms", "end_ms", "score", "grade", "title",
                        "event_summary", "clip_reason", "context_required",
                        "reason", "category",
                    ],
                },
            },
        },
        "required": ["candidates"],
    }
    provider = provider_for_stage(settings, "polish", sender=post)
    content = provider.complete(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        max_tokens=3500,
        temperature=0.2,
        timeout=(15, 120),
        enable_thinking=False,
        response_format={"type": "json_object"},
        stage="studio_highlight",
        structured_retry_system_prompt=GENERIC_SYSTEM_PROMPT,
        json_schema=schema,
        cancel_check=cancel_check,
    )
    ranked = parse_highlight_payload(content, locals_)
    for candidate in ranked:
        local = next(
            (
                item for item in locals_
                if max(0, min(candidate.source_out_ms, item.end_ms) - max(candidate.source_in_ms, item.start_ms)) > 0
            ),
            None,
        )
        if local is not None:
            candidate.signal_in_ms = local.start_ms
            candidate.signal_out_ms = local.end_ms
            candidate.context_in_ms, candidate.context_out_ms = signal_context_range(
                project, local.start_ms, local.end_ms
            )
            candidate.danmaku_signal = candidate.danmaku_signal or _danmaku_signal(local, local.danmaku)
            candidate.danmaku_evidence = candidate.danmaku_evidence or _danmaku_evidence(local.danmaku)
            candidate.quotes = candidate.quotes or list(local.quotes)
            if not candidate.subtitle_evidence:
                candidate.subtitle_evidence = transcript_window(project, local.start_ms, local.end_ms, limit=4).splitlines()
            # 2026-09-19 P1：信号范围内的完整字幕上下文随候选存档——
            # "发生了什么"的可追溯证据，重生成解释/人工核对都读这一份。
            if not candidate.subtitle_context:
                candidate.subtitle_context = transcript_window(
                    project, local.start_ms, local.end_ms, limit=40
                ).splitlines()
            if candidate.source_out_ms - candidate.source_in_ms < min_seconds * 1000:
                candidate.source_in_ms, candidate.source_out_ms = expand_candidate_context(
                    project,
                    local.start_ms,
                    local.end_ms,
                    min_ms=min_seconds * 1000,
                    max_ms=max_seconds * 1000,
                )
    wanted = max(1, int(target_count))
    duration = int(project.media.duration_ms or 0)
    if len(ranked) == 1 and duration and ranked[0].source_out_ms - ranked[0].source_in_ms > duration * 0.7:
        ranked = []
    existing = {(item.source_in_ms // 1000, item.source_out_ms // 1000) for item in ranked}
    for index, item in enumerate(locals_):
        if len(ranked) >= wanted:
            break
        key = (item.start_ms // 1000, item.end_ms // 1000)
        if key in existing:
            continue
        source_in_ms, source_out_ms = expand_candidate_context(
            project,
            item.start_ms,
            item.end_ms,
            min_ms=min_seconds * 1000,
            max_ms=max_seconds * 1000,
        )
        context_in_ms, context_out_ms = signal_context_range(
            project, item.start_ms, item.end_ms
        )
        ranked.append(
            HighlightCandidate(
                id=f"hl-local-{index:03d}",
                title=_local_candidate_title(item, index, project),
                source_in_ms=source_in_ms,
                source_out_ms=source_out_ms,
                signal_in_ms=item.start_ms,
                signal_out_ms=item.end_ms,
                context_in_ms=context_in_ms,
                context_out_ms=context_out_ms,
                score=item.score,
                reason=_local_candidate_reason(item),
                quotes=item.quotes,
                danmaku_signal=_danmaku_signal(item, item.danmaku),
                danmaku_evidence=_danmaku_evidence(item.danmaku),
                subtitle_evidence=transcript_window(project, item.start_ms, item.end_ms, limit=4).splitlines(),
                status="suggested",
                origin="ai",
            )
        )
        existing.add(key)
    return merge_overlapping_candidates(ranked)[:wanted]


def analyze_highlights(
    project: SubtitleProject,
    *,
    danmaku_path: str = "",
    mode: str = "subtitles_xml",
    runtime_settings: dict | None = None,
    target_count: int = 20,
    min_seconds: int = 30,
    max_seconds: int = 180,
    ai_service: str = "",
    model: str = "",
    post: Callable[..., str] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    project = highlight_transcript_project(project)
    if cancel_check is not None and cancel_check():
        raise RuntimeError("分析已取消")
    skill = HighlightSkillAdapter.discover()
    danmaku = None
    if danmaku_path and mode in {"xml", "subtitles_xml"}:
        danmaku = parse_danmaku_xml(danmaku_path)
    if mode == "xml" and danmaku is None:
        raise ValueError("请先导入弹幕 XML")
    locals_ = discover_local_candidates(project, danmaku if mode != "subtitles" else None)
    if cancel_check is not None and cancel_check():
        raise RuntimeError("分析已取消")
    llm_status = "completed"
    llm_error = ""
    try:
        ranked = rank_candidates_with_llm(
            project,
            locals_,
            runtime_settings=runtime_settings,
            skill=skill,
            target_count=target_count,
            min_seconds=min_seconds,
            max_seconds=max_seconds,
            ai_service=ai_service,
            model=model,
            post=post,
            cancel_check=cancel_check,
        )
    except Exception as exc:
        if cancel_check is not None and cancel_check():
            raise RuntimeError("分析已取消") from exc
        ranked = candidates_from_local(project, locals_, limit=target_count, max_seconds=max_seconds)
        llm_status = "local_fallback"
        llm_error = " ".join(str(exc).split())[:240]
    return {
        "skill_found": skill.found,
        "skill_path": skill.path,
        "local_count": len(locals_),
        "danmaku_count": danmaku.count if danmaku else 0,
        "danmaku_duration_ms": danmaku.duration_ms if danmaku else 0,
        "llm_status": llm_status,
        "llm_error": llm_error,
        "ai_service": str(ai_service or ""),
        "model": str(model or ""),
        "candidates": ranked,
    }
