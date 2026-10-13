"""segmentation stage implementation extracted from subtitle_core."""

import re
import warnings

# The core owns runtime configuration; these imports preserve the existing public contract.
from subtitle_core import *  # noqa: F401,F403
from twobyteasr.runtime import get_runtime_context
from twobyteasr.language_rules import CONTENT_CHAR_CLASS

__all__ = [
    'INTERJECTION_MERGES',
    'INTERJECTION_WORDS',
    'merge_split_interjections',
    'space_separate_interjections',
    'merge_split_interjections_in_cues',
    'SEMANTIC_RESTART_MARKERS',
    'NOW_RESTART_LEFT_SUFFIXES',
    'DANGLING_SHORT_FRAGMENTS',
    'INCOMPLETE_BOUNDARY_SUFFIXES',
    'LATIN_FOLLOWING_PREDICATES',
    'AWKWARD_BOUNDARY_LEFT_SUFFIXES',
    'AWKWARD_BOUNDARY_RIGHT_PREFIXES',
    'AWKWARD_SHORT_DE_LEFT_MAX_CHARS',
    'HANGING_ATTRIBUTE_LEFT_ENDINGS',
    'HANGING_ATTRIBUTE_RIGHT_BLOCK_PREFIXES',
    'SHORT_COMPLETION_RIGHT_MAX_CHARS',
    'LEXICAL_LE_PREFIXES',
    'SHORT_REACTION_TAILS',
    'ALIGNMENT_CHINESE_DIGITS',
    'individual_cue',
    'segment_content_timeline',
    'firered_pause_character_boundaries',
    'firered_pause_character_gaps',
    '_vad_silence_ratio',
    'snap_internal_cue_boundaries',
    'hard_break_character_offsets',
    'source_segment_character_offsets',
    'protected_source_boundary_offsets',
    'text_boundary_hints',
    'semantic_restart_boundary_offsets',
    'refine_resegmented_texts',
    'split_text_at_content_ranges',
    'indexed_content_for_prompt',
    'lexical_boundary_terms',
    'lexical_forbidden_boundary_offsets',
    'chinese_word_spans',
    'looks_like_category_field_list',
    'repair_segmenter_word_boundary_offsets',
    'repair_compact_utterance_boundary_offsets',
    'repair_dependent_prefix_boundary_offsets',
    'repair_lexical_boundary_offsets',
    'repair_incomplete_boundary_offsets',
    'repair_latin_predicate_boundary_offsets',
    'left_has_hanging_attribute',
    'right_is_short_completion',
    'should_merge_hanging_attribute',
    'repair_hanging_attribute_boundary_offsets',
    'repair_category_field_list_cues',
    'merge_hanging_attribute_cues',
    'starts_with_dependent_le',
    'semantically_awkward_boundary',
    'repair_dependent_particle_boundary_offsets',
    'texts_from_boundary_offsets',
    'snap_boundaries_away_from_word_interiors',
    'segmenter_forbidden_boundary_offsets',
    'repair_mid_word_adjacent_cues',
    'locally_repair_resegmented_cue',
    'cues_from_resegmented_texts',
    'fallback_group',
    'call_grouping_api',
    'merge_same_speaker_dangling_cues',
    'merge_isolated_two_character_cues',
    'resolve_isolated_single_character_cues',
    'validate_editorial_cue_result',
    'apply_isolated_single_character_rules_safely',
    'merge_consecutive_short_repeated_cues',
    'group_subtitles',
    'firered_token_start',
    'arabic_number_for_alignment',
    'boundary_alignment_content',
    'boundary_alignment_units',
]

SEMANTIC_RESTART_MARKERS = ("但是", "不过", "所以", "然后", "结果")

# 语气词防拆：ASR/校对可能把“哎呦”拆成“哎 呦”甚至“哎，呦”。
# 人工校对稿一律连写（“哎呦打不动”“哎呦但是这个龙”），成片时按白名单合并；
# 组合不在表内的（如“哎 那”“哦 呀”）保持原样，避免误并。
INTERJECTION_MERGES = {
    ("哎", "呦"): "哎呦",
    ("哎", "哟"): "哎哟",
    ("诶", "呦"): "诶呦",
    ("诶", "哟"): "诶哟",
    ("哎", "呀"): "哎呀",
    ("诶", "呀"): "诶呀",
    ("哦", "豁"): "哦豁",
}
_INTERJECTION_SPLIT_RE = re.compile(r"([哎诶哦])[\s，,。.!！?？]{1,2}([呦哟呀豁])")

