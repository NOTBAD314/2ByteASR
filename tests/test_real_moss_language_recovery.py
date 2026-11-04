"""Wrong German text over English audio: honest recovery, no network/model fixture claims."""
import copy,json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication,QWidget,QMenu
from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
from twobyteasr.studio.language_recovery_dialog import show_candidates
from twobyteasr.recognition.language_recovery_project import review_scope,project_pending,project_review_ranges
from tests.test_moss_empty_recovery import DE

APP=QApplication.instance() or QApplication([])

class Page(QWidget):
    def __init__(self,requested='auto'):
        super().__init__();self._recognition_running=False;self.calls=[]
        self.project=SubtitleProject(StudioMedia('offline-fixture.wav',duration_ms=20000),
            cues=[StudioCue('old',0,2000,DE)],generation_metadata={'language':{'requested':requested,'code':'de'},
                'transcript_acceptance':{'version':1,'ranges':[]}})
        self.video=SimpleNamespace(set_paused=lambda value:None)
    def _open_recognition_sheet(self,**kw):self.calls.append(kw)
    def _seek(self,value):pass

@pytest.fixture
def page():
    value=Page()
    yield value
    for dialog in value.findChildren(QWidget):dialog.close()
    value.close();value.deleteLater();APP.processEvents()


def show(page):
    region=dict(id='scope',start=0.,end=20.,status='observation',raw_rows=[dict(start=0.,end=2.,text=DE)])
    show_candidates(page,region,'auto');return page._language_candidate_controls


def test_confirming_english_audio_can_rerecognize_wrong_german_without_endorsing_text(page):
    c=show(page);c['language'].setCurrentIndex(c['language'].findData('en'))
    c['local'].click();assert not page.calls and '源语言' in c['problem'].text()
    c['source_confirmed'].setChecked(True)
    assert not c['confirmed'].isChecked() and not c['reuse'].isEnabled()
    c['local'].click();assert len(page.calls)==1
    policy=page.calls[0]['language_recovery']['requested_language'];assert policy=='en'
    receipt=page.calls[0]['language_recovery']
    assert receipt['explicit_local_range'] and not receipt['force_cloud']
    assert receipt['source_language_confirmed'] and not receipt['candidate_text_confirmed']
    assert page.project.generation_metadata['language']['requested']=='auto'


def test_cloud_retry_uses_source_confirmation_not_candidate_approval(page):
    c=show(page);c['language'].setCurrentIndex(c['language'].findData('en'));c['source_confirmed'].setChecked(True)
    c['cloud'].click();receipt=page.calls[0]['language_recovery']
    assert receipt['force_cloud'] and receipt['requested_language']=='en' and not receipt['candidate_text_confirmed']


def test_confirmation_is_bound_to_current_choice_and_reuse_stays_stronger(page):
    c=show(page);c['language'].setCurrentIndex(c['language'].findData('en'));c['source_confirmed'].setChecked(True)
    assert not c['reuse'].isEnabled()
    c['confirmed'].setChecked(True);assert c['reuse'].isEnabled()
    c['language'].setCurrentIndex(c['language'].findData('fr'))
    assert not c['source_confirmed'].isChecked() and not c['confirmed'].isChecked() and not c['reuse'].isEnabled()
    c['local'].click();assert not page.calls


def test_auto_project_without_detected_conflict_has_an_executable_review_action(page):
    from twobyteasr.studio.language_recovery_ui import add_actions
    assert not project_pending(page.project) and not project_review_ranges(page.project)
    before=copy.deepcopy(page.project.to_dict());menu=QMenu(page);add_actions(page,menu)
    action=next(x for x in menu.actions() if x.objectName()=='languageReviewAction')
    assert action.isEnabled();action.trigger()
    c=page._language_candidate_controls
    assert c['rows'].count()==1 and DE in c['rows'].item(0).text()
    assert not c['reuse'].isEnabled()  # processed captions are not raw ASR candidates
    c['language'].setCurrentIndex(c['language'].findData('en'));c['source_confirmed'].setChecked(True);c['local'].click()
    assert page.calls[0]['language_recovery']['requested_language']=='en'
    assert page.project.to_dict()==before


def test_reference_scope_does_not_create_pending_or_mutate_source(page):
    before=copy.deepcopy(page.project.to_dict());r=review_scope(page.project)
    assert r['raw_origin']=='project_subtitles' and not r['reusable']
    assert r['reason']=='user_requested_review' and not project_pending(page.project)
    assert page.project.to_dict()==before


def _local_fixture(tmp_path,monkeypatch,change=None):
    from twobyteasr.recognition import asr,local_language_recovery as local
    model=tmp_path/'model';model.mkdir();(model/'config.json').write_text('{}')
    runtime=tmp_path/'python.exe';runtime.write_bytes(b'fake worker, never executed')
    monkeypatch.setattr(asr,'resolve_qwen_asr_local_source',lambda:str(model))
    monkeypatch.setattr(asr,'_main_worker_python',lambda:str(runtime))
    def worker(command,*args,**kw):
        jobs=json.loads(Path(command[command.index('--manifest')+1]).read_text('utf8'))['jobs'];rows=[]
        for job in jobs:
            row=dict(job,text=DE*8,language='English',request_language='English',generation={'token_limit_reached':False})
            if change=='empty':row['text']=''
            if change=='identity':row['pcm_sha256']='wrong'
            if change=='truncated':row['generation']['token_limit_reached']=True
            rows.append(row)
        return {'results':rows}
    monkeypatch.setattr(asr,'_run_isolated_asr_worker',worker)
    return local


def test_manual_local_attempt_keeps_text_observation_without_quarantining_valid_rows(tmp_path,monkeypatch):
    local=_local_fixture(tmp_path,monkeypatch)
    result=local.recognize_range(np.zeros(320000,np.float32),0,320000,language='en',cache_root=tmp_path/'cache')
    assert result['status']=='accepted' and result['processing_language']=='en'
    assert result['text_language_warning'] and result['language_evidence']['language']=='de'
    assert result['rows'][0]['text']==DE*8 and result['policy']['language']=='English'


@pytest.mark.parametrize('failure',['empty','identity','truncated'])
def test_local_attempt_keeps_independent_integrity_gates(tmp_path,monkeypatch,failure):
    local=_local_fixture(tmp_path,monkeypatch,failure)
    with pytest.raises(RuntimeError):
        local.recognize_range(np.zeros(320000,np.float32),0,320000,language='en',cache_root=tmp_path/'cache')
    assert not list((tmp_path/'cache').rglob('accepted.json'))



def test_local_primary_does_not_report_unused_moss_cloud_settings_as_its_constraint():
    from twobyteasr.recognition.run_context import RuntimeContext
    from twobyteasr.recognition.language_decision import bind
    context=RuntimeContext(requested_language='en',asr_settings_snapshot={'models':{'primary_asr_backend':'qwen_local'}},
        asr_endpoint_snapshot={'protocol':'mosi_transcriptions','model':'moss-transcribe-diarize-pro'})
    bind(context,['A genuine local English transcript'])
    control=context.language_decision['remote_language_control']
    assert context.task_language=='en' and control['route']=='local'
    assert control['language_control']=='not_used' and control['request_language'] is None
    assert not control['parameter_sent']
