"""三十八轮守护：主页配置按钮 + 旧通道删除迁移 + diarization 说话人轨。

用户指令：word 级已验证 → 删旧 multipart 通道；完整保留 speaker metadata
（parser/normalization/segmentation 不得丢失）；speaker change 是最高优先级
强制字幕边界；每个 SubtitleSegment 保存 speaker_id；说话人可显示/隐藏/试听/
重命名/设主播/仅保留；预留 SpeakerIdentityResolver；**不假设 Speaker 0 恒为
同一人（file-local ID）**。
"""

import numpy as np
import pytest
from unittest.mock import MagicMock

from twobyteasr.recognition import asr
from twobyteasr.recognition.asr import _api_transcription_rows, _normalize_speaker_id

SAMPLING = 16_000


def _fake_media(tmp_path):
    from twobyteasr.projects.studio_project import StudioMedia

    target = tmp_path / "media.mp4"
    target.write_bytes(b"0")
    return StudioMedia(path=str(target))


def test_normalize_speaker_id_variants():
    assert _normalize_speaker_id(0) == "S00"
    assert _normalize_speaker_id(1) == "S01"
    assert _normalize_speaker_id("2") == "S02"
    assert _normalize_speaker_id("S03") == "S03"
    assert _normalize_speaker_id(None) is None
    assert _normalize_speaker_id("") is None


def test_word_speaker_inherited_from_segment():
    words = [
        {"start": 0.0, "end": 0.5, "text": "你"},
        {"start": 0.5, "end": 1.0, "text": "好", "speaker": "S01"},
    ]
    segments = [{"start": 0.0, "end": 2.0, "text": "你好", "speaker": "S00"}]
    asr._inherit_word_speakers_from_segments(words, segments)
    assert words[0]["speaker"] == "S00", "缺失的 word speaker 必须按所处 segment 继承"
    assert words[1]["speaker"] == "S01", "已有 word speaker 不得被覆盖"


def test_rows_split_at_speaker_change_without_silence():
    """同一 segment 内 speaker 切换必须切成两行——即使零间隙。"""
    chunk = {"start": 10.0, "end": 16.0, "audio": (np.zeros(1, dtype=np.float32), SAMPLING)}
    result = {
        "text": "甲说的乙说的",
        "segments": [{"start": 0.2, "end": 4.0, "text": "甲说的乙说的", "speaker": 0}],
        "words": [
            {"word": "甲", "start": 0.2, "end": 0.5, "speaker": 0},
            {"word": "说", "start": 0.5, "end": 0.8, "speaker": 0},
            {"word": "的", "start": 0.8, "end": 1.0, "speaker": 0},
            {"word": "乙", "start": 1.0, "end": 1.3, "speaker": 1},
            {"word": "说", "start": 1.3, "end": 1.6, "speaker": 1},
            {"word": "的", "start": 1.6, "end": 1.9, "speaker": 1},
        ],
    }
    rows = _api_transcription_rows(result, chunk)
    assert len(rows) == 2, "speaker change 是最高优先级强制边界（无静音也切）"
    assert rows[0]["speaker"] == "S00"
    assert rows[1]["speaker"] == "S01"
    assert rows[0]["text"] == "甲说的"
    assert rows[1]["text"] == "乙说的"
    assert rows[0]["end"] == pytest.approx(11.0)
    assert rows[1]["start"] == pytest.approx(11.0)


def test_rows_keep_segment_speaker_when_words_have_none():
    chunk = {"start": 0.0, "end": 5.0, "audio": (np.zeros(1, dtype=np.float32), SAMPLING)}
    result = {
        "text": "段落一",
        "segments": [
            {"start": 0.1, "end": 2.0, "text": "段落一", "speaker": 2},
        ],
        "words": [],
    }
    rows = _api_transcription_rows(result, chunk)
    assert len(rows) == 1
    assert rows[0]["speaker"] == "S02"


def test_alternate_primary_segments_carry_speaker_and_resolver_seam():
    import moss_firered_pipeline as pipeline
    from twobyteasr.recognition import speaker_identity

    legacy = MagicMock()
    legacy.clean_subtitle_text = lambda s: str(s)
    legacy.content_only = lambda s: str(s)
    legacy.best_alternate_window = lambda *args: ("", 0.0)
    from subtitle_core import WordUnit, SpeechSegment
    legacy.WordUnit = WordUnit
    legacy.SpeechSegment = SpeechSegment
    legacy.segment_content_timeline = lambda segment, _: segment.words
    legacy.record_run_event = lambda *a, **k: None
    rows = [
        {"start": 0.0, "end": 1.0, "text": "一", "speaker": "S00"},
        {"start": 1.2, "end": 2.0, "text": "二", "speaker": "S01"},
    ]
    segments = pipeline.build_alternate_primary_segments(rows, [], legacy, "api")
    assert [seg.speaker for seg in segments] == ["S00", "S01"]

    # Resolver 缝隙：自定义映射生效且可还原
    class _Upper(speaker_identity.PassthroughSpeakerIdentityResolver):
        def resolve(self, file_key, local_speaker_id):
            return f"ID-{local_speaker_id}"

    speaker_identity.set_speaker_identity_resolver(_Upper())
    try:
        segments2 = pipeline.build_alternate_primary_segments(rows, [], legacy, "api")
        assert [seg.speaker for seg in segments2] == ["ID-S00", "ID-S01"]
    finally:
        speaker_identity.set_speaker_identity_resolver(
            speaker_identity.PassthroughSpeakerIdentityResolver()
        )


