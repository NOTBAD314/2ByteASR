"""Opt-in normal-window reproduction and interaction checks, isolated data only."""
import json, os, time, traceback
from pathlib import Path

def start(window, output):
    if os.environ.get('TWOBYTEASR_EDITOR_REVIEW_INTERACTION_AUDIT') == '1':
        from .editor_review_interaction_audit import start as run_interaction
        return run_interaction(window, output)
    if os.environ.get('TWOBYTEASR_EDITOR_BACKGROUND_AUDIT') == '1':
        from .editor_background_audit import start as run_background
        return run_background(window, output)
    from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtGui import QKeyEvent, QTextCursor
    from PySide6.QtTest import QTest
    app=QApplication.instance();output=Path(output);baseline=os.environ.get('EDITOR_DOWNLOAD_BASELINE')=='1'
    ticket_only = os.environ.get('TWOBYTEASR_TICKET_AUDIT') == '1'
    result=dict(passed=False,checks={},top_level_shows=[],native_creates=[],baseline=baseline)
    def save(): (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    def check(name, value):
        result['checks'][name]=bool(value);save()
        if not value and not baseline: raise AssertionError(name)
    def wait(predicate, seconds=50):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if predicate():return
            app.processEvents();time.sleep(.003)
        raise TimeoutError('editor/download wait')
    class Shows(QObject):
        def eventFilter(self,w,e):
            if e.type()==QEvent.Type.WinIdChange and isinstance(w,QWidget) and w.isWindow():
                result['native_creates'].append(dict(type=type(w).__name__,name=w.objectName(),title=w.windowTitle(),
                    handle=int(w.internalWinId()),visible=w.isVisible(),id=id(w),stack=''.join(traceback.format_stack(limit=10))))
            if e.type()==QEvent.Type.Show and isinstance(w,QWidget) and w.isWindow():
                result['top_level_shows'].append(dict(type=type(w).__name__,name=w.objectName(),title=w.windowTitle(),
                    text=getattr(w,'text',lambda:'')(),id=id(w),stack=''.join(traceback.format_stack(limit=9))))
            return False
    shows=Shows(app)
    def run():
        try:
            save()
            from ..design.theme_manager import apply_theme
            apply_theme(os.environ.get('CAPTION_PRESS_THEME','sand'),app)
            if ticket_only:
                check('language guard row hidden on main window', window._language_guard_row.isHidden())
                check('language repair details hidden', not window._language_repair_limits.isVisible())
            page=window.studio_page;window._switch_page(page)
            page.project_controller.open_project_entry(os.environ['TWOBYTEASR_STARTUP_PROJECT'],single_shot_fn=QTimer.singleShot,skip_dirty_guard=True)
            wait(lambda:page.project is not None and page._readiness.ready)
            wait(lambda:not page._readiness.overlay.isVisible())
            page.video.set_paused(True);result['dpr']=page.devicePixelRatioF()
            if os.environ.get('CAPTION_PRESS_AUDIT')=='1':
                from .caption_press_audit import exercise
                exercise(page,window,output,check,wait)
            if not ticket_only:
                page._open_caption_editor('a','original');page._lock_caption_editor()
                editor=page.subtitle_edit_input;panel=page.subtitle_edit_card;dock=page.subtitle_edit_dock
                QApplication.setActiveWindow(dock);editor.setFocus();QTest.qWait(250)
                from ..subtitle_rules.review_suggestions import ReviewSuggestion,SuggestionOption
                text=editor.toPlainText();pos=text.index('营第')
                draft=page._caption_draft
                draft.suggestions=(ReviewSuggestion(0,1,'她',(SuggestionOption('他'),SuggestionOption('它')),'pronoun'),
                    ReviewSuggestion(pos,pos+2,'营第',tuple(SuggestionOption(v) for v in ('营地','营区','营地附近')),'model'))
                draft.suggestion_text=text;page._refresh_editor_suggestions();QTest.qWait(250)
                dock.fit_to_workspace();QTest.qWait(100)
                dock.grab().save(str(output/'editor-before.png' if baseline else output/'editor-single.png'))
                window.grab().save(str(output/'studio-context.png'))
                check('actions below body',panel.strip.mapTo(panel,QPoint()).y()>panel.face.mapTo(panel,QPoint()).y())
                check('edit tag at top',panel.tag.y()<panel.face.mapTo(panel,QPoint()).y()+10)
                check('candidate above body',panel.bubble.geometry().bottom()<=panel.face.mapTo(panel,QPoint()).y()+3)
                check('arrow tip aligned with current glyph',arrow_aligned(panel))
                if not baseline:
                    exercise_editor(page,window,output,check,wait)
                else:
                    QTest.keyClick(editor,Qt.Key_P,Qt.ShiftModifier)
                    result['old_shift_p_result']=editor.toPlainText()
            page._cancel_canvas_inline_edit()
            from ..app.ui_zoom import set_zoom_percent
            set_zoom_percent(120)
            app.installEventFilter(shows)
            window.link_download_button.click();QTest.qWait(300)
            from ..app.link_download_controller import controller_for
            controller=controller_for(window);dialog=controller.dialog
            dialog.grab().save(str(output/'download.png'))
            first=list(result['top_level_shows']);result['first_download_shows']=first
            check('only complete link dialog shown',len(first)==1 and first[0]['type']=='LinkDownloadDialog')
            check('one controller one dialog reused',controller_for(page) is controller)
            for _ in range(5): page.studio_link_download_button.click()
            QTest.qWait(100)
            check('repeated entry does not create another window',len({s['id'] for s in result['top_level_shows']})==1)
            check('opening window does not start tasks',not controller.queue.snapshots())
            if ticket_only and os.environ.get('TWOBYTEASR_BOOTH_AUDIT') == '1':
                exercise_booth_home(dialog, output, check)
            if not baseline: exercise_download(controller,dialog,check,wait)
            if ticket_only:
                exercise_ticket_ui(dialog,output,check)
            dialog.close();app.removeEventFilter(shows)
            page._cancel_canvas_inline_edit()
            window.close()
            result['passed']=all(result['checks'].values()) or baseline;save()
            QTimer.singleShot(200,app.quit)
        except Exception:
            result['passed']=False;result['error']=traceback.format_exc();save();app.removeEventFilter(shows);app.exit(1)
    QTimer.singleShot(100,run)

def exercise_editor(page,window,output,check,wait):
    from PySide6.QtCore import Qt,QPoint,QEvent
    from PySide6.QtGui import QTextCursor,QKeyEvent,QInputMethodEvent,QFont
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from ..studio.caption_editor import qt_position
    editor=page.subtitle_edit_input;panel=page.subtitle_edit_card;view=panel.suggestions;dock=page.subtitle_edit_dock
    original=page.project.cues[0].text
    def caret(at,selection=False):
        c=editor.textCursor();c.setPosition(qt_position(editor.toPlainText(),at))
        if selection:c.setPosition(qt_position(editor.toPlainText(),at+1),QTextCursor.KeepAnchor)
        editor.setTextCursor(c);editor.setFocus();QTest.qWait(30)
    target=QTextCursor(editor.document());target.setPosition(qt_position(editor.toPlainText(),original.index('它')))
    pos=editor.cursorRect(target).center()+QPoint(max(1,editor.fontMetrics().horizontalAdvance('它')//3),0)
    QTest.mouseClick(editor.viewport(),Qt.LeftButton,Qt.NoModifier,pos);QTest.qWait(40)
    check('glyph click selects corresponding location',view.current_row().row.start==original.index('它'))
    at=original.index('他');caret(at,True)
    for key,value in ((Qt.Key_1,'他'),(Qt.Key_2,'她'),(Qt.Key_3,'它'),(Qt.Key_Exclam,'他'),(Qt.Key_At,'她'),(Qt.Key_NumberSign,'它')):
        before=editor.toPlainText();QTest.keyClick(editor,key,Qt.ShiftModifier)
        check('direct '+str(key),editor.toPlainText()==before[:at]+value+before[at+1:])
        check('live preview '+str(key),page._live_edit_text_overrides.get('a',page.project.cues[0].text)==editor.toPlainText())
    before=editor.toPlainText();revision=page._caption_draft.revision
    QTest.keyClick(editor,Qt.Key_3,Qt.ShiftModifier)
    check('same value no revision',editor.toPlainText()==before and page._caption_draft.revision==revision)
    QApplication.sendEvent(editor,QKeyEvent(QEvent.KeyPress,Qt.Key_1,Qt.ShiftModifier,'!',True))
    check('auto repeat consumed once',editor.toPlainText()==before)
    # Actual clicked glyph switches the active suggestion, every mark remains.
    caret(0,True);panel.pronoun_button.click();QTest.qWait(50)
    row=view.current_row();check('toolbar selects one target',row.row.start==0 and [o.text for o in row.row.options]==list('他她它'))
    mark=view.selected[0];button=view.candidate_button(mark,2)
    QTest.mouseClick(button,Qt.LeftButton);QTest.qWait(60)
    check('candidate click direct one char',editor.toPlainText()[0]=='它' and editor.toPlainText()[at]=='它')
    editor.undo();QTest.qWait(80);check('draft undo restores clicked target',editor.toPlainText()[0]=='她')
    editor.redo();QTest.qWait(80);check('draft redo reapplies clicked target',editor.toPlainText()[0]=='它')
    page._cancel_canvas_inline_edit();check('cancel restores full cue',page.project.cues[0].text==original)
    page._open_caption_editor('a','original');page._lock_caption_editor();caret(0,True)
    QTest.keyClick(editor,Qt.Key_1,Qt.ShiftModifier);changed=editor.toPlainText();index=page.undo_stack.index()
    page._caption_trigger_commit('audit');check('confirm keeps exact draft',page.project.cues[0].text==changed and page.undo_stack.index()==index+1)
    page.undo_stack.undo();check('project undo restores',page.project.cues[0].text==original)
    page.undo_stack.redo();check('project redo restores',page.project.cues[0].text==changed)
    page.undo_stack.undo()
    page._open_caption_editor('b','original');page._lock_caption_editor();caret(0,True)
    QTest.keyClick(editor,Qt.Key_3,Qt.ShiftModifier)
    check('switch cue does not reuse old target',editor.toPlainText().startswith('它') and page.project.cues[0].text==original)
    for width,height,size in ((1200,850,22),(980,720,30),(1450,900,18)):
        window.resize(width,height);font=QFont(editor.font());font.setPixelSize(size);editor.setFont(font)
        QTest.qWait(120);dock.fit_to_workspace();QTest.qWait(80)
        rects=[(w,w.mapTo(panel,QPoint()),w.size()) for w in (panel.tag,panel.bubble,panel.face,panel.strip)]
        check('complete geometry '+str(size),all(panel.rect().contains(__import__('PySide6.QtCore',fromlist=['QRect']).QRect(p,s)) for w,p,s in rects))
        check('fixed order '+str(size),panel.bubble.geometry().bottom()<panel.face.mapTo(panel,QPoint()).y() and panel.strip.y()>=panel.face.geometry().bottom())
        check('arrow aligned at font '+str(size),arrow_aligned(panel))
    dock.grab().save(str(output/'editor-multiline.png'))
    page._cancel_canvas_inline_edit();page._open_caption_editor('a','translation');page._lock_caption_editor();caret(0,True)
    QTest.keyClick(editor,Qt.Key_3,Qt.ShiftModifier)
    check('translation draft isolated',editor.toPlainText().startswith('它和他') and page.project.cues[0].text==original)
    page._cancel_canvas_inline_edit();page._open_caption_editor('a','original');page._lock_caption_editor()
    editor.setPlainText('正常文字');caret(2)
    for key,symbol in ((Qt.Key_Exclam,'!'),(Qt.Key_At,'@'),(Qt.Key_NumberSign,'#')):
        QApplication.sendEvent(editor,QKeyEvent(QEvent.KeyPress,key,Qt.ShiftModifier,symbol))
    check('no target normal symbols',editor.toPlainText()=='正常!@#文字')
    editor.setPlainText('她说');caret(0)
    QApplication.sendEvent(editor,QInputMethodEvent('ni',[]))
    event=QKeyEvent(QEvent.KeyPress,Qt.Key_1,Qt.ShiftModifier,'!')
    check('IME key remains with input method',not page._caption_editor_key(event,text_focus=True) and editor.toPlainText()=='她说')
    commit=QInputMethodEvent();commit.setCommitString('你');QApplication.sendEvent(editor,commit)
    check('IME commit survives',editor.toPlainText().startswith('你'))
    page._cancel_canvas_inline_edit()

    # Distinct candidates at one span and separate locations, no fictional text.
    page._open_caption_editor('a','original');page._lock_caption_editor();text=editor.toPlainText();start=text.index('营第')
    from ..subtitle_rules.review_suggestions import ReviewSuggestion,SuggestionOption
    rows=(ReviewSuggestion(start,start+2,'营第',tuple(SuggestionOption(v) for v in ('营地','营区','营地附近')),'glossary'),)
    draft=page._caption_draft;draft.suggestion_text=text;draft.suggestions=rows
    page._refresh_editor_suggestions();caret(start,False);QTest.qWait(80)
    check('all three ordinary candidates',view.current_row().row.start==start and len(view.current_row().row.options)==3)
    check('all pronoun locations remain marked',len([r for r in draft.suggestions if r.kind=='pronoun'])==3)
    # Bound the complete candidate list, including options after the first row.
    longrow=ReviewSuggestion(start,start+2,'营第',tuple(SuggestionOption('完整候选文字'+str(n)) for n in range(120)),'glossary')
    view.update_rows(text,(longrow,));view.set_budget(190,75);QTest.qWait(30)
    last=view.candidate_button(0,119);view.ensureWidgetVisible(last,0,0);QTest.qWait(30)
    check('overflow last option reachable',len(view._buttons)==120 and view.verticalScrollBar().maximum()>0)
    dock.grab().save(str(output/'editor-candidates-scroll.png'))
    view.reset();page._refresh_editor_suggestions();caret(start);QTest.qWait(50)
    # Click the last of a multi-option row, then resolve relocated marks.
    mark=view.selected[0];button=view.candidate_button(mark,2);QTest.mouseClick(button,Qt.LeftButton);QTest.qWait(100)
    check('last ordinary option clickable',editor.toPlainText()==text.replace('营第','营地附近'))
    check('all remaining marks at current text',all(editor.toPlainText()[r.start:r.end]==r.original for r in page._caption_draft.suggestions))
    page._cancel_canvas_inline_edit()

def arrow_aligned(panel):
    """The painted tail uses a rounded-corner clamp, not just _tail_x."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QTextCursor
    from ..studio.caption_editor import qt_position
    item=panel.suggestions.current_row()
    if item is None:return False
    text=panel.editor.toPlainText();cursor=QTextCursor(panel.editor.document())
    cursor.setPosition(qt_position(text,item.row.start));a=panel.editor.cursorRect(cursor)
    cursor.setPosition(qt_position(text,item.row.end));b=panel.editor.cursorRect(cursor)
    centre=(a.left()+b.left())/2 if a.top()==b.top() and item.row.end>item.row.start else a.left()+8
    expected=panel.editor.viewport().mapTo(panel,QPoint(int(centre),a.top())).x()
    painted=panel.bubble.x()+max(18.0,min(panel.bubble.width()-18.0,panel.bubble._tail_x))
    return panel.bubble._tail_down and abs(painted-expected)<=1

def exercise_download(controller,dialog,check,wait):
    import threading
    from PySide6.QtCore import QTimer,Qt
    from PySide6.QtTest import QTest
    from ..media.link_tools import DownloadCancelled
    calls=[];gate=threading.Event()
    class Engine:
        tools=None
        def analyze(self,url,**kw):
            calls.append(url)
            while not gate.wait(.01):
                if kw['cancel']():raise DownloadCancelled()
            raise RuntimeError('受控网络失败：可重试')
    controller.engine=Engine()
    dialog.url.setText('https://www.youtube.com/watch?v=fixture')
    pulses=[];timer=QTimer(dialog);timer.setInterval(15);timer.timeout.connect(lambda:pulses.append(True));timer.start()
    for _ in range(5):dialog.parse_button.click()
    wait(lambda:len(calls)==1);wait(lambda:len(pulses)>=3,5)
    check('slow parse one job responsive',len(calls)==1 and len(pulses)>=3 and dialog.cancel_parse.isEnabled())
    for _ in range(5):controller.analyze(dialog.url.text(),owner='dialog',**dialog._network())
    check('duplicate requests coalesced',len(calls)==1)
    QTest.mouseClick(dialog.cancel_parse,Qt.LeftButton);QTest.qWait(80)
    check('cancel restores parse',dialog.parse_button.isEnabled() and not dialog.cancel_parse.isEnabled())
    gate.set();QTest.qWait(60);dialog.parse_button.click()
    wait(lambda:len(calls)==2 and dialog.parse_button.isEnabled())
    check('failure in same structured window','受控网络失败' in dialog.message.text() and dialog.isVisible())
    dialog.parse_button.click();wait(lambda:len(calls)==3 and dialog.parse_button.isEnabled())
    check('retry exactly one fresh job',len(calls)==3)
    dialog.close();controller.show();QTest.qWait(50)
    check('reopen keeps same complete dialog',controller.dialog is dialog and dialog.isVisible() and dialog.parse_button.isEnabled())
    check('no queue task until user enqueues',not controller.queue.snapshots())
    from ..media.link_catalog import video_catalog
    downloads=[]
    class Downloader:
        def download(self,task,**kw):
            downloads.append(task['task_id'])
            while not kw['cancel']():time.sleep(.01)
            raise DownloadCancelled()
    controller.queue.engine=Downloader()
    catalog=video_catalog(dict(id='BaW_jenozKc',title='受控下载条目',duration=12,
        formats=[dict(format_id='v',vcodec='avc1',acodec='aac',height=360,ext='mp4')]))
    dialog.set_catalog(catalog);dialog.mode.setCurrentIndex(dialog.mode.findData('video'))
    dialog.auto_import.setChecked(False)
    timeline=controller.page().timeline;position=timeline.playhead_ms
    with controller.queue._condition:
        for offset in (0,40,80,120):
            timeline.set_playhead(position+offset);dialog.add_button.click()
        check('four download clicks one queue task',len(controller.queue.snapshots())==1)
    timeline.set_playhead(position)
    wait(lambda:len(downloads)==1)
    task=controller.queue.snapshots()[0];controller.task_action('cancel',task['task_id'])
    wait(lambda:controller.queue.snapshots()[0]['state']=='cancelled')
    dialog.add_button.click();wait(lambda:len(downloads)==2)
    check('cancelled download allows new submission',len(controller.queue.snapshots())==2)
    controller.task_action('cancel',downloads[-1]);wait(lambda:controller.queue.snapshots()[-1]['state']=='cancelled')
    timer.stop()


def exercise_booth_home(dialog, output, check):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QScrollArea
    import time

    previous_history = dialog.preferences.get("history", [])
    previous_mode = dialog.mode.currentIndex()
    previous_width = dialog.width()
    dialog.preferences["history"] = [
        dict(url="https://www.youtube.com/watch?v=fixture1", title="First subtitle download", duration=88, saved=time.time()),
        dict(url="https://www.bilibili.com/video/BV2", title="Second parse", duration=5432, saved=time.time() - 86400),
        dict(url="https://www.youtube.com/watch?v=fixture3", title="Old history item"),
    ]
    dialog._refresh_recent()
    from ..runtime_paths import get_runtime_paths
    dialog.helper_strip.refresh(get_runtime_paths().install_root, ['Chrome', 'Edge', 'Brave', 'Firefox'])
    dialog.resize(dialog.minimumWidth(), dialog.height())
    QTest.qWait(200)
    check("mascot peeks across the counter edge", dialog.booth_bunny.isVisible() and
          dialog.booth_bunny.y() < dialog.counter.y() <= dialog.booth_bunny.geometry().bottom())
    check("four visible ticket choices", len(dialog.kind_tickets) == 4 and all(button.isVisible() for button in dialog.kind_tickets))
    QTest.mouseClick(dialog.kind_tickets[3], Qt.MouseButton.LeftButton)
    QTest.mouseClick(dialog.kind_tickets[3], Qt.MouseButton.LeftButton)
    check("selected ticket stays selected on a second click", dialog.kind_tickets[3].isChecked() and
          dialog.mode.currentData() == "subtitles")
    check("three recent stubs preserve old records", all(stub.isVisible() for stub in dialog.recent_tickets) and
          "1:30:32" in dialog.recent_tickets[1].note.text() and dialog.recent_tickets[2].note.text() == "YouTube")
    check("booth fits the minimum window width", all(
          area.horizontalScrollBar().maximum() == 0 for area in dialog.findChildren(QScrollArea) if area.isVisible()))
    check("booth screenshot saved", dialog.grab().save(str(output / "download-booth.png")))
    scroll = dialog.pages.currentWidget()
    scroll.ensureWidgetVisible(dialog.recent_tickets[-1])
    QTest.qWait(120)
    check("all three ticket stubs reached by scrolling", all(
          scroll.viewport().rect().contains(stub.mapTo(scroll.viewport(), stub.rect().center()))
          for stub in dialog.recent_tickets))
    check("recent ticket screenshot saved", dialog.grab().save(str(output / "download-recent-tickets.png")))
    scroll.verticalScrollBar().setValue(0)
    dialog.preferences["history"] = previous_history
    dialog.mode.setCurrentIndex(previous_mode)
    dialog._refresh_recent()
    dialog._refresh_helper()
    dialog.resize(previous_width, dialog.height())


def exercise_ticket_ui(dialog, output, check):
    from unittest.mock import patch

    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QFontInfo
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QScrollArea
    from ..app import browser_helper_dialog
    from ..app.browser_helper_dialog import STEPS, StepStub
    from ..design.typography import CONTENT_FONT_FAMILIES

    dialog.resize(dialog.minimumWidth(), dialog.height())
    QTest.qWait(150)
    check('parsed ticket remains visible at minimum width', dialog.result_card.isVisible())
    check('parsed ticket has no horizontal overflow', all(
        area.horizontalScrollBar().maximum() == 0
        for area in dialog.findChildren(QScrollArea)
        if area.isVisible()
    ))
    check('parsed ticket screenshot saved', dialog.grab().save(str(output/'download-parsed.png')))
    check('packaged interface uses bundled Source Han Sans', QApplication.font().families()[0] == CONTENT_FONT_FAMILIES[0])
    check('URL input keeps the bundled content font', (
        dialog.url.font().families()[0] == CONTENT_FONT_FAMILIES[0]
        and QFontInfo(dialog.url.font()).family() == CONTENT_FONT_FAMILIES[0]
    ))

    wizard_results = {}

    def inspect_wizard():
        wizard = QApplication.activeModalWidget()
        if not isinstance(wizard, QDialog):
            wizard = dialog.findChild(QDialog, 'browserHelperDialog')
        if wizard is None:
            return
        try:
            wizard_results['opens at the first unfinished step'] = STEPS[wizard.step] == 'link'
            wizard_results['six numbered installation steps'] = len(wizard.findChildren(StepStub)) == 6
            QTest.mouseClick(wizard.stubs[0], Qt.MouseButton.LeftButton)
            wizard_results['four browser tiles'] = len(wizard.tiles) == 4 and wizard.tiles['Firefox'].isVisible()
            firefox = wizard.tiles['Firefox']
            QTest.mouseClick(firefox, Qt.MouseButton.LeftButton)
            QTest.mouseClick(wizard.stubs[2], Qt.MouseButton.LeftButton)
            wizard_results['browser selection changes installation steps'] = (
                wizard.browser == 'Firefox' and wizard.step == 2 and 'Firefox' in wizard.step_title.text()
            )
            wizard_results['installation screenshot saved'] = wizard.grab().save(str(output/'browser-helper-wizard.png'))
            tip = wizard.tip_text.text()
            QTest.mouseClick(wizard.stuck, Qt.MouseButton.LeftButton)
            wizard_results['stuck button changes the tip'] = wizard.tip_text.text() != tip
            wizard.show_tab('manage')
            QTest.qWait(150)
            rows = [wizard.rows_host.itemAt(i).widget() for i in range(wizard.rows_host.count())]
            wizard_results['my browsers page screenshot saved'] = (
                wizard.pages.currentIndex() == 1 and len(rows) == 4
                and all(row.isVisible() and row.height() > 0 for row in rows)
                and wizard.grab().save(str(output/'browser-helper-browsers.png'))
            )
        finally:
            wizard.close()

    with patch.object(browser_helper_dialog, 'detect', return_value={'Chrome': 'fixture', 'Firefox': 'fixture'}), \
            patch.object(browser_helper_dialog, 'registration', return_value=False), \
            patch.object(browser_helper_dialog, 'helper_in_browser', return_value=None), \
            patch.object(browser_helper_dialog, 'last_contact', return_value={}):
        QTimer.singleShot(180, inspect_wizard)
        dialog._show_helper()
    check('installation window opened from download', bool(wizard_results))
    for name, passed in wizard_results.items():
        check(name, passed)
