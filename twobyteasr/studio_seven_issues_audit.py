"""Opt-in real-window regression of the seven October editing issues."""
import copy
import json
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .asr_source_evidence import cue_source_hypotheses
    from .build_identity import load_build_identity
    from .studio_project import load_project
    spec=json.loads((output/'input.json').read_text('utf-8'))
    result=dict(checks=[],events=[],identity=load_build_identity().to_dict(),passed=False)
    page=window.studio_page
    event_file=(output/'operations.jsonl').open('w',encoding='utf-8')

    def event(kind, **values):
        row=dict(t=time.monotonic(),kind=kind,**values)
        event_file.write(json.dumps(row,ensure_ascii=False,default=str)+'\n');event_file.flush()

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name,passed=bool(ok),detail=detail))
        event('check',**result['checks'][-1])

    def capture(name):
        _capture(window,output/(name+'.png'))
        event('capture',name=name)

    def observe():
        video=page.video;clock=video.playback_position_snapshot();c=video.controller
        return dict(project_ms=page.timeline.playhead_ms,clock_ms=clock.presentation_media_ms,
            paused=video._paused,exact=clock.exact_seek_pending,clip=page._active_video_preview_clip_id,
            key=page._active_video_preview_key,mode=page._playback_mode,generation=clock.playback_generation,
            source=c.observed_property('path',None),source_ms=(c.observed_property('time-pos',0) or 0)*1000,
            clock_only=video._clock_only,media_attached=video._media_attached,eof=video.at_eof,
            mpv_pause=c.observed_property('pause',None),audio=page.audio_engine.clock_observation())

    def seek(ms):
        b=page.timecode_input;b.setFocus();QTest.keyClick(b,Qt.Key_A,Qt.ControlModifier)
        s,m=divmod(ms,1000);mins,s=divmod(s,60);h,mins=divmod(mins,60)
        QTest.keyClicks(b,f'{h:02d}:{mins:02d}:{s:02d}.{m:03d}');QTest.keyClick(b,Qt.Key_Return)
        event('timecode_seek',requested_ms=ms)

    def ready():
        return page.project is not None and page._readiness.ready and not page._readiness.active and page.video.controller

    def settled(ms):
        v=observe()
        return not v['exact'] and abs(v['project_ms']-ms)<70 and v['paused']

    def point(t,ms,kind='video',speaker=None):
        rect=t._video_track_rect('V1') if kind=='video' else t._track_layout()[0][speaker]
        return QPoint(round(t._time_to_x(ms)),round(rect.center().y()))

    def drag(t,a,b,modifier=Qt.NoModifier):
        event('drag_press',a=(a.x(),a.y()),b=(b.x(),b.y()),modifier=str(modifier))
        if modifier:QTest.keyPress(t,Qt.Key_Control)
        QTest.mousePress(t,Qt.LeftButton,modifier,a)
        for i in range(1,9):
            QTest.mouseMove(t,a+(b-a)*i/8,15)
        event('drag_preview',intervals={k:vars(v) for k,v in t._timing_preview.items()},group=t._group_drag)
        capture('gesture-'+str(len(result['checks'])))
        QTest.mouseRelease(t,Qt.LeftButton,modifier,b)
        if modifier:QTest.keyRelease(t,Qt.Key_Control)
        event('drag_release')

    def geometry():
        import ctypes
        from ctypes import wintypes
        u=ctypes.windll.user32;rect=wintypes.RECT();u.GetWindowRect(wintypes.HWND(int(window.winId())),ctypes.byref(rect))
        return dict(state=int(window.windowState().value),maximized=window.isMaximized(),fullscreen=window.isFullScreen(),
            geometry=window.geometry().getRect(),frame=window.frameGeometry().getRect(),
            native=(rect.left,rect.top,rect.right,rect.bottom),margins=tuple(getattr(window.contentsMargins(),k)() for k in ['left','top','right','bottom']),
            available=window.screen().availableGeometry().getRect(),screen=window.screen().geometry().getRect(),
            video=page.video.geometry().getRect(),dpr=window.devicePixelRatioF())

    def steps():
        window.showMaximized()
        window.open_studio_project(spec['project'],mode='edit',source='seven_issues_audit')
        yield ready;yield .7
        if not page.video._paused:QTest.mouseClick(page.play_button,Qt.LeftButton);yield .3
        check('current project is the preserved 194 cue edit',len(page.project.cues)==194,len(page.project.cues))
        cue=page.project.cues[0];hyp=cue_source_hypotheses(page.project,cue)
        check('3 evidence roles survive edited project reopening',len({x['source'] for x in hyp})>=3,list(hyp))
        # Review through the existing actual button, if present, then capture.
        table=page.cue_table
        QTest.mouseClick(table.viewport(),Qt.LeftButton,Qt.NoModifier,table.visualRect(table.model().index(0,0)).center())
        yield .5
        button=getattr(page,'review_entry_button',None)
        if button is not None:
            QTest.mouseClick(button,Qt.LeftButton)
            yield .6
        check('review button enters actual review workspace',page._review_mode)
        from .studio_qc import model_evidence, review_candidates
        from .studio_cards import ReviewCandidateCard
        evidence = model_evidence(page.project, cue)
        cards = page.findChildren(ReviewCandidateCard)
        check('mixed source context never becomes an adoptable neighbor suffix',
            all(item.context_only for item in evidence if '我会了' in item.text)
            and all(not card.isEnabled() for card in cards if card._candidate.context_only),
            [dict(text=item.text, context_only=item.context_only) for item in evidence])
        capture('current-194-review')
        if button is not None:
            QTest.mouseClick(button,Qt.LeftButton)
            yield .3
        result['grouping_node']=spec.get('grouping_node')
        check('grouping node separately traced',bool(spec.get('grouping_node')),spec.get('grouping_node'))
        # Selection and gestures use the copied current project and real widget events.
        t=page.timeline;t.set_visible_window(0,10000)
        QTest.mouseClick(t,Qt.LeftButton,Qt.NoModifier,QPoint(t.TRACK_HEADER_WIDTH+100,10));yield .15
        QTest.keyClick(t,Qt.Key_A,Qt.ControlModifier)
        original=[(c.id,c.timeline_in_ms,c.timeline_out_ms) for tr in page.project.video_tracks for c in tr.clips]
        event('select_all',selected=t.clip_selection().count)
        # Move all towards the fixed project playhead, just inside snap distance.
        page.video.set_paused(True);t.set_playhead(1000)
        a=point(t,2200);b=QPoint(a.x()+round(t._time_to_x(1000)-t._time_to_x(0))+3,a.y())
        drag(t,a,b);yield .15
        after=[(c.id,c.timeline_in_ms,c.timeline_out_ms) for tr in page.project.video_tracks for c in tr.clips]
        check('Ctrl+A group snaps exactly to fixed playhead',after[0][1]==1000,dict(before=original,after=after))
        QTest.keyClick(t,Qt.Key_Z,Qt.ControlModifier);yield .1
        # First adjacent pair on one speaker: Ctrl seam must change both edges.
        pairs=[(a,b) for a in t._cues_by_start for b in t._cues_by_start
            if a.id!=b.id and a.speaker_id==b.speaker_id and a.end_ms==b.start_ms
            and a.end_ms-a.start_ms>150 and b.end_ms-b.start_ms>150]
        if pairs:
            left,right=pairs[0];boundary=left.end_ms
            seek(boundary);yield lambda:settled(boundary)
            t.set_visible_window(max(0,left.start_ms-200),max(3000,right.end_ms-left.start_ms+400))
            before=(left.start_ms,left.end_ms,right.start_ms,right.end_ms)
            a=point(t,boundary,'subtitle',left.speaker_id);b=QPoint(a.x()+25,a.y())
            drag(t,a,b,Qt.ControlModifier);yield .15
            saved={c.id:c for c in page.project.cues};l,r=saved[left.id],saved[right.id]
            check('Ctrl seam rolls both edges and holds outer bounds',l.end_ms==r.start_ms and l.end_ms!=boundary
                and (l.start_ms,r.end_ms)==(before[0],before[3]),dict(before=before,after=(l.start_ms,l.end_ms,r.start_ms,r.end_ms)))
            QTest.keyClick(t,Qt.Key_Z,Qt.ControlModifier)
        else:check('Ctrl seam fixture exists',False)
        # Windows system commands exercise the native minimize/restore event path.
        import ctypes
        from ctypes import wintypes
        u=ctypes.windll.user32;hwnd=wintypes.HWND(int(window.winId()))
        for name in ['normal','maximized','fullscreen']:
            if name=='normal':window.showNormal();window.resize(1440,900);window.move(80,60)
            elif name=='maximized':window.showMaximized()
            else:window.showFullScreen()
            yield .25
            before=geometry();event('window_before',mode=name,geometry=before)
            u.PostMessageW(hwnd,0x112,0xF020,0);yield .25
            event('window_minimized',mode=name,geometry=geometry())
            u.PostMessageW(hwnd,0x112,0xF120,0);yield .5
            after=geometry();event('window_restored',mode=name,geometry=after)
            entered = (before['maximized'] if name=='maximized' else before['fullscreen'] if name=='fullscreen' else before['state']==0)
            check('native minimize restore '+name,entered and before['state']==after['state'] and before['geometry']==after['geometry'],dict(before=before,after=after))
            capture('restore-'+name)
        window.showMaximized()
        window.open_studio_project(spec['gap_project'],mode='edit',source='seven_issues_gap_audit')
        yield ready;yield .7
        if not page.video._paused:QTest.mouseClick(page.play_button,Qt.LeftButton);yield .3
        t=page.timeline;t.set_visible_window(2000,3400);yield .2
        a=point(t,spec['gap_start']+(spec['gap_end']-spec['gap_start'])//2)
        QTest.mouseClick(t,Qt.LeftButton,Qt.NoModifier,a);yield .1
        check('tiny real gap can be selected without trimming',t.selected_gap==('V1',spec['gap_start'],spec['gap_end']),t.selected_gap)
        capture('tiny-gap-hit')
        from .studio_edit_sequence import timeline_duration_ms
        def geometry_data():
            return dict(video=[(c.id,c.timeline_in_ms,c.timeline_out_ms,c.source_in_ms,c.source_out_ms) for tr in page.project.video_tracks for c in tr.clips],
                audio=[(c.id,c.timeline_in_ms,c.timeline_out_ms,c.source_in_ms,c.source_out_ms) for tr in page.project.audio_tracks for c in tr.clips],
                cues=[(c.id,c.start_ms,c.end_ms,c.text) for c in page.project.cues])
        before=geometry_data();duration=timeline_duration_ms(page.project)
        QTest.keyClick(t,Qt.Key_Delete);yield .3
        after=geometry_data()
        check('Delete closes exactly 23ms in video audio and captions',timeline_duration_ms(page.project)==duration-23
            and all(b[1]-a[1]==23 and b[2]-a[2]==23 and b[3:]==a[3:] for b,a in zip(before['cues'],after['cues'])))
        QTest.keyClick(t,Qt.Key_Z,Qt.ControlModifier);yield .2
        check('gap deletion one undo restores all geometry',geometry_data()==before)
        QTest.keyClick(t,Qt.Key_Z,Qt.ControlModifier|Qt.ShiftModifier);yield .2
        check('gap deletion redo restores closed geometry',geometry_data()==after)
        QTest.keyClick(t,Qt.Key_Z,Qt.ControlModifier);yield .2
        # Playback crosses the retained 3.389s cut. Capture every tick, including transients.
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QContextMenuEvent
        from PySide6.QtWidgets import QMenu
        t.set_visible_window(2000,3400)
        gap_point=point(t,3400)
        menu_clicked=[]
        def choose_gap_action():
            menu=QApplication.activePopupWidget()
            if isinstance(menu,QMenu):
                action=next((x for x in menu.actions() if x.text()=='波纹删除空隙'),None)
                if action:
                    menu_clicked.append(action.text())
                    QTest.mouseClick(menu,Qt.LeftButton,Qt.NoModifier,menu.actionGeometry(action).center())
                else:menu.close()
        QTimer.singleShot(200,choose_gap_action)
        context=QContextMenuEvent(QContextMenuEvent.Mouse,gap_point,t.mapToGlobal(gap_point))
        QApplication.sendEvent(t,context)
        yield .3
        check('gap context menu closes the same precise interval',bool(menu_clicked) and geometry_data()==after)
        QTest.keyClick(t,Qt.Key_Z,Qt.ControlModifier);yield .2
        check('gap menu undo restores original geometry',geometry_data()==before)
        seek(spec['gap_start']-450);yield lambda:settled(spec['gap_start']-450)
        samples=[]
        sampler=QTimer(window);sampler.setInterval(10)
        def sample():
            v=observe();samples.append(v);event('playback_sample',**v)
        sampler.timeout.connect(sample);sampler.start()
        QTest.mouseClick(page.play_button,Qt.LeftButton);event('play_clicked')
        yield 5.
        if not page.video._paused:QTest.mouseClick(page.play_button,Qt.LeftButton)
        sampler.stop()
        check('gap crossing never writes source clock as project tail',bool(samples) and max(x['project_ms'] for x in samples)<15000,
              dict(max_project_ms=max((x['project_ms'] for x in samples),default=-1),final=observe()))
        capture('gap-after-play')
        for variant in spec.get('gap_variants',[]):
            window.open_studio_project(variant['path'],mode='edit',source='seven_issues_gap_matrix')
            yield ready;yield .4
            if not page.video._paused:QTest.mouseClick(page.play_button,Qt.LeftButton);yield .15
            a,b=variant['start'],variant['end'];size=variant['duration']
            t=page.timeline;t.set_visible_window(2000,max(5000,size+2000))
            for method,requested in [('before',a-400),('ruler',a+size//2),('backward',a-150)]:
                if method=='backward':
                    seek(b+800);yield lambda target=b+800:settled(target)
                if method=='ruler':
                    QTest.mouseClick(t,Qt.LeftButton,Qt.NoModifier,QPoint(round(t._time_to_x(requested)),10))
                    event('ruler_seek',gap_ms=size,requested_ms=requested)
                else:seek(requested)
                yield lambda target=requested:settled(target)
                snapshots=[]
                watch=QTimer(window);watch.setInterval(10)
                def record():
                    value=observe();snapshots.append(value);event('gap_matrix_sample',gap_ms=size,method=method,**value)
                watch.timeout.connect(record);watch.start()
                QTest.mouseClick(page.play_button,Qt.LeftButton)
                seconds=max(1.5,size/1000+1.)
                yield seconds
                if not page.video._paused:QTest.mouseClick(page.play_button,Qt.LeftButton)
                watch.stop()
                values=[v['project_ms'] for v in snapshots]
                check(f'{size}ms gap {method} progresses without tail jump',bool(values) and max(values)<b+6000
                    and values[-1]>b+100,dict(first=values[0] if values else None,last=values[-1] if values else None,max=max(values,default=0)))
                check(f'{size}ms gap {method} detaches media while clock-only',all(not v['media_attached'] for v in snapshots if v['clock_only']))
            capture(f'gap-matrix-{size}ms')
        result['passed']=all(x['passed'] for x in result['checks'])

    iterator=steps();state=dict(wait=None,deadline=0.,until=0.)
    timer=QTimer(window);timer.setInterval(40)
    def save():
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),'utf-8')
    def finish():
        timer.stop();save();event_file.close();page.project_path=None
        window.close();QTimer.singleShot(500,QApplication.instance().quit)
    def tick():
        if state.get('ticking'):return
        state['ticking']=True
        try:
            if state['wait'] is not None:
                if state['wait']():state['wait']=None
                elif time.monotonic()>state['deadline']:raise TimeoutError('Real GUI condition did not settle')
                else:return
            if time.monotonic()<state['until']:return
            value=next(iterator)
            if callable(value):state.update(wait=value,deadline=time.monotonic()+45)
            else:state['until']=time.monotonic()+float(value or 0)
        except StopIteration:finish()
        except BaseException:
            result['error']=traceback.format_exc()
            try:capture('failure')
            except Exception:pass
            finish()
        finally:
            state['ticking']=False
    def shutdown():
        result['gui_shutdown']=True;save()
    QApplication.instance().aboutToQuit.connect(shutdown)
    timer.timeout.connect(tick);timer.start()
