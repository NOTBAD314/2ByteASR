import copy
import time
import pytest
from twobyteasr.projects.link_cleanup_validation import validate_cleanup_response
from twobyteasr.projects.studio_project import StudioCue,StudioMedia,SubtitleProject


def project():
    value=SubtitleProject(media=StudioMedia(path=""),cues=[
        StudioCue("one",0,1000,"hello world"),StudioCue("two",1000,2000,"yes yes")])
    value.studio_state["link_imports"]={"version":1}
    value.validate()
    return value


@pytest.mark.parametrize("bad",[
    {"cue_id":"absent","original":"hello world","replacement":"Hello world","reason":"case"},
    {"cue_id":"one","original":"hello","replacement":"Hello","reason":"case"},
    {"cue_id":"one","original":"hello world","replacement":"","reason":"erase"},
    {"cue_id":"one","original":"hello world","replacement":"Hello world","reason":"case","start_ms":12},
    {"cue_id":"one","original":"hello world","replacement":"Hello world","reason":"case","confidence":float("nan")},
])
def test_bad_ai_batch_rejects_every_change_without_mutating_source(bad):
    source=project();before=copy.deepcopy(source.cues)
    valid=dict(cue_id="two",original="yes yes",replacement="Yes yes.",reason="punctuation")
    with pytest.raises(ValueError):
        validate_cleanup_response({"changes":[valid,bad]},source.cues)
    assert source.cues==before


def test_valid_ai_subset_and_duplicate_ids():
    source=project()
    item=dict(cue_id="one",original="hello world",replacement="Hello world.",reason="punctuation")
    assert validate_cleanup_response({"changes":[item]},source.cues)["changes"]==[item]
    with pytest.raises(ValueError):
        validate_cleanup_response({"changes":[item,item]},source.cues)


@pytest.mark.parametrize("dialog_kind", ["download", "standard"])
def test_light_defaults_async_and_stale_preview_is_discarded(monkeypatch, dialog_kind):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    from twobyteasr.studio import link_caption_cleanup as module
    from twobyteasr.app import api_key_explainer
    app=QApplication.instance() or QApplication([])
    page=SubtitleStudioPage()
    page.project=project()
    from twobyteasr.studio.studio_find_replace import AiCleanupDialog
    dialog_type = module.LinkCaptionCleanupDialog if dialog_kind == "download" else AiCleanupDialog
    dialog=dialog_type(page,page)
    monkeypatch.setattr(api_key_explainer,"ask_for_key_if_missing",lambda *a,**k:False)
    def slow(*a,**k):
        time.sleep(.25)
        return []
    monkeypatch.setattr(module,"request_text_cleanup",slow)
    try:
        checked={key for key,box in dialog.ai_option_boxes.items() if box.isChecked()}
        assert checked=={"glossary","punctuation"}
        from twobyteasr.studio.studio_find_replace import AiCleanupDialog
        assert isinstance(dialog, AiCleanupDialog) and dialog.ai_run_button.isEnabled()
        started=time.monotonic();dialog._do_ai_preview()
        assert time.monotonic()-started<.2 and dialog._cleanup_running
        page.project.cues[0].text="new edit"
        # Under QTest.qWait the worker gets little time; wait for the result.
        for _ in range(250):
            if not dialog._cleanup_running:
                break
            QTest.qWait(20)
        assert not dialog._cleanup_running and "未应用" in dialog.status_label.text()
        assert page.project.cues[0].text=="new edit"
        dialog._do_ai_preview()
        dialog.reject()
        assert dialog._cleanup_cancel.is_set() and not dialog._runner.timer.isActive()
        QTest.qWait(300)
    finally:
        dialog.reject();page.close_page();page.close();app.processEvents()
