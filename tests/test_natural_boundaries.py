from subtitle_core import (
    SpeechSegment,
    content_exact,
    repair_compact_utterance_boundary_offsets,
    repair_dependent_prefix_boundary_offsets,
    repair_incomplete_boundary_offsets,
    repair_segmenter_word_boundary_offsets,
    texts_from_boundary_offsets,
)


def _segment(text, duration=3.0):
    return SpeechSegment(1, 0.0, duration, text, 0.9, [], speaker="S01")


def _parts(text, offsets):
    return texts_from_boundary_offsets([_segment(text)], offsets)


def test_complete_date_and_welcome_line_are_not_split():
    date = "今天是2026年7月29日"
    date_offsets = [content_exact(date).index("年"), len(content_exact(date))]
    assert repair_compact_utterance_boundary_offsets([_segment(date)], date_offsets) == [
        len(content_exact(date))
    ]

    welcome = "欢迎收看鹰角嘉年华的特别报道"
    welcome_offsets = [content_exact(welcome).index("嘉"), len(content_exact(welcome))]
    assert repair_compact_utterance_boundary_offsets(
        [_segment(welcome)], welcome_offsets
    ) == [len(content_exact(welcome))]


def test_storyline_and_theme_phrase_move_to_natural_boundary():
    text = "在众多以国家剧情线为主题的布景中有1块区域相当特殊"
    source = content_exact(text)
    inside_storyline = source.index("线")
    end_of_second = source.index("1")
    offsets = repair_segmenter_word_boundary_offsets(
        [_segment(text)],
        [inside_storyline, end_of_second, len(source)],
    )
    offsets = repair_dependent_prefix_boundary_offsets([_segment(text)], offsets)
    assert _parts(text, offsets) == [
        "在众多以国家剧情线为主题的",
        "布景中有1块区域相当特殊",
    ]


def test_modal_and_locative_fragments_attach_to_the_right_phrase():
    modal = "最后胜利的源石虫会为押对宝的博士们"
    source = content_exact(modal)
    offsets = [source.index("为"), len(source)]
    fixed = repair_dependent_prefix_boundary_offsets([_segment(modal)], offsets)
    assert _parts(modal, fixed) == ["最后胜利的源石虫", "会为押对宝的博士们"]

    locative = "拉特兰地下冰冷神秘的文明造物"
    source = content_exact(locative)
    offsets = [source.index("地"), len(source)]
    fixed = repair_dependent_prefix_boundary_offsets([_segment(locative)], offsets)
    assert _parts(locative, fixed) == ["拉特兰地下", "冰冷神秘的文明造物"]


def test_bude_bu_moves_with_its_predicate():
    text = "编年史确实是不得不品的一环啊"
    source = content_exact(text)
    offsets = [source.index("品"), len(source)]
    fixed = repair_incomplete_boundary_offsets([_segment(text)], offsets)
    assert _parts(text, fixed) == ["编年史确实是", "不得不品的一环啊"]
