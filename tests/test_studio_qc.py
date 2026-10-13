import copy
from time import perf_counter

from PySide6.QtGui import QUndoStack

from twobyteasr.studio_commands import ApplySafeFixesCommand
from twobyteasr.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject
from twobyteasr.studio_qc import (
    QCResult,
    QCCategory,
    QCSeverity,
    SubtitleQCEngine,
    TerminologyEntry,
    build_safe_fix_plan,
    normalize_candidate_text,
    normalize_spoken_text,
    review_candidates,
)


def test_segmentation_only_time_window_evidence_is_info_not_review_conflict():
    cue = StudioCue("seg", 10_000, 12_400, "那我们现在就是依旧是奖金600", speaker_id="S01")
    project = _project([cue], evidence={
        "m1": {"start_ms": 9700, "end_ms": 10800, "moss_text": "OK啊那我们现在"},
        "m2": {"start_ms": 10800, "end_ms": 12500, "moss_text": "就是依旧是奖金六百"},
        "q1": {"start_ms": 9950, "end_ms": 12400, "qwen_asr_text": "那我们现在就是依旧是奖金600。"},
    })

    result = SubtitleQCEngine().analyze(project)
    issues = result.for_cue("seg")

    assert normalize_spoken_text("奖金600。") == normalize_spoken_text("奖金六百")
    assert "model_disagreement" not in {issue.issue_type for issue in issues}
    assert "suspected_word" not in {issue.issue_type for issue in issues}
    assert any(issue.issue_type == "segmentation_difference" and issue.severity == QCSeverity.INFO for issue in issues)
    assert len(review_candidates(project, cue)) == 1


def _project(cues, *, evidence=None):
    project = SubtitleProject(
        media=StudioMedia(path="D:/qc.mp4", duration_ms=60_000),
        cues=list(cues),
        speakers=[StudioSpeaker("S01"), StudioSpeaker("S02")],
        asr_evidence=evidence or {},
    )
    project.validate()
    return project


def test_qc_covers_timing_readability_text_model_and_terminology_without_normal_noise():
    project = _project(
        [
            StudioCue("conflict", 0, 300, "星见鸦！！", speaker_id="S01", evidence_refs=["e:1"]),
            StudioCue("overlap", 180, 900, "  有  空格  ", speaker_id="S01"),
            StudioCue("normal", 1_500, 3_500, "这条字幕正常", speaker_id="S01"),
            StudioCue("duplicate", 3_700, 4_700, "完全相同", speaker_id="S01"),
            StudioCue("duplicate-2", 4_710, 5_710, "完全相同", speaker_id="S01"),
        ],
        evidence={
            "e:1": {
                "moss_text": "星见雅",
                "qwen_asr_text": "星见雅",
                "firered_text": "星见鸦",
                "confidence": 0.42,
            }
        },
    )
    result = SubtitleQCEngine().analyze(
        project,
        terminology=[TerminologyEntry("星见雅", ("星见鸦",), "绝区零")],
    )
    types = {issue.issue_type for issue in result.issues}

    assert {
        "model_disagreement",
        "low_confidence",
        "suspected_word",
        "terminology_mismatch",
        "high_cps",
        "overlap",
        "duplicate_punctuation",
        "extra_spaces",
        "consecutive_duplicate",
    } <= types
    assert not result.for_cue("normal")
    assert any(
        issue.category == QCCategory.TERMINOLOGY and issue.severity == QCSeverity.CRITICAL
        for issue in result.for_cue("conflict")
    )


def test_qc_flags_repeated_characters_numbers_lines_and_speaker_only_as_suggestions():
    project = _project(
        [
            StudioCue("a", 0, 1_000, "上一句没有结束", speaker_id="S01"),
            StudioCue("b", 1_020, 1_700, "好好好好 １２，３４", speaker_id="S02"),
            StudioCue("c", 1_720, 2_700, "短", speaker_id="S01"),
            StudioCue("lines", 3_000, 5_000, "一\n这是明显非常非常非常非常非常非常非常长的第二行", speaker_id="S01"),
        ]
    )
    result = SubtitleQCEngine().analyze(project)
    types = {issue.issue_type for issue in result.issues}

    assert {"repeated_character", "width_mismatch", "number_format", "speaker_jump", "unbalanced_lines"} <= types
    assert all(
        not issue.safe_fixable
        for issue in result.for_cue("b")
        if issue.category == QCCategory.SPEAKER
    )


