"""In-process acceptance through normal Studio controls, source and frozen."""
import copy,json,time,traceback
from pathlib import Path


def start(window,out):
    from PySide6.QtCore import Qt,QTimer,QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QLineEdit,QPushButton
    from .build_identity import load_build_identity
    from .studio_edit_sequence import timeline_duration_ms,sequence_of
    from .studio_runtime_state import state_for
    from .studio_track_header import button_rect
    from .studio_analysis_request import begin_request
    out=Path(out);page=window.studio_page;started=time.monotonic()
    report={'passed':False,'checks':{},'identity':load_build_identity().to_dict(),'samples':[],'provider_calls':0}
    config=json.loads((out/'config.json').read_text('utf8'))

    def pump(seconds=.1):
        end=time.monotonic()+seconds
        while time.monotonic()<end:QApplication.processEvents();time.sleep(.003)

    def wait(predicate,seconds=90):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if predicate():return
            pump(.025)
        raise TimeoutError('multisource GUI wait')

    def check(label,value):
        report['checks'][label]=bool(value)
        (out/'progress.json').write_text(json.dumps(report,ensure_ascii=False,default=str),'utf8')
        if not value:raise AssertionError(label)

    def activate():
        QApplication.setActiveWindow(window);window.activateWindow();page.timeline.setFocus();pump(.03)

    def key(code,mod=Qt.NoModifier):
        activate();QTest.keyClick(window.windowHandle(),code,mod);pump(.13)

    def clip(lane,index=0):return next(t for t in page.project.video_tracks if t.id==lane).clips[index]
    def spans(lane):return [(c.timeline_in_ms,c.timeline_out_ms,c.source_in_ms,c.source_out_ms) for t in page.project.video_tracks if t.id==lane for c in t.clips]
    def point(lane,ms):
        return page.timeline.mapTo(window,QPoint(round(page.timeline._time_to_x(ms)),round(page.timeline._video_track_rect(lane).center().y())))
    def click(lane,ms):
        activate();QTest.mouseClick(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,point(lane,ms));pump(.15)
    def header(lane,action):
        activate();rect=button_rect('video',action,page.timeline._video_track_rect(lane))
        QTest.mouseClick(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,page.timeline.mapTo(window,rect.center().toPoint()));pump(.2)
    def capture(name):
        window.grab().save(str(out/(name+'-ui.png')))
        if page.video.controller:page.video.controller.screenshot_to_file(out/(name+'-native.png'),mode='window')
    def opened(name):
        page.undo_stack.setClean();page.show_project_hub(skip_dirty_guard=True)
        pump(.2)
        done=[];window.open_studio_project(out/(name+'.2byteproj'),on_ready=lambda *_:done.append(True))
        wait(lambda:bool(done) and page.project is not None and page._readiness.ready)
        page.video.set_paused(True);page._set_volume(0)
        page.follow_playhead_toggle.setChecked(False);page.timeline.set_visible_window(0,35000)
        page.timeline.set_tool_mode('selection');pump(.2)
    def seek(ms):
        page._seek(ms/1000);wait(lambda:not page.video._playback_clock.exact_seek_pending,20);pump(.15)
    def none_selected():
        key(Qt.Key_Escape)
        page.timeline.selected_segment_ids.clear();page.timeline.selected_segment_id=''
        page.timeline.selected_video_clip_id='';page.timeline.selected_video_track_id=''
    def play_until(ms,timeout):
        page.video.set_paused(False)
        end=time.monotonic()+timeout
        reported=time.monotonic()
        last_position=page.timeline.playhead_ms;advanced_at=time.monotonic()
        while page.timeline.playhead_ms<ms and time.monotonic()<end:
            pump(.1)
            report['samples'].append({'project_ms':page.timeline.playhead_ms,'paused':page.video._paused,
                'eof':page.video.at_eof,'source':page._active_video_preview_source_path,
                'buffered':page.video._buffered_play_pending,'startup':page.video._startup_state,
                'tooltip':page.video.toolTip()})
            if abs(page.timeline.playhead_ms-last_position)>100:
                last_position=page.timeline.playhead_ms;advanced_at=time.monotonic()
            if time.monotonic()-advanced_at>20:
                report['stalled_audio']=page.audio_engine.telemetry_snapshot()
                report['stalled_request']=page.audio_engine._last_payload
                report['stalled_ready']=page._playback_buffers_ready()
                raise TimeoutError('Playback did not advance for 20 seconds')
            if time.monotonic()-reported>10:
                (out/'transport-progress.json').write_text(json.dumps(report['samples'][-1],ensure_ascii=False),'utf8')
                reported=time.monotonic()
        check(f'play reaches {ms} ms',page.timeline.playhead_ms>=ms)
    def links(label):
        for t in page.project.video_tracks:
            for c in t.clips:
                sounds=[a for track in page.project.audio_tracks for a in track.clips if a.linked_video_clip_id==c.id]
                check(label+' one audio '+c.id,len(sounds)==1 and all(getattr(sounds[0],k)==getattr(c,k) for k in
                    ('source_in_ms','source_out_ms','timeline_in_ms','timeline_out_ms')))
        check(label+' subscribers healthy',not state_for(page.project).subscriber_errors)

    def export(name, region=None):
        QTest.mouseClick(page.studio_render_button,Qt.LeftButton);pump(.2)
        wait(lambda:page.export_workspace is not None and page.export_workspace.isVisible(),10)
        ui=page.export_workspace
        ui.directory.setText(str(out));ui.filename.setText(name)
        for widget,value in ((ui.extension,'mp4'),(ui.resolution,(-1,-1)),(ui.fps,-1.0),
                             (ui.encoder_preset,'fastest'),(ui.audio,'aac'),(ui.export_range,'all')):
            index=next((i for i in range(widget.count()) if
                (tuple(widget.itemData(i)) if isinstance(value,tuple) else widget.itemData(i))==value),-1)
            if index<0:raise ValueError(f'Export option missing {value}')
            widget.setCurrentIndex(index)
        ui.custom_resolution_width.setValue(320);ui.custom_resolution_height.setValue(180)
        ui.custom_fps.setValue(10)
        if region:ui.project_range_bar.apply(region)
        ui._target_changed();good=[];errors=[]
        ui.render_succeeded.connect(good.append);ui.render_failed.connect(errors.append)
        ui.preview_scroll.ensureWidgetVisible(ui.export_button);pump(.1)
        QTest.mouseClick(ui.export_button,Qt.LeftButton)
        wait(lambda:bool(good or errors),500)
        check(name+' production export '+repr(errors),bool(good) and not errors)
        ui.grab().save(str(out/(name+'-export.png')))
        report.setdefault('exports',[]).append({'path':str(ui._last_job.output_path),
            'receipt':dict(ui._last_job.completion_metadata)})
        page._close_export_workspace();pump(.2)

    def run_core():
        opened('two')
        header('V2','locked')
        check('V2 header lock committed',page.project.video_tracks[1].locked)
        before=copy.deepcopy(page.project.video_tracks)
        click('V2',5000);key(Qt.Key_Delete)
        check('locked V2 blank Delete unchanged',page.project.video_tracks==before)
        check('locked blank not selected',page.timeline.selected_gap is None)
        click('V2',16000);key(Qt.Key_Delete)
        check('locked V2 clip Delete unchanged',page.project.video_tracks==before)
        header('V2','enabled')
        check('locked V2 visibility cannot mutate',page.project.video_tracks==before)
        capture('locked')
        header('V2','locked')
        click('V2',5000);key(Qt.Key_Delete)
        check('unlocked V2 gap closes',clip('V2').timeline_in_ms==0)
        key(Qt.Key_Z,Qt.ControlModifier)
        check('gap undo restores offset',clip('V2').timeline_in_ms==10000)
        opened('overlap');none_selected();seek(7500)
        key(Qt.Key_K,Qt.ControlModifier)
        check('no selection Ctrl+K both tracks',len(spans('V1'))==len(spans('V2'))==2)
        links('razor');key(Qt.Key_Z,Qt.ControlModifier)
        none_selected();seek(7500);key(Qt.Key_Q)
        check('shared Q V1 source content',spans('V1')==[(0,5000,0,5000),(5000,7500,7500,10000)])
        check('shared Q V2 source content',spans('V2')==[(5000,17500,2500,15000)])
        key(Qt.Key_Z,Qt.ControlModifier);none_selected();seek(7500);key(Qt.Key_W)
        check('shared W both tracks source content',spans('V1')==[(0,7500,0,7500)] and spans('V2')==[(5000,7500,0,2500),(7500,17500,5000,15000)])
        key(Qt.Key_Z,Qt.ControlModifier)
        click('V1',2000);seek(15000);key(Qt.Key_K,Qt.ControlModifier)
        check('stale V1 selection cuts only V2 at playhead',len(spans('V1'))==1 and len(spans('V2'))==2)
        key(Qt.Key_Z,Qt.ControlModifier)
        editor=QLineEdit(page);editor.setGeometry(300,140,200,40);editor.show();editor.setFocus();pump(.1)
        graph=copy.deepcopy(page.project.video_tracks)
        QTest.keyClicks(editor,'qw');QTest.keyClick(editor,Qt.Key_K,Qt.ControlModifier);pump(.1)
        check('text input consumes Q W Ctrl K',editor.text()=='qw' and page.project.video_tracks==graph)
        editor.close();editor.deleteLater()
        opened('two');activate();a,b=point('V2',17000),point('V1',17000)
        QTest.mousePress(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,a)
        for i in range(1,7):QTest.mouseMove(window.windowHandle(),a+(b-a)*i/6,20);pump(.03)
        QTest.mouseRelease(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,b);pump(.3)
        check('mouse V2 enters V1 as second source',len(spans('V1'))==2 and not spans('V2'))
        check('cross lane source range preserved',spans('V1')[1]==(10000,25000,0,15000))
        links('moved');capture('same-lane')
        committed=copy.deepcopy(page.project.video_tracks);page.save();pump(.2);opened('two')
        check('save hub reopen retains multisource',page.project.video_tracks==committed)
        # I/O remains an export selection, not an implicit playback region.
        sequence_of(page.project).in_point_ms=1000;sequence_of(page.project).out_point_ms=2000
        seek(0);play_until(12000,25);capture('second-source-playing')
        page.video.set_paused(True);pump(.25);paused=page.timeline.playhead_ms
        page._toggle_playback();pump(.5)
        check('midway resume remains in second source',page.timeline.playhead_ms>=paused and page.timeline.playhead_ms>10000)
        play_until(25000,20);pump(.3)
        check('project end pauses without loop',page.video._paused and page.video.at_eof and page.timeline.playhead_ms==25000)
        page._toggle_playback();pump(.7)
        check('replay begins at project start',0<=page.timeline.playhead_ms<4000)
        page.video.set_paused(True)
        opened('gap');seek(9000);play_until(13500,12)
        check('cross track and intentional gap continue',page._active_video_preview_track_id=='V2' and not page.video._paused)
        page.video.set_paused(True);seek(22000);play_until(23000,6)
        check('manual seek starts inside V2',page.timeline.playhead_ms>=23000)
        page.video.set_paused(True)
        opened('three');seek(9000);play_until(27000,28)
        check('three sources on V1 play to final source',page._active_video_preview_source_path.endswith('third.mp4'))
        page.video.set_paused(True);seek(29000);play_until(30000,6);page.video.set_paused(True)
        export('three-source-export')

    def run_held_preview():
        from .audio_graph import capture_audio_graph,preview_audio_layers
        opened('deep');t=page.timeline
        page.workspace_splitter.setSizes([280,520]);pump(.2)
        t.set_visible_window(0,20000)
        b_id=clip('V2').id
        wait(lambda:all(a.asset_id in t.waveform_caches for a in page.project.media_pool),90)
        source_graph=copy.deepcopy(page.project.video_tracks)
        source_audio=copy.deepcopy(page.project.audio_tracks)
        count=page.undo_stack.count()
        activate();a,b=point('V2',17000),point('V1',12000)
        drawn=[];original_envelope=t._waveform_envelope
        def record(cache,sin,sout,pixels,left,right,rect):
            drawn.append({'source':cache.metadata.source_path,'source_in':sin,'source_out':sout,
                          'left':left,'right':right,'y':rect.center().y()})
            return original_envelope(cache,sin,sout,pixels,left,right,rect)
        t._waveform_envelope=record
        try:
            QTest.mousePress(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,a)
            for i in range(1,13):
                QTest.mouseMove(window.windowHandle(),a+(b-a)*i/12,10);pump(.02)
            check('held actual left mouse button',bool(QApplication.mouseButtons() & Qt.LeftButton))
            check('held drag active and valid',bool(t._clip_drag and t._clip_drag.get('snapshot') and not t._clip_drag.get('invalid')))
            snapshot=t._clip_drag['snapshot'];v=snapshot[0][0].clips[1];sound=snapshot[1][0].clips[1]
            check('held target V1 and A1 same mapping',v.id==b_id and
                (v.timeline_in_ms,v.timeline_out_ms,v.source_in_ms,v.source_out_ms)==(10000,15000,100000,105000)
                and sound.linked_video_clip_id==b_id and sound.timeline_in_ms==10000 and sound.source_in_ms==100000)
            # Keep drawing records from the move events. A plain repaint may
            # legitimately reuse the already rasterized, correctly moved wave.
            t.repaint();pump(.05);capture('held-cross-track')
            report['held_waveform_draws']=drawn[:]
            report['held_geometry']={'timeline':str(t.geometry()),'A1':str(t._audio_track_rects()['A1']),
                'visible':str(t.visibleRegion().boundingRect()),'view_start':t.visible_start_ms,'view_duration':t.visible_duration_ms}
            report['held_cache_sources']={key:cache.metadata.source_path for key,cache in t.waveform_caches.items()}
            report['held_asset_sources']={a.asset_id:a.canonical_source for a in page.project.media_pool}
            check('held real source peaks drawn on A1 at 10 seconds',any(x['source'].endswith('deep-b.mp4')
                and x['source_in']==100000 and x['source_out']==105000 and abs(x['left']-t._time_to_x(10000))<1
                and x['y']==t._audio_track_rects()['A1'].center().y() for x in drawn))
            check('held project and undo untouched',page.project.video_tracks==source_graph and page.project.audio_tracks==source_audio
                  and page.undo_stack.count()==count)
            report['held_waveform_draws']=drawn[:];report['held_update_ms']=t._clip_drag['update_ms'][:]
            capture('held-cross-track')
            QTest.mouseRelease(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,b);pump(.3)
        finally:
            t._waveform_envelope=original_envelope
        check('release commits one atomic group',page.undo_stack.count()==count+1 and len(spans('V1'))==2 and not spans('V2'))
        links('deep move');key(Qt.Key_Z,Qt.ControlModifier)
        check('single undo restores V and A',page.project.video_tracks==source_graph and page.project.audio_tracks==source_audio)
        key(Qt.Key_Y,Qt.ControlModifier)
        layers=preview_audio_layers(capture_audio_graph(page.project),12000)
        check('12 seconds maps audio B102 exactly',len(layers)==1 and layers[0]['source_ms']==102000 and layers[0]['source_path'].endswith('deep-b.mp4'))
        committed=copy.deepcopy(page.project.video_tracks);page.save();pump(.2);opened('deep')
        check('deep save reopen retains source and track',page.project.video_tracks==committed)
        seek(12000);capture('deep-b-102')
        check('preview source B at project 12',page._active_video_preview_source_path.endswith('deep-b.mp4'))
        seek(9000);play_until(14000,12);page.video.set_paused(True)
        check('continuous A to B source handoff',page._active_video_preview_source_path.endswith('deep-b.mp4'))
        seek(13000);play_until(15000,6);pump(.2)
        check('deep graph end pauses at 15 seconds',page.video._paused and page.timeline.playhead_ms==15000)
        export('deep-source-export')
        t.set_visible_window(0,15000);activate()
        a,b=point('V1',12000),point('V2',12000)
        QTest.mousePress(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,a)
        QTest.mouseMove(window.windowHandle(),b,20);pump(.05)
        check('reverse held V2 A2 preview',bool(t._clip_drag and t._clip_drag.get('snapshot')
             and len(t._clip_drag['snapshot'][0][1].clips)==1 and len(t._clip_drag['snapshot'][1][1].clips)==1))
        capture('held-reverse-track');QTest.mouseRelease(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,b);pump(.2)
        check('reverse move committed',len(spans('V1'))==len(spans('V2'))==1)
        seek(12000);key(Qt.Key_K,Qt.ControlModifier)
        check('moved source still independently splits',spans('V2')==[(10000,12000,100000,102000),(12000,15000,102000,105000)])
        key(Qt.Key_Z,Qt.ControlModifier)
        original=copy.deepcopy(page.project.video_tracks);count=page.undo_stack.count()
        a,b=point('V2',12000),point('V2',13000)
        QTest.mousePress(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,a)
        QTest.mouseMove(window.windowHandle(),b,20);pump(.05)
        snapshot=t._clip_drag['snapshot']
        check('same lane held audio follows',snapshot[0][1].clips[0].timeline_in_ms==snapshot[1][1].clips[0].timeline_in_ms
              and snapshot[0][1].clips[0].timeline_in_ms!=10000)
        capture('held-same-track');key(Qt.Key_Escape)
        QTest.mouseRelease(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,b);pump(.1)
        check('Escape cancels all with no history',not t._clip_drag and page.project.video_tracks==original and page.undo_stack.count()==count)
        t.set_visible_window(0,20000);activate()
        a=point('V2',12000)
        QTest.mousePress(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,a)
        for at in (12030,11975,12020):
            QTest.mouseMove(window.windowHandle(),point('V1',at),15);pump(.03)
            s=t._clip_drag['snapshot']
            check('continuous snap '+str(at),s[0][0].clips[1].timeline_in_ms==s[1][0].clips[1].timeline_in_ms==10000)
        key(Qt.Key_Escape);QTest.mouseRelease(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,point('V1',12000))
        t.set_visible_window(0,15000);a=point('V2',12000)
        edge=t.mapTo(window,QPoint(round(t._content_right()-3),round(t._video_track_rect('V2').center().y())))
        QTest.mousePress(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,a)
        QTest.mouseMove(window.windowHandle(),edge,15);pump(.4)
        s=t._clip_drag['snapshot']
        check('held edge timer scroll keeps audio mapping',t.visible_start_ms>0 and
              s[0][1].clips[0].timeline_in_ms==s[1][1].clips[0].timeline_in_ms)
        capture('held-edge-scroll');key(Qt.Key_Escape)
        QTest.mouseRelease(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,edge);pump(.05)
        check('edge cancel no committed mutation',page.project.video_tracks==original and page.undo_stack.count()==count)

    def run_real():
        if (out/'user.2byteproj').exists():
            opened('user');capture('real-project')
            report['real_duration_ms']=timeline_duration_ms(page.project)
            if config.get('long_play'):
                seek(0);play_until(timeline_duration_ms(page.project),timeline_duration_ms(page.project)/1000+90)
                check('full real edited project reaches end',page.video._paused)
            if config.get('detect') or (out/'analysis.json').exists():
                panel=page.highlight_panel
                if config.get('detect'):
                    page.context_drawer.setCurrentIndex(page.highlight_tab_index)
                    panel.config_toggle.setChecked(True);pump(.2)
                    scroll=page.context_drawer.widget(page.highlight_tab_index)
                    scroll.ensureWidgetVisible(panel.autocut_detect_button);pump(.2)
                    before=copy.deepcopy(page.project.video_tracks)
                    QTest.mouseClick(panel.autocut_detect_button,Qt.LeftButton);pump(.2)
                    QTest.mouseClick(panel.autocut_cancel_button,Qt.LeftButton)
                    wait(lambda:page._autocut_worker is None,30);pump(.2)
                    check('detect cancel unchanged',page.project.video_tracks==before and not page._autocut_preview_ranges)
                    QTest.mouseClick(panel.autocut_detect_button,Qt.LeftButton)
                    wait(lambda:page._autocut_worker is None,180);pump(.5)
                    check('real detector offers candidates',bool(page._autocut_preview_ranges))
                    analysis=page._autocut_analysis
                    (out/'actual-analysis.json').write_text(json.dumps(analysis,ensure_ascii=False,indent=2),'utf8')
                    capture('speech-candidates')
                else:
                    analysis=json.loads((out/'analysis.json').read_text('utf8'))
                    request=begin_request(page,'autocut');page._autocut_preview_request=request
                    page._autocut_analysis=analysis
                ranges=[(c['start_ms'],c['end_ms']) for c in analysis['candidates']]
                page._autocut_preview_ranges=tuple(ranges)
                panel.show_autocut_preview(ranges,analysis['removed_ms'],analysis['duration_ms'],analysis=analysis)
                panel._autocut_select_all(False);check('candidate deselect all',not panel._autocut_selected_ranges())
                panel._autocut_select_all(True)
                if ranges:
                    if config.get('detect'):
                        panel.autocut_results.setCurrentRow(0)
                        audition=next(b for b in panel.autocut_review_controls.findChildren(QPushButton) if b.text()=='试听当前剪口')
                        scroll.ensureWidgetVisible(audition);pump(.1)
                        capture('speech-review')
                        unchanged=copy.deepcopy(page.project.video_tracks)
                        QTest.mouseClick(audition,Qt.LeftButton);pump(1)
                        check('candidate audition plays real PCM without edits',
                            hasattr(page,'_autocut_player') and page._autocut_player.position()>0
                            and page.project.video_tracks==unchanged)
                        page._autocut_player.stop()
                    panel.autocut_results.item(0).setCheckState(Qt.Unchecked)
                    check('candidate excludes one',len(panel._autocut_selected_ranges())==len(ranges)-1)
                    panel.autocut_results.item(0).setCheckState(Qt.Checked)
                    before=copy.deepcopy(page.project.video_tracks);before_end=timeline_duration_ms(page.project)
                    # Choose a real V2 pause, and export across its NEW join.
                    # Exporting an arbitrary early range would not test a cut.
                    secondary_start=min((c.timeline_in_ms for t in before[1:] for c in t.clips),default=0)
                    a,b=next(((a,b) for a,b in ranges if a>=secondary_start),ranges[0])
                    join=a-sum(y-x for x,y in ranges if y<=a)
                    source_clip=next(c for t in before for c in t.clips if c.timeline_in_ms<=a<b<=c.timeline_out_ms)
                    asset=next(x for x in page.project.media_pool if x.asset_id==source_clip.asset_id)
                    rate=(source_clip.source_out_ms-source_clip.source_in_ms)/(source_clip.timeline_out_ms-source_clip.timeline_in_ms)
                    report['seam_reference']={'source':asset.canonical_source,'rate':rate,'join_ms':join,
                        'source_before_ms':source_clip.source_in_ms+(a-source_clip.timeline_in_ms)*rate,
                        'source_after_ms':source_clip.source_in_ms+(b-source_clip.timeline_in_ms)*rate}
                    panel._autocut_apply_clicked();pump(.5)
                    after_end=timeline_duration_ms(page.project)
                    check('real batch applied exact duration',before_end-after_end==analysis['removed_ms'])
                    links('real batch');report['batch_removed_ms']=before_end-after_end
                    key(Qt.Key_Z,Qt.ControlModifier)
                    check('real batch one undo',page.project.video_tracks==before)
                    key(Qt.Key_Y,Qt.ControlModifier)
                    check('real batch redo duration',timeline_duration_ms(page.project)==after_end)
                    page.save();pump(.2);opened('user')
                    check('real batch saved reopened',timeline_duration_ms(page.project)==after_end)
                    capture('real-batch-reopened')
                    export('real-edited-seam-export',(join-2000,join+2000))

    def run():
        try:
            wait(lambda:page.project is not None and page._readiness.ready)
            if config.get('real_only') and not config.get('detect'):
                opened('user');seek(0)
                report['seek_debug']={'playhead':page.timeline.playhead_ms,'mode':page._playback_mode,
                    'duration':page.video._duration,'mapping':page.video._project_time_mapping_enabled,
                    'clock':str(page.video._playback_clock.snapshot()),'active':page._active_video_preview_clip_id,
                    'trace':page.video.seek_latency_traces()[-4:]}
                check('real initial seek lands at zero',abs(page.timeline.playhead_ms)<100)
                play_until(12000,35);page.video.set_paused(True)
                seek(429000);play_until(timeline_duration_ms(page.project),35)
                check('real deep final source reaches end',page.video._paused and page.video.at_eof)
                report['passed']=True
                return
            if config.get('held_preview'):run_held_preview()
            elif not config.get('real_only'):run_core()
            run_real()
            report['passed']=True
        except Exception:
            report['error']=traceback.format_exc()
            try:capture('failure')
            except Exception:pass
        finally:
            report['final_transport']={'playhead':page.timeline.playhead_ms,'mode':getattr(page,'_playback_mode',''),
                'duration':page.video._duration,'mapping':page.video._project_time_mapping_enabled,
                'clock':str(page.video._playback_clock.snapshot()),'traces':page.video.seek_latency_traces()[-4:]}
            report['elapsed_seconds']=time.monotonic()-started
            (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),'utf8')
            page.video.set_paused(True);page.undo_stack.setClean();QTimer.singleShot(100,window.close)
    QTimer.singleShot(500,run)
