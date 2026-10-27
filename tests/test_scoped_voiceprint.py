import copy

import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project, load_project
from twobyteasr.recognition.scoped_voiceprint import (apply_reviewed, cue_signature, proposals, sample_windows)
from twobyteasr.recognition.speaker_recovery import candidate_snapshot
from twobyteasr.timeline.studio_commands import RecoverSpeakersCommand


def project_fixture():
    labels = ['R001_S00','R002_S00','R003_S00']
    cues = [StudioCue(f'{label}-{i}', base+i*4000, base+i*4000+3000,
                      f'原文 {label} {i}', label)
            for label,base in zip(labels,(0,20000,40000)) for i in range(2)]
    raw = [dict(speaker=c.speaker_id,start=c.start_ms/1000,end=c.end_ms/1000,text=c.text) for c in cues]
    project = SubtitleProject(media=StudioMedia('',duration_ms=60000), cues=cues,
                              speakers=[StudioSpeaker(label) for label in labels])
    project.validate()
    project.generation_metadata['speaker_recovery'] = candidate_snapshot(raw,labels,source='native')
    project.generation_metadata['translations'] = {c.id:'翻译'+c.id for c in cues}
    return project


def observations(project):
    samples = sample_windows(project.cues)
    vectors = {'0|'+s['id']:([1.,0.,0.] if s['label'] != 'R003_S00' else [0.,1.,0.]) for s in samples}
    return samples,vectors


def test_same_voice_across_requests_is_a_review_candidate_only():
    project = project_fixture()
    before = copy.deepcopy(project.to_dict())
    samples,vectors = observations(project)
    report = proposals(project.cues,samples,vectors)
    assert report['groups'] == [['R001_S00','R002_S00']]
    assert project.to_dict() == before
    assert report['cue_signature'] == cue_signature(project.cues)


def test_same_request_and_overlapping_voices_are_conflicts():
    project = project_fixture()
    project.cues[2].speaker_id = project.cues[3].speaker_id = 'R001_S01'
    samples = sample_windows(project.cues)
    vectors = {'0|'+s['id']:[1.,0.] for s in samples}
    report = proposals(project.cues,samples,vectors)
    assert any(item['reason']=='same_request' for item in report['conflicts'])
    assert not any('R001_S00' in g and 'R001_S01' in g for g in report['groups'])
    project = project_fixture()
    project.cues[2].start_ms,project.cues[2].end_ms = 1000,4000
    samples = sample_windows(project.cues)
    # Include two independent samples for each side; a later overlap must
    # still bar merging even if their selected samples were otherwise clean.
    samples += [dict(id='extra1',label='R001_S00',start=10,end=12.6),
                dict(id='extra2',label='R002_S00',start=30,end=32.6)]
    vectors = {'0|'+s['id']:[1.,0.] for s in samples}
    report = proposals(project.cues,samples,vectors)
    assert any(item['reason']=='overlap' for item in report['conflicts'])
    assert not any('R001_S00' in g and 'R002_S00' in g for g in report['groups'])


def test_insufficient_and_inconsistent_samples_do_not_form_groups():
    project = project_fixture()
    samples,vectors = observations(project)
    vectors.pop('0|'+next(s['id'] for s in samples if s['label']=='R002_S00'))
    report = proposals(project.cues,samples,vectors)
    assert report['excluded']['R002_S00'] == 'insufficient_samples'
    assert not report['groups']


def test_overlapping_samples_do_not_count_as_independent_evidence():
    project = project_fixture()
    samples,vectors = observations(project)
    selected = [sample for sample in samples if sample['label']=='R002_S00']
    selected[1]['start'],selected[1]['end'] = selected[0]['start'],selected[0]['end']
    report = proposals(project.cues,samples,vectors)
    assert report['excluded']['R002_S00'] == 'insufficient_samples'
    assert not report['groups']


def test_voice_worker_cancellation_stops_owned_child(tmp_path):
    import sys
    import time
    from twobyteasr.recognition.service import CancelledError
    from twobyteasr.system.processes import run_speaker_embed_worker
    worker = tmp_path/'waiting_worker.py'
    worker.write_text('import time\ntime.sleep(60)\n',encoding='utf8')
    started = time.monotonic()
    with pytest.raises(CancelledError):
        run_speaker_embed_worker(worker_path=str(worker),main_python=sys.executable,manifest={},
                                 cancel_check=lambda:time.monotonic()-started>.4)
    assert time.monotonic()-started < 6


