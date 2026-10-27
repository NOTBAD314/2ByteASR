import copy
import pytest

from twobyteasr.forced_alignment import ALIGNER_CODE, ALIGNER_REPO, ALIGNER_REVISION, UNIT_POLICY_VERSION
from twobyteasr.recognition.transcript_data import SubtitleCue
from twobyteasr.recognition.word_evidence_reuse import plan_reuse


def payload():
    text = 'hello world again'
    spans = [(0, 5, 100, 400), (6, 11, 450, 800), (12, 17, 850, 1200)]
    pieces = [dict(char_start=a, char_end=b, start_ms=start, end_ms=end,
                   granularity='word', start_basis='model', end_basis='model')
              for a, b, start, end in spans]
    return {'protocol': 'qwen-aligner-units-v1', 'model': ALIGNER_REPO,
            'model_revision': ALIGNER_REVISION, 'code': ALIGNER_CODE, 'unit_policy': UNIT_POLICY_VERSION,
            'policy': {'version': 'qwen-aligner-units-v1', 'sample_rate': 16000, 'audio_format': 'float32-mono-npy-v1'},
            'audio_sha256': 'audio', 'results': [{'id': 'S01@0-1500', 'text': text,
            'status': 'aligned', 'language': 'English', 'window_start_ms': 0, 'window_end_ms': 1500,
            'segments': pieces, 'word_units': []}]}


def cues():
    return [SubtitleCue(1, 0., .82, 'Hello, world!', speaker='S01'),
            SubtitleCue(2, .82, 1.4, 'again', speaker='S01')]


def test_punctuation_and_grouping_reuse_measured_units_without_moving_cues():
    values = cues()
    before = [(cue.text, cue.start, cue.end, cue.speaker) for cue in values]
    reused, reasons = plan_reuse(values, payload(), language='English', audio_digest='audio')
    assert set(reused) == {1, 2} and not reasons
    assert [(p['start_ms'], p['end_ms']) for p in reused[1]['segments']] == [(100, 400), (450, 800)]
    assert [(cue.text, cue.start, cue.end, cue.speaker) for cue in values] == before
    assert reused[1]['run']['source'] == 'source-word-evidence-v1'


def test_changed_word_invalidates_its_cue_but_not_unchanged_neighbor():
    values = cues()
    values[0].text = 'Hello, planet!'
    reused, reasons = plan_reuse(values, payload(), language='English', audio_digest='audio')
    assert set(reused) == {2}
    assert reasons['text_changed_or_unmapped'] == 1


def test_wrong_audio_speaker_and_unmeasured_time_are_never_reused():
    assert not plan_reuse(cues(), payload(), language='English', audio_digest='other')[0]
    values = cues()
    values[0].speaker = 'S02'
    reused, reasons = plan_reuse(values, payload(), language='English', audio_digest='audio')
    assert set(reused) == {2} and reasons['speaker_or_status'] == 1
    data = payload()
    data['results'][0]['segments'][0]['start_basis'] = 'interpolated'
    reused, reasons = plan_reuse(cues(), data, language='English', audio_digest='audio')
    assert set(reused) == {2} and reasons['unmeasured_or_outside_cue'] == 1


def test_a_measured_unit_crossing_a_new_cue_boundary_is_not_split():
    data = payload()
    first, second, third = data['results'][0]['segments']
    merged = dict(first, char_end=second['char_end'], end_ms=second['end_ms'], granularity='merged')
    data['results'][0]['segments'] = [merged, third]
    split = [SubtitleCue(1, 0., .43, 'hello', speaker='S01'),
             SubtitleCue(2, .43, .82, 'world', speaker='S01'),
             SubtitleCue(3, .82, 1.4, 'again', speaker='S01')]
    reused, reasons = plan_reuse(split, data, language='English', audio_digest='audio')
    assert set(reused) == {3} and reasons['incomplete_or_crossing_unit'] == 2


def test_duplicate_receipt_and_model_version_are_rejected():
    data = payload()
    data['results'].append(copy.deepcopy(data['results'][0]))
    assert not plan_reuse(cues(), data, language='English', audio_digest='audio')[0]
    data = payload()
    data['model_revision'] = 'other'
    assert not plan_reuse(cues(), data, language='English', audio_digest='audio')[0]


def test_wrong_audio_format_and_language_are_rejected():
    data = payload()
    data['policy']['sample_rate'] = 8000
    assert not plan_reuse(cues(), data, language='English', audio_digest='audio')[0]
    data = payload()
    data['results'][0]['language'] = 'Chinese'
    assert not plan_reuse(cues(), data, language='English', audio_digest='audio')[0]


