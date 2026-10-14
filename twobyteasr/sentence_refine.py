"""AI 断句/句内节奏优化（2026-09-18 III）。

模型只返回"在原文第几个字符后切分/插半角空格"的字符索引——文本守恒由
构造保证，本地只做索引合法性与反例护栏校验。时间分配优先用工程
asr_evidence 的词级证据对齐切分点；无精确文本匹配证据时拒绝自动拆分。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from .studio_project import StudioCue, SubtitleProject

# 独立语气词/应答白名单：句内空格或独立成句的候选，反例保护由 prompt+护栏共同兜
# 2026-09-18 VIII：补短语句末助词（吧/呢/嘛/啦…）——"长停顿也可能在普通短语
# 之间"，这些是自然的句内节奏锚点，护栏只在语气字后放行 space。
INTERJECTION_CHARS = set("啊嗯哦喔噢哇呀哈哎唉哟呦哼唔诶欸咦嘻嘿对好是呀吧呢嘛啦呗咯")

REFINE_SYSTEM_PROMPT = """你是中文直播字幕的断句与节奏编排引擎。输入是一批字幕 cue（含原文、时间与
真实停顿证据），你必须为每条 cue 决定：

- keep：保持原样（默认；不确定时一律 keep）。
- split：在"原文第几个字符后"切分成多条 cue。判据：两段各自语义完整、
  构成先后两个分句，cue 时长足以承载两条可读字幕（每段≥约1.2s），
  切分点必须落在真实字词边界；停顿是加强证据，连续说话中的明确语义转折也可拆分。
  语气词收尾+新完整句（如"这个直言不讳的说啊|其实我想要的是"）应拆。
- space：不拆 cue，只在"原文第几个字符后"插入一个半角空格 U+0020，
  用于组织句内阅读节奏。覆盖三类位置：
  a. 句首独立语气词/应答之后（"啊 我很喜欢这个角色"、"嗯 然后我们走"）；
  b. 连续重复应答之间（"对对"→"对 对"、"好好好"→"好 好 好"）；
  c. 句末独立语气词之前——它与前面的语义单元各自独立（"很不错啊 嗯"）。
  判据：整体连贯、时长不足两条，但内部确有节奏边界；被空格分开的每个
  语义单元自身要自然（"很不错啊"是完整单元，不要在"啊"前再插空格）。
  典型样例："对对很不错啊嗯" → "对 对 很不错啊 嗯"（空格点：索引0、1、5 后）。

停顿证据的使用：
- pause_hints 给出词级时间戳推得的词间真实停顿（after_chars = 第几个
  字符后，gap_ms = 停顿毫秒）；null/缺失 = 无证据，不要臆造停顿。
- 真实停顿长且时长可读性允许 → split；停顿明显但整体仍是一句 → space；
  无停顿证据的位置只做语义判断，宁可 keep。

硬性规则：
1. 只能返回字符索引，禁止改写、增删、重排原文任何字符。
2. 不得因包含"好/对/啊"等单字拆开固定搭配：好像还不错、这个好厉害、
   对这个角色很满意、队伍搭配、我喜欢这个角色啊、这个判断是对的——
   全部 keep。
3. 人名、游戏术语、数字、英文单词内部禁止切分或插空格。
4. 切分产生的每段长度≥3 个字符；真正独立说出的"嗯/好/对"（前后有真实
   停顿且自身成句）可以单独成句，否则并入相邻句。
5. 已经含有半角空格的文本保持既有空格，不重复插空格。
6. 连续笑声/哭声等拟声（"哈哈哈哈"）不逐字加空格。
   不删去重复词（例如“继续继续”），不把收尾语气词移到下一句开头。
