import copy
import json
from tests.test_studio_style_controller import _page,_finish

def test_incremental_completion_keeps_task_alive_and_cancel_rejects_old_callbacks(tmp_path,monkeypatch):
    app,page=_page(tmp_path,monkeypatch)
    try:
        controller=page._theme_drafts();page._ai_request_generation+=1
        controller.begin(page._ai_request_generation,'a','subtitle','fixture','fixture')
        operation=controller.provider_operation;cancel=controller.cancel_event
        shown=[]
        def show(op,previews):
            shown.append(copy.deepcopy(controller.design));controller.phase='CHOOSING'
        monkeypatch.setattr(controller,'_concepts_ready',show)
        event=dict(name='candidate_complete',label='方向 A 已保存',request_id='fixture/A',status='complete',
            partial_concepts=[dict(id='A',name='A',composition='complete',technical_status='failed')],
            pending_directions=[dict(id='B',name='B',composition_family='B'),dict(id='C',name='C',composition_family='C')],
            brief={'raw_user_prompt':'fixture'})
        controller._compiler_event(operation,event)
        assert controller.generation_running and len(shown)==1
        assert [c['technical_status'] for c in shown[0]['concepts']]==['failed','pending','pending']
        assert controller.provider_request_current(operation,controller.current.generation,cancel)
        controller.cancel()
        assert controller.phase=='CANCELLED' and not controller.generation_running
        controller._compiler_event(operation,event)
        assert len(shown)==1 and not controller.provider_request_current(operation,controller.current.generation,cancel)
    finally:_finish(page)

def test_saved_discovery_ignores_broken_files_and_never_claims_remote_running(tmp_path):
    from twobyteasr.caption_design.saved_theme_tasks import saved_tasks
    for name,value in [('valid',json.dumps(dict(pipeline='authored-stages-1',raw_user_prompt='北极熊',status='implementing',
            partial_concepts=[dict(id='A',motion_preview={'status':'motion_ready'})]))),('broken','{')]:
        path=tmp_path/name/'creative';path.mkdir(parents=True);(path/'ledger.json').write_text(value,'utf8')
    rows=saved_tasks(tmp_path)
    assert len(rows)==1 and '1/3' in rows[0]['label'] and 'running' not in rows[0]['label']


def test_later_provider_timeout_keeps_selected_operation(tmp_path,monkeypatch):
    app,page=_page(tmp_path,monkeypatch)
    try:
        controller=page._theme_drafts();page._ai_request_generation+=1
        controller.begin(page._ai_request_generation,'a','subtitle','fixture','fixture')
        provider=controller.provider_operation
        controller.operation='selected-export';controller.phase='EXPORTING'
        controller._failed(provider,'bounded deadline','provider_total_timeout')
        assert not controller.generation_running
        assert controller.operation=='selected-export' and controller.phase=='EXPORTING'
        assert not controller.cancel_event.is_set()
        assert controller.design['generation_failure']['category']=='provider_total_timeout'
    finally:_finish(page)


def test_saved_dialog_keeps_explicit_legacy_record_entry(tmp_path,monkeypatch):
    from twobyteasr.caption_design.saved_theme_tasks import SavedThemeTasksDialog,QFileDialog
    app,page=_page(tmp_path,monkeypatch)
    try:
        path=str(tmp_path/'old-ledger.json')
        monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a,**k:(path,''))
        dialog=SavedThemeTasksDialog([],page);dialog.open_record()
        assert dialog.path==path and dialog.resume
        dialog.deleteLater()
    finally:_finish(page)
