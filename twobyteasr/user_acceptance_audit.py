"""Bounded normal-window reproduction of the September user failures."""
import json
import os
import time
import traceback

from PySide6.QtCore import QTimer, Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QLineEdit, QToolButton


def start(window, out):
    page = window.studio_page
    started = time.monotonic()
    config = json.loads((out/'audit-config.json').read_text('utf8')) if (out/'audit-config.json').exists() else {}
    result = {'steps': [], 'error': '', 'input_method': 'QTest normal widgets', 'pid':os.getpid(),
              'hwnd':int(window.winId())}
    from .build_identity import load_build_identity
    result['identity'] = load_build_identity().to_dict()
    stage = ['ready']

    def snapshot(label):
        from .studio_performance import performance_snapshot
        row = performance_snapshot(page, compact=True)
        row['label'] = label
        row['track_ids'] = [s.id for s in page.project.speakers]
        row['media'] = [dict(id=a.asset_id, offline=a.offline) for a in page.project.media_pool]
        row['caption'] = page.subtitle_visibility_trace(reason='user_acceptance')
        row['cues'] = [dict(id=c.id, speaker=c.speaker_id, text=c.text)
                       for c in page.session.runtime.cues_at(page.timeline.playhead_ms)]
        result['steps'].append(row)
        from .processes import run_hidden_subprocess
        from .runtime_paths import detect_install_root
        # Capturing is an audit step; do not count it as playback timing.
        run_hidden_subprocess([str(detect_install_root()/'tools/ffmpeg/bin/ffmpeg.exe'), '-v', 'error', '-f', 'lavfi',
            '-i', f'gfxcapture=hwnd={int(window.winId())}:max_framerate=10:capture_cursor=0',
            '-vf', 'hwdownload,format=bgra', '-frames:v', '1', '-y', str(out/(label+'.png'))],
            timeout=10, purpose='actual acceptance window pixels')

    def finish():
        timer.stop()
        page.video.set_paused(True)
        (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')
        page.undo_stack.setClean()
        window.close()

    def tick():
        try:
            if time.monotonic()-started > 40:
                raise TimeoutError('user acceptance readiness/playback exceeded 40 seconds')
            if stage[0] == 'ready':
                if not page._readiness.ready:
                    if page._readiness.profile.get('error'):
                        raise RuntimeError(str(page._readiness.profile['error']))
                    return
                if config.get('matrix') in ('audio','offline','tracks'):
                    timer.stop()
                    if os.environ.get('TWOBYTEASR_USER_FAILURE_PHASE')=='reopen':
                        QTest.qWait(1600);snapshot('reopened')
                        result['checks']=dict(reopened_three=set(result['steps'][-1]['caption'].get('rendered_cue_ids',[]))=={'cue0','cue1','cue2'},
                            no_solo=not any(t.soloed for t in (*page.project.video_tracks,*page.project.audio_tracks)))
                    elif config['matrix']=='tracks':run_track_matrix(window,out,config,result,snapshot)
                    else:run_audio_matrix(window,out,config,result,snapshot)
                    QTest.mouseClick(page.save_button,Qt.LeftButton);QTest.qWait(400)
                    finish()
                    return
                stage[0] = 'settle'
                result['ready_seconds'] = time.monotonic()-started
                QTimer.singleShot(1200, lambda: stage.__setitem__(0, 'relink' if config.get('relink_path') else 'play'))
            elif stage[0] == 'relink':
                stage[0] = 'relink-select'
                snapshot('offline')
                result['old_path'] = page.project.media_pool[0].canonical_source
                QTest.mouseClick(page.media_availability.relink, Qt.LeftButton)
            elif stage[0] == 'relink-select':
                stage[0] = 'relink-wait'
                tree = page.media_pool_panel.assets
                snapshot('media-pool')
                QTest.mouseClick(tree.viewport(), Qt.LeftButton, pos=tree.visualItemRect(tree.topLevelItem(0)).center())
                assert page.media_pool_panel.selected_asset_id(), 'Normal media selection did not select an asset'
                QApplication.setAttribute(Qt.AA_DontUseNativeDialogs, True)
                def fill_dialog():
                    dialog = next((w for w in QApplication.topLevelWidgets() if isinstance(w, QFileDialog) and w.isVisible()), None)
                    if dialog is None:
                        result['dialog_not_opened'] = True
                        return
                    field = dialog.findChild(QLineEdit, 'fileNameEdit')
                    clip = QApplication.clipboard(); old = clip.text()
                    clip.setText(config['relink_path'])
                    QTest.mouseClick(field, Qt.LeftButton)
                    QTest.keyClick(field, Qt.Key_A, Qt.ControlModifier)
                    QTest.keyClick(field, Qt.Key_V, Qt.ControlModifier)
                    clip.setText(old)
                    QTest.keyClick(field, Qt.Key_Return)
                QTimer.singleShot(250, fill_dialog)
                QTest.mouseClick(page.media_pool_panel.relink_button, Qt.LeftButton)
            elif stage[0] == 'relink-wait':
                if page.project.media_pool[0].canonical_source != config['relink_path']:
                    return
                snapshot('relinked')
                button = next(w for w in page.findChildren(QToolButton) if w.toolTip() == '撤销 (Ctrl+Z)')
                QTest.mouseClick(button, Qt.LeftButton)
                stage[0] = 'undo-wait'
            elif stage[0] == 'undo-wait':
                if page.project.media_pool[0].canonical_source != result['old_path']:
                    return
                result['relink_undo'] = True
                snapshot('relink-undone')
                button = next(w for w in page.findChildren(QToolButton) if w.toolTip() == '重做 (Ctrl+Y)')
                QTest.mouseClick(button, Qt.LeftButton)
                stage[0] = 'redo-wait'
            elif stage[0] == 'redo-wait':
                if page.project.media_pool[0].canonical_source != config['relink_path']:
                    return
                result['relink_redo'] = True
                stage[0] = 'settle'
                QTimer.singleShot(1500, lambda: stage.__setitem__(0, 'play'))
            elif stage[0] == 'play':
                stage[0] = 'playing'
                snapshot('ready')
                result['start_ms'] = page.timeline.playhead_ms
                page.volume_slider.setValue(12)
                page.audio_engine.capture_pcm('backend', True)
                QTest.mouseClick(page.play_button, Qt.LeftButton)
                QTimer.singleShot(3000, lambda: stage.__setitem__(0, 'end'))
            elif stage[0] == 'end':
                stage[0] = 'finished'
                snapshot('playing')
                audio = page.audio_engine.telemetry_snapshot()
                result['checks'] = dict(
                    offline_count=sum(a.offline for a in page.project.media_pool)==config.get('offline_count',2),
                    progress=page.timeline.playhead_ms-result['start_ms'] > 1500,
                    consumed_audio=(audio.get('sink_consumed_rms', 0)>0) == config.get('has_audio',True),
                    notification=page.media_availability.banner.isVisible(),
                )
                if config.get('expected_cue_count'):
                    result['checks']['all_cues_prepared'] = all(len(row['caption'].get('rendered_cue_ids', ())) == config['expected_cue_count'] for row in result['steps'])
                    result['checks']['all_cues_expected'] = all(len(row['caption'].get('expected_cue_ids', ())) == config['expected_cue_count'] for row in result['steps'])
                    result['checks']['all_cues_have_pixels'] = all(len(row['caption'].get('cue_pixels', ())) == config['expected_cue_count'] and all(c.get('alpha_nonzero',0)>0 for c in row['caption']['cue_pixels']) for row in result['steps'])
                if config.get('track_actions'):
                    QTest.mouseClick(page.play_button,Qt.LeftButton)
                    stage[0]='track-delete'
                else:finish()
            elif stage[0] == 'track-delete':
                stage[0]='track-delete-settle'
                result['tracks_before']=[s.id for s in page.project.speakers]
                rect=page.timeline._track_layout()[0][result['tracks_before'][0]]
                QTest.mouseClick(page.timeline,Qt.LeftButton,pos=QPoint(214,round(rect.center().y())))
                QTimer.singleShot(1800,lambda:stage.__setitem__(0,'track-undo'))
            elif stage[0] == 'track-undo':
                snapshot('track-deleted')
                result['checks']['delete_button']=len(page.project.speakers)==len(result['tracks_before'])-1
                button=next(w for w in page.findChildren(QToolButton) if w.toolTip()=='撤销 (Ctrl+Z)')
                QTest.mouseClick(button,Qt.LeftButton)
                stage[0]='track-undo-settle'
                QTimer.singleShot(1800,lambda:stage.__setitem__(0,'track-key'))
            elif stage[0] == 'track-key':
                snapshot('track-undo')
                result['checks']['track_undo']=[s.id for s in page.project.speakers]==result['tracks_before']
                sid=result['tracks_before'][1];rect=page.timeline._track_layout()[0][sid]
                QTest.mouseClick(page.timeline,Qt.LeftButton,pos=QPoint(75,round(rect.center().y())))
                QTest.keyClick(page.timeline,Qt.Key_Delete)
                result['checks']['header_delete']=sid not in {s.id for s in page.project.speakers}
                stage[0]='track-key-settle'
                QTimer.singleShot(1800,lambda:stage.__setitem__(0,'track-done'))
            elif stage[0] == 'track-done':
                snapshot('track-key-deleted')
                button=next(w for w in page.findChildren(QToolButton) if w.toolTip()=='撤销 (Ctrl+Z)')
                QTest.mouseClick(button,Qt.LeftButton)
                stage[0]='track-final-settle'
                QTimer.singleShot(1800,lambda:stage.__setitem__(0,'track-final'))
            elif stage[0] == 'track-final':
                snapshot('track-restored')
                result['checks']['restored_pixels']=len(result['steps'][-1]['caption'].get('rendered_cue_ids',[]))==len(result['tracks_before'])
                finish()
        except Exception:
            result['error'] = traceback.format_exc()
            finish()
    timer = QTimer(window)
    timer.setInterval(50)
    timer.timeout.connect(tick)
    timer.start()


def run_audio_matrix(window,out,config,result,snapshot):
    """Normal S/M buttons, with FFT of PCM actually consumed by QAudioSink."""
    import numpy as np
    from pathlib import Path
    page=window.studio_page;timeline=page.timeline
    checks=result.setdefault('checks',{})
    def pump(seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:QApplication.processEvents();QTest.qWait(15)
    def wait(predicate,seconds,label):
        end=time.monotonic()+seconds
        while not predicate():
            if time.monotonic()>end:raise TimeoutError(label)
            pump(.03)
    def button(tid,x):
        from .studio_track_header import button_rect
        rect=timeline._audio_track_rects()[tid]
        bar=timeline.vertical_scrollbar
        if rect.top()<timeline.RULER_HEIGHT or rect.bottom()>timeline.height()-22:
            bar.setValue(bar.value()+round(rect.center().y()-timeline.height()*.55));pump(.12)
        rect=timeline._audio_track_rects()[tid]
        assert timeline.RULER_HEIGHT<rect.center().y()<timeline.height()-20,(tid,rect,timeline.height())
        action={120:'muted',178:'solo',208:'delete'}[x]
        QTest.mouseClick(timeline,Qt.LeftButton,pos=button_rect('audio',action,rect).center().toPoint())
        pump(1.2)
    def record(name,expected):
        page.audio_engine.capture_pcm(name,True)
        wait(lambda:(out/(name+'.started')).exists(),3,'capture start')
        pump(.7);page.audio_engine.capture_pcm(name,False)
        wait(lambda:(out/(name+'.json')).exists(),3,'capture complete')
        telemetry=page.audio_engine.telemetry_snapshot()
        data=(out/(name+'.pcm')).read_bytes()
        fmt=telemetry.get('output_format',{})
        # The endpoint ring always owns interleaved signed 16-bit stereo PCM.
        samples=np.frombuffer(data[:len(data)//4*4],dtype='<i2').reshape(-1,2).mean(axis=1)/32768 if data else np.zeros(0)
        samples=samples[-48000:]
        spectrum=np.abs(np.fft.rfft(samples*np.hanning(len(samples)))) if len(samples)>32 else np.zeros(1)
        hz=np.fft.rfftfreq(len(samples),1/48000) if len(samples)>32 else np.zeros(1)
        powers={f:float(spectrum[np.abs(hz-f)<5].max(initial=0)) for f in (440,660,880)}
        largest=max(powers.values());present={f for f,v in powers.items() if v>max(.5,largest*.035)}
        checks[name]=present==set(expected)
        result.setdefault('audio_captures',[]).append(dict(name=name,expected=list(expected),actual=sorted(present),
            powers=powers,rms=float(np.sqrt(np.mean(samples*samples))) if len(samples) else 0,
            bytes=len(data),format=fmt,clock_ms=timeline.playhead_ms,telemetry=telemetry))
        if not checks[name]:raise AssertionError(f'{name}: consumed frequencies {present}, expected {expected}')
    pump(1.4);snapshot('ready')
    before=timeline.playhead_ms
    page.volume_slider.setValue(20);QTest.mouseClick(page.play_button,Qt.LeftButton);pump(2)
    checks['clock_progress']=timeline.playhead_ms>before+1000
    checks['default_no_solo']=not any(t.soloed for t in (*page.project.video_tracks,*page.project.audio_tracks))
    checks['default_no_master']=page.project.studio_state.get('audio_master_mode','mix_all')!='manual'
    if config['matrix']=='offline':
        checks['offline_banner']=page.media_availability.banner.isVisible() and sum(a.offline for a in page.project.media_pool)==2
        record('offline-independent',[880]);snapshot('offline-playing')
        button('A1',178);record('offline-solo',[])
        snapshot('offline-solo');button('A1',178);record('offline-solo-restored',[880])
        import copy
        def edits():
            from dataclasses import asdict
            return dict(video=[asdict(t) for t in page.project.video_tracks],
                audio=[asdict(t) for t in page.project.audio_tracks],cues=[asdict(c) for c in page.project.cues])
        original_edits=copy.deepcopy(edits());old_path=page.project.media_pool[0].canonical_source
        QTest.mouseClick(page.media_availability.relink,Qt.LeftButton);pump(.3)
        tree=page.media_pool_panel.assets
        QTest.mouseClick(tree.viewport(),Qt.LeftButton,pos=tree.visualItemRect(tree.topLevelItem(0)).center())
        QApplication.setAttribute(Qt.AA_DontUseNativeDialogs,True)
        def fill():
            dialog=next(w for w in QApplication.topLevelWidgets() if isinstance(w,QFileDialog) and w.isVisible())
            field=dialog.findChild(QLineEdit,'fileNameEdit');old=QApplication.clipboard().text()
            QApplication.clipboard().setText(config['relink_path']);QTest.mouseClick(field,Qt.LeftButton)
            QTest.keyClick(field,Qt.Key_A,Qt.ControlModifier);QTest.keyClick(field,Qt.Key_V,Qt.ControlModifier)
            QApplication.clipboard().setText(old);QTest.keyClick(field,Qt.Key_Return)
        from PySide6.QtWidgets import QScrollArea
        parent=page.media_pool_panel.parentWidget()
        while parent:
            if isinstance(parent,QScrollArea):parent.ensureWidgetVisible(page.media_pool_panel.relink_button)
            parent=parent.parentWidget()
        pump(.1);QTimer.singleShot(250,fill);QTest.mouseClick(page.media_pool_panel.relink_button,Qt.LeftButton)
        wait(lambda:page.project.media_pool[0].canonical_source==config['relink_path'],10,'normal relink')
        pump(1.5);checks['relink_preserves_edits']=edits()==original_edits
        record('relinked-mix',[440,880]);snapshot('relinked')
        checks['relink_removes_placeholder']=not page.media_availability.gap_visible
        assert checks['relink_removes_placeholder']
        undo=next(w for w in page.findChildren(QToolButton) if w.toolTip()=='撤销 (Ctrl+Z)')
        QTest.mouseClick(undo,Qt.LeftButton);pump(1.5)
        checks['relink_undo']=page.project.media_pool[0].canonical_source==old_path and edits()==original_edits
        record('relink-undone',[880])
        redo=next(w for w in page.findChildren(QToolButton) if w.toolTip()=='重做 (Ctrl+Y)')
        QTest.mouseClick(redo,Qt.LeftButton);pump(1.5)
        checks['relink_redo']=page.project.media_pool[0].canonical_source==config['relink_path'] and edits()==original_edits
        record('relink-redone',[440,880])
        # The remaining offline V2 must produce a readable failure through
        # the ordinary export button, with no successful partial output.
        from PySide6.QtWidgets import QPushButton
        QTest.mouseClick(page.studio_render_button,Qt.LeftButton)
        wait(lambda:page.export_workspace is not None,3,'offline export panel');pump(.3)
        ui=page.export_workspace
        for widget,value in ((ui.filename,'offline-must-fail'),(ui.directory,str(out))):
            old=QApplication.clipboard().text();QApplication.clipboard().setText(value)
            QTest.mouseClick(widget,Qt.LeftButton);QTest.keyClick(widget,Qt.Key_A,Qt.ControlModifier)
            QTest.keyClick(widget,Qt.Key_V,Qt.ControlModifier);QApplication.clipboard().setText(old)
        QTest.mouseClick(ui.export_button,Qt.LeftButton)
        wait(lambda:ui.pages.currentWidget() is ui.failure_page,8,'missing-media export failure')
        message=ui.failure_reason.text();result['missing_export_message']=message
        checks['missing_export_rejected']='重新链接' in message and 'video-660.mp4' in message and not (out/'offline-must-fail.mp4').exists()
        assert checks['missing_export_rejected'],message
        pump(.4)
        snapshot('missing-export-failure')
        QTest.mouseClick(next(b for b in ui.failure_page.findChildren(QPushButton) if b.text()=='返回设置'),Qt.LeftButton)
        QTest.mouseClick(next(b for b in ui.setup_page.findChildren(QPushButton) if b.text().startswith('← 返回')),Qt.LeftButton)
        pump(.5)
    else:
        record('mix-all',[440,660,880]);button('A1',178);record('solo-one',[440])
        button('A2',178);record('solo-two',[440,660]);button('A1',120);record('mute-wins',[660])
        button('A1',178);record('solo-two-only',[660]);button('A2',178);record('mix-with-muted',[660,880])
        button('A1',120);record('mix-restored',[440,660,880])
        snapshot('solo-off-restored')
        # Playback deletion uses the same visible track button, then toolbar undo.
        button(config['independent_audio_id'],208);record('audio-deleted',[440,660])
        undo=next(w for w in page.findChildren(QToolButton) if w.toolTip()=='撤销 (Ctrl+Z)')
        QTest.mouseClick(undo,Qt.LeftButton);pump(1.5);record('audio-delete-undo',[440,660,880])
        source=Path(config['runtime_source']);junction=Path(config['runtime_junction']);target=Path(config['runtime_target'])
        assert junction.parent.resolve()==out.resolve() and junction.resolve()==target.resolve() and target.resolve().is_relative_to(out.resolve())
        import stat
        assert junction.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        os.rmdir(junction)  # Remove the checked link itself; never its target files.
        try:
            wait(lambda:next(a for a in page.project.media_pool if a.canonical_source==str(source)).offline,8,'runtime loss detection')
            pump(1.5);record('runtime-loss',[660,880]);snapshot('runtime-loss')
        finally:
            from .processes import run_hidden_subprocess
            run_hidden_subprocess(['cmd','/d','/c','mklink','/J',str(junction),str(target)],check=True,capture_output=True,
                timeout=5,purpose='restore owned acceptance source mount')
        wait(lambda:not next(a for a in page.project.media_pool if a.canonical_source==str(source)).offline,8,'runtime recovery')
        pump(1.5);record('runtime-recovered',[440,660,880])
    snapshot('final');QTest.mouseClick(page.play_button,Qt.LeftButton)
    checks['all_three_subtitles']=set(result['steps'][-1]['caption'].get('rendered_cue_ids',[]))=={'cue0','cue1','cue2'}


def run_track_matrix(window,out,config,result,snapshot):
    from PySide6.QtWidgets import QScrollArea, QPushButton, QPlainTextEdit
    page=window.studio_page;timeline=page.timeline;checks=result.setdefault('checks',{})
    from PySide6.QtCore import QObject,QEvent
    class KeyTrace(QObject):
        def eventFilter(self,watched,event):
            if event.type() in (QEvent.KeyPress,QEvent.KeyRelease) and event.key()==Qt.Key_Delete:
                import shiboken6
                result.setdefault('key_events',[]).append(dict(kind=str(event.type()),
                    watched=type(watched).__name__,widget=int(shiboken6.getCppPointer(watched)[0]),
                    event=int(shiboken6.getCppPointer(event)[0]),accepted=event.isAccepted(),spontaneous=event.spontaneous(),
                    stamp=event.timestamp(),repeat=event.isAutoRepeat()))
            return False
    key_trace=KeyTrace(page);QApplication.instance().installEventFilter(key_trace)
    original_delete=page._command_callbacks['delete']
    def traced_delete():
        result.setdefault('delete_calls',[]).append(dict(stack=traceback.format_stack(limit=9),
            header=timeline.selected_track_header,selected=page.selected_cue_id))
        return original_delete()
    page._command_callbacks['delete']=traced_delete
    def pump(seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:QApplication.processEvents();QTest.qWait(15)
    def wait(fn,timeout,label):
        end=time.monotonic()+timeout
        while not fn():
            if time.monotonic()>end:raise TimeoutError(label)
            pump(.04)
    def click(widget):
        parent=widget.parentWidget()
        while parent:
            if isinstance(parent,QScrollArea):parent.ensureWidgetVisible(widget)
            parent=parent.parentWidget()
        pump(.05);assert widget.isVisible() and widget.isEnabled(),widget.objectName()
        target=widget.viewport() if isinstance(widget,QPlainTextEdit) else widget
        QTest.mouseClick(target,Qt.LeftButton);pump(.1)
    def type_value(widget,value):
        click(widget);QTest.keyClick(widget,Qt.Key_A,Qt.ControlModifier)
        original=QApplication.clipboard().text();QApplication.clipboard().setText(str(value))
        QTest.keyClick(widget,Qt.Key_V,Qt.ControlModifier);QApplication.clipboard().setText(original)
        QTest.keyClick(widget,Qt.Key_Return);pump(.4)
    def header(sid,x):
        rect=timeline._track_layout()[0][sid];bar=timeline.vertical_scrollbar
        bar.setValue(bar.value()+round(rect.center().y()-timeline.height()*.45));pump(.1)
        rect=timeline._track_layout()[0][sid]
        QTest.mouseClick(timeline,Qt.LeftButton,pos=QPoint(x,round(rect.center().y())));pump(.2)
    def undo():click(next(w for w in page.findChildren(QToolButton) if w.toolTip()=='撤销 (Ctrl+Z)'));pump(.8)
    def pixels(name,ids):
        pump(.9);snapshot(name);actual=result['steps'][-1]['caption']
        checks[name]=set(actual.get('rendered_cue_ids',[]))==set(ids) and all(r.get('alpha_nonzero',0)>0 for r in actual.get('cue_pixels',[]))
        assert checks[name],actual
    pump(1.2);pixels('three-original',{'cue0','cue1','cue2'})
    header('S2',160);pixels('two-visible',{'cue0','cue1'})
    header('S1',160);pixels('one-visible',{'cue0'})
    header('S2',160);header('S1',160);pixels('three-restored',{'cue0','cue1','cue2'})
    ruler=QPoint(round(timeline._time_to_x(3000)),timeline.RULER_HEIGHT//2)
    QTest.mouseClick(timeline,Qt.LeftButton,pos=ruler);pixels('seek-three',{'cue0','cue1','cue2'})
    QTest.mousePress(timeline,Qt.LeftButton,pos=ruler)
    QTest.mouseMove(timeline,QPoint(round(timeline._time_to_x(1000)),ruler.y()),80)
    QTest.mouseRelease(timeline,Qt.LeftButton,pos=QPoint(round(timeline._time_to_x(1000)),ruler.y()))
    pixels('scrub-three',{'cue0','cue1','cue2'})
    click(page.play_button);pump(.6)
    header('S2',214);pixels('playing-delete-two',{'cue0','cue1'})
    undo();pixels('playing-undo-three',{'cue0','cue1','cue2'})
    click(page.play_button)
    click(page.add_subtitle_track_button);new=page.project.speakers[-1].id
    checks['fourth_empty_preserves_three']=len(page.project.speakers)==4
    pixels('fourth-empty',{'cue0','cue1','cue2'})
    QTest.keyClick(timeline,Qt.Key_T);pump(.4)
    created=page.selected_cue_id;assert created not in {'cue0','cue1','cue2'}
    editor=page._canvas_editor;type_value(editor,'第四轨新增字幕')
    # Enter commits; Escape also safely closes the inline editor when the
    # user's Enter preference inserts a newline.
    QTest.keyClick(editor,Qt.Key_Escape);pump(.3)
    assert next(c for c in page.project.cues if c.id==created).speaker_id==new
    tab=page.context_drawer.tabBar();QTest.mouseClick(tab,Qt.LeftButton,pos=tab.tabRect(2).center());pump(.2)
    section=next(b for b in page.findChildren(QPushButton)+page.findChildren(QToolButton) if '高级位置与对齐' in b.text())
    if not page.style_position_y.isVisible():click(section)
    type_value(page.style_position_y,980)
    pixels('four-cue-pixels',{'cue0','cue1','cue2',created})
    before=len(page.project.speakers)
    def selection(label):
        result.setdefault('focus_steps',[]).append(dict(label=label,header=timeline.selected_track_header,
            cue_ids=[c.id for c in page.project.cues],selected=page.selected_cue_id,
            focus=type(QApplication.focusWidget()).__name__,editing=page._editing_has_focus(),
            undo=[page.undo_stack.command(i).text() for i in range(page.undo_stack.index())]))
    # The actual text editor owns Delete, even while a track header remains selected.
    header(new,75);QTest.keyClick(page,Qt.Key_E);pump(.2)
    editor=page._canvas_editor
    click(editor);QTest.keyClick(editor,Qt.Key_Home)
    selection('before-text-delete');text_before=editor.toPlainText()
    QTest.keyClick(editor,Qt.Key_Delete);pump(.15)
    selection('after-text-delete')
    checks['text_delete_does_not_remove_track']=len(page.project.speakers)==before and len(page.project.cues)==4 and len(editor.toPlainText())==len(text_before)-1
    assert checks['text_delete_does_not_remove_track'],result['focus_steps']
    QTest.keyClick(editor,Qt.Key_Escape);pump(.1)
    selection('after-escape');header(new,75);selection('before-header-delete')
    assert timeline.selected_track_header==('subtitle',new)
    QTest.keyClick(timeline,Qt.Key_Delete);selection('after-header-delete');pixels('header-delete-three',{'cue0','cue1','cue2'})
    undo();pixels('header-delete-undo-four',{'cue0','cue1','cue2',created})
    header(new,214);pixels('final-three',{'cue0','cue1','cue2'})
    # The last clip removes its now-empty linked lanes in the same operation.
    video=next(t for t in page.project.video_tracks if t.id!='V1');clip_id=video.clips[0].id
    rect=timeline._video_track_rect(video.id);bar=timeline.vertical_scrollbar
    bar.setValue(bar.value()+round(rect.center().y()-timeline.height()*.55));pump(.15)
    rect=timeline._video_track_rect(video.id)
    QTest.mouseClick(timeline,Qt.LeftButton,pos=QPoint(timeline.TRACK_HEADER_WIDTH+90,round(rect.center().y())))
    pump(.2);assert timeline.selected_video_clip_id==clip_id and timeline.selected_track_header is None
    QTest.keyClick(timeline,Qt.Key_Delete);pump(.5)
    checks['clip_delete_removes_empty_group']=not any(t.id==video.id for t in page.project.video_tracks) and len(page.project.cues)==3
    assert checks['clip_delete_removes_empty_group']
    undo();checks['clip_undo_restores']=any(c.id==clip_id for t in page.project.video_tracks for c in t.clips)
    pixels('clip-undo-three',{'cue0','cue1','cue2'})
    # Actual normal export settings and worker, restricted to four seconds.
    click(page.studio_render_button);wait(lambda:page.export_workspace is not None,3,'export panel')
    ui=page.export_workspace;pump(.3)
    type_value(ui.filename,'three-track-export');type_value(ui.directory,str(out))
    ui.preview_scrub.setValue(4000)
    out_button=next(b for b in ui.findChildren(QPushButton) if b.text().startswith('设置出点'))
    click(out_button)
    ui.export_range.setCurrentIndex(ui.export_range.findData('in_out'))
    original_resolution=ui.resolution.findData('original')
    if original_resolution>=0:ui.resolution.setCurrentIndex(original_resolution)
    snapshot('export-settings');click(ui.export_button)
    wait(lambda:ui.pages.currentWidget() in (ui.success_page,ui.failure_page),120,'real export')
    checks['export_success']=ui.pages.currentWidget() is ui.success_page
    if not checks['export_success']:raise AssertionError(ui.failure_reason.text())
    result['export_path']=str(ui._success_output);result['export_receipt']=dict(ui._last_job.completion_metadata)
    snapshot('export-complete');click(ui.success_page.back);pump(.3)
