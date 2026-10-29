"""MOSS Pro (and other single-request API) speaker labels: voiceprint merging.

2026-10-28 user report: MOSS Pro cloud results still split one person into
many speakers; the 0.8.7 voiceprint review never ran on them (``API_S01``
labels, same-request labels barred, short-window thresholds, candidates only).
"""
import math
from types import SimpleNamespace

import pytest

from twobyteasr.recognition import scoped_voiceprint as voiceprint

LABELS = ('API_S01', 'API_S02', 'API_S03')
SAME = [1., 0., 0., 0.]
OTHER = [0., 1., 0., 0.]
MEDIUM = [.47, 0., math.sqrt(1 - .47 ** 2), 0.]  # cosine .47 with SAME, 0 with OTHER


def runtime_cues(labels=LABELS, rounds=4, length=3.5):
    """Labels take turns without overlapping; each says ``rounds`` lines."""
    cues = []
    for index in range(rounds * len(labels)):
        start = index * 4.0
        cues.append(SimpleNamespace(cue_id=f'c{index:03d}', start=start, end=start + length,
                                    text=f'第{index}句', speaker=labels[index % len(labels)]))
    return cues


def embeddings(voices, *, split=()):
    """Worker output: every label's two halves and whole; ``split`` halves disagree."""
    result = {}
    for label, vector in voices.items():
        for key in ('#0', '#1', '#w'):
            result['0|' + label + key] = list(vector)
        if label in split:
            result['0|' + label + '#1'] = [0., 0., 1., 0.]
    return result


def report_for(cues, voices, **kwargs):
    samples = voiceprint.sample_windows(cues)
    return voiceprint.proposals(cues, samples, embeddings(voices, **kwargs))


def test_single_request_api_labels_are_sampled():
    samples = voiceprint.sample_windows(runtime_cues())
    assert {sample['label'] for sample in samples} == set(LABELS)
    for label in LABELS:
        parts = {sample['part'] for sample in samples if sample['label'] == label}
        assert parts == {0, 1}


def test_same_request_labels_with_one_voice_merge_automatically():
    report = report_for(runtime_cues(), {'API_S01': SAME, 'API_S02': OTHER, 'API_S03': SAME})
    assert report['automatic_groups'] == [['API_S01', 'API_S03']]
    assert report['groups'] == [['API_S01', 'API_S03']]
    pair = next(item for item in report['pair_scores'] if item['labels'] == ['API_S01', 'API_S03'])
    assert pair['same_request'] is True and pair['tier'] == 'automatic'
    assert not any(item['reason'] == 'same_request' for item in report['conflicts'])


def test_medium_similarity_is_only_a_candidate():
    report = report_for(runtime_cues(), {'API_S01': SAME, 'API_S02': OTHER, 'API_S03': MEDIUM})
    assert report['automatic_groups'] == []
    assert report['groups'] == [['API_S01', 'API_S03']]


def test_simultaneous_speech_never_merges():
    cues = runtime_cues()
    cues[2].start, cues[2].end = cues[0].start + 1.0, cues[0].end + 1.0  # API_S03 talks over API_S01
    report = report_for(cues, {'API_S01': SAME, 'API_S02': OTHER, 'API_S03': SAME})
    assert {'labels': ['API_S01', 'API_S03'], 'reason': 'overlap'} in report['conflicts']
    assert report['groups'] == [] and report['automatic_groups'] == []


def test_short_or_inconsistent_labels_stay_separate():
    cues = runtime_cues()
    for cue in cues:
        if cue.speaker == 'API_S03':
            cue.end = cue.start + .9  # about 3 s of speech in all
    report = report_for(cues, {'API_S01': SAME, 'API_S02': OTHER, 'API_S03': SAME})
    assert report['excluded']['API_S03'] == 'insufficient_samples'
    assert report['groups'] == []
    report = report_for(runtime_cues(), {'API_S01': SAME, 'API_S02': OTHER, 'API_S03': SAME}, split={'API_S03'})
    assert report['excluded']['API_S03'] == 'inconsistent_samples'
    assert report['groups'] == []


def new_project(tmp_path, voices, *, text_suffix='', cues=None):
    from twobyteasr.projects.studio_project import project_from_runtime_cues
    from twobyteasr.recognition.speaker_recovery import candidate_snapshot
    cues = cues or runtime_cues()
    report = report_for(cues, voices)
    raw = [dict(speaker=c.speaker, start=c.start, end=c.end, text=c.text) for c in cues]
    recovery = candidate_snapshot(raw, {c.speaker for c in cues}, source='native')
    recovery['processing'] = {'mode': 'native', 'primary_backend': 'api', 'voiceprint_review': report}
    for cue in cues:
        cue.text += text_suffix
    metadata = {'speaker_recovery': recovery, 'translations': {c.cue_id: '译' + c.cue_id for c in cues}}
    return project_from_runtime_cues(str(tmp_path / 'missing.mp4'), cues, generation_metadata=metadata,
                                     initialize_layout=False)