# 连写语气词（人工稿观感：每个语气词独立、用空格隔开，如「哎呦 哎呦 可以吗 哎呀」）
INTERJECTION_WORDS = (
    "哎呦", "哎哟", "诶呦", "诶哟", "哎呀", "诶呀", "哦豁", "哇哦",
    "哎哎", "嗯嗯", "啊啊", "哦哦", "欸欸", "哟呵", "呦呵", "嗨呀",
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def merge_split_interjections(text: str) -> str:
    """Merge split interjections like “哎 呦” back into “哎呦” (whitelist only)."""

    def repl(match):
        pair = (match.group(1), match.group(2))
        return INTERJECTION_MERGES.get(pair, match.group(0))

    return _INTERJECTION_SPLIT_RE.sub(repl, text)


def space_separate_interjections(text: str) -> str:
    """Space out each multi-char interjection so it reads clearly:
    “哎呦打不动” → “哎呦 打不动”，“…可以吗哎呀” → “…可以吗 哎呀”。
    Single characters and non-CJK neighbors are left untouched."""
    for word in INTERJECTION_WORDS:
        index = 0
        while True:
            pos = text.find(word, index)
            if pos < 0:
                break
            if pos > 0 and _CJK_RE.match(text[pos - 1]):
                text = text[:pos] + " " + text[pos:]
                pos += 1
            end = pos + len(word)
            if end < len(text) and _CJK_RE.match(text[end]):
                text = text[:end] + " " + text[end:]
                end += 1
            index = end
    return text


def merge_split_interjections_in_cues(cues):
    """Merge split interjections and space them out in every final cue."""
    for cue in cues:
        text = getattr(cue, "text", None)
        if not isinstance(text, str):
            continue
        merged = space_separate_interjections(merge_split_interjections(text))
        if merged != text:
            cue.text = merged
    return cues


DISCOURSE_PREFIXES = (
    "就是", "其实", "不过", "但是", "所以", "然后", "那就",
)


NOW_RESTART_LEFT_SUFFIXES = (
    "不要紧", "没关系", "结束了", "够了", "可以", "没事", "完了", "算了",
    "的话",
)


DANGLING_SHORT_FRAGMENTS = frozenset(
    ("这里", "那里", "我们", "你们", "他们", "这个", "那个", "因为", "所以", "然后", "但是", "如果")
)


SHORT_ACTION_FRAGMENTS = frozenset(("我们抽", "我们来", "我们看", "我们试"))


def semantic_restart_boundary_offsets(text):
    """识别口语中第二个独立重点的开头，避免两个判断挤在同一条。"""
    from twobyteasr.language_rules import is_japanese, japanese_strong_breaks
    if is_japanese():
        # 日语：句末助词后、感叹词/连词前、MOSS 停顿处（文节分析给出）。
        return japanese_strong_breaks(text)
    source = content_exact(text)
    if len(source) < 10:
        return set()
    offsets = set()
    forbidden = lexical_forbidden_boundary_offsets(source)

    # 完整问句尾应作为新的口语节拍，不能切成“……有｜感觉吗”。
    # 仅处理左侧已有完整陈述的“有感觉吗”，短句“哎有感觉吗”保持整条。
    start = source.find("有感觉吗", 1)
    while start >= 0:
        if start >= 6 and start not in forbidden:
            offsets.add(start)
        start = source.find("有感觉吗", start + 1)

    # 直播倒计时承诺是一个不可拆的操作：“十秒内不上舰”。前后若还有
    # 独立成分，就在整段短语外侧换句，而不是从“十秒｜内不上舰”中间劈开。
    for phrase in ("十秒内不上舰", "十秒内不上剑", "十秒内不上线"):
        start = source.find(phrase)
        while start >= 0:
            end = start + len(phrase)
            if start >= 5 and start not in forbidden:
                offsets.add(start)
            if len(source) - end >= 4 and end not in forbidden:
                offsets.add(end)
            start = source.find(phrase, start + 1)
    # 开场口语“好，来”本身就是一个独立节拍，不能和后面的完整判断挤成一条。
    if source.startswith("好来") and len(source) >= 10 and 2 not in forbidden:
        offsets.add(2)

    # “能不能……，给我们……”是两个清晰重点：前半是判断，后半是期望结果。
    # 只在左侧已有完整谓语证据时使用，避免把普通“给我们”机械切开。
    start = source.find("给我们", 1)
    while start >= 0:
        left = source[:start]
        if (
            start >= 8
            and len(source) - start >= 6
            and any(marker in left for marker in ("能不能", "发点力", "希望", "争取"))
            and start not in forbidden
        ):
            offsets.add(start)
        start = source.find("给我们", start + 1)
    for marker in SEMANTIC_RESTART_MARKERS:
        start = source.find(marker, 1)
        while start >= 0:
            if (
                start >= 6
                and len(source) - start >= 5
                and start not in forbidden
            ):
                offsets.add(start)
            start = source.find(marker, start + 1)
    start = source.find("现在", 1)
    while start >= 0:
        left = source[:start]
        if (
            start >= 6
            and len(source) - start >= 5
            and left.endswith(NOW_RESTART_LEFT_SUFFIXES)
            and start not in forbidden
        ):
            offsets.add(start)
        start = source.find("现在", start + 1)
    start = source.find("的话", 1)
    while start >= 0:
        boundary = start + len("的话")
        if (
            boundary >= 4
            and len(source) - boundary >= 4
            and boundary not in forbidden
        ):
            offsets.add(boundary)
        start = source.find("的话", start + 1)
    # “还没到保底，我就……”前后是两个完整重点。比起停在“抽到｜了”，
    # 应优先在主语“我就”前换句。
    start = source.find("我就", 1)
    while start >= 0:
        left_window = source[max(0, start - 12) : start]
        if (
            start >= 6
            and len(source) - start >= 4
            and any(
                marker in left_window
                for marker in ("还没", "终于", "结果", "居然", "没想到")
            )
            and start not in forbidden
        ):
            offsets.add(start)
        start = source.find("我就", start + 1)
    return offsets


def refine_resegmented_texts(segment_batch, proposed_texts, firered_tokens=()):
    """保留 Qwen 的全文断句，只修正明确的残句和新分句漏切。"""
    source_text = "".join(
        clean_subtitle_text(segment.text) for segment in segment_batch
    )
    total_length = display_length(source_text)
    source_content = content_exact(source_text)
    boundaries = set()
    cursor = 0
    for text in proposed_texts:
        cursor += display_length(text)
        boundaries.add(cursor)
    if cursor != total_length:
        return proposed_texts

    from .subtitle_fidelity import independent_response
    response_boundaries = set()
    response_cursor = 0
    for text in proposed_texts:
        next_cursor = response_cursor + display_length(text)
        if independent_response(text):
            response_boundaries.update((response_cursor, next_cursor))
        response_cursor = next_cursor
    changed = False
    semantic_required_offsets = set()
    required_boundaries = hard_break_character_offsets(
        segment_batch,
        firered_tokens,
    ) | set(
        protected_source_boundary_offsets(segment_batch)
    )
    source_cursor = 0
    for segment in segment_batch:
        segment_length = display_length(segment.text)
        segment_end = source_cursor + segment_length
        internal = sorted(
            offset for offset in boundaries if source_cursor < offset < segment_end
        )
        cohesion_ranges = [
            (source_cursor + start, source_cursor + end)
            for start, end, _term in structural_cohesion_spans(segment.text)
        ]
        split_atomic = {
            offset
            for offset in internal
            if any(start < offset < end for start, end in cohesion_ranges)
            and offset not in required_boundaries
        }
        if split_atomic:
            boundaries.difference_update(split_atomic)
            internal = [offset for offset in internal if offset not in split_atomic]
            changed = True
        semantic = {
            source_cursor + offset
            for offset in semantic_restart_boundary_offsets(segment.text)
        }
        semantic_required_offsets.update(semantic)
        compact = (
            segment_length <= MAX_SUBTITLE_CHARS
            and segment.end - segment.start <= MAX_SUBTITLE_SECONDS + 0.05
        )
        if compact and semantic:
            for offset in internal:
                boundaries.discard(offset)
            boundaries.update(semantic)
            changed = changed or set(internal) != semantic
        elif semantic:
            # 长句保留 Qwen 已有的自然边界，同时强制补入高置信语义重点；
            # 否则 22 字以上的开场句仍可能落入本地均分。
            before = set(boundaries)
            boundaries.update(semantic)
            changed = changed or boundaries != before
        elif compact and internal:
            local_edges = [source_cursor, *internal, segment_end]
            local_lengths = [
                right - left for left, right in zip(local_edges, local_edges[1:])
            ]
            # Qwen 若把一个完整短操作切出不足 6 字的残句，恢复 MOSS 完整语义段。
            if min(local_lengths) <= MIN_BALANCED_SEGMENT_CHARS:
                for offset in internal:
                    boundaries.discard(offset)
                changed = True

        # 长原段中也可能被 Qwen 单独切出“这里 / 我们……”一类 2～5 字悬空条。
        # 只移除同一原段内部、且不属于真实停顿/插话保护的边界；下一条合并后
        # 仍必须不超过绝对字数上限。
        current_internal = sorted(
            offset for offset in boundaries if source_cursor < offset < segment_end
        )
        local_edges = [source_cursor, *current_internal, segment_end]
        for edge_index, offset in enumerate(current_internal, 1):
            left = source_content[local_edges[edge_index - 1] : offset]
            right_end = local_edges[edge_index + 1]
            left_content = content_exact(left)
            if (
                offset not in required_boundaries
                and left_content in DANGLING_SHORT_FRAGMENTS
                and len(left_content) <= 5
                and right_end - local_edges[edge_index - 1] <= MAX_SUBTITLE_CHARS
            ):
                boundaries.discard(offset)
                changed = True
        source_cursor = segment_end

    boundaries.add(total_length)
    before_mid = sorted(boundaries)
    snapped = snap_boundaries_away_from_word_interiors(
        source_text,
        before_mid,
        blocked=(required_boundaries | semantic_required_offsets),
    )
    if snapped != before_mid:
        boundaries = set(snapped)
        boundaries.add(total_length)
        changed = True
    boundaries.update(offset for offset in response_boundaries if 0 < offset < total_length)
    normalized = sorted(boundaries)
    ranges = []
    start = 0
    for end in normalized:
        ranges.append((start, end))
        start = end
    refined = split_text_at_content_ranges(source_text, ranges)
    if changed:
        print("   [语义护栏] 修正了完整短操作残句或漏掉的新分句边界。")
    return refined


def split_text_at_content_ranges(text, ranges):
    positions = [
        index
        for index, char in enumerate(text)
        if re.match(f"[{CONTENT_CHAR_CLASS}]", char)
    ]
    parts = []
    string_start = 0
    for _, content_end in ranges:
        string_end = (
            len(text)
            if content_end >= len(positions)
            else positions[content_end]
        )
        part = clean_subtitle_text(text[string_start:string_end])
        if not part:
            raise ValueError("本地修复产生了空字幕。")
        parts.append(part)
        string_start = string_end
    return parts


def indexed_content_for_prompt(text, line_size=36):
    """把可计数字符明确编号，避免大模型自己估算中文字符位置。"""
    content = content_exact(text)
    items = [f"{index}{char}" for index, char in enumerate(content, 1)]
    return "\n".join(
        " ".join(items[offset : offset + line_size])
        for offset in range(0, len(items), line_size)
    )


def lexical_boundary_terms():
    runtime_context = get_runtime_context()
    terms = {
        content_exact(term)
        for term in BOUNDARY_COHESION_TERMS
        if content_exact(term)
    }
    terms.update(
        content_exact(value)
        for pair in active_canonical_replacements()
        for value in pair
        if content_exact(value)
    )
    terms.update(
        content_exact(term)
        for term in runtime_context.discovered_terms
        if content_exact(term)
    )
    if runtime_context.enable_domain_terms:
        terms.update(content_exact(term) for term in active_profile_terms())
        from .terminology import runtime_snapshot
        for library in runtime_snapshot().libraries:
            for entry in library.terms:
                terms.update(content_exact(x) for x in (entry.canonical, *entry.aliases) if content_exact(x))
    return sorted((term for term in terms if len(term) >= 2), key=len, reverse=True)


def lexical_forbidden_boundary_offsets(text):
    source = content_exact(text)
    forbidden = set()
    for start,end,_ in structural_cohesion_spans(text):
        forbidden.update(range(start+1,end))
    for term in lexical_boundary_terms():
        start = source.find(term)
        while start >= 0:
            forbidden.update(range(start + 1, start + len(term)))
            start = source.find(term, start + 1)
    return forbidden



def chinese_word_spans(source_text):
    """用通用中文分词得到词级跨度；失败则退回单字跨度。

    日语任务改用文节近似（内容词连同其后的平假名），jieba 会把去掉假名后的
    日文汉字误分成中文词（「天才」被切成「…当天|才」）。
    """
    source = str(source_text or "")
    if not source:
        return []
    from twobyteasr.language_rules import is_japanese, japanese_phrase_spans
    if is_japanese():
        return japanese_phrase_spans(source)
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"pkg_resources is deprecated as an API.*",
                category=UserWarning,
            )
            import jieba

        words = [word for word in jieba.lcut(source) if word]
    except Exception:
        words = list(source)
    spans = []
    cursor = 0
    for word in words:
        if not word:
            continue
        if source.startswith(word, cursor):
            start = cursor
            end = cursor + len(word)
        else:
            found = source.find(word, cursor)
            if found < 0:
                if cursor >= len(source):
                    break
                start = cursor
                end = cursor + 1
                word = source[start:end]
            else:
                while cursor < found:
                    spans.append((cursor, cursor + 1, source[cursor]))
                    cursor += 1
                start = found
                end = found + len(word)
        spans.append((start, end, word))
        cursor = end
    while cursor < len(source):
        spans.append((cursor, cursor + 1, source[cursor]))
        cursor += 1
    # 通用数量结构：300万 / 67万 / 5000万 不能从数字和量级中间切断。
    number_units = set("万亿千百元块倍")
    merged = []
    index = 0
    while index < len(spans):
        start, end, word = spans[index]
        if word and all(char.isdigit() for char in word):
            cursor = index + 1
            while cursor < len(spans) and spans[cursor][2] in number_units:
                end = spans[cursor][1]
                word = source[start:end]
                cursor += 1
            merged.append((start, end, word))
            index = cursor
            continue
        merged.append((start, end, word))
        index += 1
    return merged