def test_model_agreement_normalizes_current_and_suppresses_low_confidence_priority():
    cue = StudioCue("agree", 0, 2_000, " 开卡车是啥意思啊 ", speaker_id="S01", evidence_refs=["e:1"])
    project = _project([cue], evidence={
        "e:1": {
            "text": "开卡车是啥意思啊",
            "moss_text": "开卡车是啥意思啊",
            "firered_text": "开卡车是啥意思啊",
            "qwen_asr_text": "开卡车是啥意思啊",
            "confidence": 0.31,
        }
    })

    result = SubtitleQCEngine().analyze(project)
    issue_types = {issue.issue_type for issue in result.for_cue("agree")}
    candidates = review_candidates(project, cue)

    assert "model_disagreement" not in issue_types
    assert "suspected_word" not in issue_types
    assert "low_confidence" not in issue_types
    assert len(candidates) == 1
    assert {"Current", "MOSS", "FireRed", "Qwen"} == set(candidates[0].sources)
    assert normalize_candidate_text("Ａ， B") == normalize_candidate_text("A, B")


def test_confidence_availability_metadata_and_alignment_scores_are_not_asr_scores():
    from twobyteasr.studio_qc import _confidence_values
    cue = StudioCue('metadata', 0, 2000, '先撤', evidence_refs=['r'])
    p = _project([cue], evidence={'r': dict(confidence=.62,
        qwen_confidence=0., qwen_confidence_available=False,
        confidence_available=False, confidence_version='0',
        confidence_explanation='0', firered_alignment_confidence=0.)})
    assert _confidence_values(p, cue) == [.62]
    issues = SubtitleQCEngine().analyze(p).for_cue(cue.id)
    low = [issue for issue in issues if issue.issue_type == 'low_confidence']
    assert len(low) == 1 and low[0].evidence[0].confidence == .62


def test_explicitly_available_qwen_zero_and_low_scores_remain_real_qc_evidence():
    from twobyteasr.studio_qc import _confidence_values
    for score in (0., .25):
        cue = StudioCue('qwen', 0, 2000, '先撤', evidence_refs=['r'])
        p = _project([cue], evidence={'r': dict(start_ms=0, end_ms=2000,
            qwen_asr_text='先撤', qwen_confidence=score, qwen_confidence_available=True)})
        assert _confidence_values(p, cue) == [score]
        low = [issue for issue in SubtitleQCEngine().analyze(p).for_cue(cue.id)
            if issue.issue_type == 'low_confidence']
        assert len(low) == 1 and low[0].evidence[0].confidence == score


def test_explicit_generic_zero_and_low_scores_are_not_treated_as_qwen_placeholders():
    from twobyteasr.studio_qc import _confidence_values
    for score in (0., .31):
        cue = StudioCue('primary', 0, 2000, '先撤', evidence_refs=['r'])
        p = _project([cue], evidence={'r': dict(start_ms=0, end_ms=2000,
            moss_text='先撤', confidence=score, confidence_available=True)})
        assert _confidence_values(p, cue) == [score]
        assert any(issue.issue_type == 'low_confidence' and issue.evidence[0].confidence == score
            for issue in SubtitleQCEngine().analyze(p).for_cue(cue.id))


def test_review_candidates_group_unique_text_and_keep_current_adoptable():
    cue = StudioCue("choice", 0, 2_000, "太赖了", speaker_id="S01", evidence_refs=["e:1"])
    project = _project([cue], evidence={
        "e:1": {
            "moss_text": "太赖了",
            "firered_text": "太赖了",
            "qwen_asr_text": "太烂了",
        }
    })

    candidates = review_candidates(project, cue)

    assert [(item.text, item.sources) for item in candidates] == [
        ("太赖了", ("Current", "MOSS", "FireRed")),
        ("太烂了", ("Qwen",)),
    ]


