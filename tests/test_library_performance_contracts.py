import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


def test_summary_skips_evidence_and_caption_graph(tmp_path, monkeypatch):
    from twobyteasr.projects.project_summary import naming_payload,read_project_summary
    payload={'project_id':'a','schema_version':1,'media':{'path':'media.mp4','duration_ms':1000},
        'cues':[{'id':str(i),'text':'{ \\" [ ] 中文'} for i in range(100)],
        'asr_evidence':{'unused':{'text':'{ " \\ }','words':[{'text':'x'}]*1000}},
        'studio_state':{'project_name':'人取的名字','source_archive':[{}]*1000}}
    path=tmp_path/'project.2byteproj';path.write_text(json.dumps(payload,ensure_ascii=False),'utf-8')
    projected=naming_payload(path)
    assert projected['cues']==100 and 'asr_evidence' not in projected
    assert projected['studio_state']=={'project_name':'人取的名字'}
    summary=read_project_summary(path)
    assert summary['name_custom'] and summary['name']=='人取的名字'
    from twobyteasr.projects.project_display_name import display_project_name
    monkeypatch.setattr(Path,'stat',lambda *a,**k:pytest.fail('display attempted filesystem IO'))
    assert display_project_name(dict(summary,path=str(path)),read=False)=='人取的名字'


def test_reader_coalesces_and_never_lends_mutable_data(tmp_path,monkeypatch):
    from twobyteasr.projects import project_read_cache as cache
    import time
    path=tmp_path/'p.2byteproj';path.write_text(json.dumps({'cues':[{'text':'before'}]}))
    cache.clear();calls=[];original=cache.json.load
    def read(*args,**kwargs):calls.append(1);time.sleep(.03);return original(*args,**kwargs)
    monkeypatch.setattr(cache.json,'load',read)
    with ThreadPoolExecutor(4) as pool:values=list(pool.map(cache.read_payload,[path]*4))
    assert len(calls)==1
    values[0]['cues'][0]['text']='edit'
    assert all(value['cues'][0]['text']=='before' for value in values[1:])
    path.write_text(json.dumps({'cues':[{'text':'external replacement'}]}))
    assert cache.read_payload(path)['cues'][0]['text']=='external replacement'
    assert len(calls)==2


def test_bad_snapshot_never_calls_binding_deepcopy_and_releases_transaction():
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia
    from twobyteasr.projects.studio_runtime_state import state_for,DirtyDomain
    class NativeBinding:
        def __deepcopy__(self,memo):pytest.fail('native deepcopy invoked')
    project=SubtitleProject(media=StudioMedia(path=''));project.studio_state={'bad':NativeBinding()};state=state_for(project)
    with pytest.raises(TypeError,match='runtime data'):
        with state.transaction(project,action_id='invalid',dirty=DirtyDomain.PROJECT_METADATA):pass
    assert state._active is None
    project.studio_state={}
    with state.transaction(project,action_id='valid',dirty=DirtyDomain.PROJECT_METADATA):pass
    assert state.revision==1


def test_scoped_metadata_rollback_and_nested_upgrade():
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia
    from twobyteasr.projects.studio_runtime_state import state_for,DirtyDomain
    project=SubtitleProject(media=StudioMedia(path=''),studio_state={'local':1,'archive':{'large':[1,2]}},
        generation_metadata={'translations':{'a':'before'},'history':{'large':[3,4]}})
    state=state_for(project);archive=project.studio_state['archive'];history=project.generation_metadata['history']
    with pytest.raises(RuntimeError):
        with state.transaction(project,action_id='edit',dirty=DirtyDomain.PROJECT_METADATA,
                studio_state_keys=('local',),generation_metadata_keys=('translations',)):
            project.studio_state['local']=2;project.generation_metadata['translations']['a']='after'
            raise RuntimeError('abort')
    assert project.studio_state['local']==1 and project.generation_metadata['translations']=={'a':'before'}
    assert project.studio_state['archive'] is archive and project.generation_metadata['history'] is history
    with pytest.raises(RuntimeError):
        with state.transaction(project,action_id='outer',dirty=DirtyDomain.PROJECT_METADATA,
                studio_state_keys=('local',),generation_metadata_keys=('translations',)):
            project.studio_state['local']=2;project.generation_metadata['translations']['a']='after'
            with state.transaction(project,action_id='inner',dirty=DirtyDomain.PROJECT_METADATA):
                project.studio_state['new']='x'
            raise RuntimeError('abort')
    assert project.studio_state=={'local':1,'archive':{'large':[1,2]}}
    assert project.generation_metadata['translations']=={'a':'before'}


def test_selection_snapshot_omits_runtime_and_unrelated_evidence():
    from twobyteasr.projects.studio_project import SubtitleProject,StudioCue,StudioMedia
    from twobyteasr.projects.project_snapshot import presentation_snapshot
    project=SubtitleProject(media=StudioMedia(path=''),cues=[StudioCue(id='a',text='A',start_ms=0,end_ms=1000,evidence_refs=['used']),
        StudioCue(id='b',text='B',start_ms=1000,end_ms=2000)])
    class DontCopy:
        def __deepcopy__(self,memo):pytest.fail('unrelated graph cloned')
    project.asr_evidence={'used':{'text':'A'},'unrelated':DontCopy()};project._runtime_cache=DontCopy()
    clone=presentation_snapshot(project,cue_ids={'a'})
    assert [cue.id for cue in clone.cues]==['a'] and clone.asr_evidence=={'used':{'text':'A'}}
    clone.cues[0].text='different';assert project.cues[0].text=='A'
    assert not hasattr(clone,'_runtime_cache')


