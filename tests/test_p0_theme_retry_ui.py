"""Real panel state/Retry button, with fixture-only provider work."""
import copy,json,os,time
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtTest import QTest
from tests.test_studio_style_controller import _page,_finish


def test_phase_timeout_retains_candidates_and_button_retries_only_code(tmp_path,monkeypatch):
    from twobyteasr.caption_design import studio_theme_draft, studio_ai
    from twobyteasr.providers.ai_providers import AIProviderError
    app,page=_page(tmp_path,monkeypatch)
    try:
        design=json.loads((Path(__file__).parent/'fixtures/polar_bear_c40072_concepts.json').read_text(encoding='utf8'))
        design['selected_concept_id']='ski-bump-lockup'
        page._ai_last_instruction='北极熊滑雪镜，底部字幕'
        page._ai_request_generation+=1
        controller=page._theme_drafts();controller.begin(page._ai_request_generation,'a','subtitle','grok_oauth','grok-4.6')
        operation=controller.operation
        now=time.monotonic()
        controller._compiler_event(operation,dict(request_id='concepts-1',name='concepts',label='三个概念',
            started_monotonic=now-350,last_output_monotonic=now-200,status='complete',timeout_seconds=300,design=copy.deepcopy(design)))
        controller._compiler_event(operation,dict(request_id='code-1',name='theme_code',label='编写选定主题',
            started_monotonic=now-100,last_output_monotonic=now-1,status='running',timeout_seconds=300))
        controller.started=now-350
        controller._tick()
        assert controller.phase=='PROVIDER','second stage must have its own start, not the old 350 seconds'
        saved=json.loads((controller.root/'request.json').read_text(encoding='utf8'))
        assert saved['design']==design
        assert len(saved['compiler_phases'])==2
        controller._failed(operation,'主题代码 Provider 超时','theme_code_timeout')
        assert page.ai_retry_theme_code_button.isEnabled()
        assert controller.design==design and '北极熊' in page.ai_concept_details.toPlainText()
        calls=[]
        def request(*args,**kwargs):
            calls.append(kwargs)
            raise AIProviderError('fixture second-stage failure',category='theme_code_timeout')
        monkeypatch.setattr(studio_ai,'request_web_theme_design',request)
        page.ai_retry_theme_code_button.click()
        deadline=time.monotonic()+2.
        while time.monotonic()<deadline and controller.phase!='FAILED':QTest.qWait(10)
        assert len(calls)==1 and calls[0]['resume_design']==design
        assert controller.design==design and controller.current.model=='grok-4.6'
        assert controller.phase=='FAILED' and page.ai_retry_theme_code_button.isEnabled()
        old_detail=controller.detail
        controller._stage(operation,'old thinking result')
        assert controller.detail==old_detail
    finally:_finish(page)


def test_partial_static_heroes_retry_before_selection(tmp_path,monkeypatch):
    from twobyteasr.caption_design import studio_ai
    from twobyteasr.providers.ai_providers import AIProviderError
    from tests.test_hero_theme_compiler import design as make_design
    app,page=_page(tmp_path,monkeypatch)
    try:
        design=make_design('')
        design['concepts'][1].pop('hero_theme')
        controller=page._theme_drafts()
        page._ai_request_generation+=1
        controller.begin(page._ai_request_generation,'a','subtitle','grok_oauth','grok-4.6')
        controller.design=copy.deepcopy(design)
        controller._failed(controller.operation,'静态帧连接中断','transport_error')
        assert page.ai_retry_theme_code_button.isEnabled()
        assert page.ai_retry_theme_code_button.text()=='重试静态英雄帧'
        calls=[]
        def request(*args,**kwargs):
            calls.append(kwargs)
            raise AIProviderError('fixture interrupted',category='transport_error')
        monkeypatch.setattr(studio_ai,'request_web_theme_design',request)
        page.ai_retry_theme_code_button.click()
        deadline=time.monotonic()+2
        while time.monotonic()<deadline and controller.phase!='FAILED':QTest.qWait(10)
        assert len(calls)==1 and calls[0]['concepts_only'] is True
        assert calls[0]['resume_design']==design and controller.design['concepts'][0]['hero_theme']
    finally:_finish(page)