def test_new_recognition_project_merges_strong_groups_and_can_split_back(tmp_path):
    from twobyteasr.projects.studio_project import load_project, save_project
    from twobyteasr.recognition.speaker_recovery import apply_candidate_role
    project = new_project(tmp_path, {'API_S01': SAME, 'API_S02': OTHER, 'API_S03': SAME})
    original = runtime_cues()
    assert [(c.id, c.start_ms, c.end_ms, c.text) for c in project.cues] == [
        (c.cue_id, round(c.start * 1000), round(c.end * 1000), c.text) for c in original]
    assert [s.id for s in project.speakers] == ['API_S01', 'API_S02']
    assert [s.name for s in project.speakers] == ['S00', 'S01']
    assert {c.speaker_id for c in project.cues if c.id in {'c002', 'c005'}} == {'API_S01'}
    state = project.generation_metadata['speaker_recovery']
    assert state['roles']['API_S03'] == 'merge:API_S01' and not state.get('confirmed_by')
    assert state['voiceprint_automatic']['groups'] == [['API_S01', 'API_S03']]
    assert project.generation_metadata['translations']['c002'] == '译c002'
    restored = load_project(save_project(project, tmp_path / 'merged.2byteproj'))
    assert [s.id for s in restored.speakers] == ['API_S01', 'API_S02']
    # The merged label gets the next free number, not a name another speaker now has.
    assert restored.generation_metadata['speaker_names']['entries']['API_S03']['name'] == 'S02'
    split = apply_candidate_role(restored, restored.generation_metadata['speaker_recovery'], 'API_S03', 'unconfirmed')
    assert [c.speaker_id for c in split.cues] == [c.speaker for c in original]
    assert [(s.id, s.name) for s in split.speakers] == [('API_S01', 'S00'), ('API_S02', 'S01'), ('API_S03', 'S02')]


def test_automatic_merge_does_not_depend_on_caption_text(tmp_path):
    # Delivered text is normalised (spaces, Traditional script) after the
    # comparison; the label decision still holds.
    project = new_project(tmp_path, {'API_S01': SAME, 'API_S02': OTHER, 'API_S03': SAME}, text_suffix='。')
    assert [s.id for s in project.speakers] == ['API_S01', 'API_S02']


def test_one_voice_across_all_labels_needs_no_confirmation(tmp_path):
    project = new_project(tmp_path, {'API_S01': SAME, 'API_S02': SAME, 'API_S03': SAME})
    assert [s.id for s in project.speakers] == ['API_S01']
    assert project.generation_metadata['speaker_recovery']['needs_confirmation'] is False


def test_candidates_left_after_automatic_merge_are_reviewable(tmp_path):
    from twobyteasr.recognition.scoped_voiceprint import apply_reviewed, cue_signature
    labels = ('API_S01', 'API_S02', 'API_S03', 'API_S04')
    cues = runtime_cues(labels)
    project = new_project(tmp_path, {'API_S01': SAME, 'API_S02': OTHER, 'API_S03': SAME, 'API_S04': MEDIUM},
                          cues=cues)
    report = project.generation_metadata['speaker_recovery']['processing']['voiceprint_review']
    assert [s.id for s in project.speakers] == ['API_S01', 'API_S02', 'API_S04']
    assert report['groups'] == [['API_S01', 'API_S04']]
    assert report['cue_signature'] == cue_signature(project.cues)
    reviewed = apply_reviewed(project, report)
    assert [s.id for s in reviewed.speakers] == ['API_S01', 'API_S02']
    assert reviewed.generation_metadata['speaker_recovery']['confirmed_by'] == 'user'


def test_previous_version_reports_are_not_applied(tmp_path):
    from twobyteasr.recognition.scoped_voiceprint import apply_automatic
    project = new_project(tmp_path, {'API_S01': SAME, 'API_S02': OTHER, 'API_S03': [0., 0., 0., 1.]})
    report = project.generation_metadata['speaker_recovery']['processing']['voiceprint_review']
    report.update(version='scoped-ecapa-review-v1', automatic_groups=[['API_S01', 'API_S02']])
    assert apply_automatic(project) is False
    assert len(project.speakers) == 3
    with pytest.raises(ValueError):
        voiceprint.apply_reviewed(project, report)


