import json

import subtitle_core
from twobyteasr.recognition.run_context import activate_runtime_context, get_runtime_context
from twobyteasr.recognition.service import RunOptions


def _moss_task_context(expected_speakers):
    # Exercise the same frozen RunOptions -> RuntimeContext ownership as a
    # production queue, not an obsolete standalone facade attribute.
    settings = {"models": {"primary_asr_backend": "moss", "speaker_source": "moss"}}
    return RunOptions(expected_speakers=expected_speakers,
        dialogue_coverage_mode="host_priority",
        settings_snapshot_json=json.dumps(settings)).create_runtime_context(subtitle_core)


def test_primary_speaker_cache_changes_with_expected_speaker_count(monkeypatch):
    signatures = []
    previous = get_runtime_context()
    for count in (2, 3):
        context = _moss_task_context(count)
        assert context.speaker_source == "moss" and context.expected_speakers == count
        with activate_runtime_context(context, legacy=subtitle_core):
            signatures.append(subtitle_core.cache_stage_signature(
                "firered_primary", extra={"moss": "same-recognition"}))
    assert signatures[0] != signatures[1]
    assert get_runtime_context() is previous


def test_primary_speaker_cache_and_host_filter_share_frozen_task_count(monkeypatch):
    import moss_firered_pipeline as pipeline
    monkeypatch.setattr(subtitle_core, "add_review_item", lambda *a, **k: None)
    rows = [dict(speaker=speaker, start=float(start), end=float(start + 2), text="真实规则fixture")
        for speaker in ("S01", "S02", "S03") for start in (0, 60, 120)]
    previous = get_runtime_context()
    signatures = []
    for count in (2, 3):
        context = _moss_task_context(count)
        with activate_runtime_context(context, legacy=subtitle_core):
            signature = subtitle_core.cache_stage_signature("firered_primary", extra={"moss": "same-recognition"})
            # A stale facade write cannot change an already frozen task's cache
            # identity or the MOSS host filter used to assemble that task.
            subtitle_core.RUNTIME_EXPECTED_SPEAKERS = 6
            assert subtitle_core.cache_stage_signature("firered_primary", extra={"moss": "same-recognition"}) == signature
            assert len(pipeline.select_host_speakers(rows, 180.0, subtitle_core, context)) == count
            signatures.append(signature)
    assert signatures[0] != signatures[1]
    assert get_runtime_context() is previous
    assert subtitle_core.RUNTIME_EXPECTED_SPEAKERS == previous.expected_speakers
