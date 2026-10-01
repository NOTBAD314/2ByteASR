"""Opt-in normal GUI audit; caller already validated isolated tmp project/data."""
import copy
import json
import time
import subprocess
from pathlib import Path
from PySide6.QtCore import QTimer
from .studio_acceptance_audit import require


def exercise(page, out, pump, wait):
    from .studio_project import load_project, save_project, StudioCue
    from .studio_edit_sequence import projected_cues
    from .caption_scene import SceneRasterizer
    original_path=Path(page.project_path)
    fixture=load_project(original_path)
    first=fixture.cues[0]
    broken=copy.deepcopy(fixture.styles[0]); broken.id='audit-broken'; broken.name='故障主题验收'
    fixture.styles.append(broken)
    fixture.style_recipes[broken.id]={'engine':'native', 'name':'故障主题验收'}
    fixture.cues.append(StudioCue('audit-peer',first.start_ms,first.end_ms,'故障主题基础回退',
                                 first.speaker_id,broken.id))
    path=save_project(fixture,out/'isolation.2byteproj')
    report={'checks':{},'samples':[],'fault_injection':'one cue snapshot adapter failure; shared raster failure'}
    recorder=None
    record_log=None
    def check(name,value):
        report['checks'][name]=bool(value)
        require(value,name)
    def reopen(filename):
        old=page.project
        page.project_controller.open_project(filename,single_shot_fn=QTimer.singleShot,skip_dirty_guard=True)
        wait(lambda:page.project is not old and page._readiness.ready)
        page.video.set_paused(True)
    def sample(at,name):
        page._seek(at)
        pump(.3)
        expected={c.id for c in projected_cues(page.project) if c.start_ms<=at*1000<c.end_ms}
        wait(lambda:getattr(page,'_caption_scene',None) is not None and
             page._caption_scene.trace()['visible'] and
             {r['cue_id'] for r in page._caption_scene.trace()['cue_pixels']}==expected and
             all(r['status'] in ('rendered','fallback') for r in page._caption_scene.trace()['cue_pixels']),20)
        trace=page._caption_scene.trace()
        page.video.controller.screenshot_to_file(out/f'caption-{name}.png')
        report['samples'].append(dict(name=name,at=at,**trace))
        return trace
    from . import visual_snapshot
    original_snapshot=visual_snapshot.build_visual_cue_snapshot
    def snapshot(project,cue_id,**kwargs):
        if cue_id=='audit-peer' and 'audit-broken' in project.style_recipes:
            raise ValueError('acceptance damaged theme adapter')
        return original_snapshot(project,cue_id,**kwargs)
    visual_snapshot.build_visual_cue_snapshot=snapshot
    try:
        reopen(path)
        cue=next(c for c in projected_cues(page.project) if c.id==first.id)
        at=(cue.start_ms+min(150,(cue.end_ms-cue.start_ms)/2))/1000
        trace=sample(at,'bad-with-healthy')
        check('healthy_peer_visible',any(r['cue_id']==first.id and r['status']=='rendered' for r in trace['cue_pixels']))
        check('bad_cue_readable_fallback',any(r['cue_id']=='audit-peer' and r['status']=='fallback' and r['alpha_nonzero']>0 for r in trace['cue_pixels']))
        check('authored_theme_unchanged',page.project.style_recipes[broken.id]==fixture.style_recipes[broken.id])
        following=next(c for c in projected_cues(page.project) if c.start_ms>cue.end_ms and c.id!='audit-peer')
        after=(following.start_ms+min(150,(following.end_ms-following.start_ms)/2))/1000
        trace=sample(after,'healthy-after')
        check('following_healthy_visible',all(r['status']=='rendered' for r in trace['cue_pixels']))
        trace=sample(at,'seek-back')
        check('seek_back_keeps_healthy_peer',any(r['status']=='rendered' for r in trace['cue_pixels']))
        # Real worker/upload loop, with a deliberately failing shared raster.
        original_frame=SceneRasterizer.frame
        calls=[]
        def fail(*args,**kwargs):
            calls.append(1)
            raise RuntimeError('acceptance shared raster fault')
        SceneRasterizer.frame=fail
        try:
            scene=page._caption_scene
            with scene.lock: scene.frames.clear(); scene.warm_pending.clear()
            page._seek(after)
            wait(lambda:scene.failures.get(scene.token,0)>=2,20)
            failed_token=scene.token;before=scene.failures[failed_token];pump(.6)
            report['shared_failure_counts']=list(scene.failures.values())
            report['shared_raster_calls']=len(calls)
            check('shared_failure_bounded',scene.failures[failed_token]==before
                  and all(value<=2 for value in scene.failures.values()))
            check('shared_worker_survives',scene.thread.is_alive())
        finally:
            SceneRasterizer.frame=original_frame
        trace=sample(at,'after-shared-recovery')
        check('next_generation_recovers',any(r['status']=='rendered' for r in trace['cue_pixels']))
        reopen(original_path)
        check('project_switch_releases_old_owner',page.project is not fixture)
        page._toggle_context_panel(True)
        page.context_drawer.setCurrentIndex(2)
        page.select_cue(first.id)
        page.style_scope.setCurrentIndex(page.style_scope.findData('current'))
        page._appearance_rows['shadow'].set_expanded(True)
        scroll=page.context_drawer.currentWidget()
        scroll.ensureWidgetVisible(page._appearance_rows['shadow'])
        page.style_shadow_distance.setValue(10)
        page.style_shadow_blur.setValue(6)
        page.style_shadow_spread.setValue(3)
        page.style_shadow_angle_value.setValue(45)
        page._seek(at)
        from .visual_snapshot import build_visual_cue_snapshot
        from .processes import popen_hidden_subprocess, run_hidden_subprocess
        ffmpeg=Path.cwd()/'tools/ffmpeg/bin/ffmpeg.exe'
        record_log=(out/'shadow-gpu.log').open('wb')
        recorder=popen_hidden_subprocess([str(ffmpeg),'-v','warning','-y','-f','lavfi','-i',
            f'gfxcapture=hwnd={int(page.window().winId())}:max_framerate=60:capture_cursor=0',
            '-c:v','h264_nvenc','-preset','p1','-cq','18',str(out/'shadow-gpu.mp4')],
            stdin=subprocess.PIPE,stdout=record_log,stderr=record_log,purpose='native shadow alpha evidence')
        pump(.5);stamps=[]
        for opacity in (0,25,50,100):
            page.style_shadow_opacity.setValue(opacity)
            page._commit_style_now();pump(2)
            check(f'shadow_committed_{opacity}',
                  build_visual_cue_snapshot(page.project,first.id).shadow['opacity']==opacity/100)
            prepared=page._prepared_caption(first.id)
            report.setdefault('shadow_runtime',[]).append(dict(opacity=opacity,
                sample_ms=page._caption_sample_ms(),timeline_ms=page.timeline.playhead_ms,
                cue=getattr(page._renderer_cue_at_playhead(),'id',None),
                prepared_shadow=prepared.snapshot.shadow if prepared else None,
                prepared_route=prepared.route.engine if prepared else None,
                preview_size=page._advanced_preview_size(),tick_geometry=getattr(page,'_caption_tick_geometry',None),
                trace=page.subtitle_visibility_trace(reason='shadow_audit')))
            stamps.append((opacity,time.perf_counter()));pump(.2)
        ended=time.perf_counter()
        recorder.stdin.write(b'q\n');recorder.stdin.flush()
        wait(lambda:recorder.poll() is not None,10)
        require(recorder.returncode==0,'shadow GPU capture')
        record_log.close()
        probe=run_hidden_subprocess([str(ffmpeg.with_name('ffprobe.exe')),'-v','error','-show_entries',
            'format=duration','-of','csv=p=0',str(out/'shadow-gpu.mp4')],capture_output=True,text=True,
            timeout=10,purpose='shadow capture duration')
        zero=ended-float(probe.stdout.strip())
        for opacity,stamp in stamps:
            run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-ss',str(max(0,stamp-zero)),
                '-i',str(out/'shadow-gpu.mp4'),'-frames:v','1',str(out/f'shadow-live-{opacity}.png')],
                check=True,timeout=10,purpose='extract actual shadow alpha frame')
        from PIL import Image
        import numpy as np
        from PySide6.QtCore import QPoint
        origin=page.video.mapTo(page.window(),QPoint());dpr=page.window().devicePixelRatioF()
        x,y=round(origin.x()*dpr),round(origin.y()*dpr)
        w,h=round(page.video.width()*dpr),round(page.video.height()*dpr)
        report['shadow_capture_video_rect']=[x,y,w,h]
        frames=[np.array(Image.open(out/f'shadow-live-{v}.png'))[y:y+h,x:x+w].astype(float) for v in (0,25,50,100)]
        report['shadow_native_pixel_deltas']=[float(np.abs(a-b).sum()) for a,b in zip(frames,frames[1:])]
        check('shadow_each_step_changes_native_pixels',all(v>100 for v in report['shadow_native_pixel_deltas']))
        check('shadow_live_route_updated',all(r['trace']['renderer_route']=='advanced' for r in report['shadow_runtime'][1:]))
        scroll.ensureWidgetVisible(page.style_shadow_spread,0,20);pump(.2)
        page.window().grab().save(str(out/'shadow-panel.png'))
        check('angle_input_visible',page.style_shadow_angle_value.isVisible())
        check('compact_direction_distance',abs(page.style_shadow_angle_value.mapToGlobal(page.style_shadow_angle_value.rect().topLeft()).y()-
             page.style_shadow_distance.mapToGlobal(page.style_shadow_distance.rect().topLeft()).y())<=2)
        reopen(original_path)
        report['passed']=all(report['checks'].values())
    finally:
        if recorder is not None and recorder.poll() is None:
            recorder.terminate();recorder.wait(timeout=5)
        if record_log is not None:record_log.close()
        visual_snapshot.build_visual_cue_snapshot=original_snapshot
        (out/'caption-repair.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
