"""Language recovery input changes independently of presentation revisions."""
import json
from types import SimpleNamespace
from pathlib import Path
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
from twobyteasr.projects.studio_runtime_state import state_for,DirtyDomain
from twobyteasr.studio.language_recovery_ui import _pending
from twobyteasr.recognition import language_recovery_project as recovery


def project(tmp_path):
    p=SubtitleProject(StudioMedia(''),cues=[StudioCue('one',0,2000,'hello world')],
                     generation_metadata={'language':{'requested':'en'},'job_id':'job'})
    p.validate();p.report_path=str(tmp_path/'report.json')
    return p


def test_style_selection_and_save_do_not_reanalyse_language(tmp_path,monkeypatch):
    p=project(tmp_path);runtime=state_for(p)
    page=SimpleNamespace(project=p,session=SimpleNamespace(runtime=runtime))
    calls=[];monkeypatch.setattr(recovery,'project_pending',lambda p:calls.append(p) or [])
    _pending(page)
    for dirty in (DirtyDomain.CUE_STYLE,DirtyDomain.CUE_SELECTION,DirtyDomain.AUTOSAVE,DirtyDomain.QC,DirtyDomain.PROJECT_METADATA):
        with runtime.transaction(p,action_id='test',dirty=dirty,affected_cue_ids=('one',),snapshot_cues=False):pass
        _pending(page)
    assert len(calls)==1
    with runtime.transaction(p,action_id='edit',dirty=DirtyDomain.CUE_CONTENT,affected_cue_ids=('one',)):
        p.cues[0].text='another sentence'
    _pending(page)
    assert len(calls)==2
    p.generation_metadata['language']['requested']='it'
    _pending(page)
    assert len(calls)==3


def test_report_is_read_once_until_identity_changes_and_default_scan_is_not_repeated(tmp_path,monkeypatch):
    p=project(tmp_path);report=Path(p.report_path)
    def content(job='job',seconds=3):
        return {'job_id':job,'events':[{'event':'asr_phase_timing','provider':'mosi_moss_pro','request_index':0,'audio_seconds':seconds}]}
    report.write_text(json.dumps(content()),encoding='utf8')
    original=Path.read_text;reads=[]
    def read(path,*a,**k):
        if path==report:reads.append(path)
        return original(path,*a,**k)
    monkeypatch.setattr(Path,'read_text',read)
    from twobyteasr.recognition import language_diagnostics
    fallback=[]
    monkeypatch.setattr(language_diagnostics,'primary_language_regions',lambda rows:fallback.append(rows) or [])
    monkeypatch.setattr(language_diagnostics,'transcript_language_sample',lambda text:{'language':'it'})
    first=recovery.project_pending(p)
    p.cues[0].text='changed'
    assert recovery.project_pending(p)==first
    assert len(reads)==1 and not fallback
    report.write_text(json.dumps(content(seconds=4))+' ',encoding='utf8')
    changed=recovery.project_pending(p)
    assert len(reads)==2 and changed[0]['end']==4
    p.generation_metadata['job_id']='different'
    assert recovery.project_pending(p)==[] and fallback


def test_recovery_decisions_remain_live_when_changed_in_place(tmp_path,monkeypatch):
    p=project(tmp_path);runtime=state_for(p)
    p.generation_metadata['transcript_acceptance']={'version':1,'ranges':[]}
    page=SimpleNamespace(project=p,session=SimpleNamespace(runtime=runtime))
    calls=[];monkeypatch.setattr(recovery,'project_pending',lambda p:calls.append(p) or list(p.generation_metadata['transcript_acceptance']['ranges']))
    assert _pending(page)==[]
    p.generation_metadata['transcript_acceptance']['ranges'].append({'id':'new'})
    assert _pending(page)==[{'id':'new'}] and len(calls)==2
