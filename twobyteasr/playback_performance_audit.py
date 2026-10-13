"""Normal-entry pointer/clock/paint audit using bounded opt-in probes."""
import bisect
import json
import os
import time
import traceback
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from .cue_boundary_audit import stats
from . import playback_probe as probe


def start(window,out):
    page=window.studio_page
    result={'passed':False,'checks':{},'operations':[]}
    def pump(seconds):
        end=time.perf_counter()+seconds
        while time.perf_counter()<end:
            QApplication.processEvents();time.sleep(.001)
    def run():
        heartbeat=[];timer=QTimer(page);timer.setInterval(5);timer.setTimerType(Qt.TimerType.PreciseTimer)
        previous=[time.perf_counter()]
        def beat():
            now=time.perf_counter();heartbeat.append((now,(now-previous[0])*1000));previous[0]=now
        timer.timeout.connect(beat)
        try:
            from .build_identity import load_build_identity
            import sys
            if os.environ.get('TWOBYTEASR_AUDIT_SWITCH_INTERVAL'):
                sys.setswitchinterval(float(os.environ['TWOBYTEASR_AUDIT_SWITCH_INTERVAL']))
            result['gil_switch_interval']=sys.getswitchinterval()
            result['identity']=load_build_identity().to_dict()
            result['window']={'dpr':window.devicePixelRatioF(),'width':window.width(),'height':window.height()}
            window.raise_();window.activateWindow();page._set_review_mode(False)
            page.video.controller.set_volume(0);page.video.set_paused(True)
            page.follow_playhead_toggle.setChecked(False)
            page._seek(.3);pump(2);page._seek(0);pump(.5)
            page.timeline.setFocus();page.undo_stack.setClean();probe.EVENTS.clear()
            previous[0]=time.perf_counter();timer.start()
            if os.environ.get('TWOBYTEASR_CAPTION_AUDIT_MODE')=='boundary-light':
                starts=sorted({c.start_ms for c in page.project.cues})
                page.video.set_paused(False);pump(.45+int(os.environ.get('TWOBYTEASR_BOUNDARY_COUNT','112'))*.225)
                page.video.set_paused(True);timer.stop()
                rows=probe.take();applied=[r for r in rows if r['stage']=='apply_playhead'];boundaries=[];old=-1
                for r in applied:
                    current=bisect.bisect_right(starts,r['project_ms'])-1
                    if current!=old and current>=0:boundaries.append(r)
                    old=current
                result['boundary_handler']=stats([r['ms'] for r in boundaries])
                result['checks']['100_boundaries']=len(boundaries)>=100
                result['checks']['boundary_p95_under_8']=result['boundary_handler']['p95_ms']<8
            else:
                timeline=page.timeline;page._fit_timeline();pump(.1)
                def point(ms):return QPoint(round(timeline._time_to_x(ms)),round(timeline.RULER_HEIGHT/2))
                def finish(row,started):
                    current=getattr(page.video,'_active_seek_trace',None)
                    generation=current.get('generation') if current else None
                    row['generation']=generation
                    deadline=time.perf_counter()+1.2;seen={}
                    while time.perf_counter()<deadline:
                        for trace in page.video.seek_latency_traces()[-2:]:
                            if trace.get('generation')!=generation:continue
                            for key,value in trace.get('markers',{}).items():
                                if value>=started:seen[key]=value
                        if ('T5_first_target_frame' in seen and 'T6_seeking_false' in seen
                                and page.video.playback_position_snapshot().paused!=row['playing']):break
                        pump(.003)
                    row['markers_ms']={k:(v-started)*1000 for k,v in seen.items()}
                    row['video_ms']=row['markers_ms'].get('T5_first_target_frame')
                    row['final_project_ms']=page.video.playback_position_snapshot().presentation_media_ms
                    row['observed_video_frame_ms']=page.video._last_video_frame_pts_ms
                    row['paused_after']=page.video.playback_position_snapshot().paused
                    row['state_ready_ms']=(time.perf_counter()-started)*1000
                    result['operations'].append(row);pump(.05)
                for playing in (False,True):
                    page.video.set_paused(not playing);pump(.08)
                    for index in range(16):
                        ms=(2100+index*71) if index%2 else (9200-index*53)
                        at=time.perf_counter();QTest.mouseClick(timeline,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point(ms))
                        row={'kind':'single','playing':playing,'target_ms':timeline.playhead_ms,'at':at,'first_after_mode_change':index==0}
                        finish(row,at)
                    for kind in ('rapid','drag'):
                        for repeat in range(6):
                            start=time.perf_counter()
                            if kind=='drag':QTest.mousePress(timeline,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point(4000))
                            for index in range(12):
                                ms=4500+index*250 if repeat%2 else 9000-index*300
                                at=time.perf_counter()
                                if kind=='drag':QTest.mouseMove(timeline,point(ms))
                                else:QTest.mouseClick(timeline,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point(ms))
                                pump(.018)
                            if kind=='drag':
                                at=time.perf_counter();QTest.mouseRelease(timeline,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point(ms))
                            row={'kind':kind,'playing':playing,'target_ms':timeline.playhead_ms,'at':at,'burst_start':start}
                            finish(row,at)
                scrub=getattr(page,'_timeline_scrub_controller',None) or getattr(page,'_timeline_scrub',None)
                result['scrub']=list(scrub.samples) if scrub else []
                result['checks']['all_target_frames']=all(r['video_ms'] is not None for r in result['operations'])
                result['checks']['paused_state_preserved']=all(r['paused_after']!=r['playing'] for r in result['operations'])
                result['checks']['paused_final_frame_within_one_frame']=all(abs(r['final_project_ms']-r['target_ms'])<=1000/60+1 for r in result['operations'] if not r['playing'])
                result['checks']['paused_observed_video_within_one_frame']=all(r['observed_video_frame_ms'] is not None and abs(r['observed_video_frame_ms']-r['target_ms'])<=1000/60+1 for r in result['operations'] if not r['playing'])
                result['seek_summary']={f'{kind}-{state}':stats([r['video_ms'] for r in result['operations'] if r['kind']==kind and r['playing']==state and r['video_ms'] is not None]) for kind in ('single','rapid','drag') for state in (False,True)}
                timer.stop();page.video.set_paused(True);rows=probe.take()
            result['heartbeat']=stats([d for _,d in heartbeat])
            result['stall_counts']={str(ms):sum(d>ms for _,d in heartbeat) for ms in (16,33,50,100,200)}
            result['stages']={stage:stats([r['ms'] for r in rows if r['stage']==stage and 'ms' in r]) for stage in sorted({r['stage'] for r in rows})}
            result['arrival_intervals']={}
            for stage in ('mpv_time_pos','clock_observe','clock_sample','playhead_target','playhead_paint'):
                sequence=sorted([r['at'] for r in rows if r['stage']==stage])
                result['arrival_intervals'][stage]=stats([(b-a)*1000 for a,b in zip(sequence,sequence[1:])])
            paints=sorted((r for r in rows if r['stage']=='playhead_paint'),key=lambda r:r['at']);moving=[r for i,r in enumerate(paints) if i==0 or r['project_ms']!=paints[i-1]['project_ms']]
            result['moving_paint_intervals']=stats([(b['at']-a['at'])*1000 for a,b in zip(moving,moving[1:])])
            if os.environ.get('TWOBYTEASR_CAPTION_AUDIT_MODE')=='boundary-light':
                result['checks']['moving_paint_max_under_50']=result['moving_paint_intervals']['max_ms']<50
            inputs=[r for r in rows if r['stage'] in ('mouse_move','mouse_press','mouse_release')]
            feedback=[]
            already_displayed=0
            for i,r in enumerate(inputs):
                previous=next((p for p in reversed(paints) if p['at']+p['ms']/1000<r['at']),None)
                if previous and previous['project_ms']==r['project_ms']:
                    feedback.append(0.);already_displayed+=1;continue
                next_at=inputs[i+1]['at'] if i+1<len(inputs) else float('inf')
                paint=next((p for p in paints if r['at']<=p['at']<next_at and p['project_ms']==r['project_ms']),None)
                if paint:feedback.append((paint['at']+paint['ms']/1000-r['at'])*1000)
            result['input_to_paint']=stats(feedback)
            result['input_already_displayed']=already_displayed
            if inputs:result['checks']['pointer_feedback_under_one_frame']=len(feedback)==len(inputs) and max(feedback)<1000/60
            result['checks']['no_200ms_gui_stall']=not result['stall_counts']['200']
            result['passed']=all(result['checks'].values())
            (out/'events.json').write_text(json.dumps({'events':rows,'heartbeat':heartbeat}),encoding='utf8')
            window.grab().save(str(out/'studio.png'))
        except Exception:result['error']=traceback.format_exc()
        finally:
            timer.stop();page.video.set_paused(True);page.undo_stack.setClean()
            (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
            QTimer.singleShot(150,window.close)
    QTimer.singleShot(350,run)
