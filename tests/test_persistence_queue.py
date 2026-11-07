"""Async version ordering, request coalescing, and exact snapshot reuse."""
import threading
import time
import json
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QUndoCommand
from tests.test_studio_manual_save import _Page, drain
from twobyteasr.projects.studio_project import StudioMedia,StudioCue,SubtitleProject,save_project,load_project
from twobyteasr.projects.autosave_deadline import AutosaveDeadline

APP=QApplication.instance() or QApplication([])


def make_page(tmp_path):
    project=SubtitleProject(StudioMedia('',duration_ms=2000),cues=[StudioCue('a',0,1000,'N0')])
    target=save_project(project,tmp_path/'save.2byteproj')
    page=_Page(project,target)
    page.undo_stack.push(QUndoCommand('dirty'))
    return page


def test_only_latest_pending_request_is_written(tmp_path,monkeypatch):
    import twobyteasr.projects.studio_project as persistence
    original=persistence._atomic_json_blob_write
    release=threading.Event();started=threading.Event();calls=[]
    def write(path,content):
        calls.append(str(path));started.set()
        if len(calls)==1:release.wait(3)
        return original(path,content)
    monkeypatch.setattr(persistence,'_atomic_json_blob_write',write)
    page=make_page(tmp_path)
    page.save();assert started.wait(1)
    for text in ('N1','N2','N3'):
        page.project.cues[0].text=text
        page.undo_stack.push(QUndoCommand(text))
        page.save()
    queue=page._persistence_queue
    assert queue.jobs_started==1 and queue.max_pending==1
    assert queue.requests_coalesced==2
    release.set();drain(page)
    assert queue.jobs_started==2 and len(calls)==2
    assert load_project(page.session.project_path).cues[0].text=='N3'
    assert page.undo_stack.isClean()
    page.deleteLater();APP.processEvents()


def test_identical_inflight_requests_share_only_durable_callbacks(tmp_path, monkeypatch):
    import twobyteasr.projects.studio_project as persistence
    original = persistence._atomic_json_blob_write
    released = threading.Event()
    started = threading.Event()
    callbacks = []
    page = make_page(tmp_path)

    def held_write(path, content):
        started.set()
        released.wait(3)
        return original(path, content)

    monkeypatch.setattr(persistence, '_atomic_json_blob_write', held_write)
    first = page.project_controller.save(on_finished=lambda path, error:callbacks.append((path,error)))
    assert started.wait(1)
    second = page.project_controller.save(on_finished=lambda path, error:callbacks.append((path,error)))
    assert first == second and callbacks == []
    released.set()
    drain(page)
    assert len(callbacks) == 2 and all(path.is_file() and error is None for path,error in callbacks)
    assert page._persistence_queue.jobs_started == 1
    page.deleteLater()
    APP.processEvents()


def test_unchanged_repeated_save_skips_encoding_and_disk_but_direct_edit_does_not(tmp_path,monkeypatch):
    import twobyteasr.projects.studio_project as persistence
    original=persistence._atomic_json_blob_write;writes=[]
    def write(path,content):
        writes.append(path);return original(path,content)
    monkeypatch.setattr(persistence,'_atomic_json_blob_write',write)
    page=make_page(tmp_path);page.save();drain(page)
    count=len(writes)
    page.save();drain(page)
    assert len(writes)==count
    assert page._last_save_timeline['counters']['unchanged_file_reused']==1
    page.project.cues[0].text='direct edit without revision'
    page.save();drain(page)
    assert len(writes)==count+1
    assert load_project(page.session.project_path).cues[0].text=='direct edit without revision'
    page.deleteLater();APP.processEvents()


def test_undo_to_last_formal_content_still_supersedes_a_newer_recovery(tmp_path):
    from twobyteasr.projects.studio_project import save_autosave_revision, recoverable_autosave
    from twobyteasr.projects.studio_save import capture_manual_save
    page = make_page(tmp_path)
    page.save()
    drain(page)
    time.sleep(.03)
    page.project.cues[0].text = 'recovery B'
    page.undo_stack.push(QUndoCommand('B'))
    revision = capture_manual_save(page,page.project,2)
    save_autosave_revision(revision,page.session.project_path,session_id='beforeundo')
    assert recoverable_autosave(page.session.project_path) is not None
    page.project.cues[0].text = 'N0'
    page.undo_stack.undo()
    page.save()
    drain(page)
    assert page.undo_stack.isClean()
    assert load_project(page.session.project_path).cues[0].text == 'N0'
    assert recoverable_autosave(page.session.project_path) is None
    page.deleteLater()
    APP.processEvents()


def test_default_recovery_deadline_cannot_be_postponed_forever():
    deadline=AutosaveDeadline()
    deadline.mark_dirty(0)
    for second in range(1,30):deadline.mark_dirty(second)
    assert deadline.delay_seconds(29)==1
    assert deadline.due(30)
    deadline.mark_started();deadline.mark_dirty(31)
    assert deadline.dirty_since==0 and deadline.due(31)


def test_nested_frozen_maps_reuse_unchanged_encoded_children():
    from twobyteasr.projects.studio_revisions import FrozenMap,FrozenBlob
    from twobyteasr.projects.frozen_json_text import FrozenTextCache,frozen_part
    left=FrozenBlob.capture({'words':['unchanged']})
    right=FrozenBlob.capture({'words':['before']})
    cache=FrozenTextCache()
    def root(other):return FrozenMap((('instances',FrozenMap((('a',left),('b',other)))),))
    assert json.loads(''.join(frozen_part(root(right),cache)))['instances']['b']['words']==['before']
    cache.finish();encoded=cache.encoded
    updated = root(FrozenBlob.capture({'words':['after']}))
    assert json.loads(''.join(frozen_part(updated,cache)))['instances']['a']['words']==['unchanged']
    assert cache.encoded-encoded==1 and cache.reused>=1


