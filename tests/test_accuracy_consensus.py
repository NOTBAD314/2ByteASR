import threading

import subtitle_core
from twobyteasr.subtitle_rules.correction_safety import apply_reference_consensus_corrections
from twobyteasr.glossary.domain_terms import (
    apply_title_profile_aliases,
    repair_with_user_glossary_terms,
)
from twobyteasr.subtitle_rules.grouping import call_grouping_api, fallback_group
from twobyteasr.subtitle_rules.polishing import call_correction_api


def _segment(segment_id, text, *, firered="", qwen="", start=0.0, end=2.0):
    return subtitle_core.SpeechSegment(
        segment_id=segment_id,
        start=start,
        end=end,
        text=text,
        confidence=0.78,
        words=[],
        speaker="S01",
        moss_text=text,
        firered_text=firered,
        qwen_asr_text=qwen,
    )


def test_two_independent_asr_models_fix_local_wrong_characters_not_particles():
    segments = [
        _segment(
            1,
            "英角嘉年华也是顺利结束了",
            firered="鹰角嘉年华也是顺利结束了",
            qwen="鹰角嘉年华也是顺利结束了",
        ),
        _segment(
            2,
            "这不就做成了锤背的毛绒锤吗",
            firered="这不就做成了捶背的毛绒锤吗",
            qwen="这不就做成了捶背的毛绒锤嘛",
        ),
        _segment(
            3,
            "喜欢的角色的吧唧啊",
            firered="喜欢的角色的吧唧呀",
            qwen="喜欢的角色的吧唧呀",
        ),
        _segment(
            4,
            "全方位360度无死角",
            firered="全方位三百六十度无死角",
            qwen="全方位三百六十度无死角",
        ),
        _segment(
            5,
            "来给大家看看有意思啊",
            firered="来给大家看个有意思啊",
            qwen="来给大家看个有意思啊",
        ),
    ]

    apply_reference_consensus_corrections(segments)

    assert segments[0].text == "鹰角嘉年华也是顺利结束了"
    assert segments[1].text == "这不就做成了捶背的毛绒锤吗"
    assert segments[2].text == "喜欢的角色的吧唧啊"
    assert segments[3].text == "全方位360度无死角"
    assert segments[4].text == "来给大家看个有意思啊"


def test_title_scoped_profile_repairs_verified_event_terms_without_cloud():
    segment = _segment(
        1,
        "英角嘉年华周末地的红饼图用布织布做成不带抑制器还有文武双全气球小透足",
    )

    apply_title_profile_aliases([segment], "[NOTBAD]鹰角嘉年华前段")

    assert segment.text == (
        "鹰角嘉年华终末地的同柄图用不织布做成不戴抑制器"
        "还有文武双全气球小套组"
    )


def test_repeated_exact_homophone_uses_explicit_user_glossary():
    segments = [
        _segment(1, "Q版周边我也让阿辉帮我", start=0.0, end=1.5),
        _segment(2, "我基本上都让阿辉帮我带了", start=1.6, end=3.5),
    ]

    repair_with_user_glossary_terms(segments, ["阿晖"], "普通素材")

    assert [segment.text for segment in segments] == [
        "Q版周边我也让阿晖帮我",
        "我基本上都让阿晖帮我带了",
    ]


def test_cloud_grouping_fallback_preserves_text_and_interval_with_comfort_splits():
    text = "这个终末地的单肩包还蛮有设计感的"
    segment = _segment(1, text, start=23.88, end=25.85)

    cues = fallback_group([segment])

    # 2026-09-03 contract: local fallback splits 13–16 characters to <=12;
    # cloud semantic boundaries remain separate. No text/time is discarded.
    assert len(cues) == 2
    assert ''.join(cue.text for cue in cues) == text
    assert all(subtitle_core.display_length(cue.text)<=12 for cue in cues)
    assert cues[0].start == segment.start
    assert cues[-1].end == segment.end
    assert all(left.end==right.start for left,right in zip(cues,cues[1:]))


def test_permanent_cloud_failure_marks_later_batches_as_fallback_not_cacheable():
    segment = _segment(1, "这里是已经校对过的本地结果")
    abort = threading.Event()
    abort.set()

    with subtitle_core.capture_review_items() as polish_items:
        result = call_correction_api(
            [segment],
            glossary=[],
            context_before="",
            context_after="",
            media_title="测试",
            project_context="普通素材",
            stable_term_candidates=[],
            approved_global_mappings=[],
            verified_terms=[],
            abort_event=abort,
        )
    with subtitle_core.capture_review_items() as group_items:
        cues = call_grouping_api([segment], abort_event=abort)

    assert result == {1: segment.text}
    assert [item["category"] for item in polish_items] == ["校对回退"]
    assert [item["category"] for item in group_items] == ["断句回退"]
    assert ''.join(cue.text for cue in cues) == segment.text
    assert cues[0].start==segment.start and cues[-1].end==segment.end


def test_successful_adjudication_resolves_only_matching_disagreement_items():
    subtitle_core.reset_review_items()
    subtitle_core.add_review_item(
        1.0, "多模型争议", "待裁决", "甲", priority=2, segment_id=7
    )
    subtitle_core.add_review_item(
        2.0, "多模型争议", "另一段", "乙", priority=2, segment_id=8
    )
    subtitle_core.add_review_item(
        1.0, "低置信度", "仍需查看", "甲", priority=2, segment_id=7
    )

    removed = subtitle_core.resolve_review_items(
        categories={"多模型争议", "多模型文本冲突"}, segment_ids={7}
    )

    assert removed == 1
    assert [(item["category"], item.get("segment_id")) for item in subtitle_core.RUN_REVIEW_ITEMS] == [
        ("多模型争议", 8),
        ("低置信度", 7),
    ]
    subtitle_core.reset_review_items()
