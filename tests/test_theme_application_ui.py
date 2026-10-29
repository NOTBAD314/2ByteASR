from tests.test_studio_style_controller import _page,_finish
from tests.test_theme_usability import valid_artwork
from twobyteasr.caption_design.theme_application_ui import refresh_application_ui


def test_auto_application_state_undo_and_other_cue(tmp_path,monkeypatch):
    app,page=_page(tmp_path,monkeypatch)
    try:
        drafts=page._theme_drafts();page._ai_request_generation+=1
        drafts.begin(page._ai_request_generation,'a','subtitle','local','local')
        drafts.current=drafts.current.with_theme(valid_artwork())
        drafts.auto_apply=True;drafts.generation_running=False
        drafts._set_phase('RENDERING','正在应用')
        refresh_application_ui(page)
        assert '正在' in page.ai_application_status.text() and not page.ai_apply_button.isEnabled()
        monkeypatch.setattr(page,'_start_web_theme_storyboard',lambda *a:None)
        drafts._ready(drafts.operation,dict(passed=True,content_hash=drafts.current.content_hash,frames=[]))
        assert drafts.phase=='APPLIED'
        refresh_application_ui(page)
        assert '已应用到当前字幕' in page.ai_application_status.text()
        assert page.ai_apply_button.text()=='重新应用到当前字幕'
        assert page.ai_apply_button.minimumHeight()>=40
        page.undo_stack.undo();refresh_application_ui(page)
        assert '尚未应用' in page.ai_application_status.text()
        page.undo_stack.redo();refresh_application_ui(page)
        assert '已应用' in page.ai_application_status.text()
        page.select_cue('b');refresh_application_ui(page)
        assert '尚未应用' in page.ai_application_status.text()
        assert page.ai_apply_button.isEnabled()
    finally:_finish(page)


def test_stale_target_has_rebind_action(tmp_path,monkeypatch):
    app,page=_page(tmp_path,monkeypatch)
    try:
        drafts=page._theme_drafts();page._ai_request_generation+=1
        drafts.begin(page._ai_request_generation,'a','subtitle','local','local')
        drafts.current=drafts.current.with_theme(valid_artwork())
        drafts.phase='FAILED';drafts.category='stale_target';drafts.generation_running=False
        refresh_application_ui(page)
        assert '改变或删除' in page.ai_application_status.text()
        assert page.ai_apply_button.text()=='重试应用到当前字幕'
        calls=[];monkeypatch.setattr(drafts,'adopt',lambda theme,cue_id,**kw:calls.append(cue_id))
        page.ai_apply_button.click();assert calls==['a']
    finally:_finish(page)