def test_encoded_cache_transfer_requires_same_immutable_object_and_encoder():
    from twobyteasr.projects.studio_revisions import FrozenBlob
    from twobyteasr.projects.frozen_json_text import FrozenTextCache, pretty
    value = FrozenBlob.capture({'text':'unchanged'})
    source = FrozenTextCache()
    expected = source.frozen(value)
    source.finish()
    target = FrozenTextCache()
    assert target.reuse_from([value],[source]) == (1,len(expected))
    assert target.frozen(value) == expected and target.encoded == 0
    changed = FrozenBlob.capture({'text':'changed'})
    assert target.reuse_from([changed],[source]) == (0,0)
    assert json.loads(target.frozen(changed))['text'] == 'changed'
    incompatible = FrozenTextCache(pretty)
    assert incompatible.reuse_from([value],[source]) == (0,0)


def test_formal_save_reuses_recovery_encoding_and_still_detects_direct_evidence_edits(tmp_path):
    from twobyteasr.projects.studio_project import save_project_revision,save_autosave_revision
    from twobyteasr.projects.studio_save import capture_manual_save
    from twobyteasr.diagnostics.save_trace import SaveTrace
    page = make_page(tmp_path)
    page.project.asr_evidence = {'row':{'text':'before','words':[1,2,3]}}
    revision = capture_manual_save(page,page.project,1)
    recovery,_ = save_autosave_revision(revision,page.session.project_path,base=tmp_path/'recovery')
    trace = SaveTrace()
    with trace.activate():
        target,phases = save_project_revision(revision,tmp_path/'formal.2byteproj',compact=True)
    assert trace.counters['shared_encoded_chunks'] >= 1
    assert phases['pieces_reused'] >= 1
    page.project.asr_evidence['row']['text'] = 'after direct change'
    changed = capture_manual_save(page,page.project,2)
    save_project_revision(changed,target,compact=True)
    assert load_project(recovery).asr_evidence['row']['text'] == 'before'
    assert load_project(target).asr_evidence['row']['text'] == 'after direct change'
    page.deleteLater()
    APP.processEvents()


def test_compact_and_pretty_preserve_serialization_semantics(tmp_path):
    from dataclasses import replace
    from twobyteasr.projects.studio_save import capture_manual_save
    from twobyteasr.projects.studio_project import save_project_revision
    page=make_page(tmp_path)
    page.project.asr_evidence={'row':{'unicode':'你好 😀','nested':[None,True,False,1,1.25,-0.0],3:('tuple',2)}}
    snapshot=capture_manual_save(page,page.project,1)
    a,_=save_project_revision(snapshot,tmp_path/'pretty.2byteproj')
    b,_=save_project_revision(snapshot,tmp_path/'compact.2byteproj',compact=True)
    assert json.loads(a.read_text('utf8'))==json.loads(b.read_text('utf8'))
    page.deleteLater();APP.processEvents()


def test_save_completion_cannot_clean_undo_redo_aba(tmp_path, monkeypatch):
    import twobyteasr.projects.studio_project as persistence
    from twobyteasr.timeline.studio_commands import SetCueFieldsCommand
    from twobyteasr.projects.studio_runtime_state import state_for
    original = persistence._atomic_json_blob_write
    released = threading.Event()
    started = threading.Event()
    page = make_page(tmp_path)
    state_for(page.project)

    def held_write(path, content):
        started.set()
        released.wait(3)
        return original(path, content)

    monkeypatch.setattr(persistence, '_atomic_json_blob_write', held_write)
    page.save()
    assert started.wait(1)
    command = SetCueFieldsCommand(page.project, 'a', {'text': 'N+1'}, 'edit after request')
    page.undo_stack.push(command)
    page.undo_stack.undo()
    released.set()
    drain(page)
    assert not page.undo_stack.isClean()
    assert load_project(page.session.project_path).cues[0].text == 'N0'
    page.deleteLater()
    APP.processEvents()


def test_manual_translation_rollback_snapshots_only_translation_domains(monkeypatch):
    import twobyteasr.projects.studio_runtime_state as runtime
    from twobyteasr.studio.studio_bilingual import ManualTranslationCommand
    from twobyteasr.subtitle_rules import subtitle_translation as st
    from tests.test_bilingual_text_targets import make_project
    project = make_project()
    evidence = {'large': ['recognition']*10000}
    project.generation_metadata['raw_response'] = evidence
    unrelated = st.records_of(project)['source-b']
    before = st.snapshot(project)
    observed = []
    original = runtime._json_snapshot

    def capture(value):
        observed.append(value)
        return original(value)

    monkeypatch.setattr(runtime, '_json_snapshot', capture)
    cue = next(item for item in project.cues if item.id == 'source-a')
    command = ManualTranslationCommand(project, cue, '修改译文')
    command.redo()
    assert all(value is not project.generation_metadata and value is not evidence for value in observed)
    assert project.generation_metadata['raw_response'] is evidence
    assert st.records_of(project)['source-b'] is unrelated
    assert st.records_of(project)['source-a']['origin'] == 'manual'
    command.undo()
    assert st.snapshot(project) == before
    command.redo()
    assert st.records_of(project)['source-a']['text'] == '修改译文'
