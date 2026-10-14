"""No-CUDA cloud flow, round 2 (2026-10-14): timing honesty and resumable jobs.

Covers fixes from the round-2 audits: Qwen-Audio speaker 0, zero-length
provider words, MOSS Pro resubmission after explicit confirmation, MOSS Pro
chunk seams at the quietest second, provider multi-character words kept whole
as measured evidence, sentence-only rows marked as estimates, and a pre-run
summary that matches what actually runs. No network access.
"""
import json
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from twobyteasr.qwen31_asr import ASRProtocolError


# --- speaker 0 -------------------------------------------------------------------

def test_speaker_zero_words_stay_with_speaker_zero_inside_an_overlap():
    from twobyteasr.asr import _api_transcription_rows
    # Two diarized sentences overlap; speaker 0's word lies inside both.
    result = {'segments': [{'start': 0.0, 'end': 2.0, 'text': '你好世界', 'speaker': 0},
                           {'start': 0.5, 'end': 2.5, 'text': '再见', 'speaker': 1}],
              'words': [{'start': 0.1, 'end': 0.6, 'text': '你好', 'speaker': 0},
                        {'start': 0.7, 'end': 1.9, 'text': '世界', 'speaker': 0},
                        {'start': 0.8, 'end': 2.4, 'text': '再见', 'speaker': 1}]}
    rows = _api_transcription_rows(result, {'start': 0.0, 'end': 3.0})
    by_speaker = {}
    for row in rows:
        by_speaker.setdefault(row['speaker'], []).append(row['text'])
    assert ''.join(by_speaker['S00']) == '你好世界'
    assert ''.join(by_speaker['S01']) == '再见'


# --- Filetrans validation ---------------------------------------------------------

def test_zero_length_provider_word_does_not_fail_the_paid_job():
    from twobyteasr.cloud_asr_jobs import validate_filetrans_result
    sentence = {'begin_time': 100, 'end_time': 900, 'text': '好。',
                'words': [{'begin_time': 400, 'end_time': 400, 'text': '好', 'punctuation': '。'}]}
    validate_filetrans_result({'transcripts': [{'sentences': [sentence]}]}, 1.0)
    reversed_word = dict(sentence, words=[{'begin_time': 500, 'end_time': 400, 'text': '好'}])
    with pytest.raises(ASRProtocolError, match='词时间非法'):
        validate_filetrans_result({'transcripts': [{'sentences': [reversed_word]}]}, 1.0)
    outside = dict(sentence, end_time=1500)
    with pytest.raises(ASRProtocolError, match='句时间非法'):
        validate_filetrans_result({'transcripts': [{'sentences': [outside]}]}, 1.0)


# --- MOSS Pro: explicit resubmission, seams ----------------------------------------

class Response:
    def __init__(self, data, code=200):
        self.data, self.status_code = data, code

    def json(self):
        return self.data


class Mosi:
    def __init__(self, error=None):
        self.posts, self.error = [], error

    def post(self, url, **kw):
        self.posts.append(url)
        if self.error:
            raise self.error
        return Response({'id': 't1', 'task_id': 't1', 'status': 'PENDING', 'retry_after': 2})

    def get(self, url, **kw):
        return Response({'id': 't1', 'status': 'SUCCESS', 'text': '你好。',
                         'segments': [{'speaker': 'S01', 'text': '你好。', 'start': 0.1, 'end': 0.6}]})


def endpoint():
    return dict(model='moss-transcribe-diarize-pro', provider='mosi_moss_pro', protocol='mosi_transcriptions',
                url='https://api.mosi.cn/v1', api_key='sk-test', speaker_source='native')


