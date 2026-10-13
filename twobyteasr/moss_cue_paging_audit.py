"""Opt-in bounded GUI regression; separate model, keyboard and playback evidence."""
import json,os,time,traceback
from pathlib import Path


def start(window,out):
    from PySide6.QtCore import Qt,QTimer,QPoint
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QComboBox,QCheckBox,QPushButton,QMessageBox,QDialog,QStyle,QStyleOptionSlider
    from .build_identity import load_build_identity
    from .studio_project import save_project,load_project
    from .studio_subtitle_export import export_subtitle_artifacts,SubtitleExportOptions
    from .studio_runtime_state import state_for
    out=Path(out);page=window.studio_page
    report={'passed':False,'checks':{},'identity':load_build_identity().to_dict(),'pid':os.getpid(),
        'samples':[],'events':[],'provider_calls':0}
    def pump(seconds=.1):
        end=time.monotonic()+seconds
        while time.monotonic()<end:QApplication.processEvents();time.sleep(.003)
    def wait(predicate,seconds=40):
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
        QTest.keyClick(window.windowHandle(),code,mod);pump(.1)
    def activate():
        QApplication.setActiveWindow(window);window.activateWindow();page.timeline.setFocus();pump(.05)
    def shot(name):
        window.grab().save(str(out/(name+'.png')))
        if page.video.controller:page.video.controller.screenshot_to_file(out/(name+'-native.png'),mode='window')
    def opened(name):
        page.undo_stack.setClean();page.show_project_hub(skip_dirty_guard=True);pump(.1)
        ready=[];window.open_studio_project(out/(name+'.2byteproj'),on_ready=lambda *_:ready.append(True))
        wait(lambda:ready and page.project is not None and page._readiness.ready)
        page.video.set_paused(True);page._set_volume(0);page.follow_playhead_toggle.setChecked(False)
        page.timeline.set_visible_window(0,34000);activate()
    def seek(ms):
        page._seek(ms/1000);wait(lambda:not page.video._playback_clock.exact_seek_pending);pump(.15)
    def select_list():
        row=page.cue_model.row_for_cue_id('target');index=page.cue_model.index(row,3)
        page.cue_table.scrollTo(index);pump(.1)
        point=page.cue_table.viewport().mapTo(window,page.cue_table.visualRect(index).center())
        QTest.mouseClick(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,point);pump(.15)
        check('list selected stable cue',page.selected_cue_id=='target' and page._manual_selection_hold)
    def select_timeline():
        page.timeline.set_visible_window(0,34000)
        rect=page.timeline._track_layout()[0]['S01']
        point=page.timeline.mapTo(window,QPoint(round(page.timeline._time_to_x(11000)),round(rect.center().y())))
        QTest.mouseClick(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,point);pump(.12)
        check('timeline selected stable cue',page.selected_cue_id=='target' and page._manual_selection_hold)
    def sample():
        t=page.timeline
        report['samples'].append(dict(wall=time.monotonic(),playhead=t.playhead_ms,start=t.visible_start_ms,
            duration=t.visible_duration_ms,x=t._time_to_x(t.playhead_ms),left=t.TRACK_HEADER_WIDTH,
            right=t._content_right(),scroll=t.horizontal_scrollbar.value(),speed=page.video._playback_rate,
            selected=page.selected_cue_id,edit_lock=getattr(page,'_review_edit_lock',None),
            focus=type(QApplication.focusWidget()).__name__))
    def playback_until(target,timeout=25):
        end=time.monotonic()+timeout
        while page.timeline.playhead_ms<target and time.monotonic()<end:pump(.04);sample()
        check('playback reaches '+str(target),page.timeline.playhead_ms>=target)
    def recognize():
        opened('speech');window._apply_workshop_backend('speaker','single')
        for _ in range(2):window._refresh_workshop_after_asr_change()
        check('explicit disabled stays disabled',window.legacy.RUNTIME_SETTINGS['models']['speaker_source']=='single')
        window._apply_workshop_backend('primary','moss');window._apply_workshop_backend('firered','off')
        window._apply_workshop_backend('qwen','off');window.speaker_tracks.setChecked(True)
        received=[];errors=[];original=window._handle_event
        def observe(event):
            if event.kind in {'run_event','log','speaker_identity_stages','cache_hit','speaker_source'}:
                report['events'].append({'kind':event.kind,'payload':event.payload})
            original(event)
        window._handle_event=observe
        guard=QTimer(window)
        def dialogs():
            modal=QApplication.activeModalWidget()
            if isinstance(modal,QMessageBox):errors.append(modal.text()+' '+modal.informativeText());modal.reject()
        guard.timeout.connect(dialogs);guard.start(200)
        page._open_recognition_sheet();pump(.2)
        local=window.findChild(QCheckBox,'localSpeakerRecognition');sheet=local.parentWidget();local.setChecked(True)
        selector=next(c for c in sheet.findChildren(QComboBox) if c.findData('moss')>=0)
        check('sheet inherits disabled',selector.currentData()=='single')
        selector.setCurrentIndex(selector.findData('moss'))
        start_button=next(b for b in sheet.findChildren(QPushButton) if b.text()=='识别并替换当前字幕')
        QTest.mouseClick(start_button,Qt.LeftButton);pump(.15)
        confirm=next(b for b in sheet.findChildren(QPushButton) if b.text()=='确认替换')
        QTest.mouseClick(confirm,Qt.LeftButton);pump(.1)
        check('normal recognition created worker',window.worker is not None and window.worker.isRunning())
        worker=window.worker;check('task explicitly owns MOSS',worker.options.speaker_source=='moss')
        check('real task is local analysis only',worker.options.recognition_purpose=='analysis')
        check('task choice leaves global disabled',window.legacy.RUNTIME_SETTINGS['models']['speaker_source']=='single')
        models=json.loads(worker.options.settings_snapshot_json)['models']
        report['task_snapshot']={'speaker':worker.options.speaker_source,
            'purpose':worker.options.recognition_purpose,'models':{k:models.get(k) for k in
                ('speaker_source','primary_asr_backend','firered_asr_backend','qwen_asr_backend')}}
        worker.result_ready.connect(received.append);worker.unexpected_error.connect(errors.append)
        wait(lambda:received or errors,600);guard.stop()
        report['recognition_errors']=errors+[str(x) for result in received for x in result.failures]
        check('real model task succeeds',not errors and bool(received[0].successes))
        wait(lambda:not worker.isRunning());target=Path(received[0].successes[0].project_path)
        project=load_project(target);save_project(project,out/'recognized.2byteproj')
        report['speaker_processing']=project.generation_metadata['speaker_recovery']['processing']
        report['task_output']=str(target);report['speaker_mapping']=[{'id':s.id,'name':s.name} for s in project.speakers]
        check('MOSS task reports real backend',report['speaker_processing'].get('backend')=='moss')
        check('real MOSS identities survive project',len({c.speaker_id for c in project.cues})>=2)
        for dialog in QApplication.topLevelWidgets():
            if isinstance(dialog,QDialog) and dialog.isVisible():dialog.close()
        window._modal_host.hide_content();pump(.25)
        opened('recognized');shot('moss-tracks')
        report['ui_speaker_ids']=page.timeline.speaker_ids()
        check('real MOSS UI matches cue identities',set(page.timeline.speaker_ids())=={c.speaker_id for c in page.project.cues})
        paths=export_subtitle_artifacts(page.project,out/'moss-export','moss',SubtitleExportOptions(speaker_mode='per_speaker'))
        report['speaker_exports']=[str(p.path) for p in paths]
        check('real MOSS per-speaker exports',len(paths)==len({c.speaker_id for c in page.project.cues}))
    def run():
        try:
            wait(lambda:page.project is not None and page._readiness.ready)
            if json.loads((out/'config.json').read_text('utf8'))['recognize']:recognize()
            opened('fixture');select_list();seek(12400);before=page.timeline.playhead_ms
            key(Qt.Key_E);check('E in gap opens selected editor',page._canvas_editor is page.subtitle_edit_input
                and page.subtitle_edit_input.toPlainText()=='原文 20')
            check('E gap does not seek',abs(page.timeline.playhead_ms-before)<30)
            count=page.undo_stack.count();key(Qt.Key_Q);key(Qt.Key_W);key(Qt.Key_E)
            check('typing qwe stays text',page.subtitle_edit_input.toPlainText().endswith('qwe') and page.undo_stack.count()==count)
            event=QInputMethodEvent('拼音',[]);QApplication.sendEvent(page.subtitle_edit_input,event)
            event=QInputMethodEvent();event.setCommitString('中文');QApplication.sendEvent(page.subtitle_edit_input,event)
            check('IME stays in editor','中文' in page.subtitle_edit_input.toPlainText())
            page.timeline.set_visible_window(12000,1000);page.video.set_paused(False)
            playback_until(16300,10);page.video.set_paused(True)
            check('editing survives natural paging',page._canvas_editor is page.subtitle_edit_input
                and page._review_edit_lock['cue_id']=='target' and QApplication.focusWidget() is page.subtitle_edit_input)
            shot('editing-after-paging');key(Qt.Key_Return)
            check('commit targets original cue',page.project.cues[0].text.endswith('qwe中文') and page.project.cues[1].text=='下一条 30')
            activate();key(Qt.Key_Z,Qt.ControlModifier);check('text undo',page.project.cues[0].text=='原文 20')
            key(Qt.Key_Y,Qt.ControlModifier);check('text redo',page.project.cues[0].text.endswith('qwe中文'))
            select_timeline();seek(9000);key(Qt.Key_E);key(Qt.Key_X);key(Qt.Key_Escape)
            check('cancel before cue retains text',page.project.cues[0].text.endswith('qwe中文') and page._canvas_editor is None)
            for playing in (False,True):
                for point in (9000,11000,12400,14500):
                    select_list();seek(point);page.video.set_paused(not playing);pump(.07)
                    before=page.timeline.playhead_ms;key(Qt.Key_E)
                    check(f'E selected at {point} playing={playing}',page._canvas_editor is page.subtitle_edit_input
                        and page._review_edit_lock['cue_id']=='target' and abs(page.timeline.playhead_ms-before)<250)
                    key(Qt.Key_Escape)
            for edge,point,expected in [(Qt.Key_Q,11000,(11000,12000)),(Qt.Key_W,11000,(10000,11000)),
                    (Qt.Key_Q,9000,(9000,12000)),(Qt.Key_W,12300,(10000,12300))]:
                select_list();seek(point);activate();index=page.undo_stack.index();key(edge)
                cue=page.project.cues[0]
                check(f'keyboard {edge} at {point}',(cue.start_ms,cue.end_ms)==expected and page.undo_stack.index()==index+1)
                check(f'boundary keeps playhead {edge} {point}',abs(page.timeline.playhead_ms-point)<35)
                key(Qt.Key_Z,Qt.ControlModifier)
            select_timeline();seek(12300);activate();key(Qt.Key_W)
            save_project(page.project,out/'edited.2byteproj');opened('edited')
            check('save reopen timing text identity',page.project.cues[0].end_ms==12300
                and page.project.cues[0].text.endswith('qwe中文') and page.project.cues[0].speaker_id=='S01')
            paths=export_subtitle_artifacts(page.project,out/'edited-export','edited',SubtitleExportOptions())
            check('edited SRT matches',any('00:00:12,300' in p.path.read_text('utf8') for p in paths if p.format=='srt'))
            opened('video-context');seek(11000)
            rect=page.timeline._video_track_rect('V2')
            point=page.timeline.mapTo(window,QPoint(round(page.timeline._time_to_x(5000)),round(rect.center().y())))
            QTest.mouseClick(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,point);pump(.1)
            check('video click retires subtitle target',page.cue_controller.explicit_edit_target() is None)
            seek(11000)
            page.video.set_paused(False);playback_until(11300,4);page.video.set_paused(True)
            check('video edit retains automatic cue highlight',bool(page.timeline.active_cue_ids))
            before_duration=page.project.video_tracks[0].clips[0].timeline_out_ms
            key(Qt.Key_Q)
            spans=[(t.clips[0].timeline_in_ms,t.clips[0].timeline_out_ms) for t in page.project.video_tracks if t.clips]
            check('Q with highlight ripples both video tracks',len(spans)==2 and spans[0]==spans[1]
                and spans[0][1]<before_duration-10000)
            key(Qt.Key_Z,Qt.ControlModifier);seek(11000);key(Qt.Key_W)
            spans=[(t.clips[0].timeline_in_ms,t.clips[0].timeline_out_ms) for t in page.project.video_tracks if t.clips]
            check('W with highlight ripples both video tracks',len(spans)==2 and spans[0]==spans[1]
                and spans[0][1]==11000)
            key(Qt.Key_Z,Qt.ControlModifier);seek(12500);key(Qt.Key_E)
            check('E with no selection in gap does not invent target',page._canvas_editor is None
                and page.save_state.text()=='当前播放头没有字幕')
            opened('edited')
            # Real playback, three pages each at 1x/2x and different zooms.
            for speed,zoom in [(1.,3000),(2.,4000)]:
                page.video.set_paused(True);page._set_speed(speed);seek(0)
                page.timeline.set_visible_window(0,zoom);page.timeline._follow_suspended_until=0
                begin=len(report['samples']);page.video.set_paused(False);playback_until(zoom*3+600,22)
                page.video.set_paused(True);samples=report['samples'][begin:]
                starts=list(dict.fromkeys(s['start'] for s in samples))
                report[f'pages_{speed}']=starts
                check(f'three natural pages {speed}',len(starts)>=4)
                check(f'page clock and scrollbar agree {speed}',all(s['scroll']==s['start'] for s in samples))
                check(f'page transitions left aligned {speed}',all(abs(s['playhead']-s['start'])<200 for i,s in enumerate(samples)
                    if i and s['start']!=samples[i-1]['start']))
            seek(33000);check('tail page left aligned',page.timeline.visible_start_ms==33000
                and page.timeline.horizontal_scrollbar.value()==33000)
            shot('tail-left-aligned');seek(500);check('left seek page',page.timeline.visible_start_ms==500)
            page.follow_playhead_toggle.setChecked(True);page.video.set_paused(False);playback_until(6000,8)
            page.video.set_paused(True);check('follow continuous anchor',abs(page.timeline.playhead_ms-page.timeline.visible_start_ms-1400)<150)
            page.follow_playhead_toggle.setChecked(False)
            page._set_speed(1.);seek(20000);page.timeline.set_visible_window(0,1000)
            bar=page.timeline.horizontal_scrollbar;opt=QStyleOptionSlider();bar.initStyleOption(opt)
            handle=bar.style().subControlRect(QStyle.CC_ScrollBar,opt,QStyle.SC_ScrollBarSlider,bar)
            point=bar.mapTo(window,handle.center());QTest.mousePress(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,point)
            check('real scrollbar press owns viewport',bar.isSliderDown())
            page.video.set_paused(False);pump(.35)
            check('natural playback does not fight held scrollbar',page.timeline.visible_start_ms==0)
            QTest.mouseRelease(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,point)
            wait(lambda:page.timeline.visible_start_ms>19000,5);page.video.set_paused(True)
            check('paging resumes after scrollbar release',not bar.isSliderDown() and page.timeline.visible_start_ms>19000)
            report['passed']=True
        except BaseException:
            report['error']=traceback.format_exc();shot('failure')
        finally:
            report['finished']=time.time();(out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),'utf8')
            try:page.video.set_paused(True);page.undo_stack.setClean();window.close()
            finally:QApplication.quit()
    QTimer.singleShot(1800,run)
