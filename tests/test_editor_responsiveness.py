from types import SimpleNamespace
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from twobyteasr.studio.studio_cards import _SubtitleEditCardEditor
from twobyteasr.studio.studio_canvas_edit import StudioCanvasEditMixin
from twobyteasr.studio.studio_video_canvas import MpvCanvas

@pytest.fixture(scope='module', autouse=True)
def app():
    yield QApplication.instance() or QApplication([])

def test_preedit_enter_does_not_submit_editor():
    editor=_SubtitleEditCardEditor(); hits=[]
    editor.commit_requested.connect(hits.append)
    QApplication.sendEvent(editor,QInputMethodEvent('にほん',[]))
    QTest.keyClick(editor,Qt.Key_Return)
    assert hits == []
    event=QInputMethodEvent();event.setCommitString('日本')
    QApplication.sendEvent(editor,event)
    assert editor.toPlainText() == '日本'
    QTest.keyClick(editor,Qt.Key_Return)
    assert hits == [False]
    editor.close()

def test_preview_cannot_be_starved_by_continuous_typing():
    from PySide6.QtCore import QTimer
    editor=object();timer=QTimer();timer.setSingleShot(True);timer.setInterval(40);hits=[]
    timer.timeout.connect(lambda:hits.append(True))
    page=SimpleNamespace(_canvas_editor=editor,subtitle_edit_input=editor,selected_cue_id='c',_edit_preview_timer=timer,
                         _studio_trace=lambda *args, **kwargs: None)
    for _ in range(60):
        StudioCanvasEditMixin._queue_edit_preview(page)
        QTest.qWait(10)
    timer.stop()
    assert len(hits)>=2

def test_initial_video_size_never_queries_silent_actor():
    def blocked(*args):
        raise AssertionError('GUI performed synchronous IPC')
    page=SimpleNamespace(controller=SimpleNamespace(running=True,observed_property=lambda *a:None,get_property=blocked),_video_display_size=(0,0))
    # The old method swallowed exceptions; count instead.
    calls=[];page.controller.get_property=lambda *a:calls.append(a)
    MpvCanvas._emit_initial_video_size(page)
    assert calls == []

def test_rejected_async_subtitle_does_not_retry_synchronously(tmp_path):
    ass=tmp_path/'preview.ass';ass.write_text('test')
    calls=[]
    page=SimpleNamespace(_ass_path=str(ass),controller=SimpleNamespace(running=True,post_subtitle_file=lambda p:False,set_subtitle_file=lambda p:calls.append(p)))
    MpvCanvas._load_subtitle_when_ready(page)
    assert calls == []


def test_compile_key_does_not_thaw_unrelated_caption_archive(monkeypatch):
    from dataclasses import replace
    from twobyteasr.projects import studio_revisions as module
    from twobyteasr.projects.studio_project import SubtitleProject, StudioMedia
    revision=module.StudioRevisionStore(SubtitleProject(StudioMedia(""))).render
    archive=module.freeze_json({"instances":{"c1":{"words":[{"text":"原文"}]*1000}}})
    revision=replace(revision,studio_state=module.FrozenMap((
        ("caption_timeline",archive),("bilingual",module.freeze_json({"mode":"bilingual"})))))
    original=module.thaw_json
    def guarded(value):
        assert value is not archive, "compile_key expanded unrelated project archive"
        return original(value)
    monkeypatch.setattr(module,"thaw_json",guarded)
    assert "bi:" in revision.compile_key[-1]


def test_slow_compile_key_never_holds_submit_lock():
    import threading,time
    from twobyteasr.rendering.ass_compile_actor import AssCompileActor
    started=threading.Event();release=threading.Event();completed=threading.Event()
    class SlowRevision:
        @property
        def compile_key(self):
            started.set()
            assert release.wait(3)
            return ("same",1,1,"mono")
    actor=AssCompileActor(lambda _:None,lambda *_:None)
    actor._last_key=(0,("same",1,1,"mono"));actor._last_content="cached"
    actor.submit(1,SlowRevision())
    assert started.wait(2)
    # This is the call made by the GUI timer. Fail on a blocking queue lock,
    # then release the worker so a failing test cannot leave a hung process.
    thread=threading.Thread(target=lambda:(actor.submit(2,SlowRevision()),completed.set()))
    thread.start()
    responsive=completed.wait(.1)
    release.set();thread.join(2);actor.close()
    assert responsive


def test_persistence_shares_unchanged_evidence_and_detects_inplace_change():
    from twobyteasr.projects.studio_revisions import StudioRevisionStore,thaw_json
    from twobyteasr.projects.studio_project import SubtitleProject,StudioMedia
    project=SubtitleProject(StudioMedia(""),asr_evidence={"e":{"words":[{"text":"旧"}]}})
    store=StudioRevisionStore(project)
    first=store.refresh_persistence(1).asr_evidence
    assert store.refresh_persistence(2).asr_evidence is first
    project.asr_evidence["e"]["words"][0]["text"]="新"
    # 2026-10-22: an autosave trusts a row object it has seen (re-reading all
    # evidence cost ~80 ms per snapshot); a formal save compares every row,
    # and the idle check after an autosave drops a row changed in place.
    assert store.refresh_persistence(3).asr_evidence is first
    updated=store.refresh_persistence(4,deep=True).asr_evidence
    assert updated is not first
    assert thaw_json(updated)["e"]["words"][0]["text"]=="新"
    project.asr_evidence["e"]["words"][0]["text"]="再改"
    assert store.evidence_rows_changed_in_place(["e"])==["e"]
    assert thaw_json(store.refresh_persistence(5).asr_evidence)["e"]["words"][0]["text"]=="再改"




def test_application_filter_does_not_submit_or_cancel_ime_candidate():
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    editor=_SubtitleEditCardEditor();calls=[]
    owner=SimpleNamespace(_canvas_editor=editor,
        _FILTERED_EVENT_TYPES=SubtitleStudioPage._FILTERED_EVENT_TYPES,
        _studio_trace=lambda *a,**kw:None,
        _commit_canvas_inline_edit=lambda **kw:calls.append("commit"),
        _cancel_canvas_inline_edit=lambda:calls.append("cancel"))
    QApplication.sendEvent(editor,QInputMethodEvent('にほん',[]))
    for key in (Qt.Key_Return,Qt.Key_Enter,Qt.Key_Escape):
        event=QKeyEvent(QEvent.KeyPress,key,Qt.NoModifier)
        assert SubtitleStudioPage.eventFilter(owner,editor,event) is False
    assert calls==[]
    editor.close()