7. 只返回 JSON，不要解释。顶层必须是 results 数组，每个输入 cue_id 恰好返回一次：
{"results":[{"cue_id":"输入的ID","action":"keep","split_after_chars":[],"space_after_chars":[],"reason":"原因"}]}
split_after_chars 与 space_after_chars 都是原文的 0 基字符索引，空格也计数。
word_boundaries.after_chars 使用同一索引。不得返回输入 cues 或省略 keep 项。"""

JAPANESE_REFINE_SYSTEM_PROMPT = """你是日语字幕（日文原文）的断句与节奏编排引擎。输入是一批字幕 cue（含原文、时间与
真实停顿证据），你必须为每条 cue 决定 keep / split / space，协议与输出格式完全相同：
- keep：保持原样（默认；不确定时一律 keep）。
- split：在"原文第几个字符后"切分。只能切在文节之间：名词、动词、形容词连同其后的送假名、
  助词（は、が、を、に、で、と、も、へ、の、って）、助动词（だ、です、ます、た、て、ない）是一个整体；
  不得切开一个词（天|才、恐ろし|い、ストリート|ファイター、2024|年），下一段不得以助词或助动词开头，
  连体词（この、その、あの）与后面的名词同段。两段各自语义完整、每段≥约1.2s，停顿是加强证据。
- space：只在文节之间插入一个半角空格，用于原本有「、」或明显气口的位置
  （「恐ろしいわ すえ恐ろしいわ」「えっ ちょっと待って」）。不要在词内插空格。
硬性规则：只能返回字符索引，禁止改写、增删、翻译或重排原文任何字符；汉字/假名写法保持原样；
不删去重复词（「怖いわ怖いわ」可分开但不删）；只返回 JSON：
{"results":[{"cue_id":"输入的ID","action":"keep","split_after_chars":[],"space_after_chars":[],"reason":"原因"}]}
split_after_chars 与 space_after_chars 都是原文的 0 基字符索引，空格也计数。每个输入 cue_id 恰好返回一次。"""


ENGLISH_REFINE_SYSTEM_PROMPT = """You re-break English subtitle cues (game streams) for reading rhythm. For every cue decide:
- keep: leave it as it is (the default; when unsure, keep).
- split: start a new cue after character index N, where N is the index of the LAST letter (or punctuation) of a
  word, so the cut falls on a space. Never cut inside a word, a name, a number with its unit (10 minutes, 50%),
  "not" from its verb, or a phrasal verb (pick up, log in).
