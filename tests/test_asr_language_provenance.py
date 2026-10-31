"""Request/response boundary regressions; HTTP and ASR responses are simulated."""
from contextlib import nullcontext
from types import SimpleNamespace
import copy
import json
import re

import numpy as np
import pytest

EN = ("Today we will look at the color controls in this image. We can see the details on her face. "
      "I will double click the saturation parameter to reset it. Then we will use the other controls "
      "to adjust the image. This is the original image and this is the result. ") * 4
IT = ("Oggi vedremo il colore della immagine. Questo è un esempio per la lezione. "
      "Quindi farò un doppio clic sul parametro di saturazione per resettarlo. "
      "Non cambiamo la immagine originale e non perdiamo il lavoro. "
      "Questo è il risultato della lezione e sono qui per mostrare il colore. ") * 4


class StopAfterLanguage(BaseException):
    pass


@pytest.mark.parametrize('requested,text,warning', [('en', IT, True), ('en', EN, False),
                                                  ('it', IT, False), ('auto', IT, False),
                                                  ('en', EN + ' DaVinci, ciao, chiaroscuro.', False)],
                         ids=['english-conflict', 'english', 'italian', 'automatic', 'foreign-terms'])
def test_pipeline_warns_once_before_alignment_without_rewriting(monkeypatch, tmp_path, requested, text, warning):
    import moss_firered_pipeline as pipeline
    from twobyteasr.recognition import asr_progress, speaker_strategy
    from twobyteasr.recognition.run_context import RuntimeContext
    context = RuntimeContext(requested_language=requested)
    source = tmp_path / 'input.mp4'
    source.write_bytes(b'isolated transport fixture')
    rows = [dict(start=0., end=60., text=text, speaker='S01')]
    original = copy.deepcopy(rows)
    events, warnings = [], []
    legacy = SimpleNamespace(
        RUNTIME_SETTINGS={}, PRIMARY_ASR_BACKEND='api', FIRERED_ASR_BACKEND='qwen_aligner',
        PARALLEL_GPU_ASR=False, PARALLEL_CPU_VAD=False, USE_FIRERED_BOUNDARY_REFINEMENT=False,
        AUDIO_SAMPLE_RATE=16000, reset_review_items=lambda: None,
        output_paths_for_media=lambda p: ('unused.txt', 'unused.srt'), detect_timeline_fps=lambda p: 25,
        media_cache_context=lambda p: {'cache_dir': str(tmp_path)}, begin_media_report=lambda *a: None,
        run_timed_stage=lambda n, total, label, resource, run: run(),
        run_cached_stage=lambda name, cache, run, **kw: run(),
        load_shared_audio=lambda *a: np.zeros(16000, dtype=np.float32),
        record_run_event=lambda name, **data: events.append((name, data)),
        add_review_item=lambda *a, **kw: warnings.append((a, kw)),
        capture_review_items=lambda: nullcontext([]), extend_review_items=lambda rows: None,
        transcribe_primary_reference=lambda *a: rows,
    )
    monkeypatch.setattr(pipeline, '_script_paths', lambda _: {'firered_vad': str(tmp_path/'missing'),
                        'firered_worker': '', 'main_python': '', 'firered_source': ''})
    monkeypatch.setattr(pipeline, '_moss_stage_signature', lambda _: {})
    monkeypatch.setattr(pipeline, '_cloud_hint_signature', lambda *a: {})
    monkeypatch.setattr(pipeline, '_gpu_runtime_snapshot', lambda: {})
    monkeypatch.setattr(asr_progress, 'api_local_admission', lambda *a, **kw: {'admitted': True})
    monkeypatch.setattr(pipeline, 'detect_lightweight_vad', lambda *a: [dict(start=0, end=1)])
    monkeypatch.setattr(pipeline, '_run_audited_model_stage', lambda *a, runner, **kw: runner())
    def stop(*a, **kw):
        raise StopAfterLanguage()
    monkeypatch.setattr(speaker_strategy, 'resolve', stop)
    # A rejected all-conflict transcript now goes directly to the pending
    # project save, rather than continuing into speaker/timing processing.
    monkeypatch.setattr(pipeline, 'complete_media_run', stop)
    with pytest.raises(StopAfterLanguage):
        pipeline.process_media(str(source), 1, 1, legacy, context)
    assert bool(warnings) == warning
    assert len(warnings) <= 1 and rows == original
    assert context.requested_language == requested
    if requested != 'auto':
        assert context.task_language == requested
    assert any(name == 'primary_language_audit' for name, _ in events)
    if warning:
        assert context.transcript_acceptance['ranges'][0]['status'] == 'pending'
        assert warnings[0][1]['severity'] == 'warning'
        assert warnings[0][1]['retry_action'] == 'inspect_audio_then_recognize_range'


