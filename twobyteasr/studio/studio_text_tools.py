"""Subtitle text productivity helpers: scoped search, tidy, glossary, AI parse.

The find/replace dialog stays a thin UI over this module. Every bulk mutation
is expressed as ``{cue_id: new_text}`` so Studio can push one undo command.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from ..projects.studio_project import StudioCue, SubtitleProject


SCOPE_CURRENT = "current"
SCOPE_SELECTED = "selected"
SCOPE_SPEAKER = "speaker"
SCOPE_TRACK = "track"
SCOPE_RANGE = "range"
SCOPE_ALL = "all"

PAUSE_LIGHT_TO_SPACE = "light_to_space"
PAUSE_KEEP_LONG = "keep_long"
PAUSE_SKIP = "skip"


@dataclass(frozen=True)
class TextOccurrence:
    cue_id: str
    start_ms: int
    original: str
    replacement: str
    span: tuple[int, int]
    reason: str = ""
    confidence: float = 1.0
    default_selected: bool = True
    source: str = ""
    evidence: str = ""
    missing_evidence: str = ""


def cue_locked(cue: StudioCue, locked_ids: Iterable[str] | None = None) -> bool:
    if bool(getattr(cue, "locked", False)):
        return True
    return str(cue.id) in {str(item) for item in (locked_ids or ())}


def _playhead_ms(page) -> int:
    for attr in ("_playhead_ms", "playhead_ms"):
        value = getattr(page, attr, None)
        if value is not None:
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                pass
    video = getattr(page, "video", None)
    for name in ("position", "current_position", "playhead"):
        getter = getattr(video, name, None)
        if callable(getter):
            try:
                return max(0, int(float(getter()) * 1000))
            except (TypeError, ValueError):
                continue
        if getter is not None:
            try:
                return max(0, int(float(getter) * 1000))
            except (TypeError, ValueError):
                continue
    return 0


def scope_cue_ids(page, scope: str) -> list[str]:
    project = page.session.project if page is not None else None
    if project is None:
        return []
    cues = list(project.cues)
    lookup = {cue.id: cue for cue in cues}
    from ..timeline.studio_edit_sequence import source_cue_id_of
    resolve = lambda value: str(value) if str(value) in lookup else source_cue_id_of(str(value))
    selected = list(dict.fromkeys(resolve(v) for v in page.selected_cue_ids())) if page is not None else []
    current = resolve(getattr(page.session, "selected_cue_id", "") or (selected[0] if selected else ""))
    if scope == SCOPE_CURRENT:
        return [current] if current in lookup else []
    if scope == SCOPE_SELECTED:
        return [cue_id for cue_id in selected if cue_id in lookup] or ([current] if current in lookup else [])
    if scope == SCOPE_SPEAKER:
        cue = lookup.get(current)
        if cue is None:
            return []
        return [item.id for item in cues if item.speaker_id == cue.speaker_id]
    if scope == SCOPE_TRACK:
        cue = lookup.get(current)
        if cue is None:
            return []
        return [item.id for item in cues if item.style_id == cue.style_id]
    if scope == SCOPE_RANGE:
        if len(selected) >= 2:
            chosen = [lookup[cue_id] for cue_id in selected if cue_id in lookup]
            start = min(item.start_ms for item in chosen)
            end = max(item.end_ms for item in chosen)
        else:
            playhead = _playhead_ms(page)
            start, end = max(0, playhead - 8_000), playhead + 8_000
        return [item.id for item in cues if item.end_ms > start and item.start_ms < end]
    return [cue.id for cue in cues]


def _body_text(text: str) -> str:
    return re.sub(r"\{[^}]*\}", "", str(text or ""))


def _compile_needle(needle: str, *, case_sensitive: bool, whole_word: bool, regex: bool) -> re.Pattern[str]:
    flags = 0 if case_sensitive else re.IGNORECASE
    if regex:
        pattern = needle
    else:
        pattern = re.escape(needle)
        if whole_word:
            if re.search(r"[A-Za-z0-9_]", needle):
                pattern = rf"\b{pattern}\b"
            else:
                pattern = rf"(?<!\w){pattern}(?!\w)"
    return re.compile(pattern, flags)


def find_occurrences(
    project: SubtitleProject,
    cue_ids: Iterable[str],
    needle: str,
    replacement: str,
    *,
    case_sensitive: bool = False,
    whole_word: bool = False,
    regex: bool = False,
    body_only: bool = False,
    skip_locked: bool = True,
    locked_ids: Iterable[str] | None = None,
) -> list[TextOccurrence]:
    if not needle:
        return []
    try:
        pattern = _compile_needle(
            needle, case_sensitive=case_sensitive, whole_word=whole_word, regex=regex
        )
    except re.error:
        return []
    wanted = set(cue_ids)
    hits: list[TextOccurrence] = []
    for cue in project.cues:
        if cue.id not in wanted:
            continue
        if skip_locked and cue_locked(cue, locked_ids):
            continue
        source = _body_text(cue.text) if body_only else cue.text
        for match in pattern.finditer(source):
            if regex:
                try:
                    replaced = match.expand(replacement)
                except re.error:
                    replaced = replacement
            else:
                replaced = replacement
            hits.append(TextOccurrence(
                cue_id=cue.id,
                start_ms=cue.start_ms,
                original=match.group(0),
                replacement=replaced,
                span=(match.start(), match.end()),
            ))
    return hits


def values_from_occurrences(project: SubtitleProject, hits: Iterable[TextOccurrence], *, strict=False) -> dict[str, str]:
    grouped: dict[str, list[TextOccurrence]] = {}
    for hit in hits:
        grouped.setdefault(hit.cue_id, []).append(hit)
    lookup = {cue.id: cue for cue in project.cues}
    values: dict[str, str] = {}
    for cue_id, items in grouped.items():
        cue = lookup.get(cue_id)
        if cue is None:
            if strict:
                raise ValueError("字幕已删除，整批清理没有应用。")
            continue
        text = cue.text
        for hit in sorted(items, key=lambda item: item.span[0], reverse=True):
            start, end = hit.span
            if not 0 <= start <= end <= len(text) or text[start:end] != hit.original:
                if strict:
                    raise ValueError("字幕原文已改变，整批清理没有应用。")
                continue
            text = text[:start] + hit.replacement + text[end:]
        if text != cue.text:
            values[cue_id] = text
    return values


def occurrence_conflicts(hits: Iterable[TextOccurrence]) -> bool:
    """Competing proposals for one span require an explicit choice."""
    grouped = {}
    for hit in hits:
        grouped.setdefault(hit.cue_id, []).append(hit)
    for items in grouped.values():
        ordered = sorted(items, key=lambda hit: hit.span)
        for first, second in zip(ordered, ordered[1:]):
            if (second.span[0] < first.span[1]
                    or first.span[0] == second.span[0] == first.span[1]):
                return True
    return False


_CN_PUNCT = str.maketrans({
    ",": "，",
    ".": "。",
    "?": "？",
    "!": "！",
    ":": "：",
    ";": "；",
    "(": "（",
    ")": "）",
})
_EN_PUNCT = str.maketrans({
    "，": ",",
    "。": ".",
    "？": "?",
    "！": "!",
    "：": ":",
    "；": ";",
    "（": "(",
    "）": ")",
})
_LIGHT_PAUSE = re.compile(r"(?:\.{2,}|…+|··+|～+|~+)")
_MULTI_SPACE = re.compile(r"[ \t\u3000]{2,}")


def _fullwidth_ascii(text: str) -> str:
    chars = []
    for char in text:
        code = ord(char)
        if code == 0x3000:
            chars.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            chars.append(chr(code - 0xFEE0))
        else:
            chars.append(char)
    return "".join(chars)


def tidy_text(
    text: str,
    *,
    punctuation: str = "",
    whitespace: bool = False,
    pause: str = PAUSE_SKIP,
) -> str:
    result = str(text or "")
    if punctuation == "cn":
        result = result.translate(_CN_PUNCT)
    elif punctuation == "en":
        result = result.translate(_EN_PUNCT)
    elif punctuation == "halfwidth":
        result = _fullwidth_ascii(result)
    if pause == PAUSE_LIGHT_TO_SPACE:
        result = _LIGHT_PAUSE.sub(" ", result)
    elif pause == PAUSE_KEEP_LONG:
        result = _LIGHT_PAUSE.sub(" ", result)
        result = re.sub(r"[ \t]+([。！？；])", r"\1", result)
    if whitespace:
        result = _MULTI_SPACE.sub(" ", result)
        result = "\n".join(line.strip() for line in result.splitlines())
        result = result.strip()
    return result


def tidy_occurrences(
    project: SubtitleProject,
    cue_ids: Iterable[str],
    *,
    punctuation: str = "",
    whitespace: bool = False,
    pause: str = PAUSE_SKIP,
    skip_locked: bool = True,
    locked_ids: Iterable[str] | None = None,
) -> list[TextOccurrence]:
    wanted = set(cue_ids)
    hits: list[TextOccurrence] = []
    for cue in project.cues:
        if cue.id not in wanted:
            continue
        if skip_locked and cue_locked(cue, locked_ids):
            continue
        cleaned = tidy_text(
            cue.text, punctuation=punctuation, whitespace=whitespace, pause=pause
        )
        if cleaned != cue.text:
            hits.append(TextOccurrence(
                cue_id=cue.id,
                start_ms=cue.start_ms,
                original=cue.text,
                replacement=cleaned,
                span=(0, len(cue.text)),
                reason="文本整理",
            ))
    return hits


def glossary_pairs(project: SubtitleProject | None = None) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    try:
        from subtitle_core import enabled_glossary_adjudication_evidence

        evidence = enabled_glossary_adjudication_evidence()
        for item in evidence.get("wrong_to_correct_mappings") or []:
            wrong, correct = str(item.get("wrong") or "").strip(), str(item.get("correct") or "").strip()
            if wrong and correct and wrong != correct:
                pairs.append((wrong, correct))
        for item in evidence.get("aliases") or []:
            alias, canonical = str(item.get("alias") or "").strip(), str(item.get("canonical") or "").strip()
            if alias and canonical and alias != canonical:
                pairs.append((alias, canonical))
    except Exception:
        pass
    if project is not None:
        for cue in project.cues:
            original = str(getattr(cue, "original_text", "") or "")
            if original and original != cue.text:
                continue
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for pair in pairs:
        if pair in seen:
            continue
        seen.add(pair)
        unique.append(pair)
    unique.sort(key=lambda item: len(item[0]), reverse=True)
    return unique


def glossary_occurrences(
    project: SubtitleProject,
    cue_ids: Iterable[str],
    pairs: Iterable[tuple[str, str]] | None = None,
    *,
    skip_locked: bool = True,
    locked_ids: Iterable[str] | None = None,
    glossary_ids: Iterable[str] | None = None,
    snapshot=None,
) -> list[TextOccurrence]:
    from ..glossary.terminology import TermResolver, snapshot_glossaries, snapshot_from_pairs
    import subtitle_core as legacy
    identities = tuple(project.glossary_ids if glossary_ids is None else glossary_ids)
    if snapshot is None:
        snapshot = snapshot_from_pairs(pairs) if pairs is not None else snapshot_glossaries(legacy, identities)
    from ..subtitle_rules.chinese_script import glossary_script
    resolver = TermResolver(snapshot, script=glossary_script(project))  # 繁體 project: 2026-10-19
    from ..recognition.content_scene import resolve_content_scene
    from types import SimpleNamespace
    scene = resolve_content_scene(SimpleNamespace(enable_domain_terms=bool(snapshot.libraries),
        glossary_snapshot=snapshot, game_name=''), snapshot)
    wanted = set(cue_ids)
    hits: list[TextOccurrence] = []
    for cue in project.cues:
        if cue.id not in wanted:
            continue
        if skip_locked and cue_locked(cue, locked_ids):
            continue
        resolution = resolver.resolve(cue.text, scene=scene)
        for hit in resolution.hits:
            hits.append(TextOccurrence(cue.id, cue.start_ms, hit.source, hit.canonical,
                                       (hit.start, hit.end), reason=hit.reason))
    return hits


def clock_ms(milliseconds: int) -> str:
    value = max(0, int(milliseconds))
    minutes, seconds = divmod(value // 1000, 60)
    millis = value % 1000
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def format_preview_row(hit: TextOccurrence) -> str:
    stamp = clock_ms(hit.start_ms)
    if hit.original == hit.replacement:
        return f"{stamp}  ·  {hit.original}"
    return f"{stamp}\n原文  {hit.original}\n替换  {hit.replacement}"


AI_CLEANUP_OPTIONS = (
    ("fillers", "清理口癖"),
    ("repeats", "删除无意义重复"),
    ("particles", "修正语气词"),
    ("segmentation", "优化断句"),
    ("pauses", "调整停顿"),
    ("glossary", "术语纠正"),
    ("punctuation", "标点统一"),
)

_AI_CLEANUP_SYSTEM = (
    "你是字幕文本清理器。只修正口癖、无意义重复、语气词、断句、停顿、术语和标点。"
    "绝对不要改字幕意思、不要改写观点、不要补故事。"
    "只返回 JSON 对象：{\"changes\":[{\"cue_id\":\"\",\"original\":\"\",\"replacement\":\"\",\"reason\":\"\",\"confidence\":0.0}]}。"
    "original 必须是该 cue 的完整原文。replacement 是建议全文。confidence 是 0 到 1。"
)


def parse_cleanup_payload(raw: object, project: SubtitleProject) -> list[TextOccurrence]:
    payload = raw
    if isinstance(raw, str):
        payload = json.loads(raw)
    if isinstance(payload, Mapping) and "changes" in payload:
        items = payload.get("changes")
    elif isinstance(payload, list):
        items = payload
    else:
        raise ValueError("AI 没有返回可解析的 changes 列表")
    lookup = {cue.id: cue for cue in project.cues}
    hits: list[TextOccurrence] = []
    if not isinstance(items, list):
        raise ValueError("AI 返回的 changes 不是列表")
    for item in items:
        if not isinstance(item, Mapping):
            continue
        cue_id = str(item.get("cue_id") or "")
        cue = lookup.get(cue_id)
        if cue is None:
            continue
        original = str(item.get("original") or cue.text)
        # A 繁體 project's cleanup stays 繁體 even when the model answers in 简体 (2026-10-19).
        from ..subtitle_rules.chinese_script import for_project
        replacement = for_project(str(item.get("replacement") or ""), project)
        if not replacement or replacement == cue.text:
            continue
        if original and original != cue.text and cue.text.find(original) < 0:
            continue
        try:
            confidence = float(item.get("confidence", 0.8) or 0.8)
        except (TypeError, ValueError):
            confidence = 0.8
        hits.append(TextOccurrence(
            cue_id=cue.id,
            start_ms=cue.start_ms,
            original=cue.text,
            replacement=replacement,
            span=(0, len(cue.text)),
            reason=str(item.get("reason") or "AI 清理"),
            confidence=max(0.0, min(1.0, confidence)),
        ))
    return hits


# 2026-10-26 (user: AI 清理 on a whole project stopped with "模型结构化输出达到
# 长度上限"): one request held the first 80 captions and every change repeats a
# caption twice, so the answer overflowed. Batches keep each answer small; a
# batch that still overflows is split in half and asked again.
CLEANUP_BATCH_CUES = 24
CLEANUP_BATCH_CHARS = 1200
CLEANUP_PARALLEL = 3
_TRUNCATED = {"structured_output_truncated", "structured_output_truncated_before_answer"}


class CleanupResult(list):
    """Suggestions from every finished batch; ``error`` names a batch that failed."""

    def __init__(self, hits=(), *, batches=0, done=0, error="", skipped=0):
        super().__init__(hits)
        self.batches, self.done, self.error, self.skipped = batches, done, error, skipped


def cleanup_batches(cues: list[StudioCue], *, size: int = CLEANUP_BATCH_CUES,
                    chars: int = CLEANUP_BATCH_CHARS) -> list[list[StudioCue]]:
    """Consecutive captions, at most ``size`` of them and about ``chars`` characters."""
    batches: list[list[StudioCue]] = []
    current: list[StudioCue] = []
    length = 0
    for cue in cues:
        if current and (len(current) >= size or length + len(cue.text) > chars):
            batches.append(current)
            current, length = [], 0
        current.append(cue)
        length += len(cue.text)
    if current:
        batches.append(current)
    return batches


def _cleanup_request(project, batch, option_labels, settings, post, cancel_check):
    """One model call for ``batch``; returns its parsed suggestions."""
    from ..providers.ai_providers import provider_for_stage
    from ..subtitle_rules.math_text import FORMULA_RULE, mask_formulas, project_enabled
    # 2026-10-16 (ADR 0124): formulas travel as ⟦Fn⟧ placeholders when the
    # project's math switch is on; a suggestion that loses one is dropped.
    masks = {cue.id: mask_formulas(cue.text) for cue in batch} if project_enabled(project) else {}
    user_payload = {
        "tasks": option_labels or ["清理口癖", "删除无意义重复"],
        "cues": [{"cue_id": cue.id, "text": masks[cue.id][0] if cue.id in masks else cue.text}
                 for cue in batch],
        "rule": "不要改变原意。只返回 JSON。只列出真的需要改的字幕，不需要改的不要返回。",
    }
    system = _AI_CLEANUP_SYSTEM + (FORMULA_RULE if any(formulas for _text, formulas in masks.values()) else "")
    if project.studio_state.get("link_imports"):
        system += ("本次处理下载字幕，默认轻度校对：只执行 tasks 中明确勾选的操作，"
                   "保持原意、内容覆盖与句子对应；不扩写或补写不确定内容。"
                   "未勾选口癖或重复清理时，不删除真实重复、口吃或语气词。"
                   "不得修改时间、字幕 ID、语言来源；original 必须完整逐字对应输入原文。")
    schema = {
        "type": "object",
        "properties": {
            "changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "cue_id": {"type": "string"},
                        "original": {"type": "string"},
                        "replacement": {"type": "string"},
                        "reason": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["cue_id", "original", "replacement", "reason"],
                },
            },
        },
        "required": ["changes"],
    }
    provider = provider_for_stage(settings, "polish", sender=post)
    content = provider.complete(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        max_tokens=3000,
        temperature=0.1,
        timeout=(10, 90),
        enable_thinking=False,
        response_format={"type": "json_object"},
        stage="studio_text_cleanup",
        structured_retry_system_prompt=system,
        json_schema=schema,
        cancel_check=cancel_check,
    )
    if masks:
        content = _unmask_cleanup_payload(content, masks)
    if project.studio_state.get("link_imports"):
        from ..projects.link_cleanup_validation import validate_cleanup_response
        content = validate_cleanup_response(content, batch)
    return parse_cleanup_payload(content, project)


def _cleanup_batch(project, batch, option_labels, settings, post, cancel_check, skipped):
    """``batch``'s suggestions, halving it while the answer overflows; a single
    caption whose answer still overflows is skipped (counted in ``skipped``)."""
    try:
        return _cleanup_request(project, batch, option_labels, settings, post, cancel_check)
    except Exception as exc:
        if getattr(exc, "category", "") not in _TRUNCATED:
            raise
        if len(batch) == 1:
            skipped.append(batch[0].id)
            return []
        middle = len(batch) // 2
        return (_cleanup_batch(project, batch[:middle], option_labels, settings, post, cancel_check, skipped)
                + _cleanup_batch(project, batch[middle:], option_labels, settings, post, cancel_check, skipped))


def request_text_cleanup(
    project: SubtitleProject,
    cue_ids: Iterable[str],
    options: Iterable[str],
    runtime_settings: dict | None = None,
    *,
    post: Callable[..., str] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    progress: Callable[[dict], None] | None = None,
    parallel: int = CLEANUP_PARALLEL,
) -> CleanupResult:
    """AI cleanup suggestions for every caption in ``cue_ids``, batch by batch.

    ``progress`` gets ``{"done", "total", "found"}`` after each batch. A failed
    batch stops the run but keeps the suggestions already found (``error``)."""
    wanted_ids = set(cue_ids)
    wanted = [cue for cue in project.cues if cue.id in wanted_ids]
    if not wanted:
        return CleanupResult()
    settings = runtime_settings if isinstance(runtime_settings, dict) else {}
    if not settings.get("models"):
        from ..storage.settings import load_runtime_settings
        loaded = load_runtime_settings()
        settings = loaded[0] if isinstance(loaded, tuple) else loaded
    option_labels = [label for key, label in AI_CLEANUP_OPTIONS if key in set(options)]
    batches = cleanup_batches(wanted)
    results: dict[int, list[TextOccurrence]] = {}
    skipped: list[str] = []
    error = ""
    found = 0

    def cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    def run(index):
        if cancelled():
            return index, []
        return index, _cleanup_batch(project, batches[index], option_labels, settings, post, cancel_check, skipped)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=max(1, min(int(parallel), len(batches)))) as pool:
        pending = {pool.submit(run, index): index for index in range(len(batches))}
        for future in as_completed(pending):
            try:
                index, hits = future.result()
            except Exception as exc:
                if not error:
                    error = str(exc) or type(exc).__name__
                for other in pending:
                    other.cancel()
                continue
            results[index] = hits
            found += len(hits)
            if progress is not None:
                progress(dict(done=len(results), total=len(batches), found=found))
    ordered = [hit for index in sorted(results) for hit in results[index]]
    if cancelled() and not error:
        error = "已取消"
    return CleanupResult(ordered, batches=len(batches), done=len(results), error=error, skipped=len(skipped))


def _unmask_cleanup_payload(raw: object, masks: Mapping[str, tuple[str, tuple[str, ...]]]) -> object:
    """Put formulas back into each change; changes that lost a placeholder are dropped."""
    from ..subtitle_rules.math_text import unmask_formulas
    payload = json.loads(raw) if isinstance(raw, str) else raw
    items = payload.get("changes") if isinstance(payload, Mapping) else payload
    if not isinstance(items, list):
        return raw  # parse_cleanup_payload reports the malformed answer
    kept = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        masked, formulas = masks.get(str(item.get("cue_id") or ""), ("", ()))
        if not formulas:
            kept.append(item)
            continue
        replacement = unmask_formulas(str(item.get("replacement") or ""), formulas)
        original = unmask_formulas(str(item.get("original") or masked), formulas)
        if replacement is None or original is None:
            continue
        kept.append({**item, "original": original, "replacement": replacement})
    return {"changes": kept}