Prefer cutting after . ! ? , ; : and before and/but/or/so/because/when/which/who; never leave a piece ending with
an article or determiner (a, an, the, this, my…), a preposition, a conjunction, an auxiliary (is, was, can, will…)
or a subject pronoun waiting for its verb. Each piece should be at least two words and at least about 1.2 s; a piece
may be up to 42 characters. pause_hints (after_chars, gap_ms) are real pauses between words: a long pause is good
evidence for a split; with no evidence decide by meaning or keep. There is no "space" action for English.
Return only character indexes; never rewrite, add, remove or reorder any character. Return only JSON with a results
array, every input cue_id exactly once:
{"results":[{"cue_id":"<id>","action":"keep","split_after_chars":[],"space_after_chars":[],"reason":"short reason"}]}
split_after_chars are 0-based character indexes into the original text; spaces count."""


def refine_system_prompt(language: str = "") -> str:
    if language == "en":
        return ENGLISH_REFINE_SYSTEM_PROMPT
    return JAPANESE_REFINE_SYSTEM_PROMPT if language == "ja" else REFINE_SYSTEM_PROMPT


def _japanese_boundaries(text: str) -> set[int]:
    """Character offsets between Japanese phrases (allowed cut/space positions)."""
    from .language_rules import japanese_phrase_spans
    spans = japanese_phrase_spans(text)
    inside = {index for start, end, _word in spans for index in range(start + 1, end)}
    return {index for index in range(1, len(text)) if index not in inside}


REFINE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cue_id": {"type": "string"},
                    "action": {"type": "string", "enum": ["keep", "split", "space"]},
                    "split_after_chars": {"type": "array", "items": {"type": "integer"}},
                    "space_after_chars": {"type": "array", "items": {"type": "integer"}},
                    "reason": {"type": "string", "maxLength": 120},
                },
                "required": ["cue_id", "action"],
            },
        }
    },
    "required": ["results"],
}


@dataclass
class CueRefineAction:
    cue_id: str
    action: str = "keep"  # keep | split | space
    split_after_chars: list[int] = field(default_factory=list)
    space_after_chars: list[int] = field(default_factory=list)
    estimated_timing: bool = False


@dataclass
class RefineOutcome:
    actions: list[CueRefineAction] = field(default_factory=list)
    rejected: int = 0
    llm_status: str = "completed"
    llm_error: str = ""
    failed_cue_ids: list[str] = field(default_factory=list)
    requests: list[dict] = field(default_factory=list)


def _batch(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def validate_action(text: str, raw: Mapping[str, Any]) -> CueRefineAction | None:
    """索引合法性 + 反例护栏。非法一律丢弃（该 cue 保持原文）。"""
    action = str(raw.get("action") or "keep")
    if action not in {"keep", "split", "space"}:
        return None
    length = len(text)

    def clean_indices(value: Any) -> list[int]:
        try:
            indices = [int(item) for item in (value or []) if int(item) >= 0]
        except (TypeError, ValueError):
            return []
        return sorted(set(indices))

    splits = clean_indices(raw.get("split_after_chars"))
    spaces = clean_indices(raw.get("space_after_chars"))
    # 索引语义：第 index 个字符（0 基）之后。尾字符之后/越界均非法。
    if any(index >= length - (0 if action != "split" else 1) for index in splits):
        return None
    if any(index >= length for index in spaces):
        return None
    if action == "keep":
        return CueRefineAction(cue_id=str(raw.get("cue_id") or ""), action="keep")
    from .language_rules import is_english, is_japanese
    if is_english():
        # English: cut only where a space separates two words; no rhythm spaces.
        if action == "space":
            return CueRefineAction(cue_id=str(raw.get("cue_id") or ""), action="keep")
        if not splits or any(not (text[index] != " " and index + 1 < length and text[index + 1] == " ")
                             for index in splits):
            return None
        bounds = [0, *(index + 1 for index in splits), length]
        if any(len(text[left:right].split()) < 2 and not text[left:right].strip().endswith(("!", "?", "."))
               for left, right in zip(bounds, bounds[1:])):
            return None
        return CueRefineAction(cue_id=str(raw.get("cue_id") or ""), action="split", split_after_chars=splits)
    if is_japanese():
        # Japanese: cuts and rhythm spaces only between phrases, never inside a word.
        allowed = _japanese_boundaries(text)
        if action == "space":
            spaces = [index for index in spaces if index + 1 < length and text[index + 1] != " " and text[index] != " "]
            if not spaces:
                return CueRefineAction(cue_id=str(raw.get("cue_id") or ""), action="keep")
            if any(index + 1 not in allowed for index in spaces):
                return None
            return CueRefineAction(cue_id=str(raw.get("cue_id") or ""), action="space", space_after_chars=spaces)
        if not splits or any(index + 1 not in allowed for index in splits):
            return None
        bounds = [0, *(index + 1 for index in splits), length]
        if any(len(text[left:right].strip()) < 2 for left, right in zip(bounds, bounds[1:])):
            return None
        return CueRefineAction(cue_id=str(raw.get("cue_id") or ""), action="split", split_after_chars=splits)
    if action == "space":
        if not spaces:
            return None
        # A provider may repeat an already present rhythm space. Treat that
        # individual suggestion as a no-op, never as a failed transformation.
        spaces=[index for index in spaces if index+1>=length or text[index+1]!=' ']
        if not spaces:
            return CueRefineAction(cue_id=str(raw.get('cue_id') or ''),action='keep')
        # 每个空格点必须紧跟白名单语气字之后（句内节奏位），否则视为误报
        for index in spaces:
            if index >= length or text[index] not in INTERJECTION_CHARS:
                return None
            if index == length - 1:
                return None  # 尾字符后不允许追加尾随空格
        return CueRefineAction(
            cue_id=str(raw.get("cue_id") or ""), action="space",
            space_after_chars=spaces,
        )
    # split
    if not splits:
        return None
    # 每段 ≥3 字符（真正独立的语气词单句放开到 ≥1）
    bounds = [0, *(index + 1 for index in splits), length]
    for left, right in zip(bounds, bounds[1:]):
        segment = text[left:right]
        if not segment.strip():
            return None  # 只有空格的一段不是字幕
        if len(segment) >= 3:
            continue
        stripped = segment.strip()
        if stripped and all(char in INTERJECTION_CHARS for char in stripped):
            continue  # 独立"嗯/好/对"允许
        return None
    return CueRefineAction(
        cue_id=str(raw.get("cue_id") or ""), action="split",
        split_after_chars=splits,
    )


def _word_evidence_for_cue(project: SubtitleProject | None, cue: StudioCue) -> list[tuple[str, int, int]]:
    from .cue_word_alignment import cue_words
    words, _reason = cue_words(project, cue)
    return [(word.text, word.start_ms, word.end_ms) for word in words]


def allocate_split_times(cue, splits, *, project=None):
    """Automatic cuts use the next token's onset, retaining actual pauses.

    A boundary inside a multi-character token or an unmatched edit is refused.
    Never sort/deduplicate times independently of text (that discarded tails).
    """
    from .cue_word_alignment import cue_words, boundary_words
    words, _reason = cue_words(project, cue)
    pairs = [boundary_words(words, index+1) for index in splits]
    if not words or any(pair is None for pair in pairs):
        return [], True
    starts = [cue.start_ms] + [right.start_ms for left, right in pairs]
    ends = [min(left.end_ms, right.start_ms) for left, right in pairs] + [cue.end_ms]
    if any(end-start < 50 for start, end in zip(starts, ends)):
        return [], True
    return list(zip(starts, ends)), False


def build_replacement_cues(
    cue: StudioCue,
    action: CueRefineAction,
    *,
    project: SubtitleProject | None = None,
    used_ids: set[str] | None = None,
) -> list[StudioCue]:
    """按动作生成替换 cue 列表（split→多条；space→同条改文本；keep→空）。"""
    text = cue.text
    if action.action == "keep":
        return []
    if action.action == "space":
        chars = list(text)
        for offset, index in enumerate(action.space_after_chars):
            chars.insert(index + 1 + offset, " ")
        new_text = "".join(chars)
        if new_text == text:
            return []
        clone = StudioCue(
            id=cue.id, start_ms=cue.start_ms, end_ms=cue.end_ms, text=new_text,
            speaker_id=cue.speaker_id, style_id=cue.style_id,
            base_preset_id=cue.base_preset_id, effect_id=cue.effect_id,
            original_text=cue.original_text, evidence_refs=list(cue.evidence_refs),
            raw_ass_override=cue.raw_ass_override,
            appearance_override=dict(cue.appearance_override),
            appearance_generation=cue.appearance_generation,
            transform=dict(cue.transform),
        )
        return [clone]

    # split：split_after_chars[i] = 在第 i 个字符（0 基）之后切分
    split_indices = sorted(action.split_after_chars)
    bounds = [0, *(index + 1 for index in split_indices), len(text)]
    segments_text = [text[left:right] for left, right in zip(bounds, bounds[1:])]
    # 2026-10-12：在停顿空格处切分时空格就是边界，不留在任一段的首尾；
    # 时间仍按原文字符索引分配（allocate_split_times），与去空格无关。
    from .studio_timing import trim_cut_pieces
    segments_text = trim_cut_pieces(segments_text)
    timings, estimated = allocate_split_times(cue, split_indices, project=project)
    action.estimated_timing = estimated
    used = used_ids if used_ids is not None else set()
    result: list[StudioCue] = []
    for position, (segment_text, (start_ms, end_ms)) in enumerate(zip(segments_text, timings)):
        new_id = cue.id
        if position or f"{cue.id}-r1" in used or True:
            suffix = 0
            while True:
                suffix += 1
                candidate = f"{cue.id}-r{suffix}"
                if candidate not in used:
                    new_id = candidate
                    break
        used.add(new_id)
        result.append(StudioCue(
            id=new_id, start_ms=start_ms, end_ms=end_ms, text=segment_text,
            speaker_id=cue.speaker_id, style_id=cue.style_id,
            base_preset_id=cue.base_preset_id, effect_id=cue.effect_id,
            original_text=cue.original_text, evidence_refs=list(cue.evidence_refs),
            raw_ass_override=cue.raw_ass_override,
            appearance_override=dict(cue.appearance_override),
            appearance_generation=cue.appearance_generation,
            transform=dict(cue.transform),
        ))
    return result


def pause_hints_for_cue(
    cue: StudioCue,
    words: Sequence[tuple[str, int, int]],
    *,
    min_gap_ms: int = 150,
    max_hints: int = 12,
) -> list[dict]:
    """把词级证据里的词间真实停顿换算成"第几个字符后"的提示。

    将已匹配的词文本映射回原文（含标点）的真实索引。
    gap = 后词 start − 前词 end；无完整匹配时不臆造停顿。
    """
    hints: list[dict] = []
    from .cue_word_alignment import content_positions
    positions=content_positions(cue.text)
    if ''.join(c for _,c in positions) != ''.join(c for text,_,_ in words for _,c in content_positions(text)):
        return hints
    previous_end: int | None = None
    previous_chars = 0
    for text, start, end in words:
        char_count = len(content_positions(str(text)))
        if previous_end is not None:
            gap = int(start) - int(previous_end)
            if gap >= min_gap_ms:
                hints.append({"after_chars": positions[previous_chars - 1][0], "gap_ms": gap})
        previous_end = int(end)
        previous_chars += char_count
    return hints[:max_hints]


def refine_payload(
    cues: Sequence[StudioCue],
    *,
    neighbors: Mapping[str, tuple[str, str]] | None = None,
    project: SubtitleProject | None = None,
    following_gaps: Mapping[str, int] | None = None,
) -> dict:
    neighbors = neighbors or {}
    following_gaps = following_gaps or {}
    items = []
    for cue in cues:
        prev_text, next_text = neighbors.get(cue.id, ("", ""))
        words = _word_evidence_for_cue(project, cue) if project is not None else []
        item = {
            "cue_id": cue.id,
            "start_ms": cue.start_ms,
            "end_ms": cue.end_ms,
            "duration_ms": cue.end_ms - cue.start_ms,
            "speaker": cue.speaker_id,
            "text": cue.text,
            "context_prev": prev_text[:24],
            "context_next": next_text[:24],
        }
        if cue.id in following_gaps:
            item["gap_to_next_cue_ms"] = int(following_gaps[cue.id])
        hints = pause_hints_for_cue(cue, words)
        if hints:
            item["pause_hints"] = hints
        if words:
            from .cue_word_alignment import cue_words
            measured, _ = cue_words(project, cue)
            item['word_boundaries'] = [dict(after_chars=w.char_end-1, start_ms=w.start_ms, end_ms=w.end_ms)
                                       for w in measured]
        items.append(item)
    return {
        "cues": items,
        "rule": "只返回 JSON。action=keep 的 cue 可省略 split/space 字段。",
    }


def refine_cues_with_llm(
    cues: Sequence[StudioCue],
    *,
    project: SubtitleProject | None = None,
    runtime_settings: Mapping[str, Any] | None = None,
    ai_service: str = "",
    model: str = "",
    cancel_check: Callable[[], bool] | None = None,
    provider_post: Callable[..., str] | None = None,
    batch_size: int = 40,
    max_attempts: int = 2,
) -> RefineOutcome:
    """对给定 cue 执行 LLM 断句/节奏优化。失败抛出；拒绝项计入 rejected。"""
    from .ai_providers import provider_for_stage

    settings = dict(runtime_settings or {})
    if not settings.get("models"):
        from .settings import load_runtime_settings
        loaded = load_runtime_settings()
        settings = loaded[0] if isinstance(loaded, tuple) else loaded
    if ai_service or model:
        settings = dict(settings)
        models = dict(settings.get("models") or {})
        polish = dict(models.get("group") or {})
        if ai_service:
            polish["service"] = ai_service
        if model:
            polish["model"] = model
        models["group"] = polish
        settings["models"] = models
    provider = provider_for_stage(settings, "group", sender=provider_post)
    from .language_rules import language_scope, project_language
    from .japanese_morphology import document_for_texts, phrase_scope
    language = project_language(project) if project is not None else ""
    # Japanese: proposed breaks are checked against bunsetsu of the current
    # (possibly hand-edited) texts, as in recognition; heuristic only when the
    # tagger is unavailable.
    document = document_for_texts([cue.text for cue in cues]) if language == "ja" else None
    with language_scope(language or None), phrase_scope(document):
        return _refine_cues(cues, project, provider, cancel_check, batch_size, max_attempts, language)


def _refine_cues(cues, project, provider, cancel_check, batch_size, max_attempts, language):
    by_id = {cue.id: cue for cue in cues}
    ordered = sorted(cues, key=lambda item: item.start_ms)
    neighbors: dict[str, tuple[str, str]] = {}
    following_gaps: dict[str, int] = {}
    for index, cue in enumerate(ordered):
        prev_text = ordered[index - 1].text if index > 0 else ""
        next_text = ordered[index + 1].text if index + 1 < len(ordered) else ""
        neighbors[cue.id] = (prev_text, next_text)
        if index + 1 < len(ordered):
            following_gaps[cue.id] = ordered[index + 1].start_ms - cue.end_ms

    outcome = RefineOutcome()
    for group in _batch(ordered, batch_size):
        if cancel_check and cancel_check():
            outcome.llm_status = "cancelled"
            return outcome
        payload = refine_payload(
            group, neighbors=neighbors, project=project, following_gaps=following_gaps
        )
        rows = None
        group_ids = {cue.id for cue in group}
        for attempt in range(max(1, min(2, int(max_attempts)))):
            if cancel_check and cancel_check():
                outcome.llm_status = 'cancelled'
                outcome.actions.clear()
                return outcome
            receipt = dict(stage='sentence_refine', provider=getattr(provider,'provider_id',''),
                model=getattr(provider,'model',''), cue_ids=sorted(group_ids), attempt=attempt+1)
            try:
                content = provider.complete(
            [
                {"role": "system", "content": refine_system_prompt(language)},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            max_tokens=6000,
            temperature=0.1,
            timeout=(10, 60),
            enable_thinking=False,
            response_format={"type": "json_object"},
            stage="sentence_refine",
            json_schema=REFINE_SCHEMA,
            cancel_check=cancel_check,
                )
                from .provider_diagnostics import redact_diagnostics
                receipt['raw_response'] = str(redact_diagnostics(content))[:24000]
                trace = getattr(provider, 'invocation_trace', None)
                receipt['transport'] = redact_diagnostics(trace() if callable(trace) else getattr(provider, 'last_invocation_trace', {}))
                rows = _parse_results(content)
                if not rows:
                    raise ValueError('AI 断句响应没有有效 results 数组')
                ids = [str(row.get('cue_id') or '') for row in rows]
                if set(ids) != group_ids or len(ids) != len(group_ids):
                    raise ValueError('AI 断句响应缺少字幕或包含重复／跨批次 ID')
                receipt.update(status='validated', response=rows)
                outcome.requests.append(receipt)
                break
            except Exception as exc:
                if cancel_check and cancel_check():
                    outcome.llm_status = 'cancelled';outcome.actions.clear()
                    return outcome
                from .provider_diagnostics import redact_diagnostics
                message = str(redact_diagnostics(str(exc)))[:300]
                receipt.update(status='failed', category=getattr(exc,'category','parse_or_validation'), error=message)
                outcome.requests.append(receipt)
                outcome.llm_error = message
                rows = None
        if rows is None:
            outcome.failed_cue_ids.extend(sorted(group_ids))
            continue
        seen: set[str] = set()
        for row in rows:
            cue_id = str(row.get("cue_id") or "")
            cue = by_id.get(cue_id)
            if cue is None or cue_id in seen:
                outcome.rejected += 1
                continue
            seen.add(cue_id)
            action = validate_action(cue.text, row)
            if action is None:
                outcome.rejected += 1
                outcome.failed_cue_ids.append(cue_id)
                receipt.setdefault('field_errors', []).append(dict(cue_id=cue_id,category='invalid_action_indices'))
                outcome.llm_error='AI 建议的字符索引或操作字段未通过校验'
                continue
            outcome.actions.append(action)
    if outcome.failed_cue_ids:
        outcome.llm_status = 'partial' if outcome.actions else 'failed'
    return outcome


def _parse_results(content: str) -> list[dict]:
    text = str(content or "").strip()
    try:
        payload = json.loads(text)
    except ValueError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return []
        try:
            payload = json.loads(text[start:end + 1])
        except ValueError:
            return []
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return [row for row in payload["results"] if isinstance(row, dict)]
    return []
