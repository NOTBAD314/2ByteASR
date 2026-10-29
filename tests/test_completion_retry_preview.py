"""Completion retry restores raw records and projects only safe review proposals."""
import copy
import json
from types import SimpleNamespace

import pytest
from tests.test_stage9_cache_and_budget import context
from tests.test_stage9_provider_snapshot import config
from twobyteasr.app import completion_retry
from twobyteasr.glossary import domain_terms
from twobyteasr.recognition.service import RunOptions
from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue


def project():
    rows = {}
    for record_id in (1, 2, 3):
        text = '待重试原文' if record_id == 2 else '成功邻句' + str(record_id)
        rows['segment:' + str(record_id)] = {'text': text, 'start_ms': record_id * 1000,
            'end_ms': (record_id + 1) * 1000, 'speaker_id': 'S01', 'confidence': .8,
            'moss_text': text, 'firered_text': text, 'qwen_asr_text': text,
            'caption_arbitration': {'terminology_polish': {
                'response_state': 'fallback' if record_id == 2 else 'validated', 'original_text': text}}}
    return SubtitleProject(media=StudioMedia(path='private-source.mp4'),
        cues=[StudioCue(id='projected-' + str(i), start_ms=i*1000, end_ms=(i+1)*1000,
            text=rows['segment:' + str(i)]['text'], evidence_refs=['segment:' + str(i)]) for i in (1, 2, 3)],
        asr_evidence=rows, generation_metadata={'terminology_snapshot': {}}, glossary_ids=[])


def test_retry_service_preserves_raw_id_scope_without_queue_asr_or_saving(context, monkeypatch):
    import moss_firered_pipeline as pipeline
    from twobyteasr.recognition import service
    from twobyteasr.projects import studio_project
    _, _, cache = context
    original = project()
    before = copy.deepcopy((original.asr_evidence, original.cues))
    calls = []
    def complete(messages, **kwargs):
        ids = [row['id'] for row in json.loads(messages[1]['content'])['cues']]
        calls.append(ids)
        return json.dumps({'checked_ids': ids, 'cues': []})
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: SimpleNamespace(complete=complete))
    monkeypatch.setattr(service, 'run_media_queue', lambda *a, **k: pytest.fail('retry entered full queue'))
    monkeypatch.setattr(pipeline, 'transcribe_moss_global', lambda *a, **k: pytest.fail('retry ran MOSS'))
    monkeypatch.setattr(studio_project, 'save_project', lambda *a, **k: pytest.fail('preview saved user project'))
    report = {'started_at': 'parent-task', 'polishing_summary': {'success_cues': 2, 'fallback_cues': 1}}
    result = completion_retry.completion_retry_preview(original, report,
        RunOptions(settings_snapshot_json=json.dumps(config())), cache_context=cache)
    assert calls == [[2]] and result.receipt['scope_ids'] == [2]
    assert result.receipt['successful_ids'] == [2] and not result.receipt['asr_run']
    assert result.receipt['source_processing_records'] == 3 and result.receipt['projected_subtitles'] == 3
    assert result.hits == () and (original.asr_evidence, original.cues) == before


def test_processing_record_ids_do_not_use_projected_cue_ids():
    original = project()
    original.cues.append(StudioCue(id='extra-final-cue', start_ms=3800, end_ms=4000, text='拆分'))
    restored = completion_retry.processing_records(original)
    assert [row.segment_id for row in restored] == [1, 2, 3]
    assert len(original.cues) == 4


def test_split_record_projection_does_not_duplicate_whole_segment_or_override_manual_text():
    original = SubtitleProject(media=StudioMedia(path='private.mp4'), asr_evidence={'segment:7': {
        'text': '旧名后半', 'start_ms': 0, 'end_ms': 2000, 'speaker_id': 'S01',
        'words': [{'text': '旧名', 'start_ms': 0, 'end_ms': 1000},
                  {'text': '后半', 'start_ms': 1000, 'end_ms': 2000}]}},
        cues=[StudioCue(id='first', start_ms=0, end_ms=1000, text='旧名', evidence_refs=['segment:7']),
              StudioCue(id='second', start_ms=1000, end_ms=2000, text='后半', evidence_refs=['segment:7'])])
    hits, pending = completion_retry._project_proposals(original, {7: '新名后半'}, 'polish')
    assert [(hit.cue_id, hit.original, hit.replacement) for hit in hits] == [('first', '旧名', '新名')]
    assert pending == [] and [cue.text for cue in original.cues] == ['旧名', '后半']
    original.cues[0].text = '人工确认'
    hits, pending = completion_retry._project_proposals(original, {7: '新名后半'}, 'polish')
    assert hits == () and pending and original.cues[0].text == '人工确认'


def test_old_failure_count_without_record_evidence_does_not_guess_scope(context, monkeypatch):
    original = project()
    for row in original.asr_evidence.values():
        row['caption_arbitration']['terminology_polish']['response_state'] = 'validated'
    monkeypatch.setattr('twobyteasr.providers.ai_providers.provider_for_stage', lambda *a, **k: pytest.fail('unknown scope requested records'))
    with pytest.raises(ValueError, match='失败处理记录范围'):
        completion_retry.completion_retry_preview(original,
            {'polishing_summary': {'fallback_cues': 1}}, RunOptions(settings_snapshot_json=json.dumps(config())))


def test_original_snapshot_honors_selected_profile_and_rejects_changed_provider(context, monkeypatch):
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    from dataclasses import replace
    original = project()
    settings = config()
    snapshot = resolve_provider_snapshot(settings, stage='polish')
    report = {'events': [{'event': 'asr_provider_snapshot', 'stage': 'polished', **snapshot.public_identity()}]}
    options = RunOptions(settings_snapshot_json=json.dumps(settings))
    pinned = completion_retry._retry_options(original, report, options)
    assert resolve_provider_snapshot(json.loads(pinned.settings_snapshot_json), stage='polish').provider == snapshot.provider
    changed = replace(options, settings_snapshot_json=json.dumps(config('grok_account')))
    with pytest.raises(ValueError, match='文字服务身份不一致'):
        completion_retry._retry_options(original, report, changed)


def test_report_endpoint_mismatch_cannot_redirect_retry(context):
    from twobyteasr.providers.asr_provider_snapshot import resolve_provider_snapshot
    original = project()
    snapshot = resolve_provider_snapshot(config(), stage='polish')
    report = {'events': [{'event': 'asr_provider_snapshot', 'stage': 'polished', **snapshot.public_identity()}],
        'settings': {'models': {'polish_base_url': 'https://other.example/v1'}}}
    with pytest.raises(ValueError, match='文字服务地址不一致'):
        completion_retry._retry_options(original, report, None)
