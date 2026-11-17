"""Bound single-character edits and reentrant network/window lifecycles."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import threading,time
import pytest
from PySide6.QtCore import Qt,QEvent
from PySide6.QtGui import QKeyEvent,QInputMethodEvent,QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QWidget
from tests.test_review_replay_and_window_bounds import _page
from twobyteasr.projects.studio_project import StudioCue
from twobyteasr.studio.caption_editor import qt_position

@pytest.fixture
def page(tmp_path,monkeypatch):
    app,page=_page(tmp_path,monkeypatch,[StudioCue('a',0,5000,'😀她说他和它，其他人弹吉他。'),StudioCue('b',5100,8000,'他没改变')])
    page._open_caption_editor('a','original');page._lock_caption_editor();QTest.qWait(20)
    yield page
    page._cancel_canvas_inline_edit();page.close_page();page.deleteLater();app.processEvents()

def select(page,at,end=None):
    e=page.subtitle_edit_input;c=e.textCursor();c.setPosition(qt_position(e.toPlainText(),at))
    if end is not None:c.setPosition(qt_position(e.toPlainText(),end),QTextCursor.KeepAnchor)
    e.setTextCursor(c);e.setFocus()

@pytest.mark.parametrize('key,value',[(Qt.Key_1,'!'),(Qt.Key_2,'@'),(Qt.Key_3,'#')])
def test_retired_numbers_are_normal_text_input(page,key,value):
    select(page,3,4);before=page.subtitle_edit_input.toPlainText()
    QApplication.sendEvent(page.subtitle_edit_input,QKeyEvent(QEvent.KeyPress,key,Qt.ShiftModifier,value))
    assert page.subtitle_edit_input.toPlainText()==before[:3]+value+before[4:]
    assert page.project.cues[0].text==before

def test_noop_does_not_add_undo_or_revision(page):
    select(page,1,2);e=page.subtitle_edit_input;revision=page._caption_draft.revision
    assert page._replace_editor_pronoun('她')
    assert page._caption_draft.revision==revision and not e.document().isUndoAvailable()

def test_multi_selection_and_nonpronoun_not_consumed(page):
    select(page,1,6)
    assert not page._caption_editor_key(QKeyEvent(QEvent.KeyPress,Qt.Key_1,Qt.ShiftModifier,'!'),text_focus=True)
    at=page.subtitle_edit_input.toPlainText().index('其他')+1;select(page,at,at+1)
    # The editor now finds the nearest valid independent pronoun; the word
    # part itself remains excluded.
    assert page._caption_pronoun_target() in (1,3,5)

def test_ime_does_not_consume_digit(page):
    select(page,1,2);e=page.subtitle_edit_input
    QApplication.sendEvent(e,QInputMethodEvent('ni',[]))
    before=e.toPlainText()
    assert not page._caption_editor_key(QKeyEvent(QEvent.KeyPress,Qt.Key_1,Qt.ShiftModifier,'!'),text_focus=True)
    assert e._preediting and e.toPlainText()==before

def test_all_occurrences_and_all_three_values(page):
    page._refresh_editor_suggestions()
    rows=[r for r in page._caption_draft.suggestions if r.kind=='pronoun']
    assert [r.start for r in rows]==[1,3,5]
    assert all([o.text for o in r.options]==list('他她它') for r in rows)
    select(page,5,6);assert page.subtitle_edit_card.suggestions.current_row().row.start==5

def test_complete_editor_marks_exceed_old_card_limit():
    from types import SimpleNamespace
    from twobyteasr.subtitle_rules.review_suggestions import review_suggestions
    text='错字，'*12
    class Resolver:
        def resolve(self,text,**kw):
            return SimpleNamespace(hits=[SimpleNamespace(start=i,end=i+2,source='错字',canonical='正字') for i in range(0,len(text),3)])
    assert len(review_suggestions(text,resolver=Resolver(),max_marks=None))==12

def test_many_options_have_accessible_scroll_view():
    from twobyteasr.studio.caption_editor_panel import CaptionSuggestionView
    from twobyteasr.subtitle_rules.review_suggestions import ReviewSuggestion,SuggestionOption
    app=QApplication.instance() or QApplication([]);view=CaptionSuggestionView()
    row=ReviewSuggestion(0,1,'字',tuple(SuggestionOption('完整候选文字'+str(i)) for i in range(18)),'model')
    try:
        view.set_budget(180,70);view.update_rows('字',(row,));view.show();QTest.qWait(30)
        last=view.candidate_button(0,17);view.ensureWidgetVisible(last,0,0);QTest.qWait(20)
        assert len(view._buttons)==18 and view.verticalScrollBar().maximum()>0
        assert view.viewport().rect().intersects(last.rect().translated(last.mapTo(view.viewport(),__import__('PySide6.QtCore',fromlist=['QPoint']).QPoint())))
    finally:view.close();view.deleteLater();app.processEvents()

def test_registry_retires_old_default():
    from twobyteasr.studio.shortcut_registry import platform_defaults,load_values
    assert 'editor_pronoun_he' not in platform_defaults()
    values,*_=load_values({'editor_flip_pronoun':'Shift+P','review_flip_pronoun':'Shift+P'})
    assert not values.get('editor_flip_pronoun') and not values.get('review_flip_pronoun')

def test_reentrant_dialog_request_creates_one(tmp_path,monkeypatch):
    from twobyteasr.app.link_download_controller import LinkDownloadController
    from twobyteasr.app.link_download_dialog import LinkDownloadDialog
    app=QApplication.instance() or QApplication([]);host=QWidget();c=LinkDownloadController(host,storage=tmp_path/'queue.json')
    original=LinkDownloadDialog.__init__;calls=[]
    def nested(self,*args,**kw):
        calls.append(True);c.show('queue');original(self,*args,**kw)
    monkeypatch.setattr(LinkDownloadDialog,'__init__',nested)
    try:
        c.show();assert len(calls)==1 and c.dialog.pages.currentIndex()==1
        c.show();assert len(calls)==1
    finally:c.shutdown();c.dialog.close();host.close();app.processEvents()

def test_duplicate_analysis_cancel_and_retry(tmp_path):
    from twobyteasr.app.link_download_controller import LinkDownloadController
    app=QApplication.instance() or QApplication([]);host=QWidget();gate=threading.Event();calls=[]
    class Engine:
        def analyze(self,url,**kw):calls.append(url);gate.wait(3);raise RuntimeError('test failure')
    c=LinkDownloadController(host,engine=Engine(),storage=tmp_path/'queue.json')
    try:
        for _ in range(5):c.analyze('https://youtu.be/example')
        end=time.monotonic()+2
        while not calls and time.monotonic()<end:QTest.qWait(5)
        assert len(calls)==1
        c.cancel_analysis();c.analyze('https://youtu.be/example')
        while len(calls)<2 and time.monotonic()<end:QTest.qWait(5)
        assert len(calls)==2
    finally:gate.set();c.shutdown();host.close()

def test_repeated_submission_is_one_task_and_terminal_allows_retry(tmp_path):
    from twobyteasr.app.link_download_controller import LinkDownloadController
    from twobyteasr.media.link_catalog import video_catalog
    app=QApplication.instance() or QApplication([]);host=QWidget()
    c=LinkDownloadController(host,storage=tmp_path/'queue.json')
    catalog=video_catalog(dict(id='BaW_jenozKc',title='test',duration=12,
        formats=[dict(format_id='v',vcodec='avc1',acodec='aac',ext='mp4')]))
    try:
        with c.queue._condition:
            tasks=[c.enqueue(catalog,str(tmp_path/'downloads'),dict(mode='video',video_format='v',destination='new',auto_import=False)) for _ in range(4)]
            assert len({t['task_id'] for t in tasks})==1 and len(c.queue.snapshots())==1
            c.queue.tasks[tasks[0]['task_id']]['state']='cancelled'
            retry=c.enqueue(catalog,str(tmp_path/'downloads'),dict(mode='video',video_format='v',destination='new',auto_import=False))
            assert retry['task_id']!=tasks[0]['task_id']
            c.queue.cancel(retry['task_id'])
    finally:c.shutdown();host.close();app.processEvents()

def test_playhead_motion_is_not_a_new_download_intent(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from twobyteasr.app.link_download_controller import LinkDownloadController
    from twobyteasr.media.link_catalog import video_catalog
    app=QApplication.instance() or QApplication([]);host=QWidget()
    c=LinkDownloadController(host,storage=tmp_path/'queue.json')
    page=SimpleNamespace(timeline=SimpleNamespace(playhead_ms=0))
    monkeypatch.setattr(c,'page',lambda:page)
    monkeypatch.setattr(c,'context',lambda:dict(project_id='p',generation=1,revision=1,view=1))
    catalog=video_catalog(dict(id='BaW_jenozKc',title='test',duration=12,
        formats=[dict(format_id='v',vcodec='avc1',acodec='aac',ext='mp4')]))
    try:
        with c.queue._condition:
            tasks=[]
            for position in (0,40,80,120):
                page.timeline.playhead_ms=position
                tasks.append(c.enqueue(catalog,str(tmp_path/'downloads'),dict(mode='video',video_format='v',destination='new',auto_import=False)))
            assert len({t['task_id'] for t in tasks})==1
            assert tasks[0]['target']['position_ms']==0
            for row in c.queue.snapshots():c.queue.cancel(row['task_id'])
    finally:c.shutdown();host.close();app.processEvents()
