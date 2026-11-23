from types import SimpleNamespace

from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, load_project, save_project
from twobyteasr.recognition.independent_review import KEY, firered_readings, reading_run, supplemental_readings
from twobyteasr.subtitle_rules.current_issues import current_issue_view
from twobyteasr.subtitle_rules.segmentation_review import history_rows, record_verified_history
from twobyteasr.subtitle_rules.studio_qc import QCResult, review_candidates


def test_equal_readings_keep_two_sources_and_raw_window_after_reopening(tmp_path):
    cue = StudioCue('cue', 0, 1000, '刚好来得及', evidence_refs=['primary'])
    p = SubtitleProject(StudioMedia('fixture.wav', duration_ms=2000), cues=[cue])
    p.render_settings['_cue_domain'] = 'timeline'
    p.generation_metadata['language'] = {'code': 'zh'}
    p.asr_evidence['primary'] = dict(start_ms=0, end_ms=1000,
        hypotheses=[dict(model='asr-api:moss-transcribe-diarize-pro', text=cue.text,
                         start_ms=0, end_ms=1000)])
    run = reading_run('firered', 'firered', 'text_verification',
        [dict(start=0, end=1, text=cue.text, raw_text=cue.text + '。')],
        job_id='job', language='zh', coverage=(0, 1000), domain='timeline')
    primary = reading_run('asr-api:moss-transcribe-diarize-pro', 'api', 'primary_transcription',
        [dict(start=0, end=1, text=cue.text)], job_id='job', language='zh', coverage=(0, 1000),
        domain='timeline')
    p.generation_metadata[KEY] = [primary, run]
    path = save_project(p, tmp_path/'receipt.2byteproj')
    reopened = load_project(path)
    caption = reopened.cues[0]
    candidates = review_candidates(reopened, caption)
    assert len(candidates) == 1
    assert set(candidates[0].sources) == {'Current', 'asr-api:moss-transcribe-diarize-pro', 'FireRed'}
    mapped = {model for model, _ in supplemental_readings(reopened, caption)}
    receipt, status, windows = firered_readings(reopened, caption, mapped_models=mapped)[0]
    assert receipt['execution_id'] == run['execution_id']
    assert status == 'mapped'
    assert windows[0]['text'] == cue.text + '。'
    assert firered_readings(reopened, StudioCue('later', 1400, 1800, '后来'))[0][1] == 'outside'


def test_old_acoustic_context_keeps_the_original_model_and_scope():
    cue = StudioCue('cue', 0, 1000, '接下来')
    p = SubtitleProject(StudioMedia('fixture.wav', duration_ms=2000), cues=[cue])
    p.generation_metadata['model_statuses'] = {'firered': {
        'model_id': 'firered', 'role': 'independent_text_and_timing', 'completed': True}}
    hypothesis = dict(model='firered', observed_text='接下来继续', text='接下来', context_only=True,
                      start_ms=0, end_ms=1000, original_start_ms=0, original_end_ms=1500)
    receipt, status, rows = firered_readings(p, cue, [hypothesis])[0]
    assert receipt['model_id'] == 'firered' and status == 'unmapped'
    assert rows == [dict(start_ms=0, end_ms=1500, text='接下来继续', status='decoded')]


def test_multicue_window_projects_words_and_preserves_crossing_as_context():
    cues = [StudioCue('a', 0, 500, '原甲'), StudioCue('b', 500, 1000, '原乙')]
    p = SubtitleProject(StudioMedia('fixture.wav', duration_ms=2000), cues=cues)
    p.render_settings['_cue_domain'] = 'timeline'
    p.generation_metadata['language'] = {'code': 'zh'}
    run = reading_run('firered', 'firered', 'text_verification',
        [dict(start=0, end=1, text='甲乙', words=[
            dict(text='甲', start=.1, end=.3), dict(text='乙', start=.6, end=.9)])],
        job_id='job', language='zh', coverage=(0, 1000), domain='timeline')
    p.generation_metadata[KEY] = [run]
    assert [supplemental_readings(p, cue) for cue in cues] == [(('firered', '甲'),), (('firered', '乙'),)]
    assert supplemental_readings(p, StudioCue('beside', 850, 1200, '原文')) == ()
    assert supplemental_readings(p, StudioCue('inside', 250, 520, '原文')) == ()
    assert firered_readings(p, StudioCue('inside', 250, 520, '原文'))[0][1] == 'unmapped'
    assert run['windows'][0]['text'] == '甲乙'


def test_verified_history_keeps_source_and_reactivates_when_output_changes():
    old = [StudioCue('left', 0, 500, '那等到'), StudioCue('right', 500, 1000, '我出的时候')]
    p = SubtitleProject(StudioMedia('fixture.wav', duration_ms=2000), cues=old)
    p.generation_metadata.update(
        language={'code': 'zh'}, media_identity={'fingerprint': 'media'},
        segmentation_source_spans={'cues': {key: {'parts': [{'source_id': 7}]}
                                             for key in ('left', 'right', 'joined')}})
    r = dict(project_id=p.project_id, media_fingerprint='media', range_id='first-window',
             source_ids=[7], input_text='那等到我出的时候', start_ms=0, end_ms=1000)
    p.studio_state['ai_sentence_refine'] = {'historical_windows': [r]}
    p._qc_result = QCResult({'left': (), 'right': ()})
    view = current_issue_view(p)
    assert view.level('left') == view.level('right') == 'suggested'
    assert [row.issue_id for row in view.records if row.kind == 'segmentation_fallback'] == ['first-window']

    p.cues = [StudioCue('joined', 0, 1000, r['input_text'])]
    task = SimpleNamespace(task_id='verified', rows={'one': dict(status='applied', candidate_verified=True,
                           cue_ids=['left', 'right'])})
    record_verified_history(p, task, {'first-window': ('left', 'right')})
    assert [(item['range_id'], [cue.id for cue in mapped], state) for item, mapped, state in history_rows(p)] == [
        ('first-window', ['joined'], 'verified')]
    p.cues = old
    assert list(history_rows(p))[0][2] == 'actionable'