def test_recognition_compares_single_request_labels(monkeypatch, tmp_path):
    import moss_firered_pipeline as pipeline
    events, reviews, calls = [], [], []
    legacy = SimpleNamespace(SCRIPT_DIR=str(tmp_path),
                             record_run_event=lambda name, **fields: events.append((name, fields)),
                             add_review_item=lambda *args, **fields: reviews.append((args, fields)))
    report = {'groups': [['API_S01', 'API_S03']], 'automatic_groups': [['API_S01', 'API_S03']],
              'sample_counts': {'API_S01': 4, 'API_S03': 4}, 'excluded': {}, 'conflicts': []}

    def analyze(*args, **kwargs):
        calls.append(args)
        return report
    monkeypatch.setattr(voiceprint, 'analyze_audio', analyze)
    processing = {}
    pipeline.review_scoped_voiceprints(runtime_cues(), object(), legacy, SimpleNamespace(cancellation_token=None),
                                       {'speaker_embedding': 'model', 'main_python': 'python'}, processing,
                                       lambda name: None)
    assert calls and processing['voiceprint_review'] == report
    assert not any(name == 'recognition_branch_skipped' for name, _ in events)
    assert any('声纹' in args[1] and 'severity' in fields and fields['severity'] == 'info'
               for args, fields in reviews)


def test_short_pieces_reach_the_worker(monkeypatch):
    import numpy as np
    from twobyteasr.system import processes
    cues = runtime_cues(rounds=4, length=1.2)
    samples = voiceprint.sample_windows(cues)
    parts = [np.zeros(int((s['end'] - s['start']) * 16000), dtype=np.float32) + .1 for s in samples]
    seen = {}

    def worker(*, manifest, **kwargs):
        seen.update(manifest)
        keys = {segment['speaker'] for segment in manifest['chunks'][0]['segments']}
        return {'0|' + key: SAME for key in keys}
    monkeypatch.setattr(processes, 'run_speaker_embed_worker', worker)
    monkeypatch.setattr('twobyteasr.model_integrity.verify_model_files', lambda *a, **k: None)
    report = voiceprint.analyze_samples(cues, samples, parts, model_dir='model', main_python='python', worker_path='w')
    keys = {segment['speaker'] for segment in seen['chunks'][0]['segments']}
    assert {'API_S01#0', 'API_S01#1', 'API_S01#w'} <= keys
    assert report['version'] == voiceprint.VERSION


def test_named_host_receives_its_other_labels_after_review(tmp_path):
    from twobyteasr.recognition.scoped_voiceprint import apply_reviewed, reviewable_groups
    from twobyteasr.recognition.speaker_recovery import apply_candidate_role
    project = new_project(tmp_path, {'API_S01': SAME, 'API_S02': OTHER, 'API_S03': MEDIUM})
    report = project.generation_metadata['speaker_recovery']['processing']['voiceprint_review']
    assert report['automatic_groups'] == [] and report['groups'] == [['API_S01', 'API_S03']]
    # The user already made API_S03 the host and named it.
    project = apply_candidate_role(project, project.generation_metadata['speaker_recovery'], 'API_S03', 'main')
    next(s for s in project.speakers if s.id == 'API_S03').name = '北极熊'
    project.validate()
    groups = reviewable_groups(project, report['groups'])
    assert groups == [['API_S03', 'API_S01']]
    merged = apply_reviewed(project, dict(report, groups=groups))
    assert [(s.id, s.name) for s in merged.speakers] == [('API_S02', 'S01'), ('API_S03', '北极熊')]
    assert {c.speaker_id for c in merged.cues} == {'API_S02', 'API_S03'}
    # Two speakers a person already set up are never merged by a suggestion.
    project = apply_candidate_role(project, project.generation_metadata['speaker_recovery'], 'API_S01', 'main')
    assert reviewable_groups(project, report['groups']) == []


@pytest.mark.parametrize('current', ['API_S01', 'SUBTITLES'])
def test_review_does_not_compare_raw_labels_with_the_current_track(current):
    # 2026-10-28 user report: 「说话人候选：R001_S01 / SUBTITLES」 on captions
    # nothing disagreed about. A merge, 统一字幕 or a drag changes the track,
    # not what the recognizer heard.
    from twobyteasr.projects.studio_project import StudioCue
    from twobyteasr.subtitle_rules.studio_review import ReviewEvidenceAggregator
    cue = StudioCue('c1', 0, 1000, 'Leonardo io non posso farlo', speaker_id=current)
    readings = [{'model': 'asr-api:moss-transcribe-diarize-pro', 'text': 'Leonardo io non posso farlo',
                 'start_ms': 0, 'end_ms': 1000, 'speaker_id': 'API_S05', 'reference': 'segment:1'},
                {'model': 'asr-api:moss-transcribe-diarize-pro', 'text': '',
                 'start_ms': 0, 'end_ms': 1000, 'speaker_id': current, 'reference': 'cue-align:1'}]
    aggregate = ReviewEvidenceAggregator().aggregate(cue, readings)
    assert aggregate.models_agree_text
    assert not aggregate.speaker_only and not aggregate.requires_review
    # Two recognizers that really disagree about the speaker still ask.
    readings = [dict(readings[0], model='MOSS'), dict(readings[0], model='Qwen', speaker_id='API_S02')]
    assert ReviewEvidenceAggregator().aggregate(cue, readings).speaker_only
