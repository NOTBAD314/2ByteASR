"""Shared subtitle text normalization, numeral, and editorial safety rules."""

import os
import re
from collections import Counter
from difflib import SequenceMatcher

from subtitle_core import *  # noqa: F401,F403
from twobyteasr.runtime import get_runtime_context
from twobyteasr.text_similarity import phonetic_text

__all__ = [
    'clean_subtitle_text',
    'format_subtitle_display_text',
    'CHINESE_NUMBER_DIGITS',
    'CHINESE_NUMBER_UNITS',
    'NUMBER_CONTEXT_SUFFIXES',
    'OUTPUT_ARABIC_NUMBER_SUFFIXES',
    'OUTPUT_ARABIC_STANDALONE_VALUES',
    'OUTPUT_ARABIC_LARGE_NUMBER_MIN_VALUE',
    'CORRECTION_PROTECTED_QUANTITY_UNITS',
    'BOUNDARY_COHESION_TERMS',
    'BOUNDARY_MOVE_BEFORE_TERMS',
    'simplify_chinese',
    'chinese_numeral_value',
    'format_arabic_quantity',
    'normalize_chinese_numbers',
    'numeral_token_keys',
    'unwanted_arabic_format_values',
    'introduces_unverified_numeral',
    'quantity_expression_keys',
    'asr_candidate_support_count',
    'contextual_quantity_change_is_supported',
    'excessive_repetition_patterns',
    'EXCESSIVE_REPETITION_PATTERNS',
    'has_excessive_adjacent_repetitions',
    'collapse_excessive_adjacent_repetitions',
    'normalize_output_text',
    'OVERLAPPING_DUPLICATE_MIN_CHARS',
    'OVERLAPPING_DUPLICATE_MIN_RATIO',
    'OVERLAPPING_DUPLICATE_EDGE_SECONDS',
    'OVERLAPPING_DUPLICATE_FUZZY_EDGE_SIMILARITY',
    'remove_overlapping_duplicate_segments',
    'apply_editorial_segment_rules',
    'content_only',
    'content_exact',
    'display_length',
    'balanced_partition_word_run',
]

