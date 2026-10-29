"""Local line breaks on fast speech without pauses (2026-10-21, no API key).

Lines from the user's clip, every character evenly timed (no pause to cut
at). The local repair used to cut by length alone: 就凭你还想阻止｜我？,
最终｜决战, 都不｜太一样, 没有｜开拓的地方. The 16-character / 5-second
limits and the original text stay exactly as before.
"""
import pytest


def _even_units(text, step=0.2):
    import subtitle_core as core
    units, cursor = [], 0.0
    for char in core.content_exact(text):
        units.append(core.WordUnit(cursor, cursor + step, char, 1.0))
        cursor += step
    return units


def _repair(text):
    import subtitle_core as core
    cues = core.locally_repair_resegmented_cue(text, _even_units(text),
                                                comfort_max_chars=core.FALLBACK_COMFORT_MAX_CHARS)
    for cue in cues:
        assert core.display_length(cue.text) <= core.COMPLETE_PHRASE_SOFT_MAX_CHARS
        assert cue.end - cue.start <= core.MAX_SUBTITLE_SECONDS + 0.05
    assert "".join(cue.text for cue in cues) == text
    return [cue.text for cue in cues]


def test_a_question_keeps_its_last_word():
    lines = _repair("废铁的绝灭大剑怎么还有拳击擂台啊？就凭你还想阻止我？右边是翁法罗斯的神")
    assert "就凭你还想阻止我？" in lines
    assert not any(line.startswith("我？") for line in lines)


def test_adverbs_and_pronouns_stay_with_what_follows():
    lines = _repair("我觉得崩铁假药写的还是太保守了真的你知道我为了帮你炸毁列车付出了多少代价吗？")
    assert not any(line.endswith(("太", "为了", "多少", "你")) for line in lines), lines
    assert not any(line.startswith("代价吗") for line in lines)


@pytest.mark.parametrize("text, together", [
    ("关乎宇宙命运的最终决战即将上演", "最终决战"),
    ("这个每一次的划分都不太一样每一次都给人惊喜", "都不太一样"),
    ("妖身我们走吧去一个没有开拓的地方我想看你再笑一次对不起但我不想后悔我们三个可以重新来过", "重新来过"),
])
def test_phrases_are_not_cut_by_length_alone(text, together):
    lines = _repair(text)
    assert any(together in line for line in lines), lines
    assert not any(line.endswith(("不", "都", "没有", "再", "重新")) for line in lines), lines


def test_cut_costs_prefer_sentence_ends_and_avoid_tails():
    from twobyteasr.subtitle_rules.line_break_cohesion import line_break_cut_costs
    costs = line_break_cut_costs("就凭你还想阻止我？右边是")
    assert costs[7] >= 60  # 阻止｜我？
    assert costs[8] < 0    # 我？｜右边
    assert line_break_cut_costs("乘客们可以")[2] >= 40  # 乘客｜们


def test_japanese_tasks_keep_their_own_rules():
    from twobyteasr.recognition.run_context import get_runtime_context
    from twobyteasr.subtitle_rules.line_break_cohesion import line_break_cut_costs
    context = get_runtime_context()
    previous = context.task_language
    context.task_language = "ja"
    try:
        assert line_break_cut_costs("本当に止めるの？") == {}
    finally:
        context.task_language = previous


def test_no_key_local_grouping_without_word_times():
    import subtitle_core as core
    from twobyteasr.subtitle_rules import grouping
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    text = "拳击擂台啊？就凭你还想阻止我？右边是翁法罗斯的神黄金翼对手是我们"
    row = core.SpeechSegment(1, 0.0, 6.4, text, 0.8, [], speaker="S01")
    with activate_runtime_context(RuntimeContext(), legacy=core):
        cues = grouping.group_subtitles([row], use_ai=False, max_workers=1)
    lines = [cue.text for cue in cues]
    assert "".join(lines) == text
    assert "就凭你还想阻止我？" in lines
    assert all(core.display_length(line) <= core.FALLBACK_COMFORT_MAX_CHARS for line in lines)