def test_language_dependent_caches_change_but_audio_does_not():
    import subtitle_core  # initialize the legacy cache facade
    from twobyteasr.recognition.cache import cache_stage_signature
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    def signatures(code, target='zh-Hans'):
        with activate_runtime_context(RuntimeContext(task_language=code, requested_language=code,
                                                    translation_script=target)):
            return {stage: cache_stage_signature(stage, {'same_input': True})
                    for stage in ['audio', 'firered_vad', 'firered_primary', 'final_timing', 'grouped_local']}
    en, it = signatures('en'), signatures('it')
    assert en['audio'] == it['audio'] and en['firered_vad'] == it['firered_vad']
    for stage in ['firered_primary', 'final_timing', 'grouped_local']:
        assert en[stage] != it[stage], stage
    assert en == signatures('en', 'ja')


def test_mixed_requests_warn_even_when_english_wins_the_whole_transcript():
    from twobyteasr.recognition.language_diagnostics import audit_primary_language
    from twobyteasr.subtitle_rules.language_rules import resolve_task_language
    from twobyteasr.recognition.run_context import RuntimeContext
    rows = [dict(start=0, end=300, text=IT), dict(start=400, end=700, text=EN * 3)]
    code, evidence = resolve_task_language('en', [r['text'] for r in rows])
    assert 'disagrees_with_transcript' not in evidence
    ctx = RuntimeContext(requested_language='en', task_language=code, language_evidence=evidence)
    warnings = []
    legacy = SimpleNamespace(record_run_event=lambda *a, **kw: None,
                             add_review_item=lambda *a, **kw: warnings.append((a, kw)))
    audit_primary_language(rows, ctx, legacy)
    audit_primary_language(rows, ctx, legacy)
    assert len(warnings) == 1
    assert warnings[0][1]['language_conflicts'][0]['transcript']['language'] == 'it'
    assert ctx.task_language == 'en' and ctx.language_evidence['asr_detected'] == ''


@pytest.mark.parametrize('text', ['Quindi farò un doppio clic sul parametro di saturazione per resettarlo',
                                'DaVinci Resolve chiaroscuro', 'hello', EN + ' ciao grazie'])
def test_short_or_mixed_foreign_terms_do_not_raise_a_language_conflict(text):
    from twobyteasr.recognition.language_diagnostics import transcript_language_sample
    assert transcript_language_sample([text])['language'] in (None, 'en')


def test_mosi_real_multipart_and_raw_response_receipts_survive_resume(tmp_path, monkeypatch):
    from tests.test_no_cuda_cloud_asr import MosiClient, mosi_endpoint
    from twobyteasr.providers import mosi_asr
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    monkeypatch.setattr(mosi_asr, 'plan_ranges', lambda a: [(0, 16000), (16000, 32000)])
    client = MosiClient(segments=[dict(start=.1, end=.9, text=IT, speaker='S01')])
    audio = np.zeros(32000, dtype=np.float32)
    endpoint = mosi_endpoint()
    with activate_runtime_context(RuntimeContext(requested_language='it')):
        first = mosi_asr.transcribe(audio, endpoint, tmp_path, client=client, sleep=lambda _: None)
    with activate_runtime_context(RuntimeContext(requested_language='en')):
        resumed = mosi_asr.transcribe(audio, endpoint, tmp_path, client=client, sleep=lambda _: None)
    assert len(client.posts) == 2  # two original requests; no extra upload on language-only change
    form = client.posts[0][1]['form']
    assert 'language' not in form and form['model'][2] == b'moss-transcribe-diarize-pro'
    assert [r['text'] for r in resumed] == [r['text'] for r in first]
    receipts = [r['asr_language_receipt'] for r in resumed if 'asr_language_receipt' in r]
    assert [r['request_index'] for r in receipts] == [0, 1]
    assert [r['start'] for r in receipts] == [0, 1]
    assert all(r['request_language'] is None and r['provider_detected_language'] is None for r in receipts)
    assert all(r['transcript']['language'] == 'it' for r in receipts)
    saved = list(tmp_path.rglob('submission-parameters.json'))
    assert len(saved) == 2 and all('language' not in json.loads(p.read_text('utf8')) for p in saved)
    assert 'sk-test' not in ''.join(p.read_text('utf8') for p in tmp_path.rglob('*.json'))


