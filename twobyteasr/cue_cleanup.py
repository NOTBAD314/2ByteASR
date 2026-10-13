"""Post-grouping cleanup for dangling, short, and repeated subtitle cues."""

from subtitle_core import *  # noqa: F401,F403
from twobyteasr.segmentation import should_merge_hanging_attribute
from .subtitle_fidelity import independent_response

__all__ = [
    "merge_same_speaker_dangling_cues",
    "merge_isolated_two_character_cues",
    "resolve_isolated_single_character_cues",
    "validate_editorial_cue_result",
    "apply_isolated_single_character_rules_safely",
    "merge_consecutive_short_repeated_cues",
]

def merge_same_speaker_dangling_cues(cues):
    """合回词内孤字、单字回应和明显没说完的短语。"""
    if len(cues) < 2:
        return cues
    by_speaker = {}
    chronological = sorted(cues, key=lambda cue:(cue.start, cue.end, cue.cue_id))
    neighbors = {(id(a), id(b)) for a,b in zip(chronological, chronological[1:])}
    for cue in cues:
        by_speaker.setdefault(cue.speaker or "S00", []).append(cue)

    merged_all = []
    merged_count = 0
    for speaker_cues in by_speaker.values():
        speaker_cues.sort(key=lambda cue: (cue.start, cue.end, cue.cue_id))
        index = 0
        merged = []
        while index < len(speaker_cues):
            current = speaker_cues[index]
            if index + 1 >= len(speaker_cues):
                merged.append(current)
                break
            following = speaker_cues[index + 1]
            left = content_exact(current.text)
            right = content_exact(following.text)
            gap = following.start - current.end
            left_is_dangling = len(left) == 1
            right_is_dangling = len(right) == 1
            left_is_incomplete = any(
                left.endswith(ending)
                for ending in (
                    "还都", "能不能遇", "会玩的", "上我们的", "那我",
                    "就是", "还是", "因为", "所以", "然后", "但是", "如果",
                    "或者", "把", "给", "让", "跟", "和", "与", "从", "向",
                )
            )
            hanging_attr = should_merge_hanging_attribute(current.text, following.text)
            merge_limit = (
                COMPLETE_PHRASE_SOFT_MAX_CHARS
                if hanging_attr
                else MAX_SUBTITLE_CHARS
            )
            can_merge = (
                (id(current), id(following)) in neighbors
                and not independent_response(current.text)
                and not independent_response(following.text)
                and
                gap <= (
                    SINGLE_CHARACTER_MERGE_MAX_GAP_SECONDS
                    if left_is_dangling or right_is_dangling
                    else 1.20
                )
                and gap >= -0.20
                and (
                    left_is_dangling
                    or right_is_dangling
                    or left_is_incomplete
                    or hanging_attr
                )
                and display_length(current.text + following.text) <= merge_limit
            )
            if not can_merge:
                merged.append(current)
                index += 1
                continue
            current.text = clean_subtitle_text(current.text + following.text)
            current.start = min(current.start, following.start)
            current.end = max(current.end, following.end)
            current.timing_locked = current.timing_locked and following.timing_locked
            merged.append(current)
            merged_count += 1
            index += 2
        merged_all.extend(merged)
    if merged_count:
        print(f"   [孤字护栏] 合回 {merged_count} 处同说话人词内孤字。")
    return merged_all


TWO_CHARACTER_ATTACH_RIGHT = frozenset(
    (
        "并且", "而且", "然后", "但是", "不过", "所以", "如果", "因为",
        "还有", "另外", "以及", "或者", "接着", "其实", "那么", "就是",
        "好的", "没错", "对的", "可以", "好吧", "行吧", "等等", "朋友",
    )
)


TWO_CHARACTER_VISUAL_PAUSE = frozenset(
    ("好的", "没错", "对的", "可以", "好吧", "行吧", "等等", "朋友", "有了")
)


# Japanese openers that belong to the clause after them (いや|もはやこれは).
JAPANESE_TWO_CHARACTER_ATTACH_RIGHT = frozenset(
    ("いや", "ねえ", "ねぇ", "まあ", "でも", "ああ", "あの", "ほら", "おい", "さあ", "じゃ", "えっ", "うん", "だが")
)