COMPACT_DATE_PATTERN = re.compile(
    r"^(?:今天是|日期是|时间是)?\d{4}年\d{1,2}月\d{1,2}日$"
)
COMPACT_WELCOME_PATTERN = re.compile(r"^欢迎(?:收看|来到|回到).+$")
DEPENDENT_RIGHT_PREFIXES = ("为主题的", "地下", "地上", "内部", "外部", "上方", "下方", "的")


def structural_cohesion_spans(source_text):
    """Deterministic spans that generic tokenizers commonly split badly."""
    source = content_exact(source_text)
    spans = []
    patterns = (
        re.compile(r"(?:今天是|日期是|时间是)?\d{4}年\d{1,2}月\d{1,2}日"),
        re.compile(r"[\u3400-\u9fff]{2}嘉年华"),
        re.compile(r"剧情线"),
        re.compile(r"的时候|能不能|可不可以|会不会|是不是|有没有"),
        re.compile(r"(?:百分之)?[零〇一二两三四五六七八九十百千万亿]+(?:点[零〇一二两三四五六七八九]+)?(?:张|卡|局|秒|分|元|颗)?"),
        re.compile(r"\d+(?:\.\d+)*(?:%|张|卡|局|秒|分|元|颗)?"),
        re.compile(r"为主题"),
        # 常见趋向/尝试补语是一个完整口语动作，禁止切成“看｜一下”。
        re.compile(r"[\u3400-\u9fff]一下"),
        re.compile(r"有感觉吗"),
        re.compile(r"十秒内不上[舰剑线]"),
        re.compile(r"10\s*9\s*8"),
    )
    for pattern in patterns:
        for match in pattern.finditer(source):
            spans.append((match.start(), match.end(), match.group(0)))
    return spans


def boundary_word_spans(source_text):
    return chinese_word_spans(source_text) + structural_cohesion_spans(source_text)


def repair_compact_utterance_boundary_offsets(
    segment_batch,
    boundary_offsets,
    protected_offsets=(),
    firered_tokens=(),
):
    """Keep short date announcements and welcome lines as complete utterances."""
    if not isinstance(boundary_offsets, list) or len(boundary_offsets) < 2:
        return boundary_offsets
    repaired = sorted({int(value) for value in boundary_offsets})
    blocked = (
        hard_break_character_offsets(segment_batch, firered_tokens)
        | set(protected_source_boundary_offsets(segment_batch))
        | set(protected_offsets)
    )
    cursor = 0
    removed = 0
    for segment in segment_batch:
        text = content_exact(segment.text)
        end = cursor + len(text)
        compact = (
            len(text) <= COMPLETE_PHRASE_SOFT_MAX_CHARS
            and segment.end - segment.start <= MAX_SUBTITLE_SECONDS + 0.05
        )
        atomic = bool(
            COMPACT_DATE_PATTERN.fullmatch(text)
            or COMPACT_WELCOME_PATTERN.fullmatch(text)
        )
        if compact and atomic:
            internal = [value for value in repaired if cursor < value < end]
            removable = [value for value in internal if value not in blocked]
            if removable and len(removable) == len(internal):
                repaired = [value for value in repaired if value not in set(removable)]
                removed += len(removable)
        cursor = end
    if removed:
        print(f"   [完整短句护栏] 合并 {removed} 处日期/欢迎语内部断点。")
    return repaired


def repair_dependent_prefix_boundary_offsets(
    segment_batch,
    boundary_offsets,
    protected_offsets=(),
    firered_tokens=(),
):
    """Move a cut forward when its right side starts with an attached phrase."""
    if not isinstance(boundary_offsets, list) or len(boundary_offsets) < 2:
        return boundary_offsets
    source = content_exact("".join(segment.text for segment in segment_batch))
    repaired = sorted({int(value) for value in boundary_offsets})
    blocked = (
        hard_break_character_offsets(segment_batch, firered_tokens)
        | set(protected_source_boundary_offsets(segment_batch))
        | set(protected_offsets)
    )
    moved = 0
    for index in range(len(repaired) - 1):
        boundary = repaired[index]
        if boundary in blocked:
            continue
        previous = repaired[index - 1] if index else 0
        following = repaired[index + 1]
        left = source[previous:boundary]
        right = source[boundary:following]
        discourse_prefix = next(
            (value for value in DISCOURSE_PREFIXES if left.endswith(value)),
            "",
        )
        if discourse_prefix:
            target = boundary - len(discourse_prefix)
            if (
                target > previous
                and target not in blocked
                and target - previous >= MIN_BALANCED_SEGMENT_CHARS
                and following - target <= COMPLETE_PHRASE_SOFT_MAX_CHARS
                and following - boundary >= MIN_BALANCED_SEGMENT_CHARS
                and not any(target < value <= boundary for value in blocked)
            ):
                repaired[index] = target
                moved += 1
                boundary = target
                left = source[previous:boundary]
                right = source[boundary:following]
        prefix = next((value for value in DEPENDENT_RIGHT_PREFIXES if right.startswith(value)), "")
        modal_suffix = ""
        if not prefix and left.endswith("会") and right.startswith(
            ("为", "给", "带", "让", "把", "被", "向", "在", "有", "获得", "成为", "进行")
        ):
            modal_suffix = "会"
        if not prefix and not modal_suffix:
            continue
        if modal_suffix:
            target = boundary - len(modal_suffix)
            if (
                target <= previous
                or target in blocked
                or target - previous < MIN_BALANCED_SEGMENT_CHARS
                or following - target > MAX_SUBTITLE_CHARS
                or any(target < value <= boundary for value in blocked)
            ):
                continue
            repaired[index] = target
            moved += 1
            continue
        if prefix in ("地下", "地上", "内部", "外部", "上方", "下方") and len(left) > 4:
            continue
        target = boundary + len(prefix)
        if (
            target >= following
            or target in blocked
            or target - previous > COMPLETE_PHRASE_SOFT_MAX_CHARS
            or following - target < MIN_BALANCED_SEGMENT_CHARS
            or any(boundary < value <= target for value in blocked)
        ):
            continue
        repaired[index] = target
        moved += 1
    index = 0
    while index < len(repaired) - 1:
        previous = repaired[index - 1] if index else 0
        boundary = repaired[index]
        following = repaired[index + 1]
        left = source[previous:boundary]
        right = source[boundary:following]
        if (
            boundary not in blocked
            and left.endswith("有")
            and re.match(r"\d+[个块处项条种位只台套]", right)
            and following - previous <= MAX_SUBTITLE_CHARS
        ):
            repaired.pop(index)
            moved += 1
            continue
        index += 1
    if moved:
        print(f"   [依附短语护栏] 调整 {moved} 处方位/主题短语断点。")
    return sorted(set(repaired))


def looks_like_category_field_list(text):
    """识别“新手场中级场高级场”这类并列场次列表（无空格）。"""
    source = content_exact(text)
    return bool(re.fullmatch(r"(?:[㐀-鿿]{1,2}场){2,}", source))


