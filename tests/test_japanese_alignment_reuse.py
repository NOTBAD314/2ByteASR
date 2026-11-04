import copy
from types import SimpleNamespace

import numpy as np
import pytest

from tests.test_word_evidence_reuse import payload
from twobyteasr.recognition.word_evidence_reuse import plan_reuse
from twobyteasr.recognition.alignment_audio import prepare_audio, pcm_digest
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context


def japanese():
    data = payload()
    row = data['results'][0]
    row.update(id='R001_S01@0-1500', text='今日は晴れ', language='Japanese')
    row['segments'] = [dict(char_start=a, char_end=b, start_ms=s, end_ms=e,
        granularity='word', start_basis='model', end_basis='model')
        for a, b, s, e in [(0, 2, 100, 400), (2, 3, 450, 600), (3, 5, 650, 1100)]]
    return data


def cue(text='今日は', start=0., end=.62, speaker='R001_S01'):
    return SimpleNamespace(text=text, start=start, end=end, speaker=speaker)


def test_exact_japanese_split_keeps_measured_times_and_does_not_touch_input():
    values = [cue('今日 は！'), cue('晴れ', .62, 1.3)]
    before = copy.deepcopy([vars(x) for x in values])
    reused, reasons = plan_reuse(values, japanese(), language='Japanese', audio_digest='audio')
    assert set(reused) == {1, 2} and not reasons
    assert [(x['start_ms'], x['end_ms']) for x in reused[1]['segments']] == [(100, 400), (450, 600)]
    assert [(x['char_start'], x['char_end']) for x in reused[1]['segments']] == [(0, 2), (3, 4)]
    assert [vars(x) for x in values] == before


@pytest.mark.parametrize('change', ['text', 'speaker', 'outside', 'repaired', 'audio', 'model'])
def test_changed_or_unmeasured_japanese_never_borrows_times(change):
    data, value, digest = japanese(), cue(), 'audio'
    if change == 'text': value.text = '明日は'
    if change == 'speaker': value.speaker = 'R002_S01'
    if change == 'outside': value.start, value.end = 10., 11.
    if change == 'repaired': data['results'][0]['segments'][0]['start_basis'] = 'nearest'
    if change == 'audio': digest = 'different'
    if change == 'model': data['model_revision'] = 'different'
    assert not plan_reuse([value], data, language='Japanese', audio_digest=digest)[0]


def test_repeated_response_in_two_overlapping_same_speaker_rows_is_ambiguous():
    data = japanese()
    row = copy.deepcopy(data['results'][0]); row['id'] = 'R001_S01@20-1520'
    data['results'].append(row)
    reused, reasons = plan_reuse([cue()], data, language='Japanese', audio_digest='audio')
    assert not reused and reasons['ambiguous_time_text'] == 1


def test_new_boundary_inside_a_measured_word_requires_local_alignment():
    assert not plan_reuse([cue('今')], japanese(), language='Japanese', audio_digest='audio')[0]


def test_full_read_only_pcm_file_is_borrowed_but_slices_are_not(tmp_path, monkeypatch):
    audio_path = tmp_path / 'original.npy'
    audio = np.arange(100, dtype=np.float32)
    np.save(audio_path, audio)
    pcm = np.load(audio_path, mmap_mode='r')
    context = RuntimeContext()
    with activate_runtime_context(context):
        first = prepare_audio(pcm, tmp_path)
        assert first['path'] == str(audio_path) and first['sha256'] == pcm_digest(audio)
        assert len(context.alignment_audio_inputs) == 1
        def forbid_save(*a, **kw): pytest.fail('full PCM must not be rewritten')
        with monkeypatch.context() as patch:
            patch.setattr(np, 'save', forbid_save)
            assert prepare_audio(pcm, tmp_path) == first
        sliced = prepare_audio(pcm[5:10], tmp_path)
        assert sliced['path'] != str(audio_path) and sliced['samples'] == 5
        assert np.array_equal(np.load(sliced['path']), audio[5:10])
    pcm._mmap.close()


def test_invalid_and_cancelled_pcm_does_not_leave_an_input(tmp_path):
    with pytest.raises(ValueError): prepare_audio(np.array([np.nan], dtype=np.float32), tmp_path)
    def cancelled(): raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError, match='cancelled'):
        prepare_audio(np.zeros(4, dtype=np.float32), tmp_path, check=cancelled)
    assert not (tmp_path / 'audio.npy').exists()
