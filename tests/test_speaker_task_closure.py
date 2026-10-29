import json
from types import SimpleNamespace
import pytest


@pytest.mark.parametrize('cache_hit',[False,True])
def test_nemotron_completion_reaches_persisted_model_summary(monkeypatch,cache_hit):
    from twobyteasr import nemotron_diarization as module
    from twobyteasr.recognition import cache
    from moss_firered_pipeline import _model_stage_summary
    events=[]
    monkeypatch.setattr(cache,'record_run_event',lambda event,**data:events.append(dict(event=event,**data)))
    monkeypatch.setattr(module,'_diarize',lambda *a,**k:([{'speaker':'NEMO_01'}],dict(cache_hit=cache_hit)))
    module.diarize([],[],'.')
    summary=_model_stage_summary(SimpleNamespace(task_reporting=SimpleNamespace(active_media_report=lambda:{'events':events})))
    status=summary['NEMOTRON_DIARIZATION']
    assert status['selected'] and status['completed'] and not status['failed']
    assert status['segment_count']==1
    assert not status['started']  # A result/cached receipt cannot invent a worker start.


def test_nemotron_failure_is_not_recorded_as_completed(monkeypatch):
    from twobyteasr import nemotron_diarization as module
    from twobyteasr.recognition import cache
    from moss_firered_pipeline import _model_stage_summary
    events=[]
    monkeypatch.setattr(cache,'record_run_event',lambda event,**data:events.append(dict(event=event,**data)))
    def fail(*a,**k):raise RuntimeError('worker failed')
    monkeypatch.setattr(module,'_diarize',fail)
    with pytest.raises(RuntimeError,match='worker failed'):module.diarize([],[],'.')
    summary=_model_stage_summary(SimpleNamespace(task_reporting=SimpleNamespace(active_media_report=lambda:{'events':events})))
    status=summary['NEMOTRON_DIARIZATION']
    assert status['selected'] and status['failed'] and not status['completed']


def test_real_firered_primary_contract_uses_canonical_tokens(monkeypatch):
    from twobyteasr.recognition import asr
    from twobyteasr.recognition.asr_schema import normalize_firered_worker_result
    canonical=normalize_firered_worker_result({'results':[{'text':'你好','timestamp':[['你',0,0.4],['好',0.4,0.8]]}]},[{'offset':0}])
    monkeypatch.setattr(asr,'transcribe_firered_reference',lambda *a,**k:canonical)
    rows=asr.transcribe_primary_reference('firered','unused.wav',[dict(start=0,end=1)],None,1)
    assert rows[0]['text']=='你好' and len(rows[0]['tokens'])==2


def test_anonymous_review_keeps_unconfirmed_and_unknown_lanes(tmp_path):
    from twobyteasr.recognition.speaker_recovery import candidate_snapshot,rebuild_selected_speakers,recovery_preview
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue,StudioSpeaker,save_project,load_project
    from twobyteasr.exports.studio_subtitle_export import export_subtitle_artifacts,SubtitleExportOptions
    labels=['NEMO_01','NEMO_02','S00']
    p=SubtitleProject(media=StudioMedia('fixture.mp4',duration_ms=3000),speakers=[StudioSpeaker(x) for x in labels],
        cues=[StudioCue(str(i),i*1000,i*1000+900,'人工编辑'+str(i),x) for i,x in enumerate(labels)])
    rows=[dict(start=i,end=i+.9,text=c.text,speaker=c.speaker_id) for i,c in enumerate(p.cues)]
    state=candidate_snapshot(rows,source='nemotron');p.generation_metadata['speaker_recovery']=state
    roles=dict(zip(labels,['main','unconfirmed','unconfirmed']))
    assert set(recovery_preview(p,state,roles))==set(labels)
    result=rebuild_selected_speakers(p,state,roles)
    assert [c.to_dict() if hasattr(c,'to_dict') else vars(c) for c in result.cues]==[vars(c) for c in p.cues]
    save_project(result,tmp_path/'reviewed.2byteproj');reopened=load_project(tmp_path/'reviewed.2byteproj')
    assert [s.id for s in reopened.speakers if s.is_host]==['NEMO_01']
    assert reopened.generation_metadata['speaker_recovery']['needs_confirmation']
    outputs=export_subtitle_artifacts(reopened,tmp_path/'export','reviewed',SubtitleExportOptions(speaker_mode='per_speaker'))
    assert {a.speaker_id for a in outputs}==set(labels)