def test_recognition_records_candidates_and_keeps_labels_on_failure_or_cancel(monkeypatch,tmp_path):
    from types import SimpleNamespace
    import moss_firered_pipeline as pipeline
    from twobyteasr.recognition import scoped_voiceprint
    from twobyteasr.recognition.service import CancelledError, CancellationToken
    project = project_fixture()
    before = [cue.speaker_id for cue in project.cues]
    events, reviews, audited = [], [], []
    legacy = SimpleNamespace(SCRIPT_DIR=str(tmp_path),
        record_run_event=lambda name,**fields:events.append((name,fields)),
        add_review_item=lambda *args,**fields:reviews.append((args,fields)))
    token = CancellationToken()
    context = SimpleNamespace(cancellation_token=token)
    paths = {'speaker_embedding':'model','main_python':'python'}
    processing = {}
    report = {'groups':[['R001_S00','R002_S00']],'sample_counts':{'R001_S00':2,'R002_S00':2},
              'excluded':{},'conflicts':[]}
    monkeypatch.setattr(scoped_voiceprint,'analyze_audio',lambda *a,**k:report)
    pipeline.review_scoped_voiceprints(project.cues,object(),legacy,context,paths,processing,audited.append)
    assert processing['voiceprint_review'] == report and audited == ['voiceprint']
    assert [cue.speaker_id for cue in project.cues] == before
    assert any(name=='scoped_voiceprint_review' and not event['identity_confirmed'] for name,event in events)
    def fail(*args,**kwargs):
        raise RuntimeError('model missing')
    monkeypatch.setattr(scoped_voiceprint,'analyze_audio',fail)
    pipeline.review_scoped_voiceprints(project.cues,object(),legacy,context,paths,processing,audited.append)
    assert processing['voiceprint_review']['status']=='unavailable' and reviews
    assert [cue.speaker_id for cue in project.cues] == before
    token.cancel()
    with pytest.raises(CancelledError):
        pipeline.review_scoped_voiceprints(project.cues,object(),legacy,context,paths,processing,audited.append)


def test_reviewed_merge_is_atomic_undoable_and_survives_save(tmp_path):
    app = QApplication.instance() or QApplication([])
    project = project_fixture()
    samples,vectors = observations(project)
    report = proposals(project.cues,samples,vectors)
    original = copy.deepcopy(project.to_dict())
    result = apply_reviewed(project,report)
    assert [c.text for c in result.cues] == [c.text for c in project.cues]
    assert result.generation_metadata['translations'] == project.generation_metadata['translations']
    assert result.generation_metadata['speaker_recovery']['voiceprint_review']['pair_scores'] == report['pair_scores']
    assert len(result.speakers) == 2
    from twobyteasr.recognition.speaker_recovery import apply_candidate_role
    split = apply_candidate_role(result,result.generation_metadata['speaker_recovery'],'R002_S00','unconfirmed')
    assert [cue.speaker_id for cue in split.cues] == [cue.speaker_id for cue in project.cues]
    stack = QUndoStack()
    stack.push(RecoverSpeakersCommand(project,result))
    assert len(project.speakers) == 2
    stack.undo()
    assert project.to_dict() == original
    stack.redo()
    restored = load_project(save_project(project,tmp_path/'review.2byteproj'))
    assert len(restored.speakers) == 2
    assert restored.generation_metadata['translations'] == original['generation_metadata']['translations']


def test_stale_or_human_confirmed_results_never_overwrite():
    project = project_fixture()
    samples,vectors = observations(project)
    report = proposals(project.cues,samples,vectors)
    project.cues[0].text = '人工修改'
    with pytest.raises(ValueError,match='变化'):
        apply_reviewed(project,report)
    project = project_fixture()
    samples,vectors = observations(project)
    report = proposals(project.cues,samples,vectors)
    project.generation_metadata['speaker_recovery']['confirmed_by'] = 'user'
    with pytest.raises(ValueError,match='人工确认'):
        apply_reviewed(project,report)


def test_manual_name_is_not_overwritten_by_a_suggestion():
    project = project_fixture()
    samples,vectors = observations(project)
    report = proposals(project.cues,samples,vectors)
    project.speakers[1].name = '已命名的嘉宾'
    with pytest.raises(ValueError,match='人工设置'):
        apply_reviewed(project,report)
