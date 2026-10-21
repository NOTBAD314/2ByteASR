"""A real Studio controller presents pixels and requires an explicit choice."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from tests.test_studio_style_controller import _page,_finish
from tests.test_caption_creative_pipeline import authored

def test_unreviewed_pixels_hold_selection_and_application(tmp_path,monkeypatch):
    app,page=_page(tmp_path,monkeypatch)
    try:
        ledger,result=authored(tmp_path/'ledger')
        page.ai_prompt.setPlainText('Balatro 三个不同构图')
        page._ai_request_generation+=1
        controller=page._theme_drafts();controller.begin(page._ai_request_generation,'a')
        controller.design=dict(schema_version=4,brief=result.brief,concepts=result.concepts,selected_concept_id='')
        controller._concepts_ready(controller.operation,{c:'not-shown.png' for c in 'ABC'})
        assert controller.phase=='VISUAL_REVIEW'
        assert controller._concept_dialog.isVisible()
        assert not controller.auto_apply and not controller.design['selected_concept_id']
        assert not page.ai_apply_button.isEnabled() and not page.ai_retry_theme_code_button.isEnabled()
    finally:_finish(page)


def test_ready_with_failed_peer_keeps_selected_theme_usable(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.caption_design.theme_draft import canonical_theme, digest
    app,page=_page(tmp_path,monkeypatch)
    try:
        ledger,result=authored(tmp_path/'ledger')
        concepts=result.concepts
        concepts[1]={'id':'B','name':'失败候选','composition':'技术检查未通过，原稿已保留',
                     'technical_status':'failed','technical_errors':[{'path':'motionSpec.ease'}]}
        controller=page._theme_drafts()
        page._ai_request_generation+=1
        draft=controller.begin(page._ai_request_generation,'a')
        theme=concepts[2]['authored_theme']
        evidence=dict(passed=True,request_id=draft.request_id,content_hash=digest(canonical_theme(theme)),frames=[])
        monkeypatch.setattr(page,'_start_web_theme_storyboard',lambda theme:None)
        suggestion=SimpleNamespace(source='ai',theme=theme,concepts=concepts,brief=result.brief,
            selected_concept_id='C',quality={'design_version':4},render_evidence=evidence)
        controller.receive(draft.generation,'a',suggestion)
        assert controller.phase=='READY'
        assert controller.allow_pending() and page.ai_apply_button.isEnabled()
        assert '失败候选' in page.ai_concept_details.toPlainText()
        assert '技术未通过，原稿保留' in page.ai_concept_details.toPlainText()
    finally:_finish(page)