def repair_segmenter_word_boundary_offsets(
    segment_batch,
    boundary_offsets,
    firered_tokens=(),
):
    """硬护栏：禁止竖线落在通用分词词内部（如 进|入、藏|品）。

    使用 jieba 通用词边界，不是手写小词表。FireRed/说话人强制边界仍优先保留。
    """
    if not isinstance(boundary_offsets, list) or len(boundary_offsets) < 2:
        return boundary_offsets
    try:
        offsets = [int(value) for value in boundary_offsets]
    except (TypeError, ValueError):
        return boundary_offsets
    if offsets != sorted(set(offsets)):
        return boundary_offsets

    source = content_exact(
        "".join(clean_subtitle_text(segment.text) for segment in segment_batch)
    )
    if not source or offsets[-1] != len(source):
        return boundary_offsets

    blocked = hard_break_character_offsets(
        segment_batch,
        firered_tokens,
    ) | protected_source_boundary_offsets(
        segment_batch
    )
    spans = boundary_word_spans(source)
    if not spans:
        return boundary_offsets

    def covering_span(boundary):
        for start, end, word in spans:
            if start < boundary < end and end - start >= 2:
                return start, end, word
        return None

    repaired = list(offsets)
    moved = 0
    for index in range(len(repaired) - 1):
        boundary = repaired[index]
        if boundary in blocked:
            continue
        hit = covering_span(boundary)
        if hit is None:
            continue
        start, end, word = hit
        previous = repaired[index - 1] if index else 0
        following = repaired[index + 1]
        candidates = []
        for target in (start, end):
            if target <= previous or target >= following:
                continue
            left_len = target - previous
            right_len = following - target
            score = 0
            if left_len >= 2:
                score += 3
            if right_len >= 2:
                score += 3
            if left_len == 0 or right_len == 0:
                score -= 10
            if target == end:
                score += 4
            else:
                score -= 1
            # 左句更接近舒适字数时加分。
            score -= abs(left_len - PREFERRED_MAX_SUBTITLE_CHARS) * 0.15
            score -= abs(target - boundary) * 0.1
            candidates.append((score, -abs(target - boundary), target))
        if not candidates:
            continue
        candidates.sort(reverse=True)
        target = candidates[0][2]
        if target != boundary:
            repaired[index] = target
            moved += 1

    repaired = sorted(set(repaired))
    if repaired[-1] != len(source):
        repaired = [offset for offset in repaired if 0 < offset < len(source)] + [len(source)]
    cleaned = []
    last = 0
    for offset in repaired:
        if offset > last:
            cleaned.append(offset)
            last = offset
    if not cleaned or cleaned[-1] != len(source):
        cleaned.append(len(source))
    if moved:
        print(f"   [词边界护栏] 挪开 {moved} 处词中竖线（如进入/藏品被切开）。")
    return cleaned


def repair_lexical_boundary_offsets(
    segment_batch,
    boundary_offsets,
    firered_tokens=(),
):
    """在不改字的前提下，避免把“卡池”等确定词语从中间切开。"""
    if not isinstance(boundary_offsets, list) or len(boundary_offsets) < 2:
        return boundary_offsets
    if any(isinstance(value, bool) for value in boundary_offsets):
        return boundary_offsets
    try:
        offsets = [int(value) for value in boundary_offsets]
    except (TypeError, ValueError):
        return boundary_offsets
    if offsets != sorted(set(offsets)):
        return boundary_offsets

    source = content_exact(
        "".join(clean_subtitle_text(segment.text) for segment in segment_batch)
    )
    if not source or offsets[-1] != len(source):
        return boundary_offsets

    blocked = hard_break_character_offsets(
        segment_batch,
        firered_tokens,
    ) | protected_source_boundary_offsets(
        segment_batch
    )
    terms = lexical_boundary_terms()
    # Reduplicated spoken tokens remain intact even when their entity spelling
    # is absent from the selected glossary; this never guesses a canonical.
    terms = sorted(set(terms) | {m.group() for m in re.finditer(r'([\u4e00-\u9fff])\1+', source)}, key=len, reverse=True)
    repaired = list(offsets)
    extra_boundaries = set()
    for index in range(len(repaired) - 1):
        boundary = repaired[index]
        if boundary in blocked:
            continue
        previous = repaired[index - 1] if index else 0
        following = repaired[index + 1]
        for term in terms:
            term_length = len(term)
            starts = range(
                max(previous, boundary - term_length + 1),
                min(boundary, len(source) - term_length) + 1,
            )
            match = next(
                (
                    start
                    for start in starts
                    if start < boundary < start + term_length
                    and source[start : start + term_length] == term
                ),
                None,
            )
            if match is None:
                continue
            target = (
                match
                if term in BOUNDARY_MOVE_BEFORE_TERMS
                else match + term_length
            )
            if target <= previous or target >= following:
                continue
            if target - previous > MAX_SUBTITLE_CHARS:
                continue
            if following - target > MAX_SUBTITLE_CHARS:
                # “你能想到｜我们能听到……”需把完整短语单独成条：既把
                # 错误边界移到短语前，也在短语后补一个边界。
                term_end = match + term_length
                if (
                    term in BOUNDARY_MOVE_BEFORE_TERMS
                    and target < term_end < following
                    and term_end - target <= MAX_SUBTITLE_CHARS
                    and following - term_end <= MAX_SUBTITLE_CHARS
                    and term_end not in blocked
                ):
                    extra_boundaries.add(term_end)
                else:
                    continue
            if following - target < PROTECTED_SOURCE_SHORT_CHARS:
                continue
            move_start, move_end = sorted((boundary, target))
            if any(move_start < required < move_end for required in blocked):
                continue
            old_context = source[max(0, boundary - 2) : min(len(source), boundary + 2)]
            repaired[index] = target
            print(
                f"   [边界修复] 避免拆开“{term}”："
                f"{boundary} -> {target}（{old_context}）"
            )
            break
    return sorted(set(repaired) | extra_boundaries)


INCOMPLETE_BOUNDARY_SUFFIXES = (
    "不得不",
    "因为", "所以", "然后", "但是", "如果", "或者",
    "他可能", "那我", "上我们的", "我们这里", "这里我们",
    "应该", "可能", "还是", "还",
)


def repair_incomplete_boundary_offsets(
    segment_batch,
    boundary_offsets,
    protected_offsets=(),
    firered_tokens=(),
):
    """把“因为｜他”“他可能｜开”一类边界移到未完成短语之前。"""
    if not isinstance(boundary_offsets, list) or len(boundary_offsets) < 2:
        return boundary_offsets
    source = content_exact(
        "".join(clean_subtitle_text(segment.text) for segment in segment_batch)
    )
    blocked = (
        hard_break_character_offsets(segment_batch, firered_tokens)
        | set(protected_source_boundary_offsets(segment_batch))
        | set(protected_offsets)
    )
    repaired = list(boundary_offsets)
    for index in range(len(repaired) - 1):
        boundary = repaired[index]
        if boundary in blocked:
            continue
        previous = repaired[index - 1] if index else 0
        following = repaired[index + 1]
        left = source[previous:boundary]
        for suffix in INCOMPLETE_BOUNDARY_SUFFIXES:
            if not left.endswith(suffix):
                continue
            target = boundary - len(suffix)
            if (
                target <= previous
                or target >= following
                or target in blocked
                or target - previous < MIN_BALANCED_SEGMENT_CHARS
                or following - target > MAX_SUBTITLE_CHARS
            ):
                continue
            repaired[index] = target
            print(
                f"   [残句修复] 把“{suffix}”移到下一条："
                f"{boundary} -> {target}。"
            )
            break
    return sorted(set(repaired))


LATIN_FOLLOWING_PREDICATES = (
    "能不能", "会不会", "要不要", "是不是", "有没有", "可不可以",
    "怎么", "为什么", "能否", "可以", "能", "会", "要",
)


