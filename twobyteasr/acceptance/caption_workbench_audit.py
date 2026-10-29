"""Real Windows/mpv scene matrix, low-overhead UI intervals and window ownership."""
import copy
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import statistics
import sys
import time
import traceback


def window_events(events):
    # Never query window titles from a GUI-thread WinEvent callback: Win32 may
    # synchronously ask the window for text while Qt is constructing it.
    import threading
    class Monitor:
        thread_id = 0
        ready = threading.Event()
        def close(self):
            if self.thread_id: ctypes.windll.user32.PostThreadMessageW(self.thread_id,0x12,0,0)
    monitor=Monitor()
    def listen():
        user=ctypes.windll.user32
        process_names={}
        callback_type=ctypes.WINFUNCTYPE(None,wintypes.HANDLE,wintypes.DWORD,wintypes.HWND,
            wintypes.LONG,wintypes.LONG,wintypes.DWORD,wintypes.DWORD)
        user.SetWinEventHook.restype=wintypes.HANDLE
        user.GetWindow.restype=wintypes.HWND;user.GetParent.restype=wintypes.HWND
        def event(hook,kind,hwnd,obj,child,thread,stamp):
            if obj!=0 or child!=0:return
            pid=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            cls=ctypes.create_unicode_buffer(128);user.GetClassNameW(hwnd,cls,len(cls))
            row=dict(time=time.monotonic(),event=int(kind),hwnd=int(hwnd or 0),
                window_class=cls.value,pid=pid.value,parent=int(user.GetParent(hwnd) or 0),
                owner=int(user.GetWindow(hwnd,4) or 0),visible=bool(user.IsWindowVisible(hwnd)))
            if pid.value not in process_names:
                try:
                    import psutil
                    process_names[pid.value]=psutil.Process(pid.value).exe()
                except Exception:process_names[pid.value]='unavailable'
            row['process_path']=process_names[pid.value]
            rect=wintypes.RECT();user.GetWindowRect(hwnd,ctypes.byref(rect))
            row['rect']=[rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top]
            row['child_window']=bool(user.GetWindowLongW(hwnd,-16)&0x40000000)
            events.append(row)
            # Bounded WM_GETTEXT; a vanished/unresponsive window keeps no title.
            title=ctypes.create_unicode_buffer(512); answer=ctypes.c_size_t()
            user.SendMessageTimeoutW(hwnd,0xD,len(title),ctypes.byref(title),2,10,ctypes.byref(answer))
            row['title']=title.value
        callback=callback_type(event)
        monitor.thread_id=ctypes.windll.kernel32.GetCurrentThreadId()
        handle=user.SetWinEventHook(0x8000,0x8003,None,callback,0,0,0)
        monitor.ready.set()
        message=wintypes.MSG()
        while user.GetMessageW(ctypes.byref(message),None,0,0)>0:
            user.TranslateMessage(ctypes.byref(message));user.DispatchMessageW(ctypes.byref(message))
        if handle:
            user.UnhookWinEvent.argtypes=[wintypes.HANDLE];user.UnhookWinEvent(handle)
    threading.Thread(target=listen,name='acceptance-window-events',daemon=True).start()
    monitor.ready.wait(1)
    return monitor,None


