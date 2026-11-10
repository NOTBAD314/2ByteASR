from types import SimpleNamespace
import json

import subtitle_core as core
from twobyteasr.recognition.streaming_recognition import LongMediaPipeline, ShardResult
from twobyteasr.recognition.vad import ALGORITHM


def pipeline():
    instance = LongMediaPipeline.__new__(LongMediaPipeline)
    instance.legacy = SimpleNamespace(
        GROUP_LOGIC_VERSION=core.GROUP_LOGIC_VERSION,
        serialize_cues=core.serialize_cues,
        deserialize_cues=core.deserialize_cues,
        serialize_segments=core.serialize_segments,
        deserialize_segments=core.deserialize_segments,
    )
    instance.vad_execution = dict(
        requested_backend="firered_vad", actual_backend="firered_vad",
        degraded=False, algorithm_version=ALGORITHM)
    instance.vad_execution_by_index = {}
    return instance


def result():
    return ShardResult(0, "fixed-input", [],
        [core.SpeechSegment(1, 0, 1, "继续处理字幕", .9, [])],
        [core.SubtitleCue(1, 0, 1, "继续处理字幕")], {}, [])


def test_current_ready_checkpoint_reuses_the_same_rule_identity(tmp_path):
    instance = pipeline()
    path = tmp_path / "ready.json"
    instance._save(path, result())
    assert instance._load(path, "fixed-input") is not None


def test_rule_upgrade_rejects_derived_result_without_changing_input_identity(tmp_path):
    instance = pipeline()
    path = tmp_path / "ready.json"
    instance._save(path, result())
    saved = json.loads(path.read_text(encoding="utf-8"))
    instance.legacy.GROUP_LOGIC_VERSION = "next-grouping-rule"
    assert instance._load(path, "fixed-input") is None
    assert json.loads(path.read_text(encoding="utf-8")) == saved
    assert saved["version"] == "fixed-input"


def test_legacy_ready_record_without_rule_identity_requires_local_revalidation(tmp_path):
    from twobyteasr.recognition.streaming_recognition import _digest
    instance = pipeline()
    path = tmp_path / "ready.json"
    instance._save(path, result())
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["data"].pop("grouping_rules")
    saved["checksum"] = _digest(saved["data"])
    path.write_text(json.dumps(saved), encoding="utf-8")
    assert instance._load(path, "fixed-input") is None