def test_mosi_uncertain_upload_is_resubmitted_only_after_explicit_confirmation(tmp_path):
    import requests
    from twobyteasr.mosi_asr import transcribe
    audio = np.zeros(16000, dtype=np.float32)
    lost = Mosi(error=requests.exceptions.ConnectionError('reset'))
    with pytest.raises(ASRProtocolError) as error:
        transcribe(audio, endpoint(), tmp_path, client=lost)
    assert error.value.category == 'submission_uncertain'
    healthy = Mosi()
    with pytest.raises(ASRProtocolError):
        transcribe(audio, endpoint(), tmp_path, client=healthy)       # not without the user's confirmation
    assert healthy.posts == []
    events = []
    rows = transcribe(audio, endpoint(), tmp_path, client=healthy, sleep=lambda *_: None, restart_terminal=True,
                      progress=lambda state, *_: events.append(state))
    assert len(healthy.posts) == 1 and rows and 'explicit_restart_uncertain' in events
    assert list(tmp_path.rglob('previous-task-*.json'))  # the uncertain attempt is kept for the record


def test_worker_passes_the_confirmation_to_mosi(monkeypatch, tmp_path):
    from twobyteasr import cloud_api_worker, mosi_asr
    seen = {}

    def fake(audio, endpoint, cache, **kw):
        seen.update(kw)
        return []

    monkeypatch.setattr(mosi_asr, 'transcribe', fake)
    monkeypatch.setattr('twobyteasr.llm_config.validate_qwen_asr_endpoint', lambda e: e)
    np.save(tmp_path / 'a.npy', np.zeros(1600, dtype=np.float32))
    request = dict(audio_array=str(tmp_path / 'a.npy'), chunks=[], workers=1, settings={'models': {}},
                   job_id='j', native_job=True, endpoint=endpoint(), cancel_file=str(tmp_path / 'cancel'),
                   cache_root=str(tmp_path / 'cache'), restart_terminal=True)
    cloud_api_worker.run(request)
    assert seen['restart_terminal'] is True


def test_mosi_long_audio_is_cut_at_the_quietest_second_not_mid_speech():
    from twobyteasr import mosi_asr
    rate = 16000
    rng = np.random.default_rng(7)
    seconds = 70 * 60
    audio = (rng.standard_normal(seconds * rate).astype(np.float32) * 0.2)   # loud "game audio" everywhere
    quiet_at = 57 * 60                                                        # one quieter second, past 55 min
    audio[quiet_at * rate:(quiet_at + 1) * rate] *= 0.05
    ranges = mosi_asr.plan_ranges(audio)
    assert ranges[0][0] == 0 and ranges[-1][1] == len(audio)
    assert all(a[1] == b[0] for a, b in zip(ranges, ranges[1:]))
    assert all(end - start <= mosi_asr.MAX_AUDIO_SECONDS * rate for start, end in ranges)
    cut = ranges[0][1] / rate
    assert quiet_at <= cut <= quiet_at + 1


# --- provider word granularity, estimates ------------------------------------------

def _qwen3_rows():
    from twobyteasr.asr import _api_transcription_rows, _filetrans_task_rows
    payload = {'transcripts': [{'text': '欢迎使用阿里云。', 'sentences': [
        {'begin_time': 100, 'end_time': 1900, 'text': '欢迎使用阿里云。', 'words': [
            {'begin_time': 100, 'end_time': 500, 'text': '欢迎', 'punctuation': ''},
            {'begin_time': 500, 'end_time': 900, 'text': '使用', 'punctuation': ''},
            {'begin_time': 900, 'end_time': 1900, 'text': '阿里云', 'punctuation': '。'}]}]}]}
    converted = _filetrans_task_rows(payload, 2.0)
    converted['timestamp_source'] = 'qwen3_filetrans_native'
    return _api_transcription_rows(converted, dict(start=0, end=2.0))


def test_provider_words_are_kept_whole_as_measured_units():
    import subtitle_core as legacy
    import moss_firered_pipeline as pipeline
    rows = _qwen3_rows()
    assert rows and rows[0].get('tokens')
    segment, = pipeline.build_alternate_primary_segments(rows, [], legacy, 'api')
    timing = segment.caption_arbitration['word_timing']
    assert timing['basis'] == 'provider_words' and timing['display_subdivision'] == 'even_within_word'
    assert [w['text'] for w in timing['measured_words']] == ['欢迎', '使用', '阿里云']
    assert timing['measured_words'][2]['start_ms'] == 900 and timing['measured_words'][2]['end_ms'] == 1900
    # The per-character split still exists for display.
    assert ''.join(w.text for w in segment.words) == '欢迎使用阿里云'