def test_qt_warning_retains_type_without_private_paths():
    from twobyteasr.diagnostics.qt_warning_detail import warning_detail
    row=warning_detail('QObject::moveToThread: object "private subtitle" C:\\Users\\person\\private.txt 0x1234 different thread')
    assert row['qt_warning_family']=='thread_affinity'
    assert all(x not in row['qt_diagnostic'] for x in ['private subtitle','person','0x1234'])


def test_pending_seek_cannot_advance_new_media_epoch(monkeypatch,tmp_path):
    from twobyteasr.playback.studio_mpv import MpvController
    player=MpvController();jobs=[];sent=[]
    monkeypatch.setattr(player,'_post',lambda fn,**kw:jobs.append(fn) or True)
    monkeypatch.setattr(player,'_send',lambda command:sent.append(command) or {})
    player.post_seek(7,generation=4)
    assert player.source_epoch==4  # visible before the actor executes it
    player.post_load_at(tmp_path/'new.mp4',0,generation=5)
    jobs[1]();jobs[0]()  # foreground load overtakes the obsolete seek
    assert player.source_epoch==5 and player.applied_seek_state()['generation']==5
    assert [command[0] for command in sent]==['loadfile']


def test_seek_during_async_load_waits_for_matching_file_loaded(monkeypatch,tmp_path):
    from twobyteasr.playback.studio_mpv import MpvController
    player=MpvController();jobs=[];sent=[];source=str((tmp_path/'current.mp4').resolve())
    monkeypatch.setattr(player,'_post',lambda fn,**kw:jobs.append(fn) or True)
    monkeypatch.setattr(player,'_send',lambda command:sent.append(command) or {})
    monkeypatch.setattr(player,'get_property',lambda *a:source)
    player._begin_subtitle_media(source)
    player.post_seek(0,generation=4);jobs.pop(0)()
    assert sent==[] and player.applied_seek_state()=={}
    player._subtitle_file_loaded();jobs.pop(0)();jobs.pop(0)()
    assert sent==[['seek',0.0,'absolute+exact']]
    assert player.applied_seek_state()['generation']==4


def test_translation_commit_reuses_caption_archive_and_persistence_detects_nested_edits():
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia,StudioCue
    from twobyteasr.projects.studio_revisions import StudioRevisionStore,thaw_json
    from twobyteasr.projects.studio_runtime_state import state_for
    from twobyteasr.timeline.studio_caption_timeline import ensure_independent_captions,KEY
    from twobyteasr.timeline.studio_commands import BatchReplaceTextCommand
    project=SubtitleProject(media=StudioMedia(path='',duration_ms=2000),
        cues=[StudioCue(id='a',start_ms=0,end_ms=1000,text='原文')],
        generation_metadata={'translations':{'a':'old'},'history':{'items':[1,2,3]}})
    project.validate();ensure_independent_captions(project)
    state=state_for(project);store=StudioRevisionStore(project);state.subscribe(store.consume)
    archive=dict(dict(store.render.studio_state.items)[KEY].items)['source_archive']
    from twobyteasr.studio.subtitle_text_targets import text_entries
    language=text_entries(project,mode='translation')[0].target.language
    command=BatchReplaceTextCommand(project,{},translation_values={'a':('new',language)})
    command.redo()
    assert thaw_json(store.render.generation_metadata)['translations']['a']=='new'
    assert dict(dict(store.render.studio_state.items)[KEY].items)['source_archive'] is archive
    before=store.refresh_persistence(state.revision)
    history=before.generation_metadata
    assert store.refresh_persistence(state.revision).generation_metadata is history
    project.generation_metadata['history']['items'].append(4)
    after=store.refresh_persistence(state.revision,deep=True)
    assert thaw_json(after.generation_metadata)['history']['items']==[1,2,3,4]
    assert thaw_json(before.generation_metadata)['history']['items']==[1,2,3]
    command.undo();assert thaw_json(store.render.generation_metadata)['translations']['a']=='old'


def test_open_save_index_keeps_media_name_and_dimensions(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.projects import studio_project as model
    from twobyteasr.projects.studio_project_controller import StudioProjectController
    path=tmp_path/('p-'+'a'*32)/'project.2byteproj';path.parent.mkdir();path.write_text('{}')
    settings=tmp_path/'settings.json'
    monkeypatch.setattr(model,'studio_settings_path',lambda:settings)
    project=model.SubtitleProject(model.StudioMedia(path='节目.mp4',display_name='节目.mp4',width=1920,height=1080))
    controller=StudioProjectController(None,SimpleNamespace(project=project))
    controller._remember_recent_project(path,settings_path_fn=lambda:settings)
    recent=json.loads(settings.read_text('utf-8'))['recent_projects'][0]
    entry=model.load_library_index()[str(path.resolve())]
    assert recent['name']=='节目' and entry['name']=='节目'
    assert (entry['width'],entry['height'])==(1920,1080)
    assert 'summary_version' not in recent and 'width' not in recent


def test_deep_evidence_refresh_reuses_equal_immutable_bytes():
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia
    from twobyteasr.projects.studio_revisions import StudioRevisionStore,thaw_json
    project=SubtitleProject(StudioMedia(path=''),asr_evidence={'row':{'words':[{'text':'a','start_ms':0,'end_ms':100}]}})
    project.validate();store=StudioRevisionStore(project)
    first=store._evidence_rows['row']
    store.refresh_persistence(1,deep=True)
    second=store._evidence_rows['row']
    assert second[1] is first[1] and second[1] is second[2].data
    project.asr_evidence['row']['words'][0]['text']='b'
    assert store.evidence_rows_changed_in_place(['row'])==['row']
    assert thaw_json(store.refresh_persistence(2).asr_evidence)['row']['words'][0]['text']=='b'
