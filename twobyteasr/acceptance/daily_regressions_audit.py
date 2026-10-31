"""Opt-in Windows actions and pixel evidence for the 2026-10-31 regressions."""
import json, os, sys, time, traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt, QMimeData
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFileDialog, QPushButton, QVBoxLayout, QWidget
    from .blank_project_audit import _capture
    from ..design.theme_manager import apply_theme
    from ..diagnostics.build_identity import load_build_identity
    from ..app.window_constraints import native_frame
    from ..projects.studio_project import load_project
    from ..subtitle_rules.studio_review import store_review_risks
    from ..subtitle_rules.current_issues import current_issue_view
    from ..recognition.asr_source_evidence import cue_source_hypotheses
    from ..recognition.run_diagnosis import DiagnosisInput, diagnose_run
    from ..app.run_diagnosis_dialog import RunDiagnosisDialog
    from ..design.main_ui_dialogs import SpringDialog
    app=QApplication.instance()
    if window.built_page('studio') is None:
        QTimer.singleShot(100,lambda:start(window,output));return
    page=window.studio_page
    spec=json.loads((output/'input.json').read_text('utf8'))
    report=json.loads((output/'report.json').read_text('utf8'))
    result=dict(passed=False,checks=[],frames=[],home=[],events=[],screenshots=[],pid=os.getpid(),
                executable=sys.executable,identity=load_build_identity().to_dict(),dpr=window.devicePixelRatioF())
    def receipt():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    def check(name,value,detail=None):
        result['checks'].append(dict(name=name,passed=bool(value),detail=detail));receipt()
        if not value:raise AssertionError(name)
    def wait(predicate,seconds=35):
        until=time.monotonic()+seconds
        while not predicate() and time.monotonic()<until:QTest.qWait(25)
        if not predicate():raise AssertionError('wait timeout')
    def describe(widget):
        return None if widget is None else dict(type=type(widget).__name__,name=widget.objectName())
    def frame(name):
        row=dict(name=name,qt_state=int(window.windowState().value),maximized=window.isMaximized(),
                 fullscreen=window.isFullScreen(),native=native_frame(window),
                 qt=[window.x(),window.y(),window.width(),window.height()],
                 margins=[window.contentsMargins().left(),window.contentsMargins().top(),window.contentsMargins().right(),window.contentsMargins().bottom()],active=describe(app.activeWindow()),
                 focus=describe(app.focusWidget()),modal=describe(app.activeModalWidget()),popup=describe(app.activePopupWidget()))
        result['frames'].append(row);receipt();return row
    def shot(name,target=None):
        QTest.qWait(100);_capture(target or window,output/(name+'.png'))
        result['screenshots'].append(name)
        if spec.get('visible') and target is None:
            import ctypes
            from ctypes import wintypes as W
            from PIL import ImageGrab
            rect=W.RECT();ctypes.windll.user32.GetWindowRect(W.HWND(int(window.winId())),__import__('ctypes').byref(rect))
            ImageGrab.grab(bbox=(rect.left,rect.top,rect.right,rect.bottom),all_screens=True).save(output/(name+'-screen.png'))
        receipt()
    class Observer(QObject):
        def eventFilter(self,obj,event):
            if event.type() in {QEvent.WindowActivate,QEvent.WindowDeactivate,QEvent.WindowStateChange,
                                QEvent.KeyPress,QEvent.ShortcutOverride} and len(result['events'])<500:
                if obj is window or isinstance(obj,QWidget) and page._caption_window_owns(obj):
                    result['events'].append(dict(event=event.type().name,target=describe(obj),
                        key=event.key() if hasattr(event,'key') else None))
            return False
    observer=Observer(window);app.installEventFilter(observer)
    heartbeat=[];pulse=QTimer(window);pulse.timeout.connect(lambda:heartbeat.append(time.monotonic()));pulse.start(20)
    def opened(cue_id='50'):
        cue=next(c for c in page.project.cues if c.id==cue_id)
        page.video.set_paused(True);page._seek((cue.start_ms+20)/1000);QTest.qWait(180)
        page.select_cue(cue_id);page.timeline.setFocus();QTest.keyClick(page.timeline,Qt.Key_E)
        wait(lambda:page.subtitle_edit_dock.isVisible())
        return page.subtitle_edit_input

    if spec.get('manual'):
        def ready():
            wait(lambda:page.project is not None and len(page.project.cues)==207)
            apply_theme(spec['theme'],app);window.showMaximized();QTest.qWait(150)
            frame('manual-ready');result['ready_for_manual']=True;receipt()
        def finish():
            pulse.stop();app.removeEventFilter(observer)
            result.update(gui_shutdown=True,passed=(output/'manual-checked.json').is_file());receipt()
        app.aboutToQuit.connect(finish)
        QTimer.singleShot(300,ready)
        return

    def execute():
        try:
            wait(lambda:page.project is not None and len(page.project.cues)==207 and not getattr(page,'_project_load_in_progress',False))
            apply_theme(spec['theme'],app);QTest.qWait(300)
            if spec.get('phase') == 'restart':
                QTest.qWait(500);state=frame('cold-restart-restored')
                check('cold restart restores native maximized state',state['maximized'] and not state['fullscreen'] and state['native']['zoomed'])
                check('cold restart client fills work area',state['native']['client']==state['native']['work'])
                shot('cold-restart-restored')
                editor=opened();QTest.keyClick(editor,Qt.Key_Return)
                check('cold restart editor confirms closed',not page.subtitle_edit_dock.isVisible())
                result['passed']=True
                return
            check('207 original captions loaded',len(page.project.cues)==207)
            wait(lambda:hasattr(page.project,'_qc_result'))
            page._refresh_cue_list_summary()
            gui_view=current_issue_view(page.project)
            result['initial_gui_counts']=gui_view.counts()
            result['initial_human_confirmations']=page.project.studio_state.get('review_confirmations',{})
            for key,count in gui_view.counts().items():
                button=page.cue_filter_buttons[key]
                check('GUI count matches canonical unique captions '+key,button.text().endswith(' '+str(count)),button.text())
            check('weak evidence alone adds no review for cue50',gui_view.level('50')=='confident')
            frame('initial');window.showMaximized();QTest.qWait(400);before=frame('maximized')
            check('maximized is not fullscreen',window.isMaximized() and not window.isFullScreen())
            # A second native top-level surface exercises deactivate/reactivate
            # on this Windows desktop without touching another user's app.
            peer=QWidget();peer.setWindowTitle('2ByteASR owned focus probe');peer.resize(380,160)
            peer.show();peer.activateWindow();QTest.qWait(160);frame('focus-away')
            window.activateWindow();window.raise_();QTest.qWait(160);after=frame('focus-return')
            check('activation preserves native client bounds',before['native']['client']==after['native']['client'])
            shot('window-after-focus-return');peer.close();peer.deleteLater()
            window.showMinimized();QTest.qWait(120);window.showMaximized();QTest.qWait(250)
            frame('minimize-restore');shot('window-after-restore')
            video_geometry=page.video_overlay_host.geometry()
            for method in ('enter','keypad','shift-r','button','x'):
                editor=opened();frame('editor-'+method+'-before')
                if method in {'button','x'}:
                    QTest.mouseClick(page.caption_confirm_button if method=='button' else page.caption_close_button,Qt.LeftButton)
                else:
                    key,mods={'enter':(Qt.Key_Return,Qt.NoModifier),'keypad':(Qt.Key_Enter,Qt.KeypadModifier),
                              'shift-r':(Qt.Key_R,Qt.ShiftModifier)}[method]
                    QTest.keyClick(editor,key,mods)
                check(method+' unchanged closes',not page.subtitle_edit_dock.isVisible() and not page._caption_following)
                page._follow_caption_editor(310000,force=True);QTest.qWait(60)
                check(method+' stays closed',not page.subtitle_edit_dock.isVisible())
                frame('editor-'+method+'-after')
            check('editor does not resize native video host',video_geometry==page.video_overlay_host.geometry())
            for review in (False,True):
                page._set_review_mode(review)
                for key,mods in [(Qt.Key_Return,Qt.NoModifier),(Qt.Key_Enter,Qt.KeypadModifier),(Qt.Key_R,Qt.ShiftModifier)]:
                    editor=opened();before=page.undo_stack.count()
                    QTest.keyClick(page.timeline,key,mods)
                    check(f'follow confirmation from timeline {review}/{key}',not page.subtitle_edit_dock.isVisible()
                          and not page._caption_following and page.undo_stack.count()==before)
            page._set_review_mode(False)
            editor=opened();QTest.mouseClick(editor.viewport(),Qt.LeftButton)
            original=editor.toPlainText();editor.setPlainText(original+' · 验收')
            page._follow_caption_editor(330000)
            check('draft stays bound during playhead changes',page._caption_draft.target.cue_id=='50' and editor.toPlainText().endswith('验收'))
            shot('editor-before-confirm');shot('editor-before-confirm-float',page.subtitle_edit_dock)
            QTest.keyClick(editor,Qt.Key_Return)
            check('changed confirmation persists and closes',not page.subtitle_edit_dock.isVisible()
                  and next(c for c in load_project(page.project_path).cues if c.id=='50').text.endswith('验收'))
            shot('editor-after-confirm');page.undo_stack.undo()
            editor=opened();QTest.mouseClick(editor.viewport(),Qt.LeftButton)
            old=editor.toPlainText();QTest.keyClick(editor,Qt.Key_Return,Qt.ShiftModifier)
            check('shift enter inserts newline',editor.toPlainText()!=old and '\n' in editor.toPlainText())
            QTest.mouseClick(page.caption_cancel_button,Qt.LeftButton)
            editor=opened();QTest.mouseClick(editor.viewport(),Qt.LeftButton)
            app.sendEvent(editor,QInputMethodEvent('ni',[]));QTest.keyClick(editor,Qt.Key_Return)
            check('Qt composition enter retains editor',page.subtitle_edit_dock.isVisible())
            commit=QInputMethodEvent();commit.setCommitString('你');app.sendEvent(editor,commit)
            QTest.mouseClick(page.caption_cancel_button,Qt.LeftButton)
            from ..projects import studio_project as persistence
            editor=opened();editor.setPlainText(original+' · 写盘失败夹具')
            replace,save=persistence.os.replace,page.save
            errors=[]
            def blocked(src,dst):
                if str(dst)==str(page.project_path):raise PermissionError('owned confirmation persistence failure')
                return replace(src,dst)
            try:
                persistence.os.replace=blocked
                page.save=lambda:page.project_controller.save(message_box_fn=lambda *a:errors.append(str(a[-1])))
                QTest.keyClick(editor,Qt.Key_R,Qt.ShiftModifier)
                check('failed disk save keeps exact target and full draft',errors and page.subtitle_edit_dock.isVisible()
                      and page._caption_draft.target.cue_id=='50' and editor.toPlainText().endswith('写盘失败夹具'))
                shot('editor-save-failure');shot('editor-save-failure-float',page.subtitle_edit_dock)
            finally:persistence.os.replace=replace;page.save=save
            QTest.keyClick(editor,Qt.Key_Return)
            check('retry closes after disk success',not page.subtitle_edit_dock.isVisible())
            page.undo_stack.undo();page.project_controller.save()
            # Use the real report in a genuinely nested exec with sibling owner.
            diagnosis=diagnose_run(DiagnosisInput(report=report,ai_ready=True))
            check('diagnosis names precise grouping batch',any(f.rule_id=='grouping_pause_fallback'
                and f.specific_args.get('batch')==2 and f.specific_args.get('total')==22 for f in diagnosis.findings))
            check('successful polish has no generic bad-model advice','ai_bad_output' not in diagnosis.rule_ids and 'ai_partial_fallback' not in diagnosis.rule_ids)
            owner=SpringDialog(window);owner.ENTRY_ANIMATED=owner.EXIT_ANIMATED=False
            owner.setWindowTitle('owned history wrapper');owner.resize(900,740)
            for mode in ('bottom','x','escape'):
                visits=[]
                def nested(mode=mode):
                    dialog=RunDiagnosisDialog(diagnosis,task_name=report['media']['name'],settings={'models':{}},parent=window)
                    dialog.ENTRY_ANIMATED=dialog.EXIT_ANIMATED=False
                    begin=len(heartbeat)
                    def interact():
                        try:
                            before_clip=app.clipboard().mimeData(); saved=QMimeData()
                            if before_clip:
                                for fmt in before_clip.formats():saved.setData(fmt,before_clip.data(fmt))
                            QTest.mouseClick(dialog.copy_button,Qt.LeftButton)
                            check('diagnosis copy '+mode,'排查' in app.clipboard().text())
                            app.clipboard().setMimeData(saved)
                            card=dialog.cards[0]
                            toggle=card.findChild(__import__('PySide6.QtWidgets',fromlist=['QToolButton']).QToolButton,'diagEvidenceToggle')
                            if toggle:QTest.mouseClick(toggle,Qt.LeftButton)
                            get_name=QFileDialog.getSaveFileName
                            try:
                                QFileDialog.getSaveFileName=lambda *a,**k:(str(output/('diagnosis-'+mode+'.txt')),'')
                                QTest.mouseClick(dialog.save_button,Qt.LeftButton)
                            finally:QFileDialog.getSaveFileName=get_name
                            check('diagnosis save '+mode,(output/('diagnosis-'+mode+'.txt')).is_file())
                            shot('diagnosis-'+mode,dialog);frame('diagnosis-'+mode)
                            if mode=='bottom':QTest.mouseClick(dialog.close_button,Qt.LeftButton)
                            elif mode=='x':
                                buttons=[b for b in dialog.findChildren(QPushButton) if b.text()=='×']
                                QTest.mouseClick(buttons[0],Qt.LeftButton)
                            else:QTest.keyClick(dialog,Qt.Key_Escape)
                            visits.append(True)
                        except BaseException:
                            result['error']=traceback.format_exc();dialog.reject()
                    QTimer.singleShot(180,interact)
                    from shiboken6 import isValid
                    QTimer.singleShot(5000,lambda:isValid(dialog) and dialog.isVisible() and dialog.reject())
                    dialog.exec()
                    check('nested diagnosis operable and closes '+mode,visits and not dialog.isVisible() and len(heartbeat)>begin)
                    dialog.deleteLater();owner.accept()
                QTimer.singleShot(50,nested);owner.exec()
            settings_visits=[]
            def settings_close():
                dialog=getattr(window,'_ai_settings_dialog',None)
                if dialog is None or not dialog.isVisible():
                    QTimer.singleShot(50,settings_close);return
                controls=[b for b in dialog.findChildren(QPushButton) if b.text() in {'取消','×'}]
                shot('diagnosis-ai-settings',dialog)
                QTest.mouseClick(controls[0],Qt.LeftButton);settings_visits.append(True)
            QTimer.singleShot(30,lambda:window._open_ai_settings_dialog(on_finished=owner.accept))
            QTimer.singleShot(250,settings_close)
            QTimer.singleShot(5000,owner.reject)
            owner.exec();QTest.qWait(120)
            check('real AI settings closes inside nested history',settings_visits and getattr(window,'_ai_settings_dialog',None) is None)
            owner.deleteLater();QTest.qWait(100)
            check('all diagnosis input guards released',not getattr(app,'_spring_dialog_guards',[]))
            editor=opened();QTest.keyClick(editor,Qt.Key_Return)
            page._toggle_playback();QTest.qWait(220);page._toggle_playback()
            check('Studio plays and edits after diagnosis',not page.subtitle_edit_dock.isVisible())
            # Reload the untouched fixture to prove old projects reclassify.
            from ..projects.studio_project import SubtitleProject
            raw=json.loads((output/'工程1.2byteproj').read_text('utf8'))
            original_project=SubtitleProject.from_dict(raw)
            from ..timeline.studio_caption_timeline import ensure_independent_captions
            ensure_independent_captions(original_project);store_review_risks(original_project)
            view=current_issue_view(original_project)
            result['review_counts']=view.counts();result['review_statistics']=view.statistics()
            for cid,text in [('50','法务部已经紧急启动了'),('21','57'),('23','55')]:
                cue=next(c for c in original_project.cues if c.id==cid)
                rows=cue_source_hypotheses(original_project,cue)
                check('full evidence '+cid,{r['text'] for r in rows}=={text} and view.level(cid)=='confident')
            # The real completion widget uses actual report categories.
            from ..recognition.service import MediaResult,QueueResult
            window._handle_result(QueueResult((MediaResult(report['media']['path'],'success',
                project_path=str(page.project_path),report_json_path=str(output/'report.json'),job_id=report['job_id']),),115.0))
            QTest.qWait(250)
            notification=getattr(window,'_completion_dialog',None)
            if notification is not None and notification.isVisible():
                QTest.mouseClick(notification.card.close_button,Qt.LeftButton)
                wait(lambda:getattr(window,'_completion_dialog',None) is None or not window._completion_dialog.isVisible())
            check('completion notification dismissed before page input',app.activeModalWidget() is None)
            todo=window.result_todo
            calls=[];completion_action=window._completion_action
            window._completion_action=lambda key,*a,**k:calls.append(key)
            todo.set_ai(enabled=True)
            try:
                for target in (todo.ai_card.icon,todo.ai_card.title,todo.ai_card.badge,None,todo.ai_card.action):
                    before=len(calls)
                    if target is todo.ai_card.action:QTest.mouseClick(target,Qt.LeftButton)
                    else:
                        pos=QPoint(todo.ai_card.width()//2,2) if target is None else target.geometry().center()
                        QTest.mouseClick(todo.ai_card,Qt.LeftButton,pos=pos)
                    check('whole AI pill routes once '+str(before),len(calls)==before+1 and calls[-1]=='repolish')
            finally:window._completion_action=completion_action
            for percent in (80,100,120):
                window._ui_zoom.request(percent);QTest.qWait(250)
                shot('completion-'+str(percent))
                check('completion controls fit '+str(percent),all(card.geometry().top()>=0 and card.geometry().bottom()<todo.height()
                    and all(child.isHidden() or card.rect().contains(child.geometry()) for child in (card.icon,card.title,card.badge))
                    for card in todo.cards if card.isVisible()),dict(height=todo.height(),cards=[
                        dict(tone=card.tone,rect=card.geometry().getRect(),children=[(c.objectName(),c.geometry().getRect())
                            for c in (card.icon,card.title,card.badge)]) for card in todo.cards if card.isVisible()]))
                check('removed category button '+str(percent),todo.review_card.action is None)
            window._return_to_settings();QTest.qWait(500)
            for percent in (80,100,120):
                window._ui_zoom.request(percent);window.showNormal();window.resize(1200,780);QTest.qWait(800)
                bar=window.settings_scroll.verticalScrollBar();wait(lambda:bar.maximum()>0,4)
                anchor=None
                for label,fraction in [('top',0),('middle',.5),('bottom',1)]:
                    bar.setValue(round(bar.maximum()*fraction));QTest.qWait(150)
                    shot(f'home-{percent}-{label}')
                    button=window.studio_entry_open;g=button.mapTo(window,QPoint())
                    bottom=window.bottom_bar.mapTo(window,QPoint()).y()
                    check(f'home footer visible {percent}/{label}',button.isVisible() and g.y()>=0
                          and g.y()+button.height()<bottom and g.x()+button.width()<=window.width())
                    check(f'home button stays inside original card {percent}/{label}',
                          window.studio_entry_card.isAncestorOf(button)
                          and window.studio_entry_card.rect().contains(button.geometry())
                          and window.content_layout.count()==2 and not hasattr(window,'home_studio_footer'))
                    if anchor is None:anchor=(g.x(),g.y(),button.width())
                    check(f'home footer fixed while scrolling {percent}/{label}',anchor==(g.x(),g.y(),button.width()),
                          dict(anchor=anchor,current=[g.x(),g.y(),button.width()],
                               card=window.studio_entry_card.geometry().getRect(),bottom=bottom))
                    result['home'].append(dict(percent=percent,position=label,scroll=bar.value(),maximum=bar.maximum(),
                        button=[g.x(),g.y(),button.width(),button.height()],recent=len(window.studio_recent_list.entries)))
            capacities={}
            for percent in (100,80):
                window._ui_zoom.request(percent);window.showMaximized();QTest.qWait(800)
                previous=None;stable=0
                for _ in range(20):
                    QTest.qWait(80)
                    signature=(window.studio_entry_card.height(),len(window.studio_recent_list.entries),window.studio_recent_hero.height())
                    stable=stable+1 if signature==previous else 0;previous=signature
                    if stable>=3:break
                shot('home-maximized-'+str(percent))
                capacities[percent]=len(window.studio_recent_list.entries)
            check('more recent projects fit at 80 percent',capacities[80]>=capacities[100] and capacities[80]>0,capacities)
            frame('final-maximized')
            result['passed']=True
        except BaseException:
            result['error']=traceback.format_exc()
        finally:
            pulse.stop();app.removeEventFilter(observer);receipt()
            app.aboutToQuit.connect(lambda:(result.update(gui_shutdown=True),receipt()))
            page.video.set_paused(True);page.undo_stack.setClean()
            window.result_exit_code=0 if result['passed'] else 1;window.close()
    QTimer.singleShot(300,execute)
