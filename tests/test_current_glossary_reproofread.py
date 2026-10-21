import copy
import threading
from types import SimpleNamespace

from PySide6.QtGui import QUndoStack
from twobyteasr.projects.studio_project import StudioCue, StudioMedia, SubtitleProject, save_project, load_project
from twobyteasr.glossary.terminology import GlossarySnapshot, GlossaryLibrary, TermEntry
from twobyteasr.studio.studio_find_replace import PreviewBinding, apply_occurrences
from twobyteasr.glossary.studio_glossary_service import preview_glossary_correction
from twobyteasr.recognition.run_context import RuntimeContext, activate_runtime_context, get_runtime_context


def snapshot():
    return GlossarySnapshot((GlossaryLibrary('v','词库','1',
        terms=(TermEntry('BerLIN',(),provenance='user_confirmed'),)),))


def project():
    return SubtitleProject(media=StudioMedia(path='isolated.mp4'),
        cues=[StudioCue('a',100,1000,'Borlin也没有接住',original_text='Borlin也没有接住',speaker_id='S01'),
              StudioCue('b',1200,2000,'人工保留文字',original_text='原始普通句',speaker_id='S02')])


def fake_provider(monkeypatch, edited=True):
    import subtitle_core
    import twobyteasr.subtitle_rules.polishing as polish
    import twobyteasr.providers.asr_provider_snapshot as provider
    monkeypatch.setattr(provider,'resolve_provider_snapshot', lambda *_a,**_kw:
        SimpleNamespace(public_identity=lambda:{'provider':'test','model':'test'}))
    seen=[]
    def correction(rows,*args,**kwargs):
        seen.extend((r.text,r.speaker) for r in rows)
        return polish.PolishBatchResult({r.segment_id:
            ('BerLIN也没有接住' if edited and r.segment_id==1 else r.text) for r in rows})
    monkeypatch.setattr(polish,'call_correction_api',correction)
    return seen


def test_original_transcription_preview_does_not_revert_manual_text(monkeypatch):
    seen=fake_provider(monkeypatch)
    p=project(); before=copy.deepcopy(p)
    result=preview_glossary_correction(p,['a','b'],snapshot(),{})
    assert seen==[('Borlin也没有接住','S01'),('原始普通句','S02')]
    assert [(h.cue_id,h.replacement) for h in result.hits]==[('a','BerLIN也没有接住')]
    assert p.cues==before.cues and p.generation_metadata==before.generation_metadata
    assert result.receipt['asr_run'] is False and result.receipt['audio_verified'] is False


def test_review_apply_undo_reopen_retains_provenance_and_boundaries(monkeypatch,tmp_path):
    fake_provider(monkeypatch)
    p=project(); p.validate()
    page=SimpleNamespace(session=SimpleNamespace(project=p,undo_stack=QUndoStack()),_changed=lambda:None)
    result=preview_glossary_correction(p,['a','b'],snapshot(),{})
    assert apply_occurrences(page,list(result.hits),title='当前词库校对',binding=PreviewBinding.capture(p),
        glossary_ids=['v'],review_receipt=result.receipt)==(1,1)
    applied=p.generation_metadata['glossary_review_jobs'][-1]
    assert applied['applied_cue_ids']==['a'] and applied['project_id']==p.project_id
    assert (p.cues[0].start_ms,p.cues[0].end_ms,p.cues[0].speaker_id)==(100,1000,'S01')
    path=tmp_path/'review.2byteproj';save_project(p,path)
    assert load_project(path).generation_metadata['glossary_review_jobs'][-1]==applied
    page.session.undo_stack.undo()
    assert p.cues[0].text=='Borlin也没有接住' and 'glossary_review_jobs' not in p.generation_metadata
    page.session.undo_stack.redo()
    assert p.cues[0].text=='BerLIN也没有接住' and p.cues[1].text=='人工保留文字'


def test_runtime_preview_refuses_concurrent_queue_and_restores_owner():
    outer=RuntimeContext(); seen=[]
    with activate_runtime_context(outer):
        def another():
            try:
                with activate_runtime_context(RuntimeContext()):
                    seen.append('entered')
            except RuntimeError:
                seen.append('busy')
        child=threading.Thread(target=another);child.start();child.join(2)
        assert seen==['busy'] and get_runtime_context() is outer


def test_old_preview_rejects_new_manual_edit(monkeypatch):
    fake_provider(monkeypatch)
    p=project();p.validate()
    binding=PreviewBinding.capture(p)
    result=preview_glossary_correction(p,['a'],snapshot(),{})
    p.cues[0].text='保留新编辑'
    page=SimpleNamespace(session=SimpleNamespace(project=p,undo_stack=QUndoStack()),_changed=lambda:None)
    assert apply_occurrences(page,list(result.hits),title='重校对',binding=binding,review_receipt=result.receipt)==(0,0)
    assert p.cues[0].text=='保留新编辑'


def test_rejected_queue_cannot_apply_legacy_settings(monkeypatch):
    import subtitle_core as core
    from twobyteasr.recognition.service import RunOptions, run_media_queue
    applied=[]
    monkeypatch.setattr(RunOptions,'apply',lambda *args: applied.append(True))
    errors=[]
    owner=RuntimeContext(game_name='active owner')
    with activate_runtime_context(owner,legacy=core):
        def concurrent():
            try:
                run_media_queue([],RunOptions(),_legacy=core,_pipeline=SimpleNamespace())
            except RuntimeError as exc:
                errors.append(str(exc))
        worker=threading.Thread(target=concurrent);worker.start();worker.join(2)
        assert errors and not applied
        assert core.RUNTIME_GAME_NAME=='active owner'


def test_configuration_error_releases_queue_ownership(monkeypatch):
    import subtitle_core as core
    from twobyteasr.recognition.service import RunOptions, run_media_queue
    before=get_runtime_context()
    def fail(*args):
        raise ValueError('invalid fixed configuration')
    monkeypatch.setattr(RunOptions,'apply',fail)
    import pytest
    with pytest.raises(ValueError,match='invalid fixed'):
        run_media_queue([],RunOptions(),_legacy=core,_pipeline=SimpleNamespace())
    assert get_runtime_context() is before
    entered=[]
    def acquire():
        with activate_runtime_context(RuntimeContext()):
            entered.append(True)
    worker=threading.Thread(target=acquire);worker.start();worker.join(2)
    assert entered==[True]
