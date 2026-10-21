"""Stammer cleanup and ordinary-word guards (2026-10-10, user report).

Cases come from user project 0852f218 and the user's own examples.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from twobyteasr.subtitle_rules.stutter_cleanup import (find_repeats, ordinary_reduplication, ordinary_word_in_context,  # noqa: E402
                                        plausible_name_span)


def cleaned(text, **kwargs):
    for finding in sorted(find_repeats(text, **kwargs), key=lambda f: f.delete_span[0], reverse=True):
        if finding.default_selected:
            a, b = finding.delete_span
            text = text[:a] + text[b:]
    return text


def test_user_examples_of_clear_stammers_are_cleaned():
    assert cleaned("再再强调一遍") == "再强调一遍"
    assert cleaned("这这次就学学聪明了") == "这次就学聪明了"
    assert cleaned("叠叠出两层龙威就好了") == "叠出两层龙威就好了"
    assert cleaned("那个没没没有那么多") == "那个没有那么多"
    assert cleaned("对这个这个印记") == "对这个印记"
    assert cleaned("我，我觉得可以") == "我觉得可以"


def test_ordinary_words_emphasis_numbers_and_names_are_kept():
    for text in ("刚刚的水灵是黑白的", "谢谢大家", "看看这个", "我们来学学人家", "20 20", "二十二十",
                 "对对对", "好好好", "冲冲冲", "等一下等一下我", "算了算了", "古龙叔叔看", "莎莎来了"):
        assert cleaned(text) == text, text
    # Glossary spellings are never shortened, even when doubled.
    assert find_repeats("荣光悠悠打不死", protected_terms=["悠悠"]) == []
    assert find_repeats("影袭影袭", protected_terms=["影袭"]) == []


def test_unclear_repeats_ask_instead_of_deleting():
    [finding] = find_repeats("然后古龙首发继续继续攻势开局")
    assert finding.kind == "ambiguous" and not finding.default_selected
    [finding] = find_repeats("不要保保一下")
    assert finding.kind == "ambiguous" and not finding.default_selected


def test_repeat_nobody_heard_or_with_overlapping_times_is_a_data_issue():
    # Both copies at the same time: a merge duplicate, not a second utterance.
    times = [(0, 100), (100, 200), (150, 260), (260, 360), (360, 460)]
    [finding] = find_repeats("这个这个好", char_times=times)
    assert finding.kind == "merge_suspect" and not finding.default_selected
    [finding] = find_repeats("他他贮藏", spoken_texts=["他贮藏我们", "他驻藏"])
    assert finding.kind == "merge_suspect" and not finding.default_selected
    # Distinct spoken copies keep the stammer decision and say why.
    [finding] = find_repeats("他他贮藏", char_times=[(0, 90), (90, 180), (200, 300), (300, 400)],
                             spoken_texts=["波他他贮藏我"])
    assert finding.kind == "stutter" and finding.default_selected
    assert "1/1" in finding.evidence and "字级时间" in finding.evidence


def test_hesitation_between_copies_marks_a_restart():
    [finding] = find_repeats("就是火火狗是用来", spoken_texts=["就是火呃火狗是用来针对"])
    assert finding.kind == "stutter" and finding.delete_span == (2, 3)


def test_common_words_are_not_name_signals_or_near_sound_targets():
    text = "这这次就学学聪明了影袭影袭"
    assert ordinary_word_in_context(text, 6, 8)        # 聪明 reads naturally here
    assert not plausible_name_span(text, 6, 8)
    assert ordinary_reduplication("对刚刚的水灵", 1, 3)   # 刚刚
    assert ordinary_reduplication("再再强调", 0, 2)       # stammer, not a name
    assert not ordinary_reduplication("球球来了", 0, 2)   # doubled nickname stays a signal
    assert not plausible_name_span("嗯 继续继续有话题他处理不了", 9, 11)  # 题他 cuts through 话题
    assert not plausible_name_span("哦 又是盾", 0, 4)       # particles only
    assert plausible_name_span("嗯 然后古龙首发", 4, 6)


def test_deleting_a_stammer_keeps_the_fluent_copy_timing():
    from twobyteasr.recognition.transcript_data import WordUnit
    from twobyteasr.glossary.terminology import deletion_embedding, remap_words
    words = [WordUnit(a, b, text, .9) for a, b, text in ((.0, .1, "这"), (.3, .4, "这"), (.4, .5, "次"),
             (.5, .6, "就"), (.6, .7, "学"), (.9, 1.0, "学"), (1.0, 1.2, "聪明"))]
    assert deletion_embedding("这这次就学学聪明", "这次就学聪明") == [1, 2, 3, 5, 6, 7]
    mapped = remap_words("这这次就学学聪明", "这次就学聪明", words, 0, 1.2)
    assert [(w.text, w.start) for w in mapped] == [("这", .3), ("次", .4), ("就", .5), ("学", .9), ("聪明", 1.0)]
    assert deletion_embedding("这次", "这个") is None


def test_stammer_write_back_keeps_exact_word_timing(tmp_path):
    from twobyteasr.recognition.cue_word_alignment import cue_words
    from twobyteasr.timeline.studio_commands import BatchReplaceTextCommand
    from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject
    project = SubtitleProject(media=StudioMedia(path="", duration_ms=2000),
                              cues=[StudioCue("c1", 0, 1000, "再再强调", evidence_refs=["segment:1"])])
    project.asr_evidence = {"segment:1": {"start_ms": 0, "end_ms": 1000, "final_timing_owner": "FireRed",
        "caption_arbitration": {"acoustic_words": [
            {"text": "再", "start_ms": 0, "end_ms": 120}, {"text": "再", "start_ms": 300, "end_ms": 420},
            {"text": "强", "start_ms": 420, "end_ms": 600}, {"text": "调", "start_ms": 600, "end_ms": 800}]}}}
    project.validate()
    before, reason = cue_words(project, project.cues[0])
    assert reason == "exact_token_text" and len(before) == 4
    command = BatchReplaceTextCommand(project, {"c1": "再强调"}, glossary_ids=[])
    command.redo()
    override = project.studio_state["term_word_overrides"]["c1"]
    assert override["alignment_provenance"] == "deletion_only"
    after, reason = cue_words(project, project.cues[0])
    assert reason == "exact_token_text"
    assert [(w.text, w.start_ms, w.end_ms) for w in after] == [("再", 300, 420), ("强", 420, 600), ("调", 600, 800)]
    command.undo()
    assert project.cues[0].text == "再再强调" and len(cue_words(project, project.cues[0])[0]) == 4
    # A real replacement is still not promoted to acoustic timing.
    BatchReplaceTextCommand(project, {"c1": "再再强化"}, glossary_ids=[]).redo()
    assert project.studio_state["term_word_overrides"]["c1"]["alignment_provenance"] == "term_local_mapping"


def test_consistency_follows_first_spelling_or_preferred_and_skips_common_words():
    from twobyteasr.subtitle_rules.stutter_cleanup import consistency_occurrences
    entries = [("a", 0, "原石不够了"), ("b", 1000, "再抽一次源石"), ("c", 2000, "继续攻势"), ("d", 3000, "这个公式"),
               ("e", 4000, "古龙来了"), ("f", 5000, "骨龙首发")]
    found = consistency_occurrences(entries)
    assert [(h.original, h.replacement, h.default_selected) for h in found["b"]] == [("源石", "原石", True)]
    assert "c" not in found and "d" not in found  # two ordinary words, not one name
    found = consistency_occurrences(entries, preferred={"骨龙"})
    assert [(h.original, h.replacement) for h in found["e"]] == [("古龙", "骨龙")] and "f" not in found


def test_two_recognizer_readings_skip_edges_names_and_particles():
    from twobyteasr.recognition.transcript_evidence import evidence_occurrences
    found = evidence_occurrences("就是那个什么天命之暗我这边暴风雪", "就是那个什么今天运气站我这边暴风雪",
                                 "就是那个什么今天运气在我这边暴风雪")
    assert [(h[1], h[2], h[3]) for h in found] == [("天命之暗", "今天运气站", False), ("天命之暗", "今天运气在", False)]
    assert evidence_occurrences("就是现在很多水灵", "会了就是现在很多水灵", "会了就是现在很多水灵") == []  # neighbour's words
    assert evidence_occurrences("我觉得不着急啊打完", "我觉得不着急呀打完", "我觉得不着急吧打完") == []  # particles
    assert evidence_occurrences("然后骨龙首发继续", "然后古龙首发继续", "然后古龙首发继续", protected=("骨龙",)) == []
    assert evidence_occurrences("这个阵容上风好爽啊", "这个阵容上分好爽啊", "这个阵容上分好爽啊")[0][2:4] == ("分", True)