def test_safe_fix_repairs_twenty_plus_items_as_one_undo_and_redo_step():
    cues = [
        StudioCue(f"text-{index}", index * 1_000, index * 1_000 + 700, f"  第{index}条 １２！！  ", speaker_id="S01")
        for index in range(22)
    ]
    cues.extend(
        [
            StudioCue("empty", 22_000, 22_500, "  ", speaker_id="S01"),
            StudioCue("dup-a", 23_000, 23_700, "重复", speaker_id="S01"),
            StudioCue("dup-b", 23_710, 24_400, "重复", speaker_id="S01"),
            StudioCue("fragment-a", 25_000, 25_250, "星", speaker_id="S01"),
            StudioCue("fragment-b", 25_270, 26_000, "见雅登场", speaker_id="S01"),
        ]
    )
    project = _project(cues)
    before = copy.deepcopy(project.cues)
    plan = build_safe_fix_plan(project)

    assert plan.total >= 25
    assert project.cues == before
    assert not any(cue.id == "empty" for cue in plan.cues)
    assert not any(cue.id == "dup-b" for cue in plan.cues)
    assert next(cue for cue in plan.cues if cue.id == "text-0").text == "第0条 12！"

    stack = QUndoStack()
    stack.push(ApplySafeFixesCommand(project, plan))
    after = copy.deepcopy(project.cues)
    assert stack.count() == 1
    assert project.cues != before

    stack.undo()
    assert project.cues == before
    stack.redo()
    assert project.cues == after


def test_safe_fix_does_not_choose_wording_or_change_speaker_conflicts():
    project = _project(
        [
            StudioCue("repeat", 0, 1_000, "好好好好", speaker_id="S01"),
            StudioCue("speaker-overlap", 800, 1_800, "另一人同时说话", speaker_id="S02"),
            StudioCue("term", 2_000, 3_000, "星见鸦", speaker_id="S01"),
        ]
    )
    plan = build_safe_fix_plan(project)

    assert [(cue.id, cue.start_ms, cue.end_ms, cue.text, cue.speaker_id) for cue in plan.cues] == [
        (cue.id, cue.start_ms, cue.end_ms, cue.text, cue.speaker_id) for cue in project.cues
    ]