def test_nearby_local_windows_do_not_overlap():
    from twobyteasr.recognition.cue_forced_alignment import local_alignment_jobs
    values = [SubtitleCue(i + 1, i * .2, i * .2 + .19, f'word{i}', speaker='S01') for i in range(8)]
    jobs, runs, targets = local_alignment_jobs(values, {1, 3, 4, 5, 6, 8}, language='English')
    assert targets == {2, 7}
    assert len(jobs) == 1
    assert [member['key'] for member in runs[0]['members']] == list(range(1, 9))


def test_local_jobs_include_only_changed_cue_and_neighbors_as_context():
    from twobyteasr.recognition.cue_forced_alignment import local_alignment_jobs
    values = [SubtitleCue(i + 1, i * 2., i * 2. + 1.8, f'word{i}', speaker='S01') for i in range(7)]
    jobs, runs, targets = local_alignment_jobs(values, {1, 2, 3, 5, 6, 7}, language='English')
    assert len(jobs) == 1 and targets == {4}
    assert [member['key'] for member in runs[0]['members']] == [3, 4, 5]
    assert jobs[0]['window_start_ms'] >= 3700 and jobs[0]['window_end_ms'] <= 10100


def test_complete_reuse_avoids_second_worker(monkeypatch):
    import numpy as np
    from types import SimpleNamespace
    from twobyteasr.recognition import asr
    from twobyteasr.recognition.cue_forced_alignment import align_final_cues
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.recognition.word_evidence_reuse import audio_sha256
    audio = np.zeros(16000 * 2, dtype=np.float32)
    data = payload()
    data['audio_sha256'] = audio_sha256(audio)
    values = cues()
    events = []
    legacy = SimpleNamespace(add_review_item=lambda *a, **k: None,
                             record_run_event=lambda name, **kw: events.append((name, kw)))
    monkeypatch.setattr(asr, 'run_qwen_aligner_worker', lambda *a, **k: pytest.fail('no second worker'))
    context = RuntimeContext()
    context.segment_alignment_evidence = {'audio': audio, 'payload': data, 'language': 'English', 'job_id': context.job_id}
    with activate_runtime_context(context):
        assert align_final_cues(values, audio, legacy, language='English') == 2
    assert context.segment_alignment_evidence is None
    assert all(cue.forced_alignment['run']['source'] == 'source-word-evidence-v1' for cue in values)
    plan = next(row for name, row in events if name == 'forced_alignment_reuse_plan')
    assert plan['reused_cues'] == 2 and plan['local_jobs'] == 0


def test_changed_word_runs_local_alignment_without_replacing_reused_neighbor(monkeypatch):
    import numpy as np
    from types import SimpleNamespace
    from twobyteasr.recognition import asr, cue_forced_alignment as alignment
    from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context
    from twobyteasr.recognition.word_evidence_reuse import audio_sha256
    audio = np.zeros(16000 * 2, dtype=np.float32)
    data = payload()
    data['audio_sha256'] = audio_sha256(audio)
    values = cues()
    values[0].text = 'Hello, planet!'
    seen, events = [], []
    def worker(_audio, jobs):
        seen.extend(jobs)
        text = jobs[0]['text']
        spans = [(text.index('Hello'), text.index('Hello') + 5, 100, 400),
                 (text.index('planet'), text.index('planet') + 6, 450, 800),
                 (text.index('again'), text.index('again') + 5, 850, 1200)]
        pieces = [dict(char_start=a, char_end=b, start_ms=x, end_ms=y, granularity='word',
                       start_basis='model', end_basis='model') for a, b, x, y in spans]
        return {'protocol':'qwen-aligner-units-v1', 'model':ALIGNER_REPO,
                'results':[dict(id=jobs[0]['id'], text=text, language='English', status='aligned',
                                window_start_ms=0, window_end_ms=1500, segments=pieces)]}
    monkeypatch.setattr(asr, 'run_qwen_aligner_worker', worker)
    monkeypatch.setattr(alignment, '_predicted_second_engine', lambda jobs: '')
    monkeypatch.setattr(alignment, 'second_opinion', lambda *a, **k: None)
    legacy = SimpleNamespace(add_review_item=lambda *a, **k: None,
                             record_run_event=lambda name, **kw: events.append((name, kw)))
    context = RuntimeContext()
    context.segment_alignment_evidence = {'audio': audio, 'payload': data, 'language': 'English', 'job_id': context.job_id}
    with activate_runtime_context(context):
        assert alignment.align_final_cues(values, audio, legacy, language='English') == 2
    assert len(seen) == 1 and seen[0]['text'] == 'Hello, planet! again'
    assert values[1].forced_alignment['run']['source'] == 'source-word-evidence-v1'
    assert values[0].forced_alignment['text'] == 'Hello, planet!'
    assert values[0].forced_alignment['segments'][1]['char_start'] == 7
    plan = next(row for name, row in events if name == 'forced_alignment_reuse_plan')
    assert plan['reused_cues'] == 1 and plan['invalidated_cues'] == 1 and plan['local_jobs'] == 1