def test_worker_freezes_language_in_its_own_context(tmp_path, monkeypatch):
    from twobyteasr.providers import cloud_api_worker
    from twobyteasr.recognition import asr
    from twobyteasr.recognition.run_context import get_runtime_context
    p = tmp_path / 'audio.npy'
    np.save(p, np.zeros(16000, dtype=np.float32))
    seen = []
    def transcribe(*a, **kw):
        seen.append(get_runtime_context().requested_language)
        return []
    monkeypatch.setattr(asr, '_transcribe_qwen_api', transcribe)
    request = dict(audio_array=str(p), chunks=[dict(offset=0, samples=16000, start=0, end=1)], workers=1,
                   settings={}, job_id='a'*32, source_path='fixture.wav', publish_primary=True, endpoint={}, context='')
    for language in ['it', 'en', 'auto', 'it', 'en']:
        cloud_api_worker.run(dict(request, requested_language=language))
    assert seen == ['it', 'en', 'auto', 'it', 'en']


def test_raw_mosi_auto_cache_has_no_fabricated_language_dependency():
    from twobyteasr.providers.asr_api_process import cache_hint_signature
    from tests.test_no_cuda_cloud_asr import mosi_endpoint, qwen3_endpoint
    assert cache_hint_signature(mosi_endpoint(), {}, 'en') == cache_hint_signature(mosi_endpoint(), {}, 'it')
    endpoint = qwen3_endpoint()
    assert cache_hint_signature(endpoint, {}, 'en') != cache_hint_signature(endpoint, {}, 'it')


def test_parent_uses_frozen_selection_when_global_settings_change(tmp_path, monkeypatch):
    from twobyteasr.providers import asr_api_process, cloud_api_worker
    from twobyteasr.recognition import asr
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from tests.test_no_cuda_cloud_asr import mosi_endpoint
    captured = []
    def worker(*a, input_text, **kw):
        captured.append(json.loads(input_text))
        return {'results': []}
    monkeypatch.setattr(asr, '_run_isolated_asr_worker', worker)
    monkeypatch.setattr(asr, 'build_qwen_asr_context', lambda _: '')
    monkeypatch.setattr(cloud_api_worker, 'cloud_worker_command', lambda root: ['fixture-worker'])
    monkeypatch.setattr(asr, 'RUNTIME_SETTINGS', {'subtitle_language': {'recognition_language': 'it'}})
    ctx = RuntimeContext(requested_language='en', asr_endpoint_snapshot=mosi_endpoint(),
                         asr_settings_snapshot={'models': {}, 'subtitle_language': {'recognition_language': 'en'}})
    with activate_runtime_context(ctx):
        asr_api_process.transcribe('fixture.wav', [dict(audio=(np.zeros(16000, dtype=np.float32), 16000),
                                                       start=0., end=1.)])
    assert captured[0]['requested_language'] == 'en'
    assert captured[0]['settings']['subtitle_language']['recognition_language'] == 'en'