def test_incremental_qc_updates_neighbors_and_500_2000_cue_scans_are_bounded():
    engine = SubtitleQCEngine()
    for size in (500, 2_000):
        project = _project(
            [
                StudioCue(f"c-{index}", index * 1_200, index * 1_200 + 900, "正常字幕", speaker_id="S01")
                for index in range(size)
            ]
        )
        started = perf_counter()
        result = engine.analyze(project)
        full_elapsed = perf_counter() - started
        assert full_elapsed < 2.0
        assert not result.issues

        target = project.cues[size // 2]
        target.text = "这是一条在极短时间里完全读不完的字幕"
        target.end_ms = target.start_ms + 200
        started = perf_counter()
        updated = engine.analyze_incremental(project, target.id, result)
        incremental_elapsed = perf_counter() - started
        assert incremental_elapsed < 0.35
        assert any(issue.severity == QCSeverity.CRITICAL for issue in updated.for_cue(target.id))


def test_p4_segmentation_only_disagreement_is_info_not_critical():
    """Two evidences differing only by sentence-split must not enter review."""
    cue = StudioCue("p4-seg", 10_000, 13_200, "那么我们今天就来看一下这个", speaker_id="S01")
    project = _project([cue], evidence={
        "m1": {"start_ms": 9900, "end_ms": 11000, "moss_text": "那么我们今天就"},
        "m2": {"start_ms": 11000, "end_ms": 13300, "moss_text": "来看一下这个"},
        "q1": {"start_ms": 9950, "end_ms": 13300, "qwen_asr_text": "那么我们今天就来看一下这个"},
    })

    result = SubtitleQCEngine().analyze(project)
    issues = result.for_cue("p4-seg")
    types = {issue.issue_type: issue.severity for issue in issues}

    assert "model_disagreement" not in types, "断句差异被升级为多模型冲突"
    assert types.get("segmentation_difference") == QCSeverity.INFO


def test_p4_real_content_disagreement_stays_critical():
    cue = StudioCue("p4-conflict", 0, 2000, "今天天气真好", speaker_id="S01")
    project = _project([cue], evidence={
        "e:1": {"start_ms": 0, "end_ms": 2000, "moss_text": "今天天气真好", "qwen_asr_text": "现金提款正好"},
    })

    result = SubtitleQCEngine().analyze(project)
    severities = {issue.issue_type: issue.severity for issue in result.for_cue("p4-conflict")}

    assert severities.get("model_disagreement") == QCSeverity.CRITICAL, "真实内容冲突必须保持高风险"


def test_p4_continuous_same_speaker_overlap_suggests_merge_not_review():
    cues = [
        StudioCue("a", 0, 1500, "我是米虫尼奈", speaker_id="S01"),
        StudioCue("b", 1400, 2900, "今天打游戏", speaker_id="S01"),
    ]
    result = SubtitleQCEngine().analyze(_project(cues))
    types = {issue.issue_type: issue.severity for issue in result.for_cue("b")}

    assert types.get("merge_overlap_suggestion") == QCSeverity.INFO
    assert "overlap" not in types or types["overlap"] != QCSeverity.CRITICAL


def test_p4_cross_speaker_overlap_stays_critical():
    cues = [
        StudioCue("a", 0, 1500, "我是米虫尼奈", speaker_id="S01"),
        StudioCue("b", 1400, 2900, "今天打游戏", speaker_id="S02"),
    ]
    result = SubtitleQCEngine().analyze(_project(cues))
    types = {issue.issue_type: issue.severity for issue in result.for_cue("b")}

    assert types.get("overlap") == QCSeverity.CRITICAL, "跨说话人重叠仍是高风险"
    assert "merge_overlap_suggestion" not in types


def test_sliced_scan_matches_full_analyze_and_chunks_are_bounded():
    """分片扫描（进入路径 2026-09-18）与全量 analyze 结果逐 cue 一致。"""
    cues = []
    for index in range(300):
        text = "正常字幕"
        if index % 7 == 0:
            text = "这是一条在极短时间里完全读不完的字幕"
        cues.append(StudioCue(f"c-{index}", index * 1_200, index * 1_200 + 200, text, speaker_id="S01"))
    cues.append(StudioCue("dup-1", 400_000, 400_900, "重复内容", speaker_id="S01"))
    cues.append(StudioCue("dup-2", 401_000, 401_900, "重复内容", speaker_id="S01"))
    project = _project(cues)
    engine = SubtitleQCEngine()
    full = engine.analyze(project)

    context = engine.build_context(project)
    collected: dict[str, tuple] = {}
    chunk = 137  # 非整除切片，覆盖边界
    ordered = list(context.ordered)
    for start in range(0, len(ordered), chunk):
        collected.update(engine.evaluate_cues(context, ordered[start:start + chunk]))
    sliced = QCResult(collected)

    assert set(sliced.issues_by_cue) == set(full.issues_by_cue)
    for cue_id, rows in full.issues_by_cue.items():
        assert list(sliced.issues_by_cue[cue_id]) == list(rows), cue_id


# —— 2026-09-18 VIII：AI 断句句内空格的 QC 豁免 ——

def test_safe_fix_preserves_interjection_rhythm_spaces():
    """语气字后的单个空格=AI 断句节奏位；一键安全修复不得回滚。"""
    from twobyteasr.studio_qc import normalize_safe_text

    assert normalize_safe_text("对 对 很不错啊 嗯") == "对 对 很不错啊 嗯"
    assert normalize_safe_text("啊 我很喜欢这个角色") == "啊 我很喜欢这个角色"
    # 2026-10-12（用户要求）：中文字间的单个半角空格一律是有意的停顿排版，
    # 安全修复不再删除（旧断言为 "你好呀"）。
    assert normalize_safe_text("你 好呀") == "你 好呀"
    # 连续空格仍收敛为单个。
    assert normalize_safe_text("对  对") == "对 对"


def test_qc_rule_does_not_flag_interjection_spaces():
    engine = SubtitleQCEngine()
    project = SubtitleProject(media=StudioMedia(path="x.flv", duration_ms=9000))
    project.speakers.append(StudioSpeaker(id="S01", name="主播"))
    project.cues.append(StudioCue("s1", 1000, 4200, "对 对 很不错啊 嗯", speaker_id="S01"))
    result = QCResult(engine.evaluate_cues(engine.build_context(project), list(project.cues)))
    assert not [i for i in result.issues_by_cue.get("s1", ()) if i.code == "extra_spaces"]


def test_safe_fix_keeps_split_repeated_responses_separate():
    """AI 断句拆出的「对」「对」不被结构合并回一条丢掉重复。"""
    project = SubtitleProject(media=StudioMedia(path="x.flv", duration_ms=9000))
    project.cues.append(StudioCue("r1", 1000, 1400, "对", speaker_id="S01"))
    project.cues.append(StudioCue("r2", 1500, 1900, "对", speaker_id="S01"))
    project.cues.append(StudioCue("r3", 2000, 2600, "嗯", speaker_id="S01"))
    project.cues.append(StudioCue("r4", 2700, 5200, "独立语气词不拼接", speaker_id="S01"))
    plan = build_safe_fix_plan(project)
    remaining = {cue.id for cue in plan.cues}
    assert {"r1", "r2", "r3"} <= remaining