def repair_latin_predicate_boundary_offsets(
    segment_batch,
    boundary_offsets,
    protected_offsets=(),
    firered_tokens=(),
):
    """把“这把ELO｜能不能”修成“这把｜ELO能不能”，避免英文提前出现。"""
    if not isinstance(boundary_offsets, list) or len(boundary_offsets) < 2:
        return boundary_offsets
    source = content_exact(
        "".join(clean_subtitle_text(segment.text) for segment in segment_batch)
    )
    blocked = (
        hard_break_character_offsets(segment_batch, firered_tokens)
        | set(protected_source_boundary_offsets(segment_batch))
        | set(protected_offsets)
    )
    repaired = list(boundary_offsets)
    for index in range(len(repaired) - 1):
        boundary = repaired[index]
        if boundary in blocked:
            continue
        previous = repaired[index - 1] if index else 0
        following = repaired[index + 1]
        left = source[previous:boundary]
        right = source[boundary:following]
        latin = re.search(r"[A-Za-z][A-Za-z0-9+.-]{1,7}$", left)
        if latin is None or not right.startswith(LATIN_FOLLOWING_PREDICATES):
            continue
        target = previous + latin.start()
        if (
            target <= previous
            or target >= following
            or target in blocked
            or target - previous < MIN_BALANCED_SEGMENT_CHARS
            or following - target > MAX_SUBTITLE_CHARS
            or any(target < offset <= boundary for offset in blocked)
        ):
            continue
        repaired[index] = target
        print(
            f"   [英文语义边界] {latin.group(0)} 与后面的谓语放在同一条："
            f"{boundary} -> {target}。"
        )
    return sorted(set(repaired))


AWKWARD_BOUNDARY_LEFT_SUFFIXES = (
    "这", "那", "他", "我们", "你们", "他们", "而", "且",
    "因为", "所以", "然后", "但是", "如果", "或者", "可能",
    "要", "再", "把", "给", "让", "跟", "和", "与", "从", "向",
    "得", "能", "想", "觉得", "感觉", "准备", "上我们的",
    "应该", "还是", "估计",
    "还",
    # 未完成的指量/修饰尾巴：后接中心语时应并到同一条或改切点。
    "一个", "这个", "那个", "哪个", "什么", "哪种", "这种", "那种",
    "有点", "有些",
)


AWKWARD_BOUNDARY_RIGHT_PREFIXES = ("的话", "了吗", "呢", "吧", "嘛", "的")


# 短“我的/他的”必算坏切；更长的“…的｜短中心语”由 hanging-attribute 合并处理。
AWKWARD_SHORT_DE_LEFT_MAX_CHARS = 3


HANGING_ATTRIBUTE_LEFT_ENDINGS = (
    "的", "地", "得",
    "一个", "这个", "那个", "哪个", "什么", "哪种", "这种", "那种",
    "有点", "有些",
)


# 右句若像新分句主语/连接，不强行并回。
HANGING_ATTRIBUTE_RIGHT_BLOCK_PREFIXES = (
    "我", "你", "他", "她", "它", "咱", "您",
    "但是", "因为", "所以", "然后", "如果", "其实", "就是", "不是",
    "怎么", "为什么", "那我", "那你", "他可能", "我们再",
)


SHORT_COMPLETION_RIGHT_MAX_CHARS = 6


LEXICAL_LE_PREFIXES = ("了解", "了不起", "了断", "了得", "了结", "了然")



def left_has_hanging_attribute(left_text):
    left = content_exact(left_text)
    if not left:
        return False
    return any(left.endswith(ending) for ending in HANGING_ATTRIBUTE_LEFT_ENDINGS)


def right_is_short_completion(right_text):
    right = content_exact(right_text)
    if not right or len(right) > SHORT_COMPLETION_RIGHT_MAX_CHARS:
        return False
    if right.startswith(HANGING_ATTRIBUTE_RIGHT_BLOCK_PREFIXES):
        # “我”开头的短反应（我靠/我去）可并；真正新分句通常更长。
        if len(right) >= 4:
            return False
    # 新动作/谓语开头通常是下一句，不是“的/一个”后的中心语。
    verbish_starts = (
        "买", "看", "去", "来", "说", "讲", "问", "是", "有", "要", "选",
        "打", "开", "用", "给", "把", "让", "做", "搞", "弄", "走", "跑",
        "进", "出", "开始", "准备", "直接", "先", "再", "又", "也", "都",
        "别", "不", "没", "请", "帮", "试", "玩", "抽", "拍", "卖", "花",
    )
    if right.startswith(verbish_starts) and not right.startswith(("一个", "这个", "那个")):
        return False
    return True


def should_merge_hanging_attribute(left_text, right_text, soft_max=None):
    """未完成定语/指量 + 短中心语：优先合成一句，允许略超常规 12 字。"""
    if soft_max is None:
        soft_max = COMPLETE_PHRASE_SOFT_MAX_CHARS
    left = content_exact(left_text)
    right = content_exact(right_text)
    if not left_has_hanging_attribute(left) or not right_is_short_completion(right):
        return False
    return len(left) + len(right) <= int(soft_max)


def repair_hanging_attribute_boundary_offsets(
    segment_batch,
    boundary_offsets,
    protected_offsets=(),
    firered_tokens=(),
):
    """去掉“300万的｜启动资金啊”“进入一个｜珊瑚场啊”这类坏竖线。

    优先直接合并；若合并会超过软上限，再尝试把“一个/这个/的”整段挪到更合适一侧。
    """
    if not isinstance(boundary_offsets, list) or len(boundary_offsets) < 2:
        return boundary_offsets
    try:
        repaired = [int(value) for value in boundary_offsets]
    except (TypeError, ValueError):
        return boundary_offsets
    if repaired != sorted(set(repaired)):
        return boundary_offsets

    source = content_exact(
        "".join(clean_subtitle_text(segment.text) for segment in segment_batch)
    )
    if not source or repaired[-1] != len(source):
        return boundary_offsets

    blocked = (
        hard_break_character_offsets(segment_batch, firered_tokens)
        | set(protected_source_boundary_offsets(segment_batch))
        | set(protected_offsets)
    )

    changed = 0
    index = 0
    while index < len(repaired) - 1:
        boundary = repaired[index]
        previous = repaired[index - 1] if index else 0
        following = repaired[index + 1]
        if boundary in blocked:
            index += 1
            continue
        left = source[previous:boundary]
        right = source[boundary:following]
        if not left_has_hanging_attribute(left) or not right_is_short_completion(right):
            index += 1
            continue

        combined = following - previous
        # 1) 能完整合成一句就删竖线。
        if combined <= COMPLETE_PHRASE_SOFT_MAX_CHARS and not any(
            previous < required < following for required in blocked
        ):
            repaired.pop(index)
            changed += 1
            print(
                f"   [定语残尾] 合并未完成修饰："
                f"“{left}｜{right}” -> “{left}{right}”。"
            )
            continue

        # 2) 合并过长时：指量结构优先在“进入｜一个珊瑚场”处切开。
        moved = False
        for ending in ("一个", "这个", "那个", "哪个", "这种", "那种", "哪种", "什么"):
            if not left.endswith(ending):
                continue
            target = boundary - len(ending)
            if (
                target <= previous
                or target >= following
                or target in blocked
                or target - previous < MIN_BALANCED_SEGMENT_CHARS
                or following - target > MAX_SUBTITLE_CHARS
                or target - previous > MAX_SUBTITLE_CHARS
                or any(min(boundary, target) < required < max(boundary, target) for required in blocked)
            ):
                continue
            repaired[index] = target
            changed += 1
            moved = True
            print(
                f"   [定语残尾] 将“{ending}”并入后句："
                f"{boundary} -> {target}（{source[previous:target]}｜{source[target:following]}）。"
            )
            break
        if moved:
            index += 1
            continue

        # 3) “…的｜短中心语”且无法合并：不把“的”甩到下一句开头；保持或略向右找词边界。
        if left.endswith("的") and combined <= COMPLETE_PHRASE_SOFT_MAX_CHARS + 2:
            # 再宽一点仍优先合并观感。
            if combined <= COMPLETE_PHRASE_SOFT_MAX_CHARS + 2 and not any(
                previous < required < following for required in blocked
            ):
                # 超过 soft+2 就不动；这里 +2 已在条件中。对 15 字极端短语保留切开。
                pass
        index += 1

    if changed:
        repaired = sorted(set(repaired))
        if not repaired or repaired[-1] != len(source):
            repaired = [offset for offset in repaired if 0 < offset < len(source)] + [len(source)]
    return repaired