def run(output, *, media=None, window=None):
    from ..test_isolation import install, install_pytest_network_guard
    install(); install_pytest_network_guard()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from ..studio.studio_ui import SubtitleStudioPage
    from ..projects.studio_project import SubtitleProject, StudioCue, StudioMedia, StudioSpeaker, save_project, hydrate_media_contract, load_project
    from ..studio.studio_helpers import probe_media_identity
    from ..caption_design.web_theme import builtin_web_themes
    from ..system.processes import run_hidden_subprocess
    from .blank_project_audit import _capture
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    result = dict(passed=False, production_source=str(Path(__import__('twobyteasr').__file__).resolve()), pid=os.getpid(), executable=sys.executable, source=str(Path(__file__).resolve()),
                  cases=[], windows=globals().get('_early_events', []), lifecycle=[], media=str(media or 'generated 24-second 720p testsrc2'))
    hook, callback = globals().get('_early_hook') or window_events(result['windows'])
    app = QApplication.instance() or QApplication([])
    from PySide6.QtCore import QObject,QEvent
    from PySide6.QtWidgets import QWidget
    class WindowOrigins(QObject):
        def eventFilter(self,obj,event):
            if event.type()==QEvent.Show and isinstance(obj,QWidget) and obj.isWindow() and obj.width()<600 and obj.height()<600:
                result.setdefault('qt_window_origins',[]).append(dict(widget=type(obj).__name__,name=obj.objectName(),
                    size=[obj.width(),obj.height()],parent=type(obj.parent()).__name__ if obj.parent() else None,
                    stack=traceback.format_stack(limit=15)))
            return False
    origins=WindowOrigins();app.installEventFilter(origins)
    input_project=os.environ.get('CAPTION_AUDIT_PROJECT')
    template=load_project(input_project) if input_project else None
    if template is not None and os.environ.get('CAPTION_AUDIT_INITIAL_ORIGINAL')=='1':
        template.studio_state['bilingual']['mode']='original'
        result['initial_original']=True
    cue_count=int(os.environ.get('CAPTION_AUDIT_CUE_COUNT','24'))
    if template is not None:media=template.media.path
    if media is None:
        media = output/'source.mp4'
        root = Path(__file__).resolve().parents[2]
        run_hidden_subprocess([str(root/'tools/ffmpeg/bin/ffmpeg.exe'), '-v','error','-y',
            '-f','lavfi','-i','testsrc2=size=1280x720:rate=30:duration=24',
            '-f','lavfi','-i','sine=frequency=440:duration=24', '-c:v','libx264','-preset','ultrafast',
            '-c:a','aac',str(media)], purpose='caption playback audit fixture', check=True, timeout=40,
            capture_output=True)
    result['media']=str(media)
    result['input_project']=input_project
    intervals = []; last = [time.monotonic()]; sampling=[False]; samples=[]; last_sample=[0.]
    def tick():
        now=time.monotonic(); intervals.append((now-last[0])*1000); last[0]=now
        if sampling[0] and page is not None and now-last_sample[0]>=.1:
            last_sample[0]=now
            from ..rendering.caption_scene import active_cues
            owner=getattr(page,'_caption_scene',None)
            if owner is not None and owner.active:
                expected={c.id for c in active_cues(page,page._caption_sample_ms())}
                if scene=='bilingual':expected|={key+'#tr' for key in tuple(expected)}
                rendered=set(owner.trace().get('rendered_cue_ids',()))
                samples.append(dict(time=now,expected=sorted(expected),rendered=sorted(rendered),matched=expected==rendered))
    timer=QTimer(); timer.setInterval(10); timer.timeout.connect(tick); timer.start()
    page = None
    profiles=[];profile_counts={}
    from ..rendering.caption_scene import SceneRasterizer
    original_frame=SceneRasterizer.frame
    def profiled_frame(self, items, *args, **kwargs):
        import cProfile, threading
        items=tuple(items)
        kind='web' if any(getattr(p,'web',None) for _,p in items) else 'marked' if any(getattr(getattr(p,'snapshot',None),'text_marks',None) for _,p in items) else 'plain'
        key=(threading.current_thread().name,kind)
        if profile_counts.get(key,0)>=3:return original_frame(self,items,*args,**kwargs)
        profile_counts[key]=profile_counts.get(key,0)+1
        profile=cProfile.Profile();began=time.perf_counter();profile.enable()
        try:return original_frame(self,items,*args,**kwargs)
        finally:
            profile.disable();profiles.append((key,profile,time.perf_counter()-began))
    if os.environ.get('CAPTION_AUDIT_PROFILE')=='1':SceneRasterizer.frame=profiled_frame
    def wait(predicate, seconds=25):
        end=time.monotonic()+seconds
        while not predicate():
            if time.monotonic()>end: raise TimeoutError('caption audit readiness')
            QTest.qWait(20)
    def visible_matches(visibility, scene):
        expected=set(visibility.get('expected_cue_ids',()))
        if scene=='bilingual': expected |= {key+'#tr' for key in tuple(expected)}
        return expected==set(visibility.get('rendered_cue_ids',()))
    def metrics(controller):
        values={}
        for key in ('decoder-frame-drop-count','frame-drop-count','mistimed-frame-count',
                    'vo-delayed-frame-count','hwdec-current','video-sync','speed'):
            try: values[key]=controller.get_property(key)
            except Exception as exc: values[key]={'unavailable':str(exc)}
        return values
    try:
        for cycle in range(1 if os.environ.get('CAPTION_AUDIT_UI_ONLY')=='1' else 3):
            page=window.studio_page if window is not None else SubtitleStudioPage()
            surface=window if window is not None else page
            surface.resize(1440,900); surface.show()
            project=copy.deepcopy(template) if template is not None else SubtitleProject(media=StudioMedia(str(media),duration_ms=max(24000,cue_count*1000),width=1280,height=720),
                speakers=[StudioSpeaker('S01','玩家'),StudioSpeaker('S02','隊友')],
                cues=[StudioCue(str(i),i*1000,(i+1)*1000,f'今天通過最後一關 {i}',speaker_id='S01' if i%2 else 'S02') for i in range(cue_count)])
            hydrate_media_contract(project,probe_media_identity(str(media))); project.validate()
            result['cue_count']=len(project.cues)
            result['speaker_count']=len(project.speakers)
            start_seconds=(project.cues[0].start_ms+100)/1000 if template is not None else 1
            path=output/f'fixture-{cycle}.2byteproj';save_project(project,path)
            began=time.monotonic()
            if window is not None: window.open_studio_project(path,mode='edit',source='caption_audit')
            else: page.open_project(path)
            _capture(page,output/f'opening-{cycle}.png')
            app.processEvents()
            wait(lambda: page.project is not None and page._readiness.ready and page.video.controller is not None)
            result['lifecycle'].append(dict(cycle=cycle,open_ms=(time.monotonic()-began)*1000,
                timer_count=len(page.findChildren(QTimer)),active_timer_count=sum(t.isActive() for t in page.findChildren(QTimer))))
            controller=page.video.controller
            scenarios=('off','plain','markdown','ai','bilingual') if cycle == 0 else ('plain',)
            if os.environ.get('CAPTION_AUDIT_UI_ONLY')=='1':
                scenarios=()
                page.project.generation_metadata['translations']={c.id:f'We cleared the final stage {c.id}' for c in page.project.cues}
                page.project.studio_state['bilingual']={'mode':'bilingual'}
                page._changed();QTest.qWait(400)
            if os.environ.get('CAPTION_AUDIT_OPEN_ONLY')=='1':scenarios=()
            for scene in scenarios:
                p=page.project
                p.style_recipes={}
                p.studio_state['bilingual']={'mode':'original'}
                for cue in p.cues: cue.appearance_override={}
                if scene=='markdown':
                    for cue in p.cues: cue.appearance_override={'text_marks':[
                        {'start':4,'end':8,'bold':True,'color':'#FFD166'}]}
                if scene=='ai':
                    p.style_recipes['default']={'name':'自由設計 DOOM95','engine':'remotion',
                        'webTheme':builtin_web_themes()['doom95'].to_dict()}
                if scene=='bilingual':
                    if template is None:
                        p.generation_metadata['translations']={c.id:f'We cleared the final stage {c.id}' for c in p.cues}
                    p.studio_state['bilingual']={'mode':'bilingual'}
                page._subtitle_track_visibility={s.id:scene!='off' for s in p.speakers}
                page._changed(); QTest.qWait(400)
                if scene=='ai': QTest.qWait(2000)
                for rate in ((1,4) if cycle==0 else (1,)):
                    page.video.set_paused(True);page._set_speed(rate);page._seek(start_seconds)
                    wait(lambda:not page.video._playback_clock.exact_seek_pending and page._playback_buffers_ready())
                    before=metrics(controller); intervals.clear();samples.clear();last[0]=time.monotonic();sampling[0]=True
                    start=page.timeline.playhead_ms; began=time.monotonic();page.video.set_paused(False)
                    QTest.qWait(2400)
                    sampling[0]=False;page.video.set_paused(True); elapsed=time.monotonic()-began
                    values=sorted(intervals); QTest.qWait(200)
                    settle_started=time.monotonic()
                    visibility=page.subtitle_visibility_trace(reason='caption_settle')
                    while scene!='off' and not visible_matches(visibility, scene) and time.monotonic()-settle_started<4:
                        QTest.qWait(30);visibility=page.subtitle_visibility_trace(reason='caption_settle')
                    settle_ms=(time.monotonic()-settle_started)*1000
                    row=dict(scene=scene,cycle=cycle,rate=rate,wall_s=elapsed,
                        project_delta_ms=page.timeline.playhead_ms-start,
                        ui_p50_ms=statistics.median(values) if values else None,
                        ui_p95_ms=values[int(.95*(len(values)-1))] if values else None,
                        ui_max_ms=max(values,default=0), ui_over_50=sum(v>50 for v in values),
                        mpv_before=before,mpv_after=metrics(controller),
                        visibility=visibility,caption_settle_ms=settle_ms,playback_visibility=list(samples))
                    result['cases'].append(row)
                    (output/'progress.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
                    if cycle==0 and rate==1:
                        controller.screenshot_to_file(output/f'{scene}-mpv.png')
                        _capture(surface,output/f'{scene}-studio.png')
                    page._seek(start_seconds+12); QTest.qWait(100);page._seek(start_seconds+3);QTest.qWait(100)
                    page.video.set_paused(False);QTest.qWait(250);page.video.set_paused(True)
            if cycle==0 and template is None and hasattr(page,'original_text_tools') and os.environ.get('CAPTION_AUDIT_OPEN_ONLY')!='1':
                from PySide6.QtCore import QPoint
                page.video.set_paused(True)
                page.timeline.setFocus()
                ruler=page.timeline
                left=ruler.TRACK_HEADER_WIDTH+30
                right=min(ruler.width()-30,left+300)
                y=max(2,ruler.RULER_HEIGHT//2)
                desired=ruler._x_to_time(right)
                QTest.mousePress(ruler,Qt.LeftButton,pos=QPoint(left,y))
                for x in range(left,right,20):QTest.mouseMove(ruler,QPoint(x,y),delay=15)
                QTest.mouseRelease(ruler,Qt.LeftButton,pos=QPoint(right,y))
                wait(lambda:not page.video._playback_clock.exact_seek_pending and page._playback_buffers_ready())
                result['scrub']={'requested_ms':desired,'timeline_ms':page.timeline.playhead_ms,
                    'video_ms':float(controller.get_property('time-pos') or 0)*1000,
                    'passed':abs(page.timeline.playhead_ms-desired)<100 and not ruler._scrub_drag}
                from ..caption_style.style_resolution import resolve_cue_visual
                from ..timeline.selection_scope import SelectionScope
                from PySide6.QtGui import QTextCursor
                p=page.project
                page.context_drawer.setCurrentIndex(1)
                original=copy.deepcopy(p.cues);styles=copy.deepcopy(p.styles)
                page.select_cue('1');page.style_font_size.setValue(77);page._commit_style_now()
                checks={'single_cue':resolve_cue_visual(p,p.cues[0]).style.font_size==styles[0].font_size
                    and resolve_cue_visual(p,p.cues[1]).style.font_size==77 and p.styles==styles}
                page.undo_stack.undo()
                page.cue_controller.apply_selection_scope(SelectionScope.explicit(['1','4'],'1'))
                page.style_fill_color.setText('#FF3B30');page._style_control_changed()
                checks['noncontiguous']=all((resolve_cue_visual(p,c).style.primary_color=='#FF3B30')==(c.id in ('1','4')) for c in p.cues)
                page.undo_stack.undo();checks['undo']=all(c.appearance_override==old.appearance_override for c,old in zip(p.cues,original))
                page.select_cue('1')
                source_size=resolve_cue_visual(p,p.cues[1]).style.font_size
                page.style_layer.setCurrentIndex(page.style_layer.findData('translation'))
                page.style_font_size.setValue(29);page._commit_style_now()
                from ..caption_style.bilingual_layout import project_display_cues
                pair={c.id:c for c in project_display_cues(p)}
                checks['translation_only']=(resolve_cue_visual(p,p.cues[1]).style.font_size==source_size
                    and resolve_cue_visual(p,pair['1#tr']).style.font_size==29)
                page.style_layer.setCurrentIndex(page.style_layer.findData('group'))
                page.style_position_x.setValue(550);page._commit_style_now()
                pair={c.id:c for c in project_display_cues(p)}
                checks['group_position']=(resolve_cue_visual(p,pair['1']).style.position_x==550
                    and resolve_cue_visual(p,pair['1#tr']).style.position_x==550)
                page._seek(1.5);QTest.qWait(250);_capture(surface,output/'bilingual-layer-controls.png')
                page.style_layer.setCurrentIndex(page.style_layer.findData('original'))
                page.original_text_tools.mode.setCurrentIndex(1)
                page.cue_text.setPlainText('今天**通過最後一關**')
                checks['markdown']=p.cues[1].text=='今天通過最後一關' and bool(p.cues[1].appearance_override.get('text_marks'))
                page.original_text_tools.mode.setCurrentIndex(0)
                if not page.current_cue_section_button.isChecked():
                    QTest.mouseClick(page.current_cue_section_button,Qt.LeftButton)
                scroll=page.context_drawer.widget(1)
                QTest.qWait(250)
                scroll.ensureWidgetVisible(page.cue_text,0,30)
                QTest.qWait(100)
                checks['editor_visible']=not page.cue_text.visibleRegion().isEmpty() and not page.original_text_tools.visibleRegion().isEmpty()
                page.cue_text.setFocus();page._review_mode=True;QTest.keyClicks(page.cue_text,'WASD')
                checks['typing_wasd']='WASD' in page.cue_text.toPlainText() and page.selected_cue_id=='1'
                page._review_mode=False
                edited_at=time.monotonic()
                def edited_ready():
                    prepared=page._prepared_caption('1')
                    revision=page._revision_store.render
                    result['edited_preview_probe']={'body':p.cues[1].text,
                        'prepared':prepared.snapshot.text if prepared else None,
                        'revision_body':next((c.text for c in revision.timeline_cues or revision.cues if c.id=='1'),None),
                        'playhead':page.timeline.playhead_ms,'visual_revision':revision.visual_revision,
                        'tick_geometry':getattr(page,'_caption_tick_geometry',None),'geometry':page._advanced_preview_size()}
                    return prepared is not None and prepared.snapshot.text==p.cues[1].text
                wait(edited_ready)
                QTest.qWait(100)
                checks['edited_preview_body']=page._prepared_caption('1').snapshot.text==p.cues[1].text
                result['edited_preview_prepare_ms']=(time.monotonic()-edited_at)*1000
                wait(lambda:not page._ass_worker_running and any(row['generation']==page._ass_generation for row in page._ass_profile))
                result['edited_ass_ready_ms']=(time.monotonic()-edited_at)*1000
                def edited_pixels_ready():
                    scene_owner=getattr(page,'_caption_scene',None)
                    if scene_owner is not None and scene_owner.active:
                        wanted=page._prepared_caption('1').snapshot_hash
                        return any(row.get('cue_id')=='1' and row.get('snapshot_hash')==wanted
                                   for row in scene_owner.trace()['cue_pixels'])
                    return 'WASD' in page._preview_path.read_text('utf-8-sig')
                wait(edited_pixels_ready)
                checks['edited_pixels_revision']=edited_pixels_ready()
                result['edited_pixels_ready_ms']=(time.monotonic()-edited_at)*1000
                QTest.qWait(200)
                controller.screenshot_to_file(output/'edited-native.png')
                scroll.ensureWidgetVisible(page.cue_text,0,30);QTest.qWait(100)
                _capture(surface,output/'markdown-editor.png')
                page.cue_table.setFocus();page._review_mode=True;page.select_cue('1')
                for key,expected in ((Qt.Key_W,'2'),(Qt.Key_A,'3'),(Qt.Key_S,'2'),(Qt.Key_D,'1')):
                    QTest.keyClick(page.cue_table,key);QTest.qWait(70)
                    checks[f'review_{key.name}']=page.selected_cue_id==expected
                page._review_mode=False
                # 2026-10-25: the panel's own words in other interface languages (CAPTION_AUDIT_LANGS=en,zh-Hant).
                languages=[c for c in os.environ.get('CAPTION_AUDIT_LANGS','').split(',') if c]
                if languages and window is not None:
                    from ..i18n import translate
                    page.context_drawer.setCurrentIndex(1);page.select_cue('1')
                    page.style_layer.setCurrentIndex(page.style_layer.findData('original'))
                    for code in [*languages,'zh']:
                        index=window.language_combo.findData(code)
                        if index<0:
                            checks[f'language_{code}_available']=False;continue
                        window.language_combo.setCurrentIndex(index);QTest.qWait(2500)
                        page._load_style_inspector();QTest.qWait(200)
                        expected_layers=[translate(name,code) for name in ('原文','译文','整组')]
                        layers=[page.style_layer.itemText(i) for i in range(page.style_layer.count())]
                        tools=page.original_text_tools
                        from PySide6.QtWidgets import QToolButton
                        buttons={b.text() for b in tools.findChildren(QToolButton)}
                        summary=page.style_scope_summary.text()
                        wanted_summary=translate('选中的 {count} 条字幕 · {layer}',code).format(
                            count=len(page.style_controller._style_target_ids()),layer=translate('原文',code))
                        result.setdefault('languages',{})[code]=dict(layers=layers,mode=tools.mode.itemText(0),
                            buttons=sorted(buttons),summary=summary,tooltip=tools.mode.toolTip())
                        checks[f'language_{code}']=(layers==expected_layers and tools.mode.itemText(0)==translate('纯文字',code)
                            and summary==wanted_summary
                            and {translate(n,code) for n in ('重点','颜色','清除')}<=buttons
                            and tools.mode.toolTip()==translate('Markdown：**粗体**、*斜体*、==重点==（兔白扩展）；\\ 可转义，`文字` 原样输入。',code))
                        row=[tools.mode,*sorted(tools.findChildren(QToolButton),key=lambda b:b.x())]
                        checks[f'language_{code}_toolbar_fits']=(all(a.geometry().right()<b.geometry().left() for a,b in zip(row,row[1:]))
                            and row[-1].geometry().right()<tools.width())
                        result['languages'][code]['toolbar']=[[w.x(),w.width()] for w in row]+[tools.width()]
                        scroll=page.context_drawer.widget(1);scroll.verticalScrollBar().setValue(0);QTest.qWait(150)
                        _capture(surface,output/f'language-{code}-panel.png')
                        scroll.ensureWidgetVisible(page.cue_text,0,30);QTest.qWait(150)
                        _capture(surface,output/f'language-{code}-text-tools.png')
                result['ui_checks']=checks
                p.cues=original;p.styles=styles;page.undo_stack.clear();page._changed()
                scroll.verticalScrollBar().setValue(0)
            page.project_controller.save()
            page.undo_stack.setClean()
            if window is None:
                page.close_page();page.close();page.deleteLater();page=None
            else:
                window._return_to_settings()
            QTest.qWait(800)
        result['ui_passed']=all(result.get('ui_checks',{}).values())
        result['visibility_passed']=all(visible_matches(c['visibility'],c['scene']) for c in result['cases'])
        result['passed']=result['ui_passed'] and result['visibility_passed'] and result.get('scrub',{}).get('passed',True)
    except Exception:
        result['error']=traceback.format_exc()
        if page is not None:
            result['failure_state']={'project': str(getattr(page.project,'media',None)),
                'readiness': repr(vars(page._readiness)),
                'windows':[(type(w).__name__,w.windowTitle(),w.isVisible()) for w in app.topLevelWidgets()]}
            _capture(page,output/'failure.png')
    finally:
        timer.stop()
        app.removeEventFilter(origins)
        SceneRasterizer.frame=original_frame
        if profiles:
            import pstats,io
            for index,(key,profile,wall) in enumerate(profiles):
                report=io.StringIO();pstats.Stats(profile,stream=report).sort_stats('cumtime').print_stats(18)
                (output/f'profile-{index}-{key[0]}-{key[1]}.txt').write_text(f'wall_s={wall}\n'+report.getvalue(),encoding='utf8')
        if page is not None:
            page.undo_stack.setClean()
            if window is None: page.close_page();page.close();QTest.qWait(500)
        if hook: hook.close()
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return 0 if result['passed'] else 1


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    def execute():
        code=run(output,window=window,media=os.environ.get('CAPTION_AUDIT_MEDIA') or None)
        window.result_exit_code=code
        def stopped():
            path=output/'result.json';result=json.loads(path.read_text('utf8'))
            result['gui_shutdown']=True;path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(100,execute)
