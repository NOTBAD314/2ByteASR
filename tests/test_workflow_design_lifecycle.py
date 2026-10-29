import copy
from types import SimpleNamespace
from tests.test_studio_style_controller import _page, _finish
from tests.test_round14_web_theme_apply_fixes import _theme_payload
from tests.theme_fixture import bind_ready_draft
from twobyteasr.timeline.studio_edit_sequence import sequence_of, projected_cues
from twobyteasr.projects.studio_project import save_project,load_project

def test_independent_request_and_delete_before_return_terminate_current_only(tmp_path,monkeypatch):
    app,page=_page(tmp_path,monkeypatch)
    try:
        baseline=copy.deepcopy(projected_cues(page.project))
        sequence_of(page.project).segments[0].source_in_ms=100
        cue=projected_cues(page.project)[0]
        assert cue==baseline[0] and cue.id=='a'
        assert page.project.render_settings['_cue_domain']=='timeline'
        page.selected_cue_id=cue.id
        drafts=page._theme_drafts();page._ai_request_generation+=1
        drafts.begin(page._ai_request_generation,cue.id)
        assert drafts.request_project.cues[0].id==cue.id
        assert drafts.request_project.cues[0].start_ms==cue.start_ms
        assert page.project.cues[0].id=='a'
        oldop=drafts.operation;oldgen=drafts.current.generation
        page.project.cues.pop(0)
        drafts.receive(oldgen,cue.id,SimpleNamespace(source='concepts'))
        assert drafts.phase=='FAILED' and not drafts.generation_running
        assert page._pending_web_theme is None and not page._ai_request_active
        page.selected_cue_id=projected_cues(page.project)[0].id
        page._ai_request_generation+=1
        drafts.begin(page._ai_request_generation,page.selected_cue_id)
        newop=drafts.operation
        drafts._compiler_event(oldop,{})
        assert drafts.generation_running and drafts.operation==newop
        drafts.cancel()
    finally:_finish(page)

def test_apply_twice_then_save_reopen_keeps_valid_target(tmp_path,monkeypatch):
    app,page=_page(tmp_path,monkeypatch)
    try:
        drafts=bind_ready_draft(page,_theme_payload(),'a')
        page.select_cue('b');page._apply_ai_preview()
        assert drafts.phase=='APPLIED' and drafts.allow_pending()
        page.select_cue('c');page._apply_ai_preview()
        assert drafts.allow_pending()
        drafts.phase='RENDERING'
        assert drafts._target_current(), 'own application must survive preview retry'
        drafts.phase='APPLIED'
        loaded=load_project(save_project(page.project,tmp_path/'applied.2byteproj'))
        assert loaded.cues==page.project.cues and loaded.style_recipes==page.project.style_recipes
    finally:_finish(page)