def repair_category_field_list_cues(cues):
    """把“什么新手场｜中级场高级场”收成“什么｜新手场中级场高级场”。"""
    if not cues or len(cues) < 2:
        return cues
    rows = sorted(
        cues,
        key=lambda cue: (cue.start, cue.end, cue.speaker or "", getattr(cue, "cue_id", 0)),
    )
    changed = 0
    index = 0
    pattern = re.compile(
        r"(?:什么|哪些|这些|那些|就是什么)((?:[㐀-鿿]{1,2}场){2,})"
    )
    while index < len(rows) - 1:
        left = rows[index]
        right = rows[index + 1]
        if (left.speaker or "S00") != (right.speaker or "S00"):
            index += 1
            continue
        if left.timing_locked or right.timing_locked:
            index += 1
            continue
        gap = right.start - left.end
        if gap > 0.45 or gap < -0.20:
            index += 1
            continue
        joined = content_exact(left.text + right.text)
        cut = len(content_exact(left.text))
        match = pattern.search(joined)
        if match is None:
            index += 1
            continue
        list_start = match.start(1)
        list_end = match.end(1)
        if not (list_start < cut < list_end):
            index += 1
            continue
        new_left = joined[:list_start]
        new_right = joined[list_start:]
        if not new_left or not new_right:
            index += 1
            continue
        if (
            display_length(new_left) > COMPLETE_PHRASE_SOFT_MAX_CHARS
            or display_length(new_right) > COMPLETE_PHRASE_SOFT_MAX_CHARS
        ):
            index += 1
            continue
        left_len = max(1, display_length(new_left))
        right_len = max(1, display_length(new_right))
        total_len = left_len + right_len
        window_start = min(left.start, right.start)
        window_end = max(left.end, right.end)
        split_at = window_start + span * left_len / total_len
        split_at = min(
            max(split_at, window_start + MIN_SUBTITLE_SECONDS * 0.5),
            window_end - MIN_SUBTITLE_SECONDS * 0.5,
        )
        left.text = clean_subtitle_text(new_left)
        right.text = clean_subtitle_text(new_right)
        left.start = window_start
        left.end = split_at
        right.start = split_at
        right.end = window_end
        changed += 1
        index += 1
    if changed:
        print(f"   [场次列表] 归整 {changed} 处“什么｜新手场中级场高级场”类切分。")
    return rows


def merge_hanging_attribute_cues(cues):
    """最终字幕轨：合回未完成定语/指量 + 短中心语。"""
    if not cues or len(cues) < 2:
        return cues
    rows = sorted(
        cues,
        key=lambda cue: (cue.start, cue.end, cue.speaker or "", getattr(cue, "cue_id", 0)),
    )
    changed = 0
    index = 0
    while index < len(rows) - 1:
        left = rows[index]
        right = rows[index + 1]
        if (left.speaker or "S00") != (right.speaker or "S00"):
            index += 1
            continue
        if left.timing_locked or right.timing_locked:
            index += 1
            continue
        gap = right.start - left.end
        if gap > 0.45 or gap < -0.20:
            index += 1
            continue
        if not should_merge_hanging_attribute(left.text, right.text):
            index += 1
            continue
        duration = max(left.end, right.end) - min(left.start, right.start)
        if duration > MAX_SUBTITLE_SECONDS + 0.05:
            index += 1
            continue
        left.text = clean_subtitle_text(left.text + right.text)
        left.start = min(left.start, right.start)
        left.end = max(left.end, right.end)
        left.timing_locked = left.timing_locked and right.timing_locked
        rows.pop(index + 1)
        changed += 1
    if changed:
        print(f"   [定语残尾] 成片合并 {changed} 处未完成修饰短尾。")
    return rows


def starts_with_dependent_le(text):
    """识别不能独立挂在下一条开头的完成助词“了”，排除“了解”等实词。"""
    right = content_exact(text)
    return right.startswith("了") and not right.startswith(LEXICAL_LE_PREFIXES)


def inside_repeat_run(text, offset):
    """``offset`` separates two identical adjacent Chinese units (1-4 chars)."""
    source = content_exact(text)
    for size in (1, 2, 3, 4):
        left, right = source[max(0, offset - size):offset], source[offset:offset + size]
        if len(left) == size and left == right and all("一" <= char <= "鿿" for char in left):
            return True
    return False


def semantically_awkward_boundary(text, offset):
    source = content_exact(text)
    left = source[:offset]
    right = source[offset:]
    short_de_left = left.endswith("的") and len(left) <= AWKWARD_SHORT_DE_LEFT_MAX_CHARS
    return (
        left.endswith(AWKWARD_BOUNDARY_LEFT_SUFFIXES)
        or short_de_left
        or right.startswith(AWKWARD_BOUNDARY_RIGHT_PREFIXES)
        or starts_with_dependent_le(right)
    )


SHORT_REACTION_TAILS = frozenset(("哈哈", "嘿嘿", "呵呵", "嘻嘻"))


def repair_dependent_particle_boundary_offsets(
    segment_batch,
    boundary_offsets,
    protected_offsets=(),
    firered_tokens=(),
):
    """修复“抽到｜了哈哈”，并把依附前句的短笑声合回完整语义块。"""
    if not isinstance(boundary_offsets, list) or len(boundary_offsets) < 2:
        return boundary_offsets
    try:
        repaired = [int(value) for value in boundary_offsets]
    except (TypeError, ValueError):
        return boundary_offsets
    if repaired != sorted(set(repaired)):
        return boundary_offsets

    source = content_exact(
        "".join(clean_subtitle_text(segment.text) for segment in segment_batch)
    )
    if not source or repaired[-1] != len(source):
        return boundary_offsets
    blocked = (
        hard_break_character_offsets(segment_batch, firered_tokens)
        | set(protected_source_boundary_offsets(segment_batch))
        | set(protected_offsets)
    )

    for index in range(len(repaired) - 1):
        boundary = repaired[index]
        if boundary in blocked or not starts_with_dependent_le(source[boundary:]):
            continue
        previous = repaired[index - 1] if index else 0
        following = repaired[index + 1]
        local_text = source[previous:following]
        semantic_candidates = {
            previous + offset
            for offset in semantic_restart_boundary_offsets(local_text)
        }
        candidates = [
            target
            for target in semantic_candidates
            if (
                previous < target < following
                and target not in blocked
                and target - previous >= MIN_BALANCED_SEGMENT_CHARS
                and following - target >= MIN_BALANCED_SEGMENT_CHARS
                and target - previous <= MAX_SUBTITLE_CHARS
                and following - target <= MAX_SUBTITLE_CHARS
                and not any(
                    min(boundary, target) < required < max(boundary, target)
                    for required in blocked
                )
            )
        ]
        if candidates:
            target = min(
                candidates,
                key=lambda item: (
                    abs((item - previous) - TARGET_RAW_SEGMENT_CHARS),
                    abs(item - boundary),
                ),
            )
        else:
            # 没有更好的语义重启点时，把完成助词“了”留在上一条；仍严格
            # 服从字数、短尾和真实长停顿约束。
            target = boundary + 1
            if (
                target >= following
                or target in blocked
                or target - previous > MAX_SUBTITLE_CHARS
                or following - target < PROTECTED_SOURCE_SHORT_CHARS
                or any(boundary < required <= target for required in blocked)
            ):
                continue
        repaired[index] = target
        print(f"   [助词边界] 避免下一条以‘了’开头：{boundary} -> {target}。")

    repaired = sorted(set(repaired))
    # Qwen 偶尔会把紧随完整陈述的“哈哈”再切成两字残尾；若合并后仍不超过
    # 12 字且没有跨越受保护停顿，就合回前条。
    index = 0
    while index < len(repaired) - 1:
        boundary = repaired[index]
        previous = repaired[index - 1] if index else 0
        following = repaired[index + 1]
        right = source[boundary:following]
        if (
            boundary not in blocked
            and right in SHORT_REACTION_TAILS
            and following - previous <= MAX_SUBTITLE_CHARS
        ):
            repaired.pop(index)
            print(f"   [短反应护栏] 合回依附前句的‘{right}’。")
            continue
        index += 1
    return repaired


def texts_from_boundary_offsets(
    segment_batch,
    boundary_offsets,
    firered_tokens=(),
):
    """只接受边界整数，并始终从本地原文切片，Qwen 无法改动任何字。"""
    source_text = "".join(clean_subtitle_text(item.text) for item in segment_batch)
    total_length = display_length(source_text)
    if total_length <= 0:
        raise ValueError("断句批次没有可用文字。")
    if not isinstance(boundary_offsets, list) or not boundary_offsets:
        raise ValueError("模型 JSON 中缺少 boundaries 数组。")

    normalized = []
    for value in boundary_offsets:
        if isinstance(value, bool):
            raise ValueError("模型 boundaries 包含布尔值。")
        try:
            offset = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("模型 boundaries 必须全部是整数。") from exc
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("模型 boundaries 包含非整数小数。")
        normalized.append(offset)

    if normalized != sorted(set(normalized)):
        raise ValueError("模型 boundaries 必须严格递增且不能重复。")
    if normalized[0] <= 0 or normalized[-1] != total_length:
        raise ValueError(
            f"模型 boundaries 必须从正数开始，并以全文长度 {total_length} 结束。"
        )
    if any(offset > total_length for offset in normalized):
        raise ValueError("模型 boundaries 超出全文长度。")

    hard_offsets = hard_break_character_offsets(segment_batch, firered_tokens)
    missing_hard = sorted(hard_offsets - set(normalized))
    if missing_hard:
        raise ValueError(f"模型 boundaries 漏掉强制停顿位置 {missing_hard[:8]}。")

    protected_offsets = protected_source_boundary_offsets(segment_batch)
    missing_source = sorted(protected_offsets - set(normalized))
    if missing_source:
        raise ValueError(
            f"模型 boundaries 漏掉受保护语音段边界 {missing_source[:8]}，"
            "不得把独立短句并入前后句。"
        )

    ranges = []
    start = 0
    for end in normalized:
        ranges.append((start, end))
        start = end
    return split_text_at_content_ranges(source_text, ranges)




