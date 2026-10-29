"""Failure boundaries, ownership and durable writes with real production adapters."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoStack

from twobyteasr.diagnostics import editor_diagnostics as diagnostics
from twobyteasr.diagnostics.event_log import EventStore,install_asyncio
from twobyteasr.diagnostics.studio_events import background_ticket
from twobyteasr.diagnostics.support_bundle import export_report
from twobyteasr.projects.studio_project import StudioMedia,StudioCue,SubtitleProject,save_project_revision,load_project
from twobyteasr.projects.studio_revisions import StudioRevisionStore
from twobyteasr.subtitle_rules.subtitle_translation import TranslationResult,TranslatedItem


@pytest.fixture
def store(tmp_path,monkeypatch):
    instance=EventStore(tmp_path/'logs');monkeypatch.setattr(diagnostics,'_INSTANCE',instance)
    yield instance
    instance.close_store(clean=True)


def project():
    p=SubtitleProject(media=StudioMedia(path='',duration_ms=4000),cues=[StudioCue('one',0,900,'原文秘密'),StudioCue('two',1000,1900,'二')])
    p.generation_metadata['language']={'code':'ja'}
    return p


def test_frozen_save_observation_cannot_fail_durable_write(store,tmp_path):
    p=project();snapshot=StudioRevisionStore(p).refresh_persistence(17)
    target=tmp_path/'saved.2byteproj'
    saved,phases=save_project_revision(snapshot,target)
    read=load_project(saved)
    assert read.cues[0].text==p.cues[0].text
    row=next(r for r in store.recent if r['event_name']=='project.saved')
    assert row['atomic_write_completed'] and row['persisted_revision']==17
    reopened=next(r for r in store.recent if r['event_name']=='project.loaded')
    assert row['file_version']==reopened['file_version']


@pytest.mark.parametrize('change',['project','edit','cancel','target','closed','session'])
def test_real_translation_result_ownership(store,monkeypatch,change):
    from twobyteasr.caption_design.studio_ai import GLOBAL_PROVIDER_REGISTRY
    from twobyteasr.studio.studio_translation_dialog import SubtitleTranslationDialog
    from twobyteasr.studio import studio_bilingual
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(GLOBAL_PROVIDER_REGISTRY,'settings',lambda:{})
    monkeypatch.setattr(studio_bilingual,'current_settings',lambda page:SimpleNamespace(mode='bilingual'))
    p=project();page=SimpleNamespace(project=p,selected_cue_ids=lambda:['one'],undo_stack=QUndoStack(),
                                   session=SimpleNamespace(generation=1))
    dialog=SubtitleTranslationDialog(page)
    dialog._diagnostic=background_ticket(p,'translation',ids=None)
    from twobyteasr.subtitle_rules.subtitle_translation import translation_source,source_sha
    source=translation_source(p)
    result=TranslationResult(dialog._target(),'synthetic','offline',project_id=source.project_id,
        project_instance=source.project_instance,content_revisions=dict(source.content_revisions),
        sources={'one':'原文秘密'},
        translations={'one':TranslatedItem('one','翻譯秘密','原文秘密',source_sha('原文秘密'),'')})
    if change=='project':page.project=project()
    if change=='edit':p.cues[0].text='後來修改'
    if change=='cancel':result.cancelled=True
    if change=='target':result.target='ja'
    if change=='closed':page._close_requested=True
    if change=='session':page.session.generation+=1
    try:
        dialog._on_finished(result)
        event=next(r for r in reversed(store.recent) if r['event_name']=='background.result')
        if change=='project':
            assert event['result']=='discarded_project_changed'
            assert not page.project.generation_metadata.get('translations') and page.undo_stack.count()==0
        elif change=='edit':
            assert event['result']=='discarded_stale' and event['stale_ids']==['one']
            assert not p.generation_metadata.get('translations') and p.cues[0].text=='後來修改'
        elif change=='cancel':
            assert event['cancelled'] and event['result']=='accepted'
            assert page.undo_stack.count()==1  # Existing policy keeps completed batches.
            assert event['applied_count']==1
        else:
            assert event['result']=={'target':'discarded_target_changed','closed':'discarded_page_closed',
                                     'session':'discarded_session_changed'}[change]
            assert page.undo_stack.count()==0 and event['applied_count']==0
    finally:dialog.deleteLater();app.processEvents()


def test_asyncio_hook_preserves_existing_handler_and_cause(store):
    loop=asyncio.new_event_loop();called=[]
    loop.set_exception_handler(lambda active,details:called.append(details))
    install_asyncio(loop)
    try:
        try:raise PermissionError('api_key=sk-do-not-record-123456')
        except PermissionError as error:loop.call_exception_handler({'exception':error,'message':'private subtitle'})
        assert called
        row=next(r for r in store.recent if r['event_name']=='async.exception')
        assert row['exception']['chain'][0]['type']=='PermissionError'
        assert 'sk-do-not-record' not in json.dumps(row)
    finally:loop.close()


def test_real_nonclean_child_recovered_in_next_bundle(store,tmp_path):
    script="""import os,sys
from twobyteasr.diagnostics.event_log import EventStore
s=EventStore(sys.argv[1]);s.record('operation.start',dict(operation_id='op-terminated',result='started'))
s.snapshot();os._exit(23)
"""
    result=subprocess.run([sys.executable,'-c',script,str(store.root)],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode==23
    target=tmp_path/'previous.zip'
    exported=export_report(target,root=store.root,instance=store,scope='previous')
    import zipfile
    with zipfile.ZipFile(target) as z:
        meta=json.loads(z.read('environment.json'))
        assert any(s['status']=='previous_not_cleanly_ended' for s in meta['sessions'])
        assert 'op-terminated' in z.read('events.jsonl').decode()
        assert '不能据此判定' in exported['summary']


def test_bridge_marks_actual_provider_failure_and_partial_validation(store):
    from twobyteasr.diagnostics.event_bridge import legacy_event
    legacy_event('translation.error',dict(category='network_timeout',error='PRIVATE_BODY'),module='translation')
    legacy_event('translation.validated',dict(accepted=1,problems={'one':'provider_error: PRIVATE_BODY'}),module='translation')
    first,last=list(store.recent)[-2:]
    assert first['result']=='failed' and first['level']=='ERROR'
    assert last['result']=='partial' and last['problem_count']==1
    assert last['problem_samples'][0]['error_code']=='provider_error'
    assert 'PRIVATE_BODY' not in json.dumps([first,last])
