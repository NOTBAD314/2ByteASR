"""Unit tests for Task 4: AI transcript rough-cut (AI 文稿粗剪)."""
from __future__ import annotations

import ast
import json
import math
import os
import sys
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from twobyteasr.projects.studio_project import (
    PROJECT_SCHEMA_VERSION,
    StudioCue,
    StudioMedia,
    StudioSpeaker,
    SubtitleProject,
    load_project,
    save_project,
)
from twobyteasr.studio.ai_rough_cut import (
    DEFAULT_BREATHING_MARGIN_MS,
    HIGHLIGHT_PAD_MS,
    REASON_BACKGROUND,
    REASON_DEAD_AIR,
    REASON_FILLER,
    REASON_MANUAL,
    REASON_NON_HIGHLIGHT,
    REASON_RETAKE,
    ROUGH_CUT_LINKED_KEY,
    ROUGH_CUT_MARKS_KEY,
    active_cut_cue_ids,
    analyze_cues_with_ai,
    build_seam_preview_steps,
    build_sliding_windows,
    clear_rough_cut_marks,
    compute_keep_highlights_marks,
    compute_rough_cut_ranges,
    compute_speaker_cut_marks,
    cue_cut_reason,
    detect_local_silence_cuts,
    get_rough_cut_marks,
    is_cue_marked_for_cut,
    is_linked_video_cut_enabled,
    make_rough_cut_seam_reel,
    merge_suggested_marks,
    next_skip_target_ms,
    parse_ai_rough_cut_response,
    plan_project_rough_cut,
    set_cue_cut_mark,
    set_linked_video_cut_enabled,
    toggle_cue_cut_mark,
)
from twobyteasr.studio.studio_autocut import rough_cut_apply_command
from twobyteasr.timeline.studio_edit_commands import EditSequenceCommand
from twobyteasr.timeline.studio_edit_sequence import (
    HighlightCandidate,
    VideoSegment,
    ensure_edit_sequence,
    projected_cues,
    sequence_of,
    source_cue_id_of,
    store_sequence,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _make_project(cues: list[StudioCue], *, duration_ms: int = 30_000, speakers=None) -> SubtitleProject:
    project = SubtitleProject(
        media=StudioMedia(path="demo.mp4", duration_ms=duration_ms, width=1280, height=720),
        cues=cues,
        speakers=list(
            speakers
            or [
                StudioSpeaker(id="S01", name="主播"),
                StudioSpeaker(id="GAME_BACKGROUND", name="游戏背景声"),
            ]
        ),
    )
    seq = ensure_edit_sequence(project)
    seq.video_track_locked = False
    seq.source_duration_ms = duration_ms
    seq.segments = [
        VideoSegment(
            id="seg-1",
            source_path="demo.mp4",
            source_in_ms=0,
            source_out_ms=duration_ms,
            timeline_in_ms=0,
            timeline_out_ms=duration_ms,
        )
    ]
    store_sequence(project, seq)
    return project


# ------------------------------------------------------- 1. Qt-free & safety


def test_ai_rough_cut_module_is_strictly_qt_free():
    path = ROOT / "twobyteasr" / "studio" / "ai_rough_cut.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & {"PySide6", "qtawesome", "shiboken6"}), imported


def test_linked_video_cut_switch_defaults_off_and_marks_toggle_cleanly():
    project = _make_project([StudioCue("c1", 0, 2000, "第一句", speaker_id="S01")])
    assert is_linked_video_cut_enabled(project) is False
    assert set_linked_video_cut_enabled(project, True) is True
    assert is_linked_video_cut_enabled(project) is True
    assert project.studio_state[ROUGH_CUT_LINKED_KEY] is True

    assert toggle_cue_cut_mark(project, "c1", reason=REASON_MANUAL) is True
    assert is_cue_marked_for_cut(project, "c1") is True
    assert cue_cut_reason(project, "c1") == REASON_MANUAL
    assert toggle_cue_cut_mark(project, "c1") is False
    assert is_cue_marked_for_cut(project, "c1") is False


# -------------------------------- 2. Merge, breathing margin, <250ms guard


def test_breathing_margin_protects_kept_cues_and_aligns_to_words():
    cues = [
        StudioCue("k1", 0, 2000, "保留前句", speaker_id="S01"),
        StudioCue("x1", 2000, 4000, "重录废稿", speaker_id="S01"),
        StudioCue("k2", 4000, 6000, "保留后句", speaker_id="S01"),
    ]
    marks = {"x1": {"reason": REASON_RETAKE, "keep": False}}

    plan = compute_rough_cut_ranges(cues, marks, breathing_margin_ms=150, timeline_duration_ms=6000)
    # Kept cues keep [0, 2150] and [3850, 6000]; cut shrinks to [2150, 3850]
    assert plan.cut_ranges == [(2150, 3850)], plan
    assert plan.total_cut_ms == 1700
    assert plan.breathing_margin_ms == DEFAULT_BREATHING_MARGIN_MS

    # Word-level alignment: k1's last word ended early at 1820, k2 starts at 4050
    word_map = {
        "k1": (100, 1820),
        "x1": (2010, 3920),
        "k2": (4050, 5900),
    }
    aligned_plan = compute_rough_cut_ranges(
        cues,
        marks,
        breathing_margin_ms=150,
        word_bounds_fn=lambda cue: word_map.get(cue.id),
        timeline_duration_ms=6000,
    )
    # k1 protected up to 1820+150=1970 (no encroachment on x1 start 2000!)
    # k2 protected from 4050-150=3900 (cuts cleanly at 3900!)
    assert aligned_plan.cut_ranges == [(2000, 3900)], aligned_plan
    assert aligned_plan.aligned_cue_count == 3


def test_adjacent_cuts_bridge_sub_250ms_gap_without_swallowing_kept_cue():
    # Two cut cues separated by 180ms empty gap -> must merge into 1 range
    cues = [
        StudioCue("k1", 0, 800, "开头", speaker_id="S01"),
        StudioCue("x1", 1200, 2200, "嗯呃", speaker_id="S01"),
        StudioCue("x2", 2380, 3400, "然后那个", speaker_id="S01"),
        StudioCue("k2", 4000, 5200, "正文", speaker_id="S01"),
    ]
    marks = {
        "x1": {"reason": REASON_FILLER, "keep": False},
        "x2": {"reason": REASON_FILLER, "keep": False},
    }
    plan = compute_rough_cut_ranges(cues, marks, breathing_margin_ms=150, min_fragment_ms=250)
    assert plan.cut_ranges == [(1200, 3400)], plan
    assert plan.merged_gap_count >= 1

    # Now put a short 160ms kept cue between x1 and x2 -> MUST NOT swallow it!
    cues_with_short_kept = [
        StudioCue("k1", 0, 800, "开头", speaker_id="S01"),
        StudioCue("x1", 1200, 2200, "废话一", speaker_id="S01"),
        StudioCue("k_mid", 2220, 2380, "好！", speaker_id="S01"),
        StudioCue("x2", 2400, 3400, "废话二", speaker_id="S01"),
        StudioCue("k2", 4000, 5200, "正文", speaker_id="S01"),
    ]
    plan_safe = compute_rough_cut_ranges(
        cues_with_short_kept, marks, breathing_margin_ms=150, min_fragment_ms=250
    )
    assert len(plan_safe.cut_ranges) == 2, plan_safe
    # k_mid [2220, 2380] + 150ms margin on both sides -> [2070, 2530] completely untouched
    assert plan_safe.cut_ranges == [(1200, 2070), (2530, 3400)], plan_safe
    for a, b in plan_safe.cut_ranges:
        assert not (a < 2380 and b > 2220)


def test_tightly_sandwiched_cut_fully_protected_is_skipped():
    cues = [
        StudioCue("k1", 0, 2000, "保留前", speaker_id="S01"),
        StudioCue("x1", 2050, 2280, "短哼", speaker_id="S01"),
        StudioCue("k2", 2320, 4000, "保留后", speaker_id="S01"),
    ]
    marks = {"x1": {"reason": REASON_FILLER, "keep": False}}
    plan = compute_rough_cut_ranges(cues, marks, breathing_margin_ms=150)
    assert plan.cut_ranges == []
    assert plan.skipped_protected_cues == ["x1"]


# ------------------------------------------- 3. Strategy ①: local silence


def test_local_silence_reuses_autocut_wav_and_maps_to_timeline(tmp_path):
    sr = 16000
    tone = [int(0.5 * 32767 * math.sin(2 * math.pi * 220 * i / sr)) for i in range(2 * sr)]
    silence = [0] * (5 * sr)
    pcm = np.array(tone + silence + tone, dtype="<i2")
    wav_file = tmp_path / "speech.wav"
    with wave.open(str(wav_file), "wb") as wf:
        wf.setparams((1, 2, sr, 0, "NONE", "not compressed"))
        wf.writeframes(pcm.tobytes())

    project = _make_project(
        [
            StudioCue("c1", 0, 2000, "前句"),
            StudioCue("c2", 7000, 9000, "后句"),
        ],
        duration_ms=9000,
    )
    ranges = detect_local_silence_cuts(project, wav_file, min_silence_s=3.0, padding_s=0.2)
    assert len(ranges) == 1, ranges
    lo, hi = ranges[0]
    assert 1900 <= lo <= 2600 and 6400 <= hi <= 7100, ranges

    # Pure transcript gap fallback (no wav)
    gap_ranges = detect_local_silence_cuts(project, None, min_silence_s=3.0, padding_s=0.2)
    assert gap_ranges == [(2200, 6800)]


# ------------------------------- 4. Strategies ② & ③: AI mock + fault tolerance


def test_sliding_windows_cover_all_cues_with_overlap():
    cues = [StudioCue(f"c{i}", i * 1000, i * 1000 + 800, f"台词 {i}") for i in range(210)]
    windows = build_sliding_windows(cues, window_size=100, overlap=12)
    assert len(windows) == 3
    assert len(windows[0]) == 100
    assert windows[0][-12].id == windows[1][0].id
    seen = {c.id for batch in windows for c in batch}
    assert len(seen) == 210


def test_ai_rough_cut_mock_produces_advisory_marks_without_mutating_timeline():
    cues = [
        StudioCue("c1", 0, 1800, "大家好今天我们来聊…哎重来重来", speaker_id="S01"),
        StudioCue("c2", 2000, 4200, "大家好今天我们来聊新版本武器", speaker_id="S01"),
        StudioCue("c3", 4500, 5600, "呃那个就是说嗯", speaker_id="S01"),
        StudioCue("c4", 6000, 8200, "等等我调下麦克风喝口水", speaker_id="S01"),
        StudioCue("c5", 8600, 11000, "第一把推荐步枪伤害超高", speaker_id="S01"),
    ]
    project = _make_project(cues, duration_ms=12_000)
    before_seq = sequence_of(project).to_dict()
    before_cues = [(c.id, c.start_ms, c.end_ms, c.text) for c in project.cues]

    class _FakeProvider:
        def complete(self, messages, **_kwargs):
            return json.dumps(
                {
                    "cuts": [
                        {"cue_id": "c1", "reason": "重录废稿"},
                        {"cue_id": "c3", "reason": "口癖水话"},
                        {"cue_id": "c4", "reason": "冷场过渡"},
                        {"cue_id": "nonexistent", "reason": "口癖水话"},
                    ]
                },
                ensure_ascii=False,
            )

    result = analyze_cues_with_ai(project, provider=_FakeProvider(), tightness="tight")
    assert result.ok is True
    assert result.suggestions == {
        "c1": REASON_RETAKE,
        "c3": REASON_FILLER,
        "c4": REASON_DEAD_AIR,
    }
    # Strictly advisory: timeline & cues completely untouched!
    assert sequence_of(project).to_dict() == before_seq
    assert [(c.id, c.start_ms, c.end_ms, c.text) for c in project.cues] == before_cues

    # Merge into studio_state['rough_cut_marks'] & respect manual restore (keep=True)
    added = merge_suggested_marks(project, result.suggestions)
    assert added == 3
    set_cue_cut_mark(project, "c3", marked=False)  # user restores c3
    assert project.studio_state[ROUGH_CUT_MARKS_KEY]["c3"]["keep"] is True
    assert is_cue_marked_for_cut(project, "c3") is False
    # Re-merging same suggestions must NOT overwrite user's keep=True
    merge_suggested_marks(project, result.suggestions)
    assert is_cue_marked_for_cut(project, "c3") is False


def test_ai_rough_cut_parser_tolerates_noisy_and_malformed_json():
    valid = {"c1", "c2", "c3"}

    # Fenced markdown + prose + trailing comma + alternate keys + synonym reason
    noisy = (
        "好的，以下是建议删减的句子：\n"
        "```json\n"
        '{"items": [{"id": "c1", "tag": "说到一半重来 NG"}, {"cueId": "c2", "label": "调麦喝水冷场"}, {"cue_id": "fake", "reason": "口癖水话"},]}\n'
        "```\n希望能帮到你！"
    )
    parsed, warns = parse_ai_rough_cut_response(noisy, valid_cue_ids=valid)
    assert parsed == {"c1": REASON_RETAKE, "c2": REASON_DEAD_AIR}
    assert not warns

    # Completely corrupted text -> no exception, empty dict + warning
    bad_parsed, bad_warns = parse_ai_rough_cut_response("<<<NOT JSON AT ALL>>>", valid_cue_ids=valid)
    assert bad_parsed == {}
    assert bad_warns


def test_ai_rough_cut_degrades_gracefully_when_text_ai_key_missing():
    from twobyteasr.providers.llm_config import activate_ai_service

    project = _make_project([StudioCue("c1", 0, 2000, "测试句子", speaker_id="S01")])
    settings: dict = {}
    activate_ai_service(settings, "deepseek")
    res = analyze_cues_with_ai(project, runtime_settings=settings)
    assert res.ok is False
    assert res.missing_key is True
    assert "密钥" in res.message or "文字 AI" in res.message

    # Also verify a failing provider degrades cleanly without raising
    class _FailingProvider:
        def complete(self, *_args, **_kwargs):
            raise RuntimeError("temporary network timeout")

    fail_res = analyze_cues_with_ai(project, provider=_FailingProvider())
    assert fail_res.ok is False
    assert fail_res.suggestions == {}
    assert fail_res.warnings


# ------------------------------------ 5. Strategy ④: Highlights & Speakers


def test_keep_highlights_preserves_2s_pad_and_marks_rest():
    cues = [
        StudioCue("c1", 0, 4000, "开场闲聊", speaker_id="S01"),
        StudioCue("c2", 8500, 9800, "高光前 1.5s 铺垫", speaker_id="S01"),
        StudioCue("c3", 10_000, 15_000, "高光正片反杀！", speaker_id="S01"),
        StudioCue("c4", 15_500, 16_800, "高光后 1.8s 余韵", speaker_id="S01"),
        StudioCue("c5", 22_000, 26_000, "后面跑题聊天", speaker_id="S01"),
    ]
    project = _make_project(cues, duration_ms=30_000)
    cand = HighlightCandidate(
        id="hl-1",
        title="反杀名场面",
        source_in_ms=10_000,
        source_out_ms=15_000,
        range_status="suggested",
        status="accepted",
        source_path="demo.mp4",
        source_duration_ms=30_000,
    )
    cuts, keep_ranges = compute_keep_highlights_marks(project, [cand], pad_ms=HIGHLIGHT_PAD_MS)
    # 10_000..15_000 padded by 2000ms -> 8_000..17_000
    assert keep_ranges == [(8_000, 17_000)], keep_ranges
    # c2, c3, c4 overlap [8_000, 17_000] -> kept; c1 and c5 marked as 非高光段
    assert cuts == {"c1": REASON_NON_HIGHLIGHT, "c5": REASON_NON_HIGHLIGHT}, cuts


def test_speaker_cut_marks_background_and_custom_speakers():
    cues = [
        StudioCue("c1", 0, 2000, "主播解说", speaker_id="S01"),
        StudioCue("c2", 2500, 4500, "敌军还有五秒到达战场", speaker_id="GAME_BACKGROUND"),
        StudioCue("c3", 5000, 7000, "路人甲插话", speaker_id="S02"),
    ]
    project = _make_project(
        cues,
        duration_ms=10_000,
        speakers=[
            StudioSpeaker(id="S01", name="主播"),
            StudioSpeaker(id="S02", name="路人甲"),
            StudioSpeaker(id="GAME_BACKGROUND", name="游戏背景声"),
        ],
    )
    assert compute_speaker_cut_marks(project) == {"c2": REASON_BACKGROUND}
    assert compute_speaker_cut_marks(project, ["S02"]) == {"c3": REASON_BACKGROUND}


# ------------------------------------ 6. Seam preview & auto-skip playback


def test_seam_preview_steps_and_wav_reel_and_live_skip(tmp_path):
    cues = [
        StudioCue("k1", 0, 2000, "第一段"),
        StudioCue("x1", 2200, 4200, "删掉一"),
        StudioCue("k2", 4500, 7500, "中间段"),
        StudioCue("x2", 7800, 9800, "删掉二"),
        StudioCue("k3", 10_000, 12_000, "结尾段"),
    ]
    marks = {
        "x1": {"reason": REASON_RETAKE, "keep": False},
        "x2": {"reason": REASON_FILLER, "keep": False},
    }
    plan = compute_rough_cut_ranges(cues, marks, breathing_margin_ms=150, timeline_duration_ms=12_000)
    assert len(plan.cut_ranges) == 2

    steps = build_seam_preview_steps(
        plan.cut_ranges, cues=cues, marks=marks, window_ms=1500, timeline_duration_ms=12_000
    )
    assert len(steps) == 2
    assert steps[0].cue_id == "x1" and steps[0].pre_start_ms == max(0, plan.cut_ranges[0][0] - 1500)
    assert steps[1].cue_id == "x2" and steps[1].post_end_ms == min(12_000, plan.cut_ranges[1][1] + 1500)

    # Live playback auto-skip helper
    c0_start, c0_end = plan.cut_ranges[0]
    assert next_skip_target_ms(500, plan.cut_ranges) is None
    assert next_skip_target_ms(c0_start + 100, plan.cut_ranges) == c0_end

    # Audition WAV reel concatenation
    sr = 16000
    wav_path = tmp_path / "timeline.wav"
    samples = np.arange(sr * 12, dtype=np.int32).astype("<i2")
    with wave.open(str(wav_path), "wb") as wf:
        wf.setparams((1, 2, sr, 0, "NONE", "not compressed"))
        wf.writeframes(samples.tobytes())
    reel = make_rough_cut_seam_reel(wav_path, plan.cut_ranges, window_ms=1500, separator_s=0.4)
    assert reel.is_file()
    with wave.open(str(reel), "rb") as rf:
        assert rf.getnframes() > sr * 4  # 2 seams * ~3s + separator


# --------------- 7. Single undoable EditSequenceCommand + schema_version == 1


def test_apply_rough_cut_via_edit_sequence_command_and_undo_restores_all():
    _app()
    cues = [
        StudioCue("c1", 0, 2_000, "开头正常句", speaker_id="S01"),
        StudioCue("c2", 3_000, 8_000, "这段是重录废稿", speaker_id="S01"),
        StudioCue("c3", 10_000, 13_000, "最后顺畅成片句", speaker_id="S01"),
    ]
    project = _make_project(cues, duration_ms=15_000)
    set_cue_cut_mark(project, "c2", marked=True, reason=REASON_RETAKE)

    plan = plan_project_rough_cut(project)
    assert plan.cut_ranges == [(3_000, 8_000)], plan

    cmd = rough_cut_apply_command(project, plan.cut_ranges, cue_ids=plan.marked_cue_ids)
    assert isinstance(cmd, EditSequenceCommand)

    cmd.redo()
    after_seq = sequence_of(project)
    assert after_seq.timeline_duration_ms == 10_000, after_seq.timeline_duration_ms
    assert active_cut_cue_ids(project) == []  # marks cleared after execution
    projected = {source_cue_id_of(c.id): (c.start_ms, c.end_ms) for c in projected_cues(project)}
    assert projected["c1"] == (0, 2_000)
    assert "c2" not in projected
    assert projected["c3"] == (5_000, 8_000)

    cmd.undo()
    restored_seq = sequence_of(project)
    assert restored_seq.timeline_duration_ms == 15_000
    assert active_cut_cue_ids(project) == ["c2"]
    restored_proj = {source_cue_id_of(c.id): (c.start_ms, c.end_ms) for c in projected_cues(project)}
    assert restored_proj["c2"] == (3_000, 8_000)
    assert restored_proj["c3"] == (10_000, 13_000)


def test_apply_rough_cut_undo_restores_independent_timeline_captions():
    _app()
    cues = [
        StudioCue("c1", 0, 2_000, "第一句", speaker_id="S01"),
        StudioCue("c2", 3_000, 7_000, "废话段", speaker_id="S01"),
        StudioCue("c3", 9_000, 12_000, "第三句", speaker_id="S01"),
    ]
    project = _make_project(cues, duration_ms=14_000)
    project.render_settings["_cue_domain"] = "timeline"
    set_cue_cut_mark(project, "c2", marked=True, reason=REASON_FILLER)
    plan = plan_project_rough_cut(project)

    cmd = rough_cut_apply_command(project, plan.cut_ranges, cue_ids=plan.marked_cue_ids)
    cmd.redo()
    assert sequence_of(project).timeline_duration_ms == 10_000
    ids_after = [c.id for c in project.cues]
    assert "c2" not in ids_after
    c3_after = next(c for c in project.cues if c.id == "c3")
    assert (c3_after.start_ms, c3_after.end_ms) == (5_000, 8_000)

    cmd.undo()
    assert sequence_of(project).timeline_duration_ms == 14_000
    assert [c.id for c in project.cues] == ["c1", "c2", "c3"]
    c3_restored = next(c for c in project.cues if c.id == "c3")
    assert (c3_restored.start_ms, c3_restored.end_ms) == (9_000, 12_000)
    assert active_cut_cue_ids(project) == ["c2"]


def test_project_save_load_keeps_schema_version_1_and_rough_cut_marks(tmp_path):
    _app()
    project = _make_project(
        [
            StudioCue("c1", 0, 2000, "保留句", speaker_id="S01"),
            StudioCue("c2", 3000, 5000, "重录废稿", speaker_id="S01"),
        ],
        duration_ms=6000,
    )
    set_linked_video_cut_enabled(project, True)
    set_cue_cut_mark(project, "c2", marked=True, reason=REASON_RETAKE)

    out_path = tmp_path / "demo.2byteproj"
    save_project(project, out_path)
    raw = json.loads(out_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == PROJECT_SCHEMA_VERSION == 1
    assert raw["studio_state"][ROUGH_CUT_MARKS_KEY]["c2"] == {"reason": REASON_RETAKE, "keep": False}

    loaded = load_project(out_path)
    assert loaded.schema_version == 1
    assert is_linked_video_cut_enabled(loaded) is True
    assert get_rough_cut_marks(loaded) == {"c2": {"reason": REASON_RETAKE, "keep": False}}


# -------------------------- 8. UI label <=6-char contract & CueTable painting


def test_rough_cut_ui_labels_and_cue_table_strikethrough_render():
    _app()
    from twobyteasr.design import theme_manager
    from twobyteasr.studio.studio_cue_table import CueReadingDelegate, CueTableModel
    from twobyteasr.studio.studio_highlight_ui import HighlightAssistantPanel

    project = _make_project(
        [
            StudioCue("c1", 0, 2000, "保留的正常字幕", speaker_id="S01"),
            StudioCue("c2", 2500, 5000, "嗯那个重来重来这段不要", speaker_id="S01"),
        ],
        duration_ms=6000,
    )
    set_cue_cut_mark(project, "c2", marked=True, reason=REASON_RETAKE)

    panel = HighlightAssistantPanel()
    bar = panel.rough_cut_bar
    bar.set_project(project)

    # Explicit switch defaults OFF
    assert bar.linked_toggle.isChecked() is False
    # All visible buttons/toggles/segments <= 6 chars
    labels = bar.action_labels()
    assert labels
    for label in labels:
        compact = label.replace(" ", "")
        assert len(compact) <= 6, f"label exceeds 6 chars: {label!r}"
    assert "待剪 1 句" in bar.count_pill.text()
    assert bar.apply_button.isEnabled() is True
    assert bar.seam_button.isEnabled() is True
    assert bar.clear_button.isEnabled() is True

    clear_rough_cut_marks(project)
    bar.refresh_from_project(project)
    assert bar.count_pill.isHidden() is True
    assert bar.apply_button.isEnabled() is False

    # Re-mark and verify CueTableModel + CueReadingDelegate read-only rendering
    set_cue_cut_mark(project, "c2", marked=True, reason=REASON_RETAKE)
    model = CueTableModel(project)
    idx_kept = model.index(0, 3)
    idx_cut = model.index(1, 3)
    assert model.data(idx_kept, Qt.ItemDataRole.FontRole) is None
    cut_font = model.data(idx_cut, Qt.ItemDataRole.FontRole)
    assert cut_font is not None and cut_font.strikeOut() is True

    delegate = CueReadingDelegate()
    orig_theme_key = theme_manager.theme_key
    try:
        for theme_name in ("warm", "grape"):
            theme_manager.theme_key = lambda _n=theme_name: _n
            bar.refresh_theme_palette()
            img = QImage(340, 180, QImage.Format.Format_ARGB32)
            img.fill(Qt.GlobalColor.transparent)
            painter = QPainter(img)
            for row in range(2):
                opt = QStyleOptionViewItem()
                opt.rect = QRect(0, row * 82, 340, 80)
                delegate.paint(painter, opt, model.index(row, 3))
            painter.end()
            assert 1 in delegate._rough_cut_rects
            assert 0 not in delegate._rough_cut_rects
    finally:
        theme_manager.theme_key = orig_theme_key
    panel.close()

def test_a_reason_chip_holds_that_kind_back_and_brings_back_only_those_cues():
    """2026-11-26 (clip assistant draft A): 「点原因可暂时不剪这类」."""
    from twobyteasr.studio.ai_rough_cut import reason_summary, set_reason_enabled

    project = _make_project(
        [StudioCue(f"c{i}", i * 1000, i * 1000 + 800, f"句子{i}", speaker_id="S01") for i in range(1, 6)],
        duration_ms=6000,
    )
    merge_suggested_marks(project, {"c1": REASON_RETAKE, "c2": REASON_RETAKE, "c3": REASON_FILLER})
    set_cue_cut_mark(project, "c4", marked=True, reason=REASON_RETAKE)
    set_cue_cut_mark(project, "c4", marked=False)              # the user kept c4 by hand
    assert reason_summary(project) == [(REASON_RETAKE, 2, True), (REASON_FILLER, 1, True)]

    assert set_reason_enabled(project, REASON_RETAKE, False) == 2
    assert sorted(active_cut_cue_ids(project)) == ["c3"]
    assert reason_summary(project) == [(REASON_RETAKE, 2, False), (REASON_FILLER, 1, True)]

    assert set_reason_enabled(project, REASON_RETAKE, True) == 2
    assert sorted(active_cut_cue_ids(project)) == ["c1", "c2", "c3"]   # c4 stays kept
    clear_rough_cut_marks(project)
    assert reason_summary(project) == []