def snap_boundaries_away_from_word_interiors(text, boundaries, blocked=None):
    """把落在通用词内部的断点挪到词前/词后；真实硬边界可进 blocked 保留。"""
    blocked = {int(value) for value in (blocked or ())}
    source = content_exact(clean_subtitle_text(text))
    if not source:
        return sorted({int(value) for value in boundaries if int(value) > 0})
    try:
        offsets = sorted({int(value) for value in boundaries if int(value) > 0})
    except (TypeError, ValueError):
        return list(boundaries)
    spans = [
        (start, end, word)
        for start, end, word in chinese_word_spans(source)
        if end - start >= 2
    ]
    if not spans:
        return offsets

    def covering(boundary):
        for start, end, word in spans:
            if start < boundary < end:
                return start, end, word
        return None

    snapped = set()
    for boundary in offsets:
        if boundary >= len(source):
            snapped.add(len(source))
            continue
        if boundary in blocked:
            snapped.add(boundary)
            continue
        hit = covering(boundary)
        if hit is None:
            snapped.add(boundary)
            continue
        start, end, _word = hit
        candidates = []
        for target in (start, end):
            if target <= 0 or target >= len(source):
                continue
            # 优先完整落到词尾，避免再次造出词首残片。
            score = abs(target - boundary) + (0 if target == end else 0.75)
            candidates.append((score, target))
        if not candidates:
            continue
        candidates.sort()
        snapped.add(candidates[0][1])
    if offsets and offsets[-1] >= len(source):
        snapped.add(len(source))
    return sorted(snapped)


def segmenter_forbidden_boundary_offsets(text):
    """返回落在通用分词词内部的偏移（词中禁切）。"""
    source = content_exact(clean_subtitle_text(text))
    forbidden = set()
    for start, end, word in chinese_word_spans(source):
        if end - start < 2:
            continue
        forbidden.update(range(start + 1, end))
    return forbidden


def repair_mid_word_adjacent_cues(cues, segments=(), firered_tokens=()):
    """最后兜底：相邻字幕把一个词左右切开时，挪切点或合并。

    挪切点（把跨界词整体归左或归右）不合并两条字幕，因此允许跨换气级
    间隙（≤ MID_WORD_MOVE_MAX_GAP_SECONDS）；真正把两条并成一条的兜底
    仍受“近乎连读”原门约束，防止跨长静音/插话合并出超长字幕。
    """
    if not cues or len(cues) < 2:
        return cues
    rows = sorted(
        cues,
        key=lambda cue: (cue.start, cue.end, cue.speaker or "", getattr(cue, "cue_id", 0)),
    )
    changed = 0
    index = 0
    while index < len(rows) - 1:
        left = rows[index]
        right = rows[index + 1]
        if (left.speaker or "S00") != (right.speaker or "S00"):
            index += 1
            continue
        gap = right.start - left.end
        combined_duration = max(left.end, right.end) - min(left.start, right.start)
        # 只有“真正相邻、近乎连读”的词内切点才允许合并两条；挪切点走下面的
        # 放宽门。过去仅检查说话人和文字，会把同一主播跨过十几秒静音及另一
        # 主播插话的两句重新合并，最终制造出超过 5 秒的字幕并让整批任务失败。
        contiguous = (
            -0.20 <= gap <= PROTECTED_SOURCE_GAP_SECONDS
            and combined_duration <= MAX_SUBTITLE_SECONDS + 0.05
        )
        left_text = clean_subtitle_text(left.text)
        right_text = clean_subtitle_text(right.text)
        if not left_text or not right_text:
            index += 1
            continue
        # “……一个金｜看一下……”是两个完整动作。jieba 偶尔把临时上下文
        # “金看”当成词，不能让通用词中兜底覆盖已经自然的动作边界。
        if (
            right_text.startswith(("看一下", "再看", "我们看"))
            and not content_exact(left_text).endswith(
                ("想", "要", "来", "去", "再", "先", "帮", "给", "让", "请", "能", "会")
            )
        ):
            index += 1
            continue
        joined = content_exact(left_text + right_text)
        cut = len(content_exact(left_text))
        hit = next(
            (
                (start, end, word)
                for start, end, word in boundary_word_spans(joined)
                if end - start >= 2 and start < cut < end
            ),
            None,
        )
        if hit is None:
            index += 1
            continue
        start, end, word = hit
        options = []
        for target in (start, end):
            new_left = joined[:target]
            new_right = joined[target:]
            if not new_left or not new_right:
                continue
            if (
                display_length(new_left) > MAX_SUBTITLE_CHARS
                or display_length(new_right) > MAX_SUBTITLE_CHARS
            ):
                continue
            left_len = display_length(new_left)
            right_len = display_length(new_right)
            balance = abs(left_len - right_len)
            # 优先词尾（完整词留在左句），再看长度平衡与是否贴近 8 字。
            options.append(
                (
                    0 if target == end else 1,
                    balance,
                    abs(left_len - PREFERRED_MAX_SUBTITLE_CHARS),
                    -left_len,
                    target,
                    new_left,
                    new_right,
                )
            )
        if not options:
            if not contiguous:
                index += 1
                continue
            merged_text = clean_subtitle_text(left_text + right_text)
            if display_length(merged_text) <= MAX_SUBTITLE_CHARS + 2:
                left.text = merged_text
                left.end = max(left.end, right.end)
                left.start = min(left.start, right.start)
                rows.pop(index + 1)
                changed += 1
                continue
            index += 1
            continue
        # 挪切点放宽门：跨换气级间隙也修（不合并、只挪字），但说话人重叠
        # 锁定段的时间冻结契约优先，超窗的长静音也不动。
        if (
            gap > MID_WORD_MOVE_MAX_GAP_SECONDS
            or getattr(left, "timing_locked", False)
            or getattr(right, "timing_locked", False)
        ):
            index += 1
            continue
        # 2026-10-10: a cut that is an ASR utterance boundary with a real
        # pause is speech evidence, not a word interior. jieba reading
        # "叠上|任任泽" as 上任 must not move 任 across a 0.83 s pause.
        if gap >= 0.30 and any(abs(float(segment.end) - left.end) <= .06 for segment in segments) and any(
                abs(float(segment.start) - right.start) <= .06 for segment in segments):
            index += 1
            continue
        options = [option for option in options
                   if not (0 < option[4] < len(joined) and joined[option[4] - 1] == joined[option[4]]
                           and "一" <= joined[option[4]] <= "鿿")]
        if not options:
            index += 1
            continue
        options.sort()
        applied = False
        window_start = min(left.start, right.start)
        window_end = max(left.end, right.end)
        span = max(MIN_SUBTITLE_SECONDS, window_end - window_start)
        for _rank, _balance, _pref, _neg, target, new_left, new_right in options:
            from .subtitle_fidelity import aligned_boundary_time
            split_at = aligned_boundary_time(left, right, target, segments, firered_tokens)
            if split_at is None:
                # A whole cue span is known; invented per-character timestamps
                # are not. Preserve it by a bounded merge when that is readable.
                if contiguous and display_length(joined) <= MAX_SUBTITLE_CHARS:
                    left.text = clean_subtitle_text(left_text + right_text)
                    left.end = window_end
                    rows.pop(index + 1)
                    record_run_event('boundary_alignment_degraded', reason='no_word_alignment_bounded_merge',
                                     start=window_start, end=window_end, text=left.text)
                    applied = True
                break
            # 保持两句都有最小时长，且任一侧都不得超过成片 5 秒上限。
            if not window_start < split_at < window_end:
                continue
            if (
                split_at - window_start > MAX_SUBTITLE_SECONDS + 0.05
                or window_end - split_at > MAX_SUBTITLE_SECONDS + 0.05
            ):
                continue
            left.text = clean_subtitle_text(new_left)
            right.text = clean_subtitle_text(new_right)
            left.start = window_start
            left.end = split_at
            right.start = split_at
            right.end = window_end
            applied = True
            break
        if applied:
            changed += 1
        index += 1
    if changed:
        print(f"   [词边界兜底] 修正 {changed} 处相邻字幕词中切开。")
    return rows


