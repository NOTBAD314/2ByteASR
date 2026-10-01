"""Normal-window mouse/key timeline acceptance; explicitly synthetic long source."""
import copy
import json
import time
import traceback
from pathlib import Path


def start(window,out):
    import faulthandler
    stack_log=(out/'thread-stacks.log').open('w',encoding='utf8')
    faulthandler.dump_traceback_later(45,repeat=True,file=stack_log)
    from PySide6.QtCore import QTimer,Qt,QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QLineEdit
    from .studio_edit_sequence import sequence_of,timeline_duration_ms,projected_cues
    from .studio_project import load_project
    from .studio_runtime_state import state_for
    from .build_identity import load_build_identity
    config=json.loads((out/'config.json').read_text('utf8'))
    report=dict(passed=False,checks={},identity=load_build_identity().to_dict(),provider_calls=0,
                source_fixture=config['source_fixture'],ranges=[],images=[])
    page=window.studio_page
    started=time.monotonic()

    def pump(seconds=.1):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            QApplication.processEvents();time.sleep(.003)

    def wait(predicate,seconds=90):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if predicate():return
            pump(.03)
        raise TimeoutError('timeline acceptance wait')

    def check(name,value):
        report['checks'][name]=bool(value)
        (out/'progress.json').write_text(json.dumps({'checks':report['checks'],'seconds':time.monotonic()-started},ensure_ascii=False),'utf8')
        if not value:raise AssertionError(name)

    def clip(lane,index=0):
        return next(t for t in page.project.video_tracks if t.id==lane).clips[index]

    def activate():
        QApplication.setActiveWindow(window);window.activateWindow();page.timeline.setFocus();pump(.04)

    def position(lane,ms):
        t=page.timeline
        local=QPoint(round(t._time_to_x(ms)),round(t._video_track_rect(lane).center().y()))
        return t.mapTo(window,local)

    def click(lane,ms):
        activate()
        point=position(lane,ms)
        if not window.rect().contains(point):
            raise ValueError(f'Click outside visible window: {lane} {ms} {point}')
        (out/'click.json').write_text(json.dumps(dict(lane=lane,time_ms=ms,x=point.x(),y=point.y(),
            viewport=[page.timeline.visible_start_ms,page.timeline.visible_duration_ms],phase='press')),'utf8')
        QTest.mousePress(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,point)
        (out/'click.json').write_text(json.dumps(dict(lane=lane,time_ms=ms,phase='release')),'utf8')
        QTest.mouseRelease(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,point);pump(.15)

    def key(code,mod=Qt.NoModifier):
        activate();QTest.keyClick(window.windowHandle(),code,mod);pump(.2)

    def drag(lane,origin,target,label):
        activate();a,b=position(lane,origin),position(lane,target)
        if not window.rect().contains(a) or not window.rect().contains(b):
            raise ValueError(f'Drag outside visible window: {label} {a} {b}')
        QTest.mousePress(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,a)
        for i in range(1,7):
            QTest.mouseMove(window.windowHandle(),a+(b-a)*i/6,20);pump(.03)
        data=copy.deepcopy(page.timeline._clip_drag)
        page.timeline.grab().save(str(out/(label+'-drag.png')))
        QTest.mouseRelease(window.windowHandle(),Qt.LeftButton,Qt.NoModifier,b);pump(.25)
        report['ranges'].append({'gesture':label,'preview':data})
        return data

    def opened(name):
        page.undo_stack.setClean()
        page.show_project_hub(skip_dirty_guard=True)
        done=[]
        window.open_studio_project(out/(name+'.2byteproj'),on_ready=lambda *_:done.append(True))
        wait(lambda:bool(done) and page.project is not None and page._readiness.ready)
        page.video.set_paused(True);page._set_volume(0)
        page.follow_playhead_toggle.setChecked(False)
        page.timeline.set_visible_window(0,60000);page.timeline.set_tool_mode('selection')
        pump(.2)

    def capture(name):
        window.grab().save(str(out/(name+'-ui.png')))
        page.video.controller.screenshot_to_file(out/(name+'-native.png'),mode='window')
        report['images'].append(name)

    def links(name):
        for group in page.project.av_track_groups:
            if not group.linked:continue
            video=next(t for t in page.project.video_tracks if t.id==group.video_track_id)
            audio=next(t for t in page.project.audio_tracks if t.id==group.audio_track_id)
            fields=('source_in_ms','source_out_ms','timeline_in_ms','timeline_out_ms','playback_rate')
            for c in video.clips:
                a=next(x for x in audio.clips if x.linked_video_clip_id==c.id)
                check(name+' linked '+c.id,all(getattr(c,k)==getattr(a,k) for k in fields))
        check(name+' subscribers healthy',not state_for(page.project).subscriber_errors)

    def export(name, short=False):
        QTest.mouseClick(page.studio_render_button,Qt.LeftButton);pump(.2)
        wait(lambda:page.export_workspace is not None and page.export_workspace.isVisible(),10)
        ui=page.export_workspace
        ui.directory.setText(str(out));ui.filename.setText(name)
        for widget,value in ((ui.extension,'mp4'),(ui.resolution,(-1,-1)),(ui.fps,-1.0),
                             (ui.encoder_preset,'fastest'),(ui.audio,'aac'),(ui.export_range,'all')):
            index=next((i for i in range(widget.count()) if
                        (tuple(widget.itemData(i)) if isinstance(value,tuple) else widget.itemData(i))==value),-1) if isinstance(value,tuple) else widget.findData(value)
            if index < 0:raise ValueError(f'Missing export option {value}')
            widget.setCurrentIndex(index)
        ui.custom_resolution_width.setValue(320);ui.custom_resolution_height.setValue(180)
        ui.custom_fps.setValue(25 if short else 2)
        if short:
            ui.project_range_bar.apply((410000,412000))
            check('real FLV export uses project I/O', (ui.in_ms,ui.out_ms)==(410000,412000))
        ui._target_changed()
        good=[];errors=[]
        ui.render_succeeded.connect(good.append);ui.render_failed.connect(errors.append)
        ui.preview_scroll.ensureWidgetVisible(ui.export_button);pump(.1)
        QTest.mouseClick(ui.export_button,Qt.LeftButton)
        wait(lambda:bool(good or errors),1000)
        check(name+' production export succeeds '+repr(errors),bool(good) and not errors)
        ui.grab().save(str(out/(name+'-export.png')))
        report.setdefault('exports',[]).append(dict(path=str(ui._last_job.output_path),
            receipt=dict(ui._last_job.completion_metadata)))
        page._close_export_workspace();pump(.2)

    def run():
        try:
            wait(lambda:page.project is not None and page._readiness.ready)
            page.video.set_paused(True);page._set_volume(0)
            page.follow_playhead_toggle.setChecked(False)
            window.resize(1440,900);pump(.5)
            report['dpr']=window.devicePixelRatioF()
            if config['baseline']:
                import importlib.util
                from .studio_timeline import WaveformTimeline
                spec=importlib.util.spec_from_file_location('twobyteasr._timeline_entry_baseline',Path(config['baseline'])/'studio_timeline.py')
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                for name in ('mousePressEvent','mouseMoveEvent','mouseReleaseEvent'):
                    setattr(WaveformTimeline,name,getattr(module.WaveformTimeline,name))
                page.timeline.set_visible_window(0,60000)
                before=clip('V1').timeline_in_ms
                drag('V1',10000,15000,'baseline-v1')
                check('baseline reproduces V1 horizontal no-op',clip('V1').timeline_in_ms==before)
                page.timeline.set_tool_mode('razor')
                click('V2',15000)
                check('baseline reproduces V2 razor no-op',len(page.project.video_tracks[1].clips)==1)
                report['passed']=True
                return
            timeline=page.timeline
            timeline.set_visible_window(0,60000);timeline.set_snap_enabled(False)
            for lane in ('V1','V2'):
                c=clip(lane);source=(c.source_in_ms,c.source_out_ms,c.playback_rate)
                data=drag(lane,c.timeline_in_ms+10000,c.timeline_in_ms+15000,lane+'-move-right')
                check(lane+' actual move equals preview',bool(data) and clip(lane).timeline_in_ms==data['preview_in'])
                check(lane+' source range unchanged',(clip(lane).source_in_ms,clip(lane).source_out_ms,clip(lane).playback_rate)==source)
                timeline.set_snap_enabled(True)
                c=clip(lane);origin=c.timeline_in_ms+10000
                data=drag(lane,origin,origin-c.timeline_in_ms,lane+'-snap-zero')
                check(lane+' snapped exactly zero',clip(lane).timeline_in_ms==0)
                timeline.set_snap_enabled(False)
                links(lane+' move')
            capture('moved')
            opened('two-lanes')
            timeline=page.timeline;timeline.set_snap_enabled(False)
            v1_before=copy.deepcopy(page.project.video_tracks[0])
            timeline.set_tool_mode('razor');click('V2',15000);click('V2',22000)
            check('V2 two razor clicks produce three pieces',len(page.project.video_tracks[1].clips)==3)
            check('V2 razor retains V1',page.project.video_tracks[0]==v1_before)
            check('V2 edit does not select V1',not timeline.selected_segment_ids)
            key(Qt.Key_Delete)
            check('V2 immediate Delete leaves two V2 pieces',len(page.project.video_tracks[1].clips)==2)
            check('V2 immediate Delete leaves V1 intact',page.project.video_tracks[0]==v1_before)
            timeline.set_tool_mode('selection');click('V2',18000)
            gap=timeline.selected_gap
            check('middle gap selected',gap is not None and gap[0]=='V2')
            capture('gap-selected')
            key(Qt.Key_Delete)
            check('middle gap closed exactly',clip('V2',0).timeline_out_ms==clip('V2',1).timeline_in_ms)
            key(Qt.Key_Z,Qt.ControlModifier)
            check('gap undo restores spacing',clip('V2',1).timeline_in_ms==gap[2])
            key(Qt.Key_Y,Qt.ControlModifier)
            links('V2 split-gap')
            # Leading gap and input-focus guard use the normal Delete shortcut.
            opened('two-lanes');timeline=page.timeline
            click('V2',5000);check('leading gap selected',timeline.selected_gap==('V2',0,10000))
            unchanged=copy.deepcopy(page.project.video_tracks)
            page.cue_search.setText('abc');page.cue_search.setCursorPosition(0);page.cue_search.setFocus()
            QTest.keyClick(page.cue_search,Qt.Key_Delete);pump(.1)
            check('Delete in text edits text only',page.cue_search.text()=='bc' and page.project.video_tracks==unchanged)
            page.cue_search.clear();key(Qt.Key_Delete)
            check('leading gap closes only V2',clip('V2').timeline_in_ms==0 and page.project.video_tracks[0]==unchanged[0])
            key(Qt.Key_Z,Qt.ControlModifier);check('leading gap Undo',clip('V2').timeline_in_ms==10000)
            # V1 and V2 left-edge drag/undo, after moving away from the origin.
            for lane in ('V1','V2'):
                opened('two-lanes');timeline=page.timeline;timeline.set_snap_enabled(False)
                before=copy.deepcopy(clip(lane))
                data=drag(lane,before.timeline_in_ms,before.timeline_in_ms+3000,lane+'-left-edge')
                check(lane+' left edge trims source',data and data['mode']=='trim_left' and clip(lane).source_in_ms>before.source_in_ms)
                key(Qt.Key_Z,Qt.ControlModifier)
                check(lane+' left trim Undo restores all',clip(lane)==before)
            # Exact right-edge hit, then restore within source bounds.
            opened('two-lanes');timeline=page.timeline;timeline.set_snap_enabled(False)
            right=clip('V2').timeline_out_ms
            data=drag('V2',right,right-3000,'V2-right-edge')
            check('precise right edge is trim',data and data['mode']=='trim_right')
            check('right trim edits source range',clip('V2').source_out_ms<20000)
            data=drag('V2',clip('V2').timeline_out_ms,35000,'V2-restore-limit')
            check('right restore clamps source end',clip('V2').source_out_ms==20000 and clip('V2').timeline_out_ms==30000)
            timeline.set_visible_window(3540000,120000)
            drag('V1',3600000,3595000,'V1-right-edge')
            check('V1 right edge trims source',clip('V1').source_out_ms<3600000)
            drag('V1',clip('V1').timeline_out_ms,3600000,'V1-right-restore')
            check('V1 right restore source bound',clip('V1').source_out_ms==3600000 and clip('V1').timeline_out_ms==3600000)
            opened('two-lanes');timeline=page.timeline;timeline.set_snap_enabled(True)
            timeline.set_visible_window(10000,60000);timeline.set_playhead(40000)
            drag('V2',20000,50020,'playhead-snap')
            check('playhead snap exact',clip('V2').timeline_in_ms==40000)
            opened('two-lanes');timeline=page.timeline;timeline.set_snap_enabled(False)
            click('V2',15000);timeline.set_playhead(20000);key(Qt.Key_K,Qt.ControlModifier)
            timeline.set_playhead(55000)
            drag('V2',25000,30000,'same-track-gap')
            timeline.set_snap_enabled(True)
            current=clip('V2',1).timeline_in_ms
            drag('V2',current+5000,25020,'same-track-snap')
            check('same-track snap exact',clip('V2',1).timeline_in_ms==clip('V2').timeline_out_ms==20000)
            opened('two-lanes');timeline=page.timeline
            # Cross-track target at a non-round millisecond, scrolled + zoomed.
            page._video_clip_trim_committed('V1',clip('V1').id,0,12347)
            timeline.set_visible_window(5000,40000);timeline.set_snap_enabled(True)
            original=clip('V2').timeline_in_ms
            data=drag('V2',original+10000,22347,'cross-track-snap')
            check('cross-track exact integer boundary',clip('V2').timeline_in_ms==12347)
            links('cross-track snap')
            # Locked linked audio: a real gesture is rejected as a whole.
            page.project.audio_tracks[1].locked=True
            snapshot=copy.deepcopy(page.project.video_tracks)
            drag('V2',22000,26000,'linked-locked')
            check('linked lock preserves complete graph',page.project.video_tracks==snapshot)
            check('linked lock visible message','锁定' in page.save_state.text())
            page.project.audio_tracks[1].locked=False
            opened('two-lanes');timeline=page.timeline
            click('V2',17000);timeline.set_playhead(17000);key(Qt.Key_Q)
            check('V2 Q is lane-local',(clip('V2').source_in_ms,clip('V2').timeline_in_ms,clip('V2').timeline_out_ms)==(7000,10000,23000) and clip('V1').timeline_out_ms==3600000)
            timeline.set_playhead(15000);key(Qt.Key_W)
            check('V2 W is lane-local',(clip('V2').source_out_ms,clip('V2').timeline_out_ms)==(12000,15000) and clip('V1').timeline_out_ms==3600000)
            # Q/W use keyboard and the current target on an actual hour source.
            opened('long');timeline=page.timeline
            timeline.set_visible_window(0,3600000)
            click('V1',1200000)
            page._seek(1800);pump(.5);timeline.set_playhead(1800000)
            key(Qt.Key_Q)
            c=clip('V1')
            check('Q keeps source 30-60 at timeline 0-30',(c.source_in_ms,c.source_out_ms,c.timeline_in_ms,c.timeline_out_ms)==(1800000,3600000,0,1800000))
            page._seek(0);pump(.5)
            capture('Q-source-30min')
            check('Q runtime captions follow',bool(state_for(page.project).cues_at(0)))
            page._seek(1200);pump(.3);timeline.set_playhead(1200000)
            key(Qt.Key_W)
            check('W keeps source 30-50 at timeline 0-20',(clip('V1').source_in_ms,clip('V1').source_out_ms,timeline_duration_ms(page.project))==(1800000,3000000,1200000))
            links('QW')
            # Independent route requested by the user: Ctrl+K, ordinary Delete,
            # a leading gap, then Delete to close it. No export/reimport.
            opened('cut-long');timeline=page.timeline;timeline.set_visible_window(0,3600000)
            click('V1',1200000)
            timeline.set_playhead(1800000);key(Qt.Key_K,Qt.ControlModifier)
            timeline.set_playhead(3000000);key(Qt.Key_K,Qt.ControlModifier)
            check('CtrlK cuts exact 30 and 50 minute edges',[(c.timeline_in_ms,c.timeline_out_ms) for c in page.project.video_tracks[0].clips]==[(0,1800000),(1800000,3000000),(3000000,3600000)])
            click('V1',3300000);key(Qt.Key_Delete)
            timeline.set_visible_window(0,3600000)
            click('V1',900000);key(Qt.Key_Delete)
            check('ordinary Delete leaves thirty minute leading gap',len(page.project.video_tracks[0].clips)==1 and clip('V1').timeline_in_ms==1800000)
            timeline.set_visible_window(0,3600000);click('V1',900000)
            check('thirty minute gap selected',timeline.selected_gap==('V1',0,1800000))
            key(Qt.Key_Delete)
            check('gap Delete keeps exact source30-50 at project0-20',(clip('V1').source_in_ms,clip('V1').source_out_ms,clip('V1').timeline_in_ms,clip('V1').timeline_out_ms)==(1800000,3000000,0,1200000))
            key(Qt.Key_Z,Qt.ControlModifier);check('thirty minute gap Undo restores source and placement',clip('V1').timeline_in_ms==1800000 and clip('V1').source_in_ms==1800000)
            key(Qt.Key_Y,Qt.ControlModifier)
            links('cut-delete-gap')
            autosave=page.flush_autosave()
            check('atomic autosave graph matches committed edit',bool(autosave) and load_project(autosave).video_tracks==page.project.video_tracks)
            page._seek(0);pump(.4)
            page.save();pump(.2)
            saved=load_project(out/'cut-long.2byteproj')
            check('ordinary save preserves edited graph',saved.video_tracks==page.project.video_tracks)
            check('canonical authored subtitle retained',any(c.text=='AUTHORED CAPTION' for c in saved.cues))
            opened('cut-long')
            check('hub exit and reopen preserves twenty-minute edit',timeline_duration_ms(page.project)==1200000 and clip('V1').source_in_ms==1800000)
            page._seek(0);pump(.4);capture('reopened')
            page.audio_engine.capture_pcm('kept-preview',True)
            wait(lambda:(out/'kept-preview.started').exists(),10)
            page.video.set_paused(False);pump(2);page.video.set_paused(True)
            page.audio_engine.capture_pcm('kept-preview',False)
            wait(lambda:(out/'kept-preview.json').exists(),10)
            report['preview_audio']=page.audio_engine.telemetry_snapshot()
            check('edited source plays from timeline zero',500<page.timeline.playhead_ms<6000)
            if not config['skip_export']:
                export('kept-source-30-to-50')
            if (out/'user-copy.2byteproj').exists():
                opened('user-copy');timeline=page.timeline;timeline.set_visible_window(200000,300000)
                before=clip('V2').timeline_in_ms
                drag('V2',before+60000,before+65000,'real-FLV-move')
                check('real screenshot project V2 moved',clip('V2').timeline_in_ms!=before)
                timeline.set_visible_window(200000,300000)
                timeline.set_tool_mode('razor');click('V2',400000)
                check('real screenshot V2 split',len(page.project.video_tracks[1].clips)==2)
                page._seek(410);pump(1);capture('real-FLV-edited')
                links('real FLV')
                committed=copy.deepcopy(page.project.video_tracks)
                page.save();pump(.2)
                opened('user-copy')
                check('real FLV V2 save and hub reopen',page.project.video_tracks==committed)
                page._seek(410);pump(.5)
                if not config['skip_export']:export('real-FLV-edited',short=True)
            report['passed']=True
        except Exception:
            report['error']=traceback.format_exc()
            try:capture('failure')
            except Exception:pass
        finally:
            faulthandler.cancel_dump_traceback_later()
            stack_log.close()
            report['elapsed_seconds']=time.monotonic()-started
            (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),'utf8')
            page.video.set_paused(True);page.undo_stack.setClean()
            QTimer.singleShot(100,window.close)
    QTimer.singleShot(500,run)
