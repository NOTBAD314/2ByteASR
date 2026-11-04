from pathlib import Path
import subtitle_core

FIXTURES = Path(__file__).resolve().parent / "fixtures"

def test_golden_dual_host_srt_and_txt(tmp_path):
    cues = [
        subtitle_core.SubtitleCue(1, 1.0, 2.2, "今天这波可以", speaker="S01"),
        subtitle_core.SubtitleCue(2, 2.4, 3.5, "你先开大", speaker="S02"),
        subtitle_core.SubtitleCue(3, 3.7, 5.0, "我来收尾", speaker="S01"),
    ]
    cues = subtitle_core.normalize_cue_times(cues, 60.0)
    txt = subtitle_core.render_txt(cues)
    srt = subtitle_core.render_srt(cues)
    expected_txt = (FIXTURES / "dual_host_golden.txt").read_text(encoding="utf-8-sig")
    expected_srt = (FIXTURES / "dual_host_golden.srt").read_text(encoding="utf-8-sig")
    assert txt.replace("\r\n", "\n") == expected_txt.replace("\r\n", "\n")
    assert srt.replace("\r\n", "\n") == expected_srt.replace("\r\n", "\n")
    out_txt = tmp_path / "sample_剪映文稿.txt"
    out_srt = tmp_path / "sample_剪映文稿.srt"
    result = subtitle_core.write_all_outputs_transactional(
        cues, str(out_txt), str(out_srt), include_review_track=False
    )
    assert out_txt.is_file() and out_srt.is_file()
    assert len(result["speaker_outputs"]) == 2

def test_tail_extension_and_gap_bridge_caps():
    cues = [
        subtitle_core.SubtitleCue(1, 0.0, 1.0, "主播一", speaker="S01"),
        subtitle_core.SubtitleCue(2, 1.2, 2.0, "主播二", speaker="S02"),
    ]
    subtitle_core.extend_cue_tails_by_speaker(cues, 4.0, 60.0)
    assert cues[0].end <= 1.2 + 1e-6
    bridge = [
        subtitle_core.SubtitleCue(1, 0.0, 1.0, "A", speaker="S01"),
        subtitle_core.SubtitleCue(2, 1.2, 2.0, "B", speaker="S02"),
    ]
    subtitle_core.bridge_short_display_gaps(bridge, 5.0, 60.0)
    assert abs(bridge[0].end - bridge[1].start) <= 1.0 / 60.0 + 1e-6
