"""Real three-card panel and selected-stage retry; provider is an explicit fixture."""
import copy,json,time
from pathlib import Path
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from tests.test_studio_style_controller import _page,_finish


def test_brief_retry_and_concept_preview_cancel_are_actionable(tmp_path,monkeypatch):
    app,page=_page(tmp_path,monkeypatch)
    try:
        controller=page._theme_drafts();page._ai_request_generation+=1
        controller.begin(page._ai_request_generation,'a','subtitle','fixture','fixture')
        controller.design={'schema_version':2,'brief':{'style':'snow'},'concepts':[],'selected_concept_id':''}
        controller._failed(controller.operation,'fixture concepts failure','concepts_error')
        assert page.ai_retry_theme_code_button.isEnabled()
        assert page.ai_retry_theme_code_button.text()=='重试三个方向'
        controller._set_phase('CONCEPT_PREVIEW','fixture preview in progress')
        assert page.ai_cancel_render_button.isEnabled()
        controller.cancel()
        assert controller.phase=='CANCELLED' and controller.design['brief']['style']=='snow'
    finally:_finish(page)


def test_three_actual_component_previews_require_selection(tmp_path,monkeypatch):
    from twobyteasr.caption_design import studio_ai
    from twobyteasr.providers.ai_providers import AIProviderError
    app,page=_page(tmp_path,monkeypatch)
    try:
        controller=page._theme_drafts();page._ai_request_generation+=1
        controller.begin(page._ai_request_generation,'a','subtitle','fixture','fixture')
        design=json.loads((Path(__file__).parent/'fixtures/snow_fleece_v2_concepts.json').read_text('utf8'))
        result=studio_ai.AIWebThemeSuggestion(theme={},source='concepts',message='',trace_path='',provider='fixture',
            elapsed_seconds=0,brief=design['brief'],concepts=design['concepts'])
        controller.receive(controller.current.generation,'a',result)
        deadline=time.monotonic()+20
        while controller.phase=='CONCEPT_PREVIEW' and time.monotonic()<deadline:QTest.qWait(30)
        assert controller.phase=='CHOOSING'
        assert len(controller.concept_previews)==3 and all(Path(p).stat().st_size>1000 for p in controller.concept_previews.values())
        assert not page.ai_retry_theme_code_button.isEnabled()
        calls=[]
        def request(*args,**kwargs):
            calls.append(copy.deepcopy(kwargs['resume_design']))
            raise AIProviderError('fixture selected-stage stop',category='fixture')
        monkeypatch.setattr(studio_ai,'request_web_theme_design',request)
        dialog=controller._concept_dialog
        buttons=dialog.findChildren(__import__('PySide6.QtWidgets',fromlist=['QPushButton']).QPushButton)
        selected=next(b for b in buttons if '采用' in b.text())
        QTest.mouseClick(selected,Qt.LeftButton)
        deadline=time.monotonic()+3
        while controller.phase=='PROVIDER' and time.monotonic()<deadline:QTest.qWait(20)
        assert len(calls)==1 and calls[0]['selected_concept_id']=='snow-fleece-halt'
        assert controller.phase=='FAILED' and len(controller.design['concepts'])==3
    finally:_finish(page)


def test_actual_archive_export_accepts_user_middle_placement(tmp_path,monkeypatch):
    from twobyteasr.caption_style.web_placement import normalize_placement
    app,page=_page(tmp_path,monkeypatch)
    try:
        theme=json.loads((Path(__file__).parent/'fixtures/snow_fleece_v2_final.json').read_text('utf8'))
        placement=normalize_placement({'x':.5,'y':.56,'originY':.95})
        page.project.cues[0].transform={'web_placement':placement}
        controller=page._theme_drafts();controller.adopt(theme,'a')
        deadline=time.monotonic()+40
        while controller.phase=='RENDERING' and time.monotonic()<deadline:QTest.qWait(20)
        assert controller.is_valid(),(controller.phase,controller.error)
        controller.export(tmp_path/'archive')
        deadline=time.monotonic()+40
        while controller.phase=='EXPORTING' and time.monotonic()<deadline:QTest.qWait(20)
        assert controller.phase=='EXPORTED',controller.error
        archive=Path(controller.last_export)
        assert json.loads((archive/'placement.json').read_text('utf8'))==placement
        evidence=json.loads(next(controller.root.glob('export-*/validation.json')).read_text('utf8'))
        assert evidence['passed'] and evidence['anchor_validation']=='user placement'
        assert evidence['cue_motion_region'][1]<480
        assert max(evidence['cue_motion_differences'])>.025
    finally:_finish(page)