def test_speaker_identity_resolver_defaults():
    from twobyteasr.recognition.speaker_identity import (
        PassthroughSpeakerIdentityResolver,
        speaker_identity_resolver,
    )

    resolver = speaker_identity_resolver()
    assert isinstance(resolver, PassthroughSpeakerIdentityResolver)
    assert resolver.resolve("file-a", "S00") == "S00"
    assert resolver.resolve("file-b", "S00") == "S00", "file-local：不承诺跨文件身份"


def test_settings_migrate_legacy_openrouter_provider():
    from twobyteasr.storage.settings import DEFAULT_SETTINGS, _merge_known_settings

    merged, warnings = _merge_known_settings(
        DEFAULT_SETTINGS,
        {
            "models": {
                "qwen_asr_api_provider": "openrouter",
                "qwen_asr_api_protocol": "openai_transcription",
            }
        },
    )
    assert merged["models"]["qwen_asr_api_provider"] == "openrouter_word"
    assert merged["models"]["qwen_asr_api_protocol"] == "openrouter_verbose_json"
    assert any("migrated" in str(item) for item in warnings)


def test_picker_card_configure_signal_is_wired():
    """主页选择弹窗的「配置」红链必须转发 controller 信号（三十八轮修复）。"""
    from pathlib import Path

    from PySide6.QtWidgets import QApplication

    from twobyteasr.local_models.model_workshop import ModelPickerPanel, ModelWorkshopPage

    app = QApplication.instance() or QApplication([])
    page = ModelWorkshopPage(
        Path("."),
        {
            "models": {
                "qwen_asr_backend": "off",
                "primary_asr_backend": "api",
                "qwen_asr_api_provider": "openrouter_word",
                "qwen_asr_api_model": "microsoft/mai-transcribe-2",
                "qwen_asr_api_url": "https://openrouter.ai/api/v1/audio/transcriptions",
            }
        },
    )
    panel = ModelPickerPanel(page, "primary")
    assert "mai_latest" in panel.cards
    fired: list = []
    page.api_configure_requested.connect(fired.append)
    panel.cards["mai_latest"].configure.click()
    assert fired == ["openrouter_word"]
    panel.deleteLater()
    page.deleteLater()


def test_speaker_hidden_fields_and_visible_cues(tmp_path):
    from twobyteasr.projects.studio_project import StudioCue, StudioSpeaker, SubtitleProject

    project = SubtitleProject(media=_fake_media(tmp_path))
    project.speakers = [
        StudioSpeaker(id="S00", name="A"),
        StudioSpeaker(id="S01", name="B", hidden=True),
    ]
    project.cues = [
        StudioCue(id="c1", start_ms=0, end_ms=900, text="甲", speaker_id="S00"),
        StudioCue(id="c2", start_ms=1000, end_ms=1900, text="乙", speaker_id="S01"),
    ]
    assert project.hidden_speaker_ids() == frozenset({"S01"})
    visible = project.visible_cues()
    assert [cue.id for cue in visible] == ["c1"]
    payload = project.to_dict()
    assert any(item.get("hidden") for item in payload["speakers"])


def test_export_excludes_hidden_speaker(tmp_path):
    from twobyteasr.timeline.studio_commands import SetSpeakersVisibilityCommand
    from twobyteasr.projects.studio_project import StudioCue, StudioSpeaker, SubtitleProject
    from twobyteasr.exports.studio_subtitle_export import (
        SubtitleExportOptions,
        export_subtitle_artifacts,
    )

    project = SubtitleProject(media=_fake_media(tmp_path))
    project.speakers = [
        StudioSpeaker(id="S00", name="A"),
        StudioSpeaker(id="S01", name="B"),
    ]
    project.cues = [
        StudioCue(id="c1", start_ms=0, end_ms=900, text="保留", speaker_id="S00"),
        StudioCue(id="c2", start_ms=1000, end_ms=1900, text="隐藏", speaker_id="S01"),
    ]
    SetSpeakersVisibilityCommand(project, ["S01"], None).redo()
    artifacts = export_subtitle_artifacts(
        project, str(tmp_path), "out", SubtitleExportOptions(frozenset({"srt"}), "combined")
    )
    content = artifacts[0].path.read_text(encoding="utf-8")
    assert "保留" in content
    assert "隐藏" not in content, "隐藏说话人的字幕不得进入成片导出"
    assert artifacts[0].cue_count == 1


def test_host_command_is_unique_and_undoable(tmp_path):
    from twobyteasr.timeline.studio_commands import SetHostSpeakerCommand
    from twobyteasr.projects.studio_project import StudioSpeaker, SubtitleProject

    project = SubtitleProject(media=_fake_media(tmp_path))
    project.speakers = [
        StudioSpeaker(id="S00"),
        StudioSpeaker(id="S01"),
        StudioSpeaker(id="S02"),
    ]
    command = SetHostSpeakerCommand(project, "S01", None)
    command.redo()
    assert [s.is_host for s in project.speakers] == [False, True, False]
    command.undo()
    assert not any(s.is_host for s in project.speakers)