def test_project_evidence_stores_provider_words_not_the_even_split(tmp_path, monkeypatch):
    import subtitle_core as legacy
    import moss_firered_pipeline as pipeline
    import twobyteasr.studio_project as storage
    from twobyteasr.studio_project import create_studio_outputs, load_project
    monkeypatch.setattr(storage, 'project_library_root', lambda *a, **k: tmp_path / 'Projects')
    media = tmp_path / 'clip.wav'
    with wave.open(str(media), 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\0\0' * 16000 * 2)
    segment, = pipeline.build_alternate_primary_segments(_qwen3_rows(), [], legacy, 'api')
    cue = SimpleNamespace(cue_id='c1', start=0.1, end=1.9, text='欢迎使用阿里云', speaker=segment.speaker,
                          segment_id=segment.segment_id)
    result = create_studio_outputs(media, [cue], txt_path='', segments=[segment])
    project = load_project(result['project'])
    row = next(iter(project.asr_evidence.values()))
    assert [w['text'] for w in row['words']] == ['欢迎', '使用', '阿里云']
    assert 'measured_words' not in row['caption_arbitration']['word_timing']
    assert row['caption_arbitration']['word_timing']['measured_word_count'] == 3
    from twobyteasr.word_timing_provenance import estimated_word_timing
    assert not estimated_word_timing(row)


def test_sentence_only_rows_without_timestamp_source_are_estimates():
    import subtitle_core as legacy
    import moss_firered_pipeline as pipeline
    # e.g. a Spark / OpenAI-compatible result with one segment and no words.
    segment, = pipeline.build_alternate_primary_segments(
        [{'start': 0.0, 'end': 2.0, 'text': '没有逐字时间的一句话', 'speaker': 'S00'}], [], legacy, 'api')
    assert segment.caption_arbitration['word_timing']['basis'] == 'uniform_display_estimate'
    assert segment.caption_arbitration['word_timing']['source'] == 'row_bounds'


def test_mlx_vad_window_rows_are_estimates_not_native_sentence_times():
    import subtitle_core as legacy
    import moss_firered_pipeline as pipeline
    segment, = pipeline.build_alternate_primary_segments(
        [{'start': 0.0, 'end': 3.0, 'text': '窗口里的一句话', 'speaker': 'S00', 'timestamp_source': 'vad_window'}],
        [], legacy, 'mlx_qwen3_asr')
    assert 'native sentence' not in segment.final_timing_owner
    assert 'estimated' in segment.final_timing_owner
    assert segment.caption_arbitration['word_timing']['source'] == 'vad_window_bounds'


# --- pre-run summary matches what runs ----------------------------------------------

def test_disclosure_names_the_cloud_review_upload_and_mlx():
    # 2026-10-14: the review stage runs again (probe fix approved by the user);
    # a cloud review uploads the whole audio once more and is confirmed first.
    from twobyteasr.recognition_choices import disclosure_text, run_disclosure
    moss = {'models': {'primary_asr_backend': 'moss', 'firered_asr_backend': 'local', 'qwen_asr_backend': 'api',
                       'qwen_asr_api_provider': 'mosi_moss_pro'}, 'switches': {}}
    info = run_disclosure(moss)
    review = [item for item in info['uploads'] if '文字复核' in item]
    assert review and review[0].startswith('音频') and '整段' in review[0] and 'MOSS' in review[0]
    assert info['paid'] and '不会运行' not in disclosure_text(moss)
    local = run_disclosure({'models': {'primary_asr_backend': 'moss', 'qwen_asr_backend': 'sensevoice'}, 'switches': {}})
    assert '文字复核：本地 SenseVoice' in local['local'] and not local['uploads']
    mac = {'models': {'primary_asr_backend': 'mlx_qwen3_asr_1_7b', 'firered_asr_backend': 'mlx_qwen_aligner',
                      'qwen_asr_backend': 'off'}, 'switches': {}}
    info = run_disclosure(mac)
    assert 'MLX' in info['engine'] and '1.7B' in info['engine'] and '对齐模型实测' in info['timestamps']
    assert not info['uploads'] and '不上传' in disclosure_text(mac)


def test_unavailable_on_host_names_the_limit():
    from twobyteasr.recognition_choices import HostProfile, unavailable_on_host
    no_gpu = HostProfile('win32', 'amd64', nvidia_tool=False, main_runtime=True, mlx_runtime=False)
    mac = HostProfile('darwin', 'arm64', nvidia_tool=False, main_runtime=False, mlx_runtime=True)
    assert unavailable_on_host('timeline', 'local', no_gpu) == '需要 NVIDIA 显卡'
    # 2026-10-14: MOSS runs on the Apple GPU of an Apple Silicon Mac; Qwen3-ASR local does not.
    assert unavailable_on_host('primary', 'moss', mac) == ''
    assert unavailable_on_host('primary', 'qwen_local', mac) == '需要 NVIDIA 显卡'
    assert unavailable_on_host('timeline', 'qwen_aligner', no_gpu) == ''
    assert unavailable_on_host('primary', 'mlx_qwen3_asr', no_gpu) == '只能在 Apple Silicon Mac 上运行'
    assert unavailable_on_host('primary', 'mlx_qwen3_asr', mac) == ''
    assert unavailable_on_host('primary', 'api', no_gpu) == ''


def test_stage_probes_are_absent_for_non_local_backends():
    """2026-10-14: a probe written as ``lambda: probe() if local else None`` is
    always callable and returned None for non-local backends, so the stage was
    skipped as probe_failed. Every ``environment_probe=`` must decide outside
    the lambda (an IfExp whose branches are a lambda and None)."""
    import ast
    from pathlib import Path
    tree = ast.parse(Path(__file__).resolve().parents[1].joinpath('moss_firered_pipeline.py').read_text('utf-8'))
    probes = [kw.value for node in ast.walk(tree) if isinstance(node, ast.Call)
              for kw in node.keywords if kw.arg == 'environment_probe']
    assert len(probes) >= 2
    for value in probes:
        assert not (isinstance(value, ast.Lambda) and isinstance(value.body, ast.IfExp)), ast.unparse(value)
        if isinstance(value, ast.IfExp):
            assert isinstance(value.body, ast.Lambda) and isinstance(value.orelse, ast.Constant), ast.unparse(value)


def test_timeline_stage_gate_never_borrows_firered_paths():
    """2026-10-14: the Qwen3 aligner (CPU or Mac MLX) stage was gated on
    FireRed's source and model folders, so without FireRed installed (the
    no-NVIDIA computer) it failed as environment_missing and no word timing
    was produced. The timeline stage's ``worker=``/``runtime=`` must not name
    FIRERED_SOURCE_DIR / FIRERED_MODEL_DIR."""
    import ast
    from pathlib import Path
    tree = ast.parse(Path(__file__).resolve().parents[1].joinpath('moss_firered_pipeline.py').read_text('utf-8'))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and getattr(node.func, 'id', '') == '_run_audited_model_stage'
             and any(kw.arg == 'role' and isinstance(kw.value, ast.Constant) and kw.value.value == 'timeline_alignment'
                     for kw in node.keywords)]
    assert calls
    for call in calls:
        model = next(kw.value for kw in call.keywords if kw.arg == 'model_id')
        if isinstance(model, ast.Constant) and model.value == 'firered':
            continue  # FireRed itself is the timeline: its own folders are the right gate
        for kw in call.keywords:
            if kw.arg in ('worker', 'runtime'):
                text = ast.unparse(kw.value)
                assert 'FIRERED_SOURCE_DIR' not in text and 'FIRERED_MODEL_DIR' not in text, text
    source = Path(__file__).resolve().parents[1].joinpath('moss_firered_pipeline.py').read_text('utf-8')
    assert 'resolve_qwen_aligner_local_source() or ""' in source and '_mlx_model_dir(_MLX_ALIGNER)' in source