def test_interleaved_http_requests_do_not_mix_languages_or_audio(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from tests.test_no_cuda_cloud_asr import MosiClient, mosi_endpoint
    from twobyteasr.providers import mosi_asr
    def run(text, amplitude):
        client = MosiClient(segments=[dict(start=.1, end=.9, text=text, speaker='S01')])
        rows = mosi_asr.transcribe(np.full(16000, amplitude, dtype=np.float32), mosi_endpoint(), tmp_path,
                                   client=client, sleep=lambda _: None)
        return rows, client.posts[0][1]['form']['file'][2]
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(run, IT, .1), pool.submit(run, EN, .2)
        italian, italian_pcm = a.result()
        english, english_pcm = b.result()
    words = lambda text: re.findall(r"[^\W\d_]+", text)
    assert words(italian[0]['text']) == words(IT) and words(english[0]['text']) == words(EN)
    assert italian[0]['asr_language_receipt']['transcript']['language'] == 'it'
    assert english[0]['asr_language_receipt']['transcript']['language'] == 'en'
    assert italian_pcm != english_pcm
    assert len(list(tmp_path.rglob('input.json'))) == 2


def test_english_translation_roundtrip_and_exports_keep_source_roles(tmp_path):
    from tests.test_subtitle_translation import FakeProvider
    from twobyteasr.subtitle_rules import subtitle_translation as translation
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia, StudioCue, save_project, load_project
    from twobyteasr.exports.studio_subtitle_export import export_language_layers
    from twobyteasr.exports.srt_codec import parse_srt
    from twobyteasr.caption_style.bilingual_layout import project_display_cues
    text = 'So I will double-click the saturation parameter to reset it.'
    chinese = '所以我会双击饱和度参数把它重置。'
    project = SubtitleProject(StudioMedia('', duration_ms=10000),
                              cues=[StudioCue('stable-en', 1000, 4000, text, speaker_id='S01')],
                              generation_metadata={'language': {'code': 'en', 'requested': 'en'}})
    project.validate()
    provider = FakeProvider(lambda payload, n: {'items': [{'id': row['id'], 'translation': chinese}
                                                         for row in payload['lines'] if row['translate']]})
    result = translation.translate(project, None, provider, target='zh-Hans')
    translation.apply_translation_result(project, result)
    project.studio_state['bilingual'] = {'mode': 'bilingual'}
    reopened = load_project(save_project(project, tmp_path/'english.2byteproj'))
    assert reopened.cues[0].text == text and reopened.generation_metadata['translations']['stable-en'] == chinese
    assert {c.text for c in project_display_cues(reopened)} == {text, chinese}
    exported = export_language_layers(reopened, tmp_path/'export', 'english')
    for artifact in exported.artifacts:
        rows, errors = parse_srt(artifact.path.read_text('utf8'))
        assert not errors and rows
        combined = '\n'.join(r.text for r in rows)
        if artifact.layer in {'original', 'bilingual'}: assert text in combined
        if artifact.layer in {'translation', 'bilingual'}: assert chinese in combined


def test_selected_second_audio_stream_reaches_the_upload(tmp_path):
    import io
    import subprocess
    import wave
    from pathlib import Path
    from tests.test_no_cuda_cloud_asr import MosiClient, mosi_endpoint
    from twobyteasr.providers.mosi_asr import transcribe
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia
    from twobyteasr.recognition.recognition_input import capture_recognition_snapshot, prepare_recognition_input
    ffmpeg = Path(__file__).resolve().parents[1]/'tools/ffmpeg/bin/ffmpeg.exe'
    media = tmp_path/'two-tracks.mkv'
    subprocess.run([str(ffmpeg), '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2:sample_rate=48000',
                    '-f', 'lavfi', '-i', 'sine=frequency=880:duration=2:sample_rate=48000', '-map', '0:a', '-map', '1:a',
                    '-c:a', 'pcm_s16le', '-metadata:s:a:0', 'language=ita', '-metadata:s:a:1', 'language=eng',
                    str(media)], check=True)
    p = SubtitleProject(StudioMedia(str(media), duration_ms=2000))
    p.validate()
    p.audio_tracks[0].clips[0].stream_index = 1
    snapshot = capture_recognition_snapshot(p)
    assert {s['stream_index'] for s in snapshot['audio_graph']['segments']} == {1}
    wav = prepare_recognition_input(snapshot, tmp_path/'cache', ffmpeg)
    with wave.open(wav, 'rb') as w:
        chosen = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2')
    pcm = chosen.astype(np.float32)/32768
    client = MosiClient()
    transcribe(pcm, mosi_endpoint(), tmp_path/'jobs', client=client, sleep=lambda _: None)
    with wave.open(io.BytesIO(client.posts[0][1]['form']['file'][2]), 'rb') as w:
        uploaded = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2')
        assert w.getframerate() == 16000 and w.getnchannels() == 1
    assert len(chosen) == len(uploaded) and np.max(np.abs(chosen.astype(int)-uploaded.astype(int))) <= 1
    spectrum = np.abs(np.fft.rfft(uploaded[1600:-1600]))
    peak = np.argmax(spectrum)*16000/len(uploaded[1600:-1600])
    assert abs(peak-880) < 2  # selected audio ordinal 1, not container index 1