def _japanese_opens_next(previous, current, following, short_text):
    """Japanese: a two-character opener joins the next clause, not the finished one."""
    from twobyteasr.language_rules import is_japanese, japanese_strong_breaks
    if not is_japanese() or following is None:
        return False
    if short_text in JAPANESE_TWO_CHARACTER_ATTACH_RIGHT:
        return True
    if previous is None:
        return False
    left = len(content_exact(previous.text))
    strong = japanese_strong_breaks(previous.text + current.text + following.text)
    return left in strong and left + 2 not in strong


def merge_isolated_two_character_cues(cues):
    """把孤立两字条安全并入紧邻的同主播字幕，不跨插话或长停顿。"""
    if len(cues) < 2:
        return cues

    rows = sorted(cues, key=lambda cue: (cue.start, cue.end, cue.speaker))
    merged_count = 0
    index = 0

    def can_merge(left, right, max_gap=TWO_CHARACTER_MERGE_MAX_GAP_SECONDS):
        if left is None or right is None:
            return False
        if left.speaker != right.speaker or left.timing_locked or right.timing_locked:
            return False
        gap = right.start - left.end
        return (
            -0.20 <= gap <= max_gap
            and display_length(left.text + right.text)
            <= COMPLETE_PHRASE_SOFT_MAX_CHARS
            and right.end - left.start <= MAX_SUBTITLE_SECONDS + 0.05
        )

    while index < len(rows):
        current = rows[index]
        short_text = content_exact(current.text)
        if len(short_text) != 2 or independent_response(current.text):
            index += 1
            continue

        previous = rows[index - 1] if index > 0 else None
        following = rows[index + 1] if index + 1 < len(rows) else None
        opens_next = short_text in TWO_CHARACTER_ATTACH_RIGHT or _japanese_opens_next(
            previous, current, following, short_text)
        can_attach_left = can_merge(previous, current)
        can_attach_right = can_merge(
            current,
            following,
            max_gap=(
                HARD_GAP_SECONDS
                if opens_next
                else TWO_CHARACTER_MERGE_MAX_GAP_SECONDS
            ),
        )

        # 连词、回答和称呼依附后文；普通两字名词/人名默认收回上一句。
        # 这里只看全局紧邻项，因此不会越过另一位主播的插话。
        attach_right = can_attach_right and (
            opens_next or not can_attach_left
        )
        if attach_right:
            separator = " " if short_text in TWO_CHARACTER_VISUAL_PAUSE else ""
            current.text = clean_subtitle_text(
                f"{current.text}{separator}{following.text}"
            )
            current.start = min(current.start, following.start)
            current.end = max(current.end, following.end)
            current.timing_locked = current.timing_locked and following.timing_locked
            rows.pop(index + 1)
            merged_count += 1
            index += 1
            continue
        if can_attach_left:
            previous.text = clean_subtitle_text(previous.text + current.text)
            previous.start = min(previous.start, current.start)
            previous.end = max(previous.end, current.end)
            previous.timing_locked = previous.timing_locked and current.timing_locked
            rows.pop(index)
            merged_count += 1
            index = max(0, index - 1)
            continue
        index += 1

    rows.sort(key=lambda cue: (cue.start, cue.end, cue.speaker))
    for cue_id, cue in enumerate(rows, 1):
        cue.cue_id = cue_id
    if merged_count:
        print(f"   [两字短条护栏] 安全并入 {merged_count} 条孤立两字字幕。")
    return rows