def locally_repair_resegmented_cue(
    text,
    units,
    forced_boundaries=None,
    preferred_boundaries=None,
    comfort_max_chars=None,
):
    """只修复 Qwen 输出中过长/跨停顿的单条，不丢弃同批其他有效断句。"""
    # 词内强制切点（如 进|入）先贴到词边界；否则 DP 只能在词中切开。
    forced_boundaries = set(
        snap_boundaries_away_from_word_interiors(
            text,
            set(forced_boundaries or ()),
        )
    )
    preferred_boundaries = set(
        snap_boundaries_away_from_word_interiors(
            text,
            set(preferred_boundaries or ())
            | text_boundary_hints(text)
            | semantic_restart_boundary_offsets(text),
        )
    )
    forbidden_boundaries = set(lexical_forbidden_boundary_offsets(text)) | set(
        segmenter_forbidden_boundary_offsets(text)
    )
    count = len(units)
    if count <= 0 or display_length(text) != count:
        raise ValueError("本地修复的文字与时间单元不一致。")

    source_chars = content_exact(text)
    # score: (total_cost, distance_to_preferred_len, -left_len)
    # 同分时优先更接近 8 字、且左句更完整（避免 直接|进入、八件|藏品）。
    best_score = [(float("inf"), 0, 0)] * (count + 1)
    best_next = [None] * (count + 1)
    best_score[count] = (0.0, 0, 0)

    for start_index in range(count - 1, -1, -1):
        for end_index in range(start_index + 1, count + 1):
            length = end_index - start_index
            duration = units[end_index - 1].end - units[start_index].start
            # 成片严格执行 16 字上限，同时避免切出“的｜启动资金”残尾。
            if length > COMPLETE_PHRASE_SOFT_MAX_CHARS or duration > MAX_SUBTITLE_SECONDS + 0.05:
                break
            if any(start_index < boundary < end_index for boundary in forced_boundaries):
                continue
            if (
                end_index < count
                and end_index in forbidden_boundaries
                and end_index not in forced_boundaries
            ):
                continue

            cost = 10.0 + 0.22 * (length - PREFERRED_MAX_SUBTITLE_CHARS) ** 2
            if length < MIN_BALANCED_SEGMENT_CHARS:
                cost += 16.0 * (MIN_BALANCED_SEGMENT_CHARS - length) ** 2
            # 超过常规 12 的完整短语略罚，但仍优于残尾两刀。
            if length > MAX_SUBTITLE_CHARS:
                cost += 6.0 * (length - MAX_SUBTITLE_CHARS) ** 2
            # 回退舒适模式：超舒适长度的整段重罚，逼 DP 落到 ~8-12 字两刀。
            if comfort_max_chars is not None and length > comfort_max_chars:
                cost += 30.0 * (length - comfort_max_chars)
            if end_index < count:
                gap = max(0.0, units[end_index].start - units[end_index - 1].end)
                cost -= min(10.0, gap * 20.0)
                if end_index in preferred_boundaries:
                    cost -= 8.0
                if semantically_awkward_boundary(text, end_index):
                    cost += 48.0
                # A run of one repeated call (影袭影袭|影袭) is one unit.
                if inside_repeat_run(text, end_index):
                    cost += 48.0
                left_piece = content_exact(text)[start_index:end_index]
                right_piece = content_exact(text)[end_index:count]
                # 仅当左右合起来本可进软顶时，才重罚这种“的｜短中心语”切法。
                if should_merge_hanging_attribute(left_piece, right_piece):
                    cost += 80.0
                # 左句明显偏短、右句更长时略惩罚，推动“直接进入｜一个…”而非“直接｜进入…”。
                right_len = count - end_index
                if length <= PREFERRED_MAX_SUBTITLE_CHARS - 2 and right_len >= length + 1:
                    cost += 2.5
            if end_index in forced_boundaries:
                cost -= 20.0

            total = cost + best_score[end_index][0]
            score = (
                total,
                abs(length - PREFERRED_MAX_SUBTITLE_CHARS),
                -length,
            )
            if score < best_score[start_index]:
                best_score[start_index] = score
                best_next[start_index] = end_index

    if best_next[0] is None:
        # Quality guards must not discard a completed file. Conservatively hard
        # split sparse/fully-protected timelines and preserve every character.
        ranges = []
        start_index = 0
        while start_index < count:
            forced_after = min((b for b in forced_boundaries if b > start_index), default=count)
            limit = min(count, forced_after, start_index + COMPLETE_PHRASE_SOFT_MAX_CHARS)
            end_index = start_index
            while end_index < limit:
                candidate = end_index + 1
                duration = units[candidate - 1].end - units[start_index].start
                if candidate > start_index + 1 and duration > MAX_SUBTITLE_SECONDS + 0.05:
                    break
                end_index = candidate
                if duration > MAX_SUBTITLE_SECONDS + 0.05:
                    break
            end_index = max(end_index, min(count, start_index + 1))
            ranges.append((start_index, end_index))
            start_index = end_index
        cues = []
        for part, (start_index, end_index) in zip(split_text_at_content_ranges(text, ranges), ranges):
            start = units[start_index].start
            acoustic_end = max(units[end_index - 1].end, start + MIN_SUBTITLE_SECONDS)
            cues.append(SubtitleCue(0, start, min(acoustic_end, start + MAX_SUBTITLE_SECONDS), part))
        print(f"   [硬切兜底] 常规词边界无法满足字幕上限，已保全文字并拆为 {len(cues)} 条。")
        record_run_event("local_hard_split_recovery", cue_count=len(cues), character_count=count)
        return cues

    ranges = []
    index = 0
    while index < count:
        next_index = best_next[index]
        if next_index is None:
            raise ValueError("Qwen 单条本地修复未覆盖完整原文。")
        ranges.append((index, next_index))
        index = next_index

    parts = split_text_at_content_ranges(text, ranges)
    cues = []
    for part, (start_index, end_index) in zip(parts, ranges):
        start = units[start_index].start
        end = max(units[end_index - 1].end, start + MIN_SUBTITLE_SECONDS)
        cues.append(SubtitleCue(0, start, end, part))
    return cues




from twobyteasr.segmentation_alignment import (
    ALIGNMENT_CHINESE_DIGITS,
    _vad_silence_ratio,
    arabic_number_for_alignment,
    boundary_alignment_content,
    boundary_alignment_units,
    firered_pause_character_boundaries,
    firered_pause_character_gaps,
    firered_token_start,
    hard_break_character_offsets,
    individual_cue,
    protected_source_boundary_offsets,
    segment_content_timeline,
    snap_internal_cue_boundaries,
    source_segment_character_offsets,
    text_boundary_hints,
)


from twobyteasr.cue_cleanup import (
    apply_isolated_single_character_rules_safely,
    merge_consecutive_short_repeated_cues,
    merge_isolated_two_character_cues,
    merge_same_speaker_dangling_cues,
    resolve_isolated_single_character_cues,
    validate_editorial_cue_result,
)


from twobyteasr.grouping import (
    call_grouping_api,
    cues_from_resegmented_texts,
    fallback_group,
    group_subtitles as _group_subtitles_impl,
)


def group_subtitles(
    segments,
    firered_tokens=(),
    speech_regions=(),
    protect_all_source_boundaries=False,
    cache_context=None,
    use_ai=True,
    provider_snapshot=None,
    max_workers=None,
):
    """兼容旧入口，并把调用方覆盖的断句依赖同步到新实现模块。"""
    import twobyteasr.grouping as grouping_module

    grouping_module.call_grouping_api = call_grouping_api
    grouping_module.PARALLEL_CLOUD_BATCHES = PARALLEL_CLOUD_BATCHES
    grouping_module.CLOUD_BATCH_WORKERS = CLOUD_BATCH_WORKERS
    grouping_module.GROUP_API_BATCH_MAX_CUES = GROUP_API_BATCH_MAX_CUES
    grouping_module.GROUP_API_BATCH_MAX_CHARS = GROUP_API_BATCH_MAX_CHARS
    return _group_subtitles_impl(
        segments,
        firered_tokens=firered_tokens,
        speech_regions=speech_regions,
        protect_all_source_boundaries=protect_all_source_boundaries,
        cache_context=cache_context,
        use_ai=use_ai,
        provider_snapshot=provider_snapshot,
        max_workers=max_workers,
    )


import subtitle_core as _core
for _name in __all__:
    setattr(_core, _name, globals()[_name])
del _core, _name
