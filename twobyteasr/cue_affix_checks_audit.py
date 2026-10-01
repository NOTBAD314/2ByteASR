"""Opt-in normal GUI acceptance for clock editing and export naming."""
import json, os, time, traceback, sys
from pathlib import Path


def start(window,out):
    from PySide6.QtCore import Qt,QTimer,QPoint,QSettings
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QPushButton
    from .build_identity import load_build_identity
    from .studio_project import load_project
    out=Path(out);page=window.studio_page
    report={'passed':False,'checks':{},'identity':load_build_identity().to_dict(),
        'pid':os.getpid(),'executable':sys.executable,'samples':[],'provider_calls':0}
    def pump(seconds=.1):
        end=time.monotonic()+seconds
        while time.monotonic()<end:QApplication.processEvents();time.sleep(.003)
    def wait(predicate,seconds=35):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if predicate():return
            pump(.03)
        raise TimeoutError('GUI predicate timed out')
    def check(label,value):
        report['checks'][label]=bool(value)
        (out/'progress.json').write_text(json.dumps(report,ensure_ascii=False,default=str),'utf8')
        if not value:raise AssertionError(label)
    def key(code,mod=Qt.NoModifier):
        QTest.keyClick(window.windowHandle(),code,mod);pump(.08)
    def activate():
        QApplication.setActiveWindow(window);window.activateWindow();page.timeline.setFocus();pump(.05)
    def click(widget):
        QTest.mouseClick(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,widget.mapTo(window,widget.rect().center()));pump(.1)
    def shot(name):
        window.grab().save(str(out/(name+'.png')))
        if page.video.controller:page.video.controller.screenshot_to_file(out/(name+'-native.png'),mode='window')
    def seek(ms):
        page._seek(ms/1000);wait(lambda:not page.video._playback_clock.exact_seek_pending);pump(.18)
        check('seek '+str(ms),abs(page.timeline.playhead_ms-ms)<100)
    def sample():
        t=page.timeline
        report['samples'].append(dict(playhead=t.playhead_ms,start=t.visible_start_ms,selected=page.selected_cue_id,
            target=page.session.playhead_target_id,editor=getattr(page,'_review_edit_lock',None),
            focus=type(QApplication.focusWidget()).__name__))
    def play_to(ms):
        page.video.set_paused(False);end=time.monotonic()+15
        while page.timeline.playhead_ms<ms and time.monotonic()<end:pump(.04);sample()
        page.video.set_paused(True);pump(.1)
        check('natural play reaches '+str(ms),page.timeline.playhead_ms>=ms)
    def select_a():
        row=page.cue_model.row_for_cue_id('a');idx=page.cue_model.index(row,3)
        page.cue_table.scrollTo(idx);pump(.08)
        QTest.mouseClick(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,
            page.cue_table.viewport().mapTo(window,page.cue_table.visualRect(idx).center()));pump(.08)
        check('manual A selected',page.selected_cue_id=='a')
    def select_timeline_a():
        page.timeline.set_visible_window(0,24000)
        rect=page.timeline._track_layout()[0]['S01']
        pt=page.timeline.mapTo(window,QPoint(round(page.timeline._time_to_x(11000)),round(rect.center().y())))
        QTest.mouseClick(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,pt);pump(.12)
        check('timeline A explicit',page.selected_cue_id=='a' and page._manual_selection_hold)
    def edit_target(expected,label):
        activate();before=page.timeline.playhead_ms;key(Qt.Key_E)
        check(label,page._canvas_editor is page.subtitle_edit_input and page._review_edit_lock['cue_id']==expected)
        check(label+' no seek',abs(page.timeline.playhead_ms-before)<100)
        key(Qt.Key_Escape);activate()
    def type_text(widget,value):
        edit=widget.lineEdit() if hasattr(widget,'lineEdit') else widget
        click(edit);key(Qt.Key_A,Qt.ControlModifier)
        if value:
            event=QInputMethodEvent();event.setCommitString(value);QApplication.sendEvent(edit,event);pump(.05)
        else:
            key(Qt.Key_Backspace)
        key(Qt.Key_Return)
    def reopen():
        page.undo_stack.setClean();page.show_project_hub(skip_dirty_guard=True);pump(.15)
        ready=[];window.open_studio_project(out/'fixture.2byteproj',on_ready=lambda *_:ready.append(True))
        wait(lambda:ready and page._readiness.ready);page.video.set_paused(True);page._set_volume(0);activate()
    def open_export():
        click(page.studio_render_button);wait(lambda:page.export_workspace is not None)
        ui=page.export_workspace;wait(lambda:hasattr(ui,'filename_prefix'));pump(.15)
        return ui
    def export_files(ui,label):
        type_text(ui.directory,str(out/'exports'))
        type_text(ui.subtitle_custom_directory,str(out/'exports'))
        click(ui.subtitle_destination_modes['custom']);click(ui.subtitle_speaker_modes['both'])
        click(ui.subtitle_export_button)
        artifacts=ui._last_subtitle_artifacts
        check(label+' subtitle only',len(artifacts)==3 and not ui._running and ui._worker is None)
        check(label+' distinct files',len({str(a.path) for a in artifacts})==3 and all(a.path.is_file() for a in artifacts))
        check(label+' naming',all(a.path.stem.startswith(ui.export_target().base_name) for a in artifacts))
        report[label+' subtitles']=[str(a.path) for a in artifacts]
        # Bound production render to two seconds using the ordinary range controls.
        from .project_range import set_range
        set_range(page.project,10000,12000)
        ui._update_range()
        ui.export_range.setCurrentIndex(ui.export_range.findData('in_out'))
        ui.resolution.setCurrentIndex(ui.resolution.findData((640,360)))
        expected=ui.export_target().full_path
        click(ui.export_button)
        wait(lambda:not ui._running and (ui.pages.currentWidget() is ui.success_page or ui._last_failure),120)
        report[label+' video error']=ui._last_failure
        check(label+' video finished',not ui._last_failure and expected.is_file())
        check(label+' preview filename equals disk',expected.name==ui.complete_name_preview.text())
        report[label+' video']=str(expected)
    def run():
        try:
            wait(lambda:page.project is not None and page._readiness.ready)
            page.video.set_paused(True);page._set_volume(0);activate()
            check('removed checks old saved page defaults to style',page.context_drawer.currentIndex()==1
                and [page.context_drawer.tabToolTip(i) for i in range(page.context_drawer.count())]==['AI设计','样式','视频','剪辑助手','素材'])
            check('removed checks no widgets or repair callback',not hasattr(page,'safe_fix_button') and not hasattr(page,'_apply_safe_fixes'))
            restart=json.loads((out/'config.json').read_text('utf8'))['restart']
            if not restart:
                page.follow_playhead_toggle.setChecked(False);seek(10500)
                for point,target in ((10500,'a'),(12400,'a'),(15100,'b'),(17300,'b')):
                    if point!=10500:play_to(point)
                    check('automatic target '+str(point),page.selected_cue_id==target)
                    edit_target(target,'continuous E '+str(point))
                seek(11000);select_a();play_to(15100);edit_target('b','manual A cannot block B')
                seek(11000);activate();key(Qt.Key_Escape);pump(.4)
                check('Escape clears effective selection',page.selected_cue_ids()==[] and page.session.playhead_target_id=='')
                play_to(12400);check('cancel survives same cue and gap',page.selected_cue_ids()==[])
                edit_target('a','explicit E restores gap target')
                page.timeline.set_visible_window(0,24000)
                rect=page.timeline._track_layout()[0]['S01']
                pt=page.timeline.mapTo(window,QPoint(round(page.timeline._time_to_x(13000)),round(rect.center().y())))
                QTest.mouseClick(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,pt);pump(.5)
                check('blank click clears actual selection',page.selected_cue_ids()==[] and page.session.playhead_target_id=='')
                play_to(15100);check('next cue restores selection',page.selected_cue_id=='b')
                seek(0);activate();key(Qt.Key_E)
                check('start has no previous cue',page._canvas_editor is None and page.selected_cue_id=='')
                seek(12400);edit_target('a','backwards gap re-resolves A')
                seek(11000);activate();key(Qt.Key_E);key(Qt.Key_Q);key(Qt.Key_W);key(Qt.Key_E)
                text=page.subtitle_edit_input.toPlainText()
                page.timeline.set_visible_window(10000,2000);play_to(15100)
                check('editor fixed while clock becomes B',page._review_edit_lock['cue_id']=='a' and page.session.playhead_target_id=='b'
                    and page.subtitle_edit_input.toPlainText()==text and QApplication.focusWidget() is page.subtitle_edit_input)
                check('editor survives actual pagination',page.timeline.visible_start_ms>=14000)
                page.cue_model.set_query('下一条');pump(.1)
                check('filtered refresh preserves editing identity and text',page._review_edit_lock['cue_id']=='a' and page.subtitle_edit_input.toPlainText()==text)
                shot('editor-paged-filtered');key(Qt.Key_Return)
                check('commit writes A only',page.project.cues[0].text==text and page.project.cues[1].text=='下一条 30')
                page.cue_model.set_query('');activate();key(Qt.Key_Z,Qt.ControlModifier)
                check('undo original A',page.project.cues[0].text=='原文 20 20')
                key(Qt.Key_Y,Qt.ControlModifier);check('redo original A',page.project.cues[0].text==text)
                key(Qt.Key_Z,Qt.ControlModifier)
                # Q/W still use explicit selection even outside its interval.
                seek(9000);select_timeline_a();key(Qt.Key_Q)
                check('Q manual boundary retained',page.project.cues[0].start_ms==9000)
                key(Qt.Key_Z,Qt.ControlModifier);seek(12300);select_timeline_a();key(Qt.Key_W)
                check('W manual boundary retained',page.project.cues[0].end_ms==12300)
                key(Qt.Key_Z,Qt.ControlModifier)
                reopen();check('reopen resets clock target',page.session.playhead_target_id=='')
                settings=QSettings('2ByteASR','2ByteASR')
                settings.setValue('render/preferences_v1',json.dumps({'prefix':'[NOTBAD]','suffix':''}));settings.sync()
            ui=open_export()
            check('editable affix combos',ui.filename_prefix.isEditable() and ui.filename_suffix.isEditable())
            if restart:
                check('restart explicit empty values',ui.filename_prefix.currentText()==ui.filename_suffix.currentText()=='')
                check('restart independent histories',ui.filename_prefix.history()==['【自定义】 ','[NOTBAD]']
                    and ui.filename_suffix.history()==['_精剪','_完整版'])
                type_text(ui.filename_prefix,'[NOTBAD]');type_text(ui.filename_suffix,'_完整版')
                export_files(ui,'restart')
            else:
                check('migrates existing NOTBAD',ui.filename_prefix.currentText()=='[NOTBAD]' and ui.filename_prefix.history()==['[NOTBAD]'])
                for value in ('_精剪','_完整版','_精剪'):type_text(ui.filename_suffix,value)
                type_text(ui.filename_prefix,'【自定义】 ')
                check('MRU no duplicate or partial',ui.filename_prefix.history()==['【自定义】 ','[NOTBAD]']
                    and ui.filename_suffix.history()==['_精剪','_完整版'])
                # Exercise a real popup item selection, then restore the custom MRU.
                click(ui.filename_prefix);ui.filename_prefix.showPopup();pump(.1)
                view=ui.filename_prefix.view();idx=ui.filename_prefix.model().index(ui.filename_prefix.findText('[NOTBAD]'),0)
                QTest.mouseClick(view.viewport(),Qt.LeftButton,Qt.NoModifier,view.visualRect(idx).center());pump(.2)
                check('popup selects exact previous prefix',ui.filename_prefix.currentText()=='[NOTBAD]')
                type_text(ui.filename_prefix,'【自定义】 ')
                shot('affix-dropdown');export_files(ui,'first')
                ui._return_to_settings();pump(.15)
                type_text(ui.filename_prefix,'');type_text(ui.filename_suffix,'')
                ui._back();wait(lambda:page.export_workspace is None)
                ui=open_export();check('back and reopen preserves explicit empty',ui.filename_prefix.currentText()==ui.filename_suffix.currentText()=='')
                shot('empty-affixes')
            ui._back();wait(lambda:page.export_workspace is None)
            report['passed']=True
        except BaseException:
            report['error']=traceback.format_exc();shot('failure')
        finally:
            report['finished']=time.time();(out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),'utf8')
            page.video.set_paused(True);page.undo_stack.setClean();window.close()
    QTimer.singleShot(1800,run)