def resolve_isolated_single_character_cues(cues):
    """先安全并入全局相邻同主播；只显式省略无实义填充词。"""
    # cue_id is the validated source-text order.  Raw timestamps may overlap or
    # briefly reverse inside noisy MOSS chunks, so they must never reorder text here.
    rows = sorted(cues, key=lambda cue: (cue.cue_id, cue.start, cue.end))
    omitted_ids = set()
    merged_ids = set()
    kept_ids = set()
    index = 0
    while index < len(rows):
        current = rows[index]
        if len(content_exact(current.text)) != 1:
            index += 1
            continue
        previous = rows[index - 1] if index > 0 else None
        following = rows[index + 1] if index + 1 < len(rows) else None

        def can_merge(left, right):
            if left is None or right is None:
                return False
            if left.speaker != right.speaker or left.timing_locked or right.timing_locked:
                return False
            gap = right.start - left.end
            return (
                -0.20 <= gap <= SINGLE_CHARACTER_MERGE_MAX_GAP_SECONDS
                and display_length(left.text + right.text) <= MAX_SUBTITLE_CHARS
                and right.end - left.start <= MAX_SUBTITLE_SECONDS + 0.05
            )

        if can_merge(previous, current):
            previous.text = clean_subtitle_text(previous.text + current.text)
            previous.end = max(previous.end, current.end)
            merged_ids.add(current.cue_id)
            rows.pop(index)
            continue
        if can_merge(current, following):
            following.text = clean_subtitle_text(current.text + following.text)
            following.start = min(current.start, following.start)
            merged_ids.add(current.cue_id)
            rows.pop(index)
            continue

        single_text = content_exact(current.text)
        # A short answer/interruption is dialogue evidence, even when its text
        # is also a common filler. Never erase a distinct speaker turn.
        separate_turn = any(neighbor is not None and neighbor.speaker != current.speaker
                            and max(0.0, current.start-neighbor.end, neighbor.start-current.end) <= 1.0
                            for neighbor in (previous, following))
        if separate_turn:
            kept_ids.add(current.cue_id)
            index += 1
            continue
        if single_text not in EDITORIAL_OMITTABLE_SINGLE_CHARACTERS:
            # “有/对/走”等实义孤字宁可单独保留并提示复核，也绝不能为了
            # 版面好看而删字。后续安全回滚还能保证任何意外都不阻断导出。
            kept_ids.add(current.cue_id)
            add_review_item(
                current.start,
                "孤立实义单字",
                "无法安全并入相邻同主播字幕，已原样保留；建议结合原音复核",
                current.text,
                priority=2,
            )
            index += 1
            continue

        # 三十九轮：逐字（verbatim）模式保留「嗯/啊/哦」等孤立语气词——
        # 合规/质检场景要求原话完整，不得为版面省略（风格设置见
        # models.api_transcribe_style；clean 维持原有省略行为）。
        import subtitle_core as _core

        if str(
            getattr(_core, "RUNTIME_SETTINGS", {}).get("models", {}).get(
                "api_transcribe_style", "clean"
            )
        ) == "verbatim":
            kept_ids.add(current.cue_id)
            add_review_item(
                current.start,
                "逐字模式保留语气词",
                "转写风格=verbatim：孤立语气词按原话保留",
                current.text,
                priority=1,
            )
            index += 1
            continue

        omitted_ids.add(current.cue_id)
        add_review_item(
            current.start,
            "成片省略语气词",
            "孤立语气词无法安全并入相邻同主播字幕，按成片规则省略",
            current.text,
            priority=1,
        )
        rows.pop(index)
        continue

    if merged_ids or omitted_ids or kept_ids:
        print(
            f"   [单字成片护栏] 安全并入 {len(merged_ids)} 条，"
            f"明确省略语气词 {len(omitted_ids)} 条，"
            f"原样保留实义孤字 {len(kept_ids)} 条。"
        )
    rows.sort(key=lambda cue: (cue.cue_id, cue.start, cue.end))
    for cue_id, cue in enumerate(rows, 1):
        cue.cue_id = cue_id
    return rows, {
        "omitted_ids": omitted_ids,
        "merged_ids": merged_ids,
        "kept_ids": kept_ids,
    }