def clean_subtitle_text(text):
    """保留问号、叹号、数字分隔符和省略号，去掉普通句读。"""
    from twobyteasr.language_rules import is_english
    if is_english():
        # 2026-10-14: English keeps commas, periods, apostrophes (don't) and one
        # space between words; the Chinese rules below would strip them.
        from twobyteasr.english_text import clean as english_clean
        return english_clean(str(text).replace("\r", " ").replace("\n", " "))
    forbidden = """《》〈〉【】[]（）(){}“”‘’\"`·・•、，。；：:;,—~～"""
    text = str(text).replace("\r", " ").replace("\n", " ")
    # Deleting a comma between spoken numbers concatenated independent events
    # before the Chinese parser (二十，二十 -> 二十二十 -> 40).
    text = re.sub(r'(?<=[零〇一二两三四五六七八九十百千万亿0-9])[，,、](?=[零〇一二两三四五六七八九十百千万亿0-9])', '\ue000', text)
    # A ratio separator belongs to the numerical expression. Removing it
    # before number formatting turns 二:三 into the ambiguous event 二三.
    text = re.sub(r'(?<=[零〇一二两三四五六七八九十百千万亿0-9])[:：](?=[零〇一二两三四五六七八九十百千万亿0-9])', '\ue001', text)
    text = text.translate(str.maketrans("", "", forbidden))
    text = text.replace('\ue000', '，')
    text = text.replace('\ue001', ':')
    text = text.replace("……", "...").replace("…", "...")
    text = re.sub(r"\.{4,}", "...", text)
    text = re.sub(r"(?<![A-Za-z0-9.])\.(?!\.)", "", text)
    text = re.sub(r"(?<!\.)\.(?![A-Za-z0-9.])", "", text)
    text = re.sub(r"(?<![A-Za-z0-9])['-]|['-](?![A-Za-z0-9])", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def format_subtitle_display_text(text):
    """只做成片可读性排版；空格不参与逐字校验和时间对齐。"""
    text = clean_subtitle_text(text)
    match = re.match(r"^好\s*来(?!\s*了)\s*", text)
    if match:
        remainder = text[match.end() :].strip()
        text = "好 来" + (f" {remainder}" if remainder else "")
    else:
        match = re.match(r"^这\s*嗯\s*", text)
        if match:
            remainder = text[match.end() :].strip()
            text = "这 嗯" + (f" {remainder}" if remainder else "")
        else:
            match = re.match(
                r"^(哦哟|哦呦|哎呀|对呀|好的好的|对对对|嗯+|啊+|哦+(?!耶|哟|呦)|哎+|哇+|诶+|唉+|OK啊|OK)",
                text,
                flags=re.IGNORECASE,
            )
            if match and match.end() < len(text):
                text = f"{match.group(0)} {text[match.end():].lstrip()}"

    # 长口语里常见的连续反应词也留一个视觉气口；不改字、不改时间。
    for source, target in (
        ("哦对", "哦 对"),
        ("哦没事", "哦 没事"),
        ("啊其实", "啊 其实"),
        ("啊不要", "啊 不要"),
        ("对我靠", "对 我靠"),
        ("我靠那", "我靠 那"),
    ):
        text = text.replace(source, target)
    # 口语填充词在正文中间也需要视觉气口；这里只插入空格，不参与文字校验。
    text = re.sub(
        r"(?<=[\u3400-\u9fffA-Za-z0-9])(?=(?:嗯+|哎呀|哎(?!呀)|哦(?!耶|哟|呦)|诶|唉|我靠)(?=[\u3400-\u9fffA-Za-z0-9]))",
        " ",
        text,
    )
    text = re.sub(
        r"(?P<filler>嗯+|哎呀|哎(?!呀)|哦(?!耶|哟|呦)|诶|唉|我靠)(?=[\u3400-\u9fffA-Za-z0-9])",
        r"\g<filler> ",
        text,
    )
    text = re.sub(
        r"([啊呀呢吧嘛])(?=(?:这|那|但是|不过|所以|然后|其实|我|你|他|我们|你们|他们|飞飞钥|夜枭|地武队|嗜波螺|草鹿|风隐))",
        r"\1 ",
        text,
    )
    # 被收敛到两次的连续反应词与后文之间留一个空格，方便观众一眼读出节奏。
    for repeated_unit in (
        "怎么办", "遁地吧", "不会", "不至于", "确定", "斩断", "颅主", "没事",
    ):
        text = re.sub(
            rf"({re.escape(repeated_unit)})\1(?=[\u3400-\u9fffA-Za-z0-9])",
            r"\1\1 ",
            text,
        )
    # 句尾补充反应需要与前一句留气口；但“哦耶”“OK啊”本身是完整反应词，
    # 不能被通用“哦/OK”规则从中间拆开。
    text = re.sub(r"(?<=没事)(?=哎(?:$|\s))", " ", text)
    text = re.sub(r"(我靠\s+那)(?=他这个|他|你|我们|这个)", r"\1 ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


CHINESE_NUMBER_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


CHINESE_NUMBER_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}


NUMBER_CONTEXT_SUFFIXES = set(
    "个命抽层次只套发点星年月日号局分秒块元岁级张把轮种位件台条枚颗份瓶杯米段"
)


# Compatibility constants; the shared conservative policy owns formatting.
OUTPUT_ARABIC_NUMBER_SUFFIXES = frozenset(("命", "抽", "元", "块"))


OUTPUT_ARABIC_STANDALONE_VALUES = frozenset(("648",))


OUTPUT_ARABIC_LARGE_NUMBER_MIN_VALUE = 10


# 校对阶段重点保护容易被同音字破坏的游戏数量；“一段话”等普通结构不锁死。
CORRECTION_PROTECTED_QUANTITY_UNITS = set("个命抽层发星级")


# 这里只保护断句边界，不替换文字，也不会像术语表一样把近音词强行改写。
BOUNDARY_COHESION_TERMS = frozenset(
    (
        "首领化队",
        "愿力冲击",
        "彩虹独角兽",
        "画间沉铁兽",
        "高温回火",
        "持续高温",
        "我们这里",
        "我们能听到",
        "我们直接",
        "我们打一发",
        "你能想到我们能听到",
        "不不我们打一发",
        "上我们的飞飞药",
        "飞飞药锁一下地刺",
        "他女朋友",
        "炮米花",
        "挂速冻",
        "水泡盾",
        "水灵呢",
        # 常见完整词也必须保护。全文断句 API 临时失败并退回本地均衡切分时，
        # 不能再出现“商|城”“所|有”“到|时候”这种词内断句。
        "商城",
        "所有",
        "到时候",
        "时候",
        "事件",
        "事情",
        "案发",
        "为什么",
        "里边",
        "衣服",
        "折现",
        "演出费",
        "辛苦费",
        "奖金",
        "水友",
        "而且",
        "这里",
        "抽枝",
        "闪燃",
        "倾泻",
        "速冻",
        "迪莫",
        "吓退",
        "飞飞药",
        "或者",
        "直接",
        "一个",
        "这个",
        "那个",
        "只有",
        "但是",
        "因为",
        "所以",
        "如果",
        "然后",
        "还是",
        "其实",
        "感觉",
        "可能",
        "已经",
        "全部",
        "唯一",
        "准备",
        "进行",
        "问题",
        "能不能",
        "对不对",
        "不要紧",
        "没关系",
        "对面",
        "我们",
        "他们",
        "没有",
        "不会",
        "不要",
        "可以",
        "时候",
        "知道",
        "继续",
        "一下",
        "一点",
        "一一点",
        "卡池",
        "抽卡",
        "保底",
        "连金",
        "双黄",
        "角色",
        "武器",
        "技能",
        "剧情",
        "主线",
        "支线",
        "任务",
        "活动",
        "玩家",
        "游戏",
        "副本",
        "地图",
        "银狼",
        "希儿",
        "姬子",
        "异常",
        "非常",
        "遇到",
        "都是",
        "你能想到我们能听到",
        "上我们的飞飞钥",
        "飞飞钥锁一下地刺",
        "血量",
        "能量",
        "状态",
        "后排",
        "水灵",
        "教练",
        "先发",
        "应该应该",
        "回个能",
    )
)


# 这类副词若被切开，边界移到词前更自然；“卡池”等名词仍移到词后。
BOUNDARY_MOVE_BEFORE_TERMS = frozenset(
    (
        "异常", "非常", "或者", "但是", "因为", "所以", "如果", "然后", "而且",
        "我们这里", "你能想到我们能听到", "不不我们打一发",
        "直接", "还是", "其实", "可能", "已经", "准备",
        "应该应该",
    )
)


_SIMPLIFIED_CHINESE_API = None


def simplify_chinese(text):
    """使用 Windows 自带映射统一为简体，不依赖词典或第三方替换权重。"""
    source = str(text or "")
    if not source or os.name != "nt":
        return source

    global _SIMPLIFIED_CHINESE_API
    try:
        if _SIMPLIFIED_CHINESE_API is None:
            import ctypes
            from ctypes import wintypes

            mapper = ctypes.windll.kernel32.LCMapStringEx
            mapper.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.LPCWSTR,
                ctypes.c_int,
                wintypes.LPWSTR,
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            mapper.restype = ctypes.c_int
            _SIMPLIFIED_CHINESE_API = (ctypes, mapper)

        ctypes, mapper = _SIMPLIFIED_CHINESE_API
        required = mapper(
            "zh-CN",
            0x02000000,
            source,
            len(source),
            None,
            0,
            None,
            None,
            None,
        )
        if required <= 0:
            return source
        buffer = ctypes.create_unicode_buffer(required)
        written = mapper(
            "zh-CN",
            0x02000000,
            source,
            len(source),
            buffer,
            required,
            None,
            None,
            None,
        )
        return buffer.value if written > 0 else source
    except Exception:
        return source


def chinese_numeral_value(token):
    """转换明确的中文数词；不负责判断“一起/一切”等词汇语境。"""
    if not token:
        return None
    from .number_fidelity import integer_value
    return integer_value(token)


def format_arabic_quantity(value_text, source_token=""):
    """Compatibility helper using the conservative ordinary-integer threshold."""
    try:
        value = int(str(value_text))
    except (TypeError, ValueError):
        return str(value_text)
    if 0 <= value < OUTPUT_ARABIC_LARGE_NUMBER_MIN_VALUE and source_token:
        return str(source_token)
    return str(value)


def _arabic_integer_to_chinese(value):
    """Convert a non-negative integer to ordinary simplified Chinese numerals."""
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return str(value)
    if number == 0:
        return "零"
    if number < 0 or number >= 10**12:
        return str(value)

    digits = "零一二三四五六七八九"
    small_units = ("", "十", "百", "千")
    large_units = ("", "万", "亿")

    def section_text(section):
        result = ""
        pending_zero = False
        for position in range(3, -1, -1):
            divisor = 10**position
            digit, section = divmod(section, divisor)
            if digit:
                if pending_zero and result:
                    result += "零"
                result += digits[digit] + small_units[position]
                pending_zero = False
            elif result and section:
                pending_zero = True
        return result

    sections = []
    while number:
        sections.append(number % 10000)
        number //= 10000
    result = ""
    need_zero = False
    for index in range(len(sections) - 1, -1, -1):
        section = sections[index]
        if not section:
            if result:
                need_zero = True
            continue
        if result and (need_zero or section < 1000):
            result += "零"
        result += section_text(section) + large_units[index]
        need_zero = False
    if result.startswith("一十"):
        result = result[1:]
    return result


def normalize_numeric_style(text):
    """Compatibility entry; never apply the retired aggressive UI-stat rules."""
    return normalize_chinese_numbers(text)


def normalize_chinese_numbers(text, *, protected_terms=()):
    """Use the same small-integer, exception and approximate policy as production."""
    from .number_fidelity import format_numbers
    return format_numbers(text, protected_terms=protected_terms)[0]


def numeral_token_keys(text):
    """把中英文数词统一成比较键，避免单套 ASR 串句制造假数字。"""
    result = set()
    pattern = re.compile(r"\d+|[零〇一二两三四五六七八九十百千万亿]+")
    for match in pattern.finditer(str(text or "")):
        token = match.group(0)
        if token.isdigit():
            result.add(token.lstrip("0") or "0")
            continue
        value = chinese_numeral_value(token)
        if value is not None:
            result.add(value.lstrip("0") or "0")
    return result


def unwanted_arabic_format_values(source, target):
    """找出仅因格式化而新增、但按最终显示规则不应转成阿拉伯数字的数值。"""
    source_digits = set(re.findall(r"\d+", str(source or "")))
    target_digits = set(re.findall(r"\d+", str(target or "")))
    introduced = target_digits - source_digits
    if not introduced:
        return set()
    source_values = numeral_token_keys(source)
    preferred_digits = set(
        re.findall(r"\d+", normalize_chinese_numbers(str(source or "")))
    )
    return (introduced & source_values) - preferred_digits


def introduces_unverified_numeral(source, target, alternates):
    """新数字必须至少得到两套 ASR 独立支持；已有数字的格式转换不受影响。"""
    introduced = numeral_token_keys(target) - numeral_token_keys(source)
    if not introduced:
        return set()
    supports = [numeral_token_keys(value) for value in (alternates or [])]
    return {
        value
        for value in introduced
        if sum(value in support for support in supports) < 2
    }


def quantity_expression_keys(text, units=None):
    """提取“30抽/六命/1个”等完整数量，数字和值统一后再比较。"""
    suffixes = re.escape("".join(sorted(units or NUMBER_CONTEXT_SUFFIXES)))
    pattern = re.compile(
        rf"(?P<number>\d+|[零〇一二两三四五六七八九十百千万亿]+)"
        rf"(?P<unit>[{suffixes}])"
    )
    result = set()
    for match in pattern.finditer(str(text or "")):
        number = match.group("number")
        if number.isdigit():
            value = number.lstrip("0") or "0"
        else:
            value = chinese_numeral_value(number)
        if value is not None:
            result.add((value.lstrip("0") or "0", match.group("unit")))
    return result


def asr_candidate_support_count(candidate, alternates, threshold=0.78):
    """统计与完整候选句在文字或读音上高度接近的独立 ASR。"""
    candidate_content = content_only(candidate)
    candidate_sound = phonetic_text(candidate_content)
    if not candidate_content:
        return 0
    supported = 0
    for alternate in alternates or []:
        alternate_content = content_only(alternate)
        if not alternate_content:
            continue
        text_score = SequenceMatcher(
            None,
            candidate_content,
            alternate_content,
            autojunk=False,
        ).ratio()
        sound_score = SequenceMatcher(
            None,
            candidate_sound,
            phonetic_text(alternate_content),
            autojunk=False,
        ).ratio()
        if max(text_score, sound_score) >= threshold:
            supported += 1
    return supported


def contextual_quantity_change_is_supported(original, candidate, alternates):
    """原句已经是数量表达时，允许一套写对、另一套读音接近的补数修正。"""
    if not numeral_token_keys(original):
        return False
    original_quantities = quantity_expression_keys(original)
    candidate_quantities = quantity_expression_keys(candidate)
    if not candidate_quantities or candidate_quantities == original_quantities:
        return False
    exact_quantity_support = sum(
        bool(candidate_quantities & quantity_expression_keys(value))
        for value in (alternates or [])
    )
    return (
        exact_quantity_support >= 1
        and asr_candidate_support_count(candidate, alternates) >= 2
    )


def excessive_repetition_patterns():
    # 故意不含数字：否则 3000000 / 670000 里的连续 0 会被当成口吃压成 300 / 6700。
    return tuple(
        re.compile(
            rf"(?P<unit>[\u3400-\u9fffA-Za-z]{{{unit_length}}})"
            rf"(?:[?!！？.]*\s*(?P=unit)){{2,}}"
        )
        for unit_length in range(6, 0, -1)
    )


EXCESSIVE_REPETITION_PATTERNS = excessive_repetition_patterns()


def has_excessive_adjacent_repetitions(text):
    return any(pattern.search(str(text or "")) for pattern in EXCESSIVE_REPETITION_PATTERNS)


def collapse_excessive_adjacent_repetitions(text):
    """三次及以上的相邻口吃只保留两次；不压缩纯数字串。"""
    result = str(text or "")

    def _collapse(match):
        unit = match.group("unit")
        if unit.isdigit():
            return match.group(0)
        return unit * 2

    for pattern in EXCESSIVE_REPETITION_PATTERNS:
        result = pattern.sub(_collapse, result)
    return result


def normalize_output_text(text):
    """执行文字清理；数字拼写只交给共用且可关闭的显式阶段。"""
    from twobyteasr.language_rules import is_english, is_japanese
    if is_japanese() or is_english():
        # Japanese kanji are not traditional Chinese; Chinese fillers, phrase
        # fixes and Chinese canonical spellings never rewrite Japanese or English text.
        return clean_subtitle_text(text)
    text = simplify_chinese(clean_subtitle_text(text)).replace("呃", "")
    # “上舰”是直播会员语境中的固定动作。仅修正带倒计时的完整短语，
    # 不对普通“剑/线”做全局同音替换。
    text = text.replace("十秒内不上剑", "十秒内不上舰")
    text = text.replace("十秒内不上线", "十秒内不上舰")
    for phrase in SUBTITLE_SUPPRESSED_PHRASES:
        text = text.replace(phrase, "")
    text = apply_active_canonical_replacements(text)
    return clean_subtitle_text(text)


OVERLAPPING_DUPLICATE_MIN_CHARS = 4
OVERLAPPING_DUPLICATE_MIN_RATIO = 0.80
OVERLAPPING_DUPLICATE_EDGE_SECONDS = 0.35
OVERLAPPING_DUPLICATE_FUZZY_EDGE_SIMILARITY = 0.88


def remove_overlapping_duplicate_segments(segments):
    """删除 MOSS 同一声学片段产生的整段包含副本，保留正常口语重复。"""
    if len(segments) < 2:
        return segments
    by_speaker = {}
    for segment in segments:
        by_speaker.setdefault(segment.speaker or "S00", []).append(segment)

    dropped_ids = set()
    for speaker_segments in by_speaker.values():
        speaker_segments.sort(
            key=lambda segment: (segment.start, segment.end, segment.segment_id)
        )
        for index, left in enumerate(speaker_segments):
            if left.segment_id in dropped_ids:
                continue
            for right in speaker_segments[index + 1 :]:
                if right.start > left.end + 0.05:
                    break
                if right.segment_id in dropped_ids:
                    continue
                if left.timing_locked or right.timing_locked:
                    continue
                # Time overlap is necessary but not enough: independent ASR
                # sources must remain evidence, not be mistaken for a chunk copy.
                if not left.primary_source or left.primary_source != right.primary_source:
                    continue
                left_text = content_only(left.text)
                right_text = content_only(right.text)
                if min(len(left_text), len(right_text)) < OVERLAPPING_DUPLICATE_MIN_CHARS:
                    continue
                if len(left_text) < len(right_text):
                    shorter, longer = left, right
                    shorter_text, longer_text = left_text, right_text
                else:
                    shorter, longer = right, left
                    shorter_text, longer_text = right_text, left_text

                overlap = max(
                    0.0,
                    min(left.end, right.end) - max(left.start, right.start),
                )
                shorter_duration = max(0.001, shorter.end - shorter.start)
                overlap_ratio = overlap / shorter_duration
                same_leading_edge = (
                    longer_text.startswith(shorter_text)
                    and abs(shorter.start - longer.start)
                    <= OVERLAPPING_DUPLICATE_EDGE_SECONDS
                )
                same_trailing_edge = (
                    longer_text.endswith(shorter_text)
                    and abs(shorter.end - longer.end)
                    <= OVERLAPPING_DUPLICATE_EDGE_SECONDS
                )
                if (
                    overlap_ratio < OVERLAPPING_DUPLICATE_MIN_RATIO
                    or not (same_leading_edge or same_trailing_edge)
                ):
                    continue
                dropped_ids.add(shorter.segment_id)
                add_review_item(
                    shorter.start,
                    "MOSS重叠副本去重",
                    (
                        f"同说话人片段重叠 {overlap_ratio:.0%}，短段是长段的"
                        f"完整{'前缀' if same_leading_edge else '后缀'}，删除重复副本"
                    ),
                    shorter.text,
                    priority=1,
                )
                if shorter is left:
                    break

    if not dropped_ids:
        return segments
    result = [segment for segment in segments if segment.segment_id not in dropped_ids]
    for segment_id, segment in enumerate(result, 1):
        segment.segment_id = segment_id
    print(
        f"   [MOSS重叠去重] 删除 {len(dropped_ids)} 个高重叠整段副本；"
        "正常的先后口语重复保持不动。"
    )
    record_run_event(
        "moss_overlapping_duplicate_removed",
        count=len(dropped_ids),
    )
    return result


def apply_editorial_segment_rules(segments):
    """即使读取的是旧 Qwen 缓存，也在分轨前执行成片删除与术语统一。"""
    normalized = []
    suppressed_count = 0
    canonical_count = 0
    canonical_applied = Counter()
    collapsed_repeat_count = 0
    dropped_count = 0
    from twobyteasr.language_rules import is_english, is_japanese
    japanese = is_japanese()
    english = is_english()
    for segment in segments:
        original = clean_subtitle_text(segment.text)
        if english:
            # No Chinese suppressed phrases, canonical spellings or numeral formatting.
            segment.text = original
            if not re.search(r"[A-Za-z0-9]", segment.text):
                dropped_count += 1
                continue
            segment.segment_id = len(normalized) + 1
            normalized.append(segment)
            continue
        if japanese:
            # No Chinese stutter collapse (ねえねえ is ordinary Japanese), no
            # Chinese canonical spellings and no Chinese numeral formatting.
            segment.text = normalize_output_text(original)
            if not content_only(segment.text):
                dropped_count += 1
                continue
            segment.segment_id = len(normalized) + 1
            normalized.append(segment)
            continue
        suppressed_count += sum(
            original.count(phrase) for phrase in SUBTITLE_SUPPRESSED_PHRASES
        )
        for source, target in active_canonical_replacements():
            if source == target:
                continue
            count = original.count(source)
            if count:
                canonical_count += count
                canonical_applied[(source, target)] += count
        segment.text = normalize_output_text(original)
        from .number_fidelity import format_segment
        format_segment(segment)
        if not content_only(segment.text):
            dropped_count += 1
            continue
        segment.segment_id = len(normalized) + 1
        normalized.append(segment)
    if suppressed_count or canonical_count or collapsed_repeat_count or dropped_count:
        print(
            "   [成片文字规则] "
            f"删除敏感口头语 {suppressed_count} 处，"
            f"术语统一 {canonical_count} 处，"
            f"三连口吃收敛 {collapsed_repeat_count} 条，"
            f"移除空字幕 {dropped_count} 条。"
        )
    if canonical_applied:
        record_run_event(
            "profile_term_mapping_applied",
            game=get_runtime_context().game_name,
            count=sum(canonical_applied.values()),
            mappings=[
                {"from": source, "to": target, "count": count}
                for (source, target), count in canonical_applied.items()
            ],
        )
    return remove_overlapping_duplicate_segments(normalized)


# Content characters: CJK ideographs, kana (incl. ー and 々, not the ・
# separator) and ASCII letters/digits. Kana never occur in Chinese transcripts,
# so Chinese results are unchanged; without them Japanese text had almost no
# "content" and was mis-measured, mis-aligned and over-merged.
from twobyteasr.language_rules import CONTENT_CHAR_CLASS  # noqa: E402
_CONTENT_RE = re.compile(f"[{CONTENT_CHAR_CLASS}]+")


def content_only(text):
    return "".join(_CONTENT_RE.findall(str(text))).lower()


def content_exact(text):
    """断句验证用：忽略标点和空格，但保留英文大小写。"""
    return "".join(_CONTENT_RE.findall(str(text)))


def display_length(text):
    return len(content_only(text))


# 2026-10-12（识别结果多余空白）：只清理排版残渣，不碰有意义的单个空格。
# 零宽字符从不表达停顿；表情符号序列里的 U+200D 是例外（见下）。
FORMAT_INVISIBLE_CHARACTERS = frozenset("\u200b\u200c\u200d\u2060\ufeff")
# 全角标点自带字距：紧贴在它们旁边的空格只是替换/拼接残留。
_FULLWIDTH_SPACE_BEFORE = "，。！？；：、）」』】》〉"
_FULLWIDTH_SPACE_AFTER = "，。！？；：、（「『【《〈"


def is_format_space(char):
    """Whitespace or an invisible zero-width character (never content)."""
    return char.isspace() or char in FORMAT_INVISIBLE_CHARACTERS


def strip_format_space(text):
    """Strip whitespace/zero-width characters at both edges of one cue text."""
    text = str(text)
    start, end = 0, len(text)
    while start < end and is_format_space(text[start]):
        start += 1
    while end > start and is_format_space(text[end - 1]):
        end -= 1
    return text[start:end]


def _emoji_joiner(text, index):
    import unicodedata
    if not 0 < index < len(text) - 1:
        return False
    before, after = text[index - 1], text[index + 1]
    return (unicodedata.category(before) in ("So", "Sk", "Mn")
            and unicodedata.category(after) == "So")


def normalize_format_whitespace(text):
    """Remove format-only whitespace junk from one cue; keep meaningful spaces.

    Removed: zero-width characters (U+200B/U+200C/U+200D/U+2060/U+FEFF; an
    emoji ZWJ sequence keeps its joiner), leading/trailing whitespace of each
    line (half-width, U+3000, NBSP, tabs), a space touching full-width
    punctuation (replacement/merge residue), and every other horizontal
    whitespace run collapses to one U+0020.  Kept: each single inner space —
    the product's CJK pause spacing ("对 对 很不错啊 嗯"), English word spaces,
    and user-normalized terms or number formats containing one space.  Line
    breaks are user typesetting and stay.  Idempotent.
    """
    text = str(text if text is not None else "")
    if not text:
        return text
    if any(char in FORMAT_INVISIBLE_CHARACTERS for char in text):
        text = "".join(char for index, char in enumerate(text)
                       if char not in FORMAT_INVISIBLE_CHARACTERS
                       or (char == "\u200d" and _emoji_joiner(text, index)))
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = strip_format_space(line)
        line = re.sub(r"[^\S\n]+", " ", line)
        line = re.sub(rf" (?=[{_FULLWIDTH_SPACE_BEFORE}])", "", line)
        line = re.sub(rf"(?<=[{_FULLWIDTH_SPACE_AFTER}]) ", "", line)
        lines.append(line)
    return "\n".join(lines).strip("\n")


def balanced_partition_word_run(units):
    """用全局分割代替从左到右贪心，优先产生均衡的 6-12 字短字幕。"""
    if not units:
        return []

    count = len(units)
    best_cost = [float("inf")] * (count + 1)
    best_next = [None] * (count + 1)
    best_cost[count] = 0.0

    for start_index in range(count - 1, -1, -1):
        for end_index in range(start_index + 1, count + 1):
            group = units[start_index:end_index]
            length = display_length("".join(item.text for item in group))
            duration = group[-1].end - group[0].start
            single_unsplittable = end_index == start_index + 1
            if (
                not single_unsplittable
                and (
                    length > MAX_RAW_SEGMENT_CHARS
                    or duration > MAX_SUBTITLE_SECONDS
                )
            ):
                break

            cost = 12.0 + 0.25 * (length - TARGET_RAW_SEGMENT_CHARS) ** 2
            if length < MIN_BALANCED_SEGMENT_CHARS:
                cost += 18.0 * (MIN_BALANCED_SEGMENT_CHARS - length) ** 2
            if length > MAX_SUBTITLE_CHARS:
                # 16-17 字可先交给 Qwen 按语义重切，不在校对前过度碎片化。
                cost += 0.5 * (length - MAX_SUBTITLE_CHARS) ** 2
            if duration > 3.7:
                cost += 18.0 * (duration - 3.7) ** 2

            if end_index < count:
                gap = max(0.0, units[end_index].start - group[-1].end)
                cost -= min(8.0, gap * 12.0)
                if re.search(r"[，。；：！？!?;:]\s*$", group[-1].text):
                    cost -= 7.0

            total = cost + best_cost[end_index]
            if total < best_cost[start_index]:
                best_cost[start_index] = total
                best_next[start_index] = end_index

    groups = []
    index = 0
    while index < count:
        next_index = best_next[index] or (index + 1)
        groups.append(units[index:next_index])
        index = next_index
    return groups



import subtitle_core as _core
for _name in __all__:
    setattr(_core, _name, globals()[_name])
del _core, _name
