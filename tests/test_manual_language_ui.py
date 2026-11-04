"""Real Studio sheet controls own the source choice and dispatch a snapshot."""
from tests.test_round42_studio_recognition import _app,_page,_open_sheet


def test_studio_language_is_explicit_and_model_plan_does_not_override_it(monkeypatch,tmp_path):
    page=_page(monkeypatch,tmp_path)
    try:
        page._subtitle_language_options=lambda:dict(recognition_language='ja',subtitle_output='original',translation_script='zh-Hans')
        controls=_open_sheet(page,tmp_path)
        language=controls['source_language']
        assert language.isEnabled() and language.currentData()=='ja'
        language.setCurrentIndex(language.findData('it'))
        controls['plan'].setCurrentIndex(controls['plan'].findData('english'))
        _app().processEvents()
        assert language.currentData()=='it'
        page.project.cues=[]
        controls['start'].click()
        assert page.recognition_request_options()['recognition_language']=='it'
        language.setCurrentIndex(language.findData('auto'))
        page._subtitle_language_options=lambda:dict(recognition_language='de')
        assert page.recognition_request_options()['recognition_language']=='it'
    finally:page.close_page()


def test_saved_manual_project_overrides_home_auto_only_on_its_own_sheet(monkeypatch,tmp_path):
    page=_page(monkeypatch,tmp_path)
    try:
        page.project.generation_metadata['language']=dict(requested='en',code='en',mode='manual')
        page._subtitle_language_options=lambda:dict(recognition_language='auto',subtitle_output='original',translation_script='zh-Hans')
        controls=_open_sheet(page,tmp_path)
        assert controls['source_language'].currentData()=='en'
    finally:page.close_page()