def validate_editorial_cue_result(before_cues, after_cues, resolution):
    """验证最终实际写出的每位说话人正文，仅允许已记录的填充词省略。"""
    omitted_ids = set(resolution.get("omitted_ids", ()))
    expected = {}
    actual = {}
    for cue in before_cues:
        if cue.cue_id in omitted_ids:
            continue
        expected.setdefault(cue.speaker or "S00", []).append(cue.text)
    for cue in after_cues:
        actual.setdefault(cue.speaker or "S00", []).append(cue.text)
    expected = {
        speaker: content_only("".join(texts))
        for speaker, texts in expected.items()
    }
    actual = {
        speaker: content_only("".join(texts))
        for speaker, texts in actual.items()
    }
    if expected != actual:
        raise RuntimeError("单字成片处理后出现未记录的漏字、重复或调序，已停止写入。")
    invalid = [
        cue
        for cue in after_cues
        if display_length(cue.text) > COMPLETE_PHRASE_SOFT_MAX_CHARS
        or cue.end - cue.start > MAX_SUBTITLE_SECONDS + 0.05
        or cue.end <= cue.start
    ]
    if invalid:
        sample = "、".join(
            f"{cue.text}({display_length(cue.text)}字/{cue.end - cue.start:.2f}s)"
            for cue in invalid[:6]
        )
        raise RuntimeError(f"最终成片仍有超长或非法字幕，已停止写入：{sample}")
    print(
        f"   [最终写出守恒] 已验证实际成片正文；"
        f"仅省略 {len(omitted_ids)} 条已记录填充词。"
    )
    return after_cues


def apply_isolated_single_character_rules_safely(cues):
    """Apply optional single-character polish transactionally.

    The input has already passed strict text/timing validation.  Therefore any
    unexpected mismatch in this cosmetic pass must roll back to the validated
    input instead of failing the whole media job and withholding all subtitles.
    """
    before = deserialize_cues(serialize_cues(cues))
    try:
        with capture_review_items() as editorial_review_items:
            after, resolution = resolve_isolated_single_character_cues(cues)
            validated = validate_editorial_cue_result(before, after, resolution)
    except Exception as exc:
        timestamp = min((float(cue.start) for cue in before), default=0.0)
        detail = " ".join(str(exc).split()) or exc.__class__.__name__
        add_review_item(
            timestamp,
            "单字护栏回滚",
            "单字合并/省略未通过正文守恒校验，已自动恢复校验前完整字幕；不影响导出",
            detail[:180],
            priority=2,
        )
        record_run_event(
            "editorial_single_character_rollback",
            error=redact_runtime_secrets(detail),
            restored_cues=len(before),
        )
        print(
            "   [单字护栏自愈] 后处理未通过守恒校验，"
            "已恢复校验前完整字幕并继续导出。"
        )
        return before
    extend_review_items(editorial_review_items)
    return validated


def merge_consecutive_short_repeated_cues(cues):
    """把“对的｜对的”这类连读重复收进一条，保留两次原字与完整时间。"""
    by_speaker = {}
    chronological = sorted(cues, key=lambda cue: (cue.start, cue.end, cue.cue_id))
    neighbors = {(id(a), id(b)) for a, b in zip(chronological, chronological[1:])}
    for cue in cues:
        by_speaker.setdefault(cue.speaker or "S00", []).append(cue)
    result = []
    merged_count = 0
    for rows in by_speaker.values():
        rows.sort(key=lambda cue: (cue.start, cue.end, cue.cue_id))
        index = 0
        while index < len(rows):
            current = rows[index]
            if index + 1 < len(rows):
                following = rows[index + 1]
                repeated = content_exact(current.text) == content_exact(following.text)
                short = 1 < display_length(current.text) <= 4
                gap = following.start - current.end
                combined_duration = following.end - current.start
                if (
                    repeated
                    and (id(current), id(following)) in neighbors
                    and not current.timing_locked and not following.timing_locked
                    and short
                    and -0.20 <= gap <= SINGLE_CHARACTER_MERGE_MAX_GAP_SECONDS
                    and display_length(current.text + following.text) <= MAX_SUBTITLE_CHARS
                    and combined_duration <= MAX_SUBTITLE_SECONDS + 0.05
                ):
                    current.text = clean_subtitle_text(
                        f"{current.text} {following.text}"
                    )
                    current.end = max(current.end, following.end)
                    current.timing_locked = (
                        current.timing_locked and following.timing_locked
                    )
                    result.append(current)
                    merged_count += 1
                    index += 2
                    continue
            result.append(current)
            index += 1
    result.sort(key=lambda cue: (cue.start, cue.end, cue.cue_id))
    for cue_id, cue in enumerate(result, 1):
        cue.cue_id = cue_id
    if merged_count:
        print(f"   [重复短句] 合并 {merged_count} 组连读重复，原字次数保持不变。")
    return result




