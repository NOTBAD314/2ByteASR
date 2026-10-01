"""Isolated normal-entry diagnostics for first visible caption frames."""
import json
import time
import traceback
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from .studio_acceptance_audit import require


def capture_window(page, path, pump):
    """Mark a settled frame in the already-running WGC stream."""
    pump(.15)
    page._audit_capture_points.append((str(path),time.perf_counter()))
    pump(.15)


def start(window, out):
    def run():
        page = window.studio_page
        report = {'passed': False, 'frames': [], 'human_listening': 'NOT VERIFIED'}
        def pump(seconds):
            until = time.perf_counter() + seconds
            while time.perf_counter() < until:
                QApplication.processEvents()
                time.sleep(.002)
        try:
            from .build_identity import load_build_identity
            report['build'] = load_build_identity().to_dict()
            until = time.perf_counter() + 90
            while (page.project is None or not page._readiness.ready) and time.perf_counter() < until:
                pump(.03)
            require(page.project is not None and page._readiness.ready, 'project readiness')
            from PySide6.QtCore import QPoint
            primary=QApplication.primaryScreen()
            window.windowHandle().setScreen(primary)
            window.resize(1440, 900)
            window.move(primary.availableGeometry().topLeft()+QPoint(160,120))
            page.video.set_paused(True)
            page._set_volume(0)
            pump(.3)
            window.resize(1440,900);pump(.15)
            from .studio_edit_sequence import projected_cues
            cues = projected_cues(page.project)
            # A previously unseen, isolated cue; no deliberate cache warming.
            cue = next(c for c in cues if c.id.split('#')[0] == '11')
            report['cue'] = dict(id=cue.id, start=cue.start_ms, end=cue.end_ms, text=cue.text)
            report['viewport'] = list(page.position_overlay._content_rect().getRect())
            report['dpr'] = window.devicePixelRatioF()
            report['window_size']=[window.width(),window.height()]
            origin=page.video.mapTo(window,QPoint())
            report['video_origin']=[origin.x(),origin.y()]
            import os
            require(abs(report['dpr']-float(os.environ.get('TWOBYTEASR_ACCEPTANCE_EXPECT_DPR','1')))<.02, 'actual DPR')
            import subprocess
            from pathlib import Path
            from .processes import popen_hidden_subprocess
            log = (out/'capture.log').open('wb')
            page._audit_capture_points=[]
            recorder = popen_hidden_subprocess([str(Path.cwd()/'tools/ffmpeg/bin/ffmpeg.exe'), '-v','warning','-y',
                '-f','lavfi','-i',f'gfxcapture=hwnd={int(window.winId())}:max_framerate=60:capture_cursor=0',
                '-c:v','h264_nvenc','-preset','p1','-cq','18',str(out/'continuous.mp4')],
                stdin=subprocess.PIPE,stdout=log,stderr=log,purpose='continuous native subtitle frame evidence')
            pump(.5)
            for repeat in range(5):
                if repeat==2:
                    page.select_cue('11')
                    page.cue_controller.set_text('11','这我的教程\n你当我忘了')
                    pump(.2)
                if repeat==3:
                    page.undo_stack.undo();pump(.2)
                    page.select_cue('11')
                    page.style_scope.setCurrentIndex(page.style_scope.findData('current'))
                    page.style_font.commit_family('Microsoft YaHei')
                    page._commit_style_now();pump(.2)
                if repeat==4:
                    page.undo_stack.undo();pump(.2)
                    page._toggle_context_panel(True);pump(.2)
                page._seek(max(0, cue.start_ms - 220) / 1000)
                pump(.25)
                page._toggle_playback()
                began = time.perf_counter()
                for i in range(120):
                    pump(.015)
                    trace = page.subtitle_visibility_trace(reason='first-frame-audit')
                    canvas = page.advanced_cue_overlay
                    snap = getattr(canvas, '_snapshot', None)
                    boundary=getattr(page.video.controller,'_caption_boundary_publisher',None)
                    trace.update(repeat=repeat, index=i, wall_ms=(time.perf_counter()-began)*1000,
                                 capture_wall=time.perf_counter(),
                                 playhead_ms=page._caption_sample_ms(),
                                 anchor=[snap.position_x, snap.position_y] if snap else None,
                                 target=list(canvas.geometry().getRect()),
                                 bounds=list(canvas._mpv_bounds_hint.getRect()),
                                 snapshot=snap.stable_hash() if snap else None,
                                 source_kind=getattr(page, '_advanced_canvas_source_kind', ''))
                    trace.update(text=snap.text if snap else '',font=snap.font_family if snap else '',
                        playback_mode=getattr(page,'_playback_mode',''),
                        boundary_active=getattr(boundary,'active',None),boundary_observation=dict(getattr(boundary,'observation',{})))
                    report['frames'].append(trace)
                page.video.set_paused(True)
            exercise_controls(page, out, pump, report)
            ended=time.perf_counter()
            recorder.stdin.write(b'q\n');recorder.stdin.flush()
            until=time.perf_counter()+8
            while recorder.poll() is None and time.perf_counter()<until: pump(.03)
            report['capture_exit']=recorder.poll()
            log.close()
            if os.environ.get('TWOBYTEASR_ACCEPTANCE_BURN_WORD')=='1':
                exercise_real_burn(page,out,report)
            from .processes import run_hidden_subprocess
            probe=run_hidden_subprocess([str(Path.cwd()/'tools/ffmpeg/bin/ffprobe.exe'),
                '-v','error','-show_entries','format=duration','-of','csv=p=0',str(out/'continuous.mp4')],
                capture_output=True,text=True,timeout=10,purpose='read GPU capture timeline')
            duration=float(probe.stdout.strip());zero=ended-duration
            for row in report['frames']:row['capture_seconds']=row.pop('capture_wall')-zero
            report['capture_points']=[]
            for path,stamp in page._audit_capture_points:
                seconds=max(0,stamp-zero)
                result=run_hidden_subprocess([str(Path.cwd()/'tools/ffmpeg/bin/ffmpeg.exe'),
                    '-v','error','-y','-ss',str(seconds),'-i',str(out/'continuous.mp4'),
                    '-frames:v','1',path],capture_output=True,timeout=10,purpose='extract native GPU acceptance frame')
                require(result.returncode==0 and Path(path).is_file(), 'native frame extraction')
                report['capture_points'].append(dict(path=path,seconds=seconds))
            window.grab().save(str(out/'controls.png'))
            report['passed'] = True
        except Exception:
            report['error'] = traceback.format_exc()
        finally:
            (out/'runtime.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            page.video.set_paused(True)
            page.undo_stack.setClean()
            window.close()
    QTimer.singleShot(600, run)


def exercise_controls(page, out, pump, report):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialog, QDialogButtonBox
    from .studio_project import save_project, load_project
    from .visual_snapshot import build_visual_cue_snapshot
    from .style_recipe import FillSpec
    page._toggle_context_panel(True)
    page.context_drawer.setCurrentIndex(2)
    page.select_cue('11')
    page.style_scope.setCurrentIndex(page.style_scope.findData('current'))
    page._seek(16.2);pump(.3)
    page._appearance_rows['fill'].set_expanded(True)
    page.context_drawer.currentWidget().ensureWidgetVisible(page.style_fill_button);pump(.1)
    report['checks']={}
    def check(name, passed):
        report['checks'][name]=bool(passed)
        require(passed, name)
    check('legacy_gradient_survives',build_visual_cue_snapshot(page.project,'11').fill['type']=='linear-gradient')
    colors=['#FFFF0000','#FF00FFFF']
    for i,angle in enumerate((0,90,180)):
        def edit_dialog():
            dialog=QApplication.activeModalWidget()
            require(isinstance(dialog,QDialog), 'fill dialog opened')
            dialog.mode_combo.setCurrentIndex(1)
            stops=[dict(position=0,color=colors[i%2]),dict(position=1,color=colors[1-i%2])]
            if i==2:stops.insert(1,dict(position=.35,color='#8000FF00'))
            dialog.gradient.set_value(dict(type='linear-gradient',angle=angle,stops=stops))
            dialog.gradient._emit()
            dialog.grab().save(str(out/f'fill-dialog-{angle}.png'))
            box=dialog.findChild(QDialogButtonBox)
            QTest.mouseClick(box.button(QDialogButtonBox.Ok),Qt.LeftButton)
        count=page.undo_stack.index()
        QTimer.singleShot(50,edit_dialog)
        QTest.mouseClick(page.style_fill_button,Qt.LeftButton)
        pump(.4)
        snapshot=build_visual_cue_snapshot(page.project,'11')
        check(f'fill_angle_{angle}',snapshot.fill['angle']==angle)
        check(f'fill_undo_{angle}',page.undo_stack.index()==count+1)
        capture_window(page,out/f'gradient-live-{angle}.png',pump)
        report.setdefault('fill_runtime',[]).append(dict(angle=angle,
            trace=page.subtitle_visibility_trace(reason='fill_audit'),
            sample=page._caption_sample_ms(),snapshot=snapshot.to_dict() if hasattr(snapshot,'to_dict') else str(snapshot),
            content=list(page.position_overlay._content_rect().getRect())))
        page.undo_stack.undo();page.undo_stack.redo();pump(.1)
        check(f'fill_redo_{angle}',build_visual_cue_snapshot(page.project,'11').fill==snapshot.fill)
    page._appearance_rows['shadow'].set_expanded(True)
    scroll=page.context_drawer.currentWidget()
    scroll.ensureWidgetVisible(page._appearance_rows['shadow']);pump(.2)
    page.style_shadow_distance.setValue(18);page.style_shadow_opacity.setValue(75);page._commit_style_now()
    disc=page.style_shadow_angle
    report['directions']=[]
    for angle,point in ((0,QPoint(65,36)),(90,QPoint(36,65)),(180,QPoint(7,36)),(270,QPoint(36,7))):
        count=page.undo_stack.index()
        QTest.mousePress(disc,Qt.LeftButton,pos=point);QTest.mouseRelease(disc,Qt.LeftButton,pos=point)
        pump(.3)
        snapshot=build_visual_cue_snapshot(page.project,'11')
        check(f'disc_{angle}',abs(disc.angle()-angle)<.1 and page.style_shadow_angle_value.value()==angle)
        check(f'drag_single_undo_{angle}',page.undo_stack.index()==count+1)
        report['directions'].append(dict(angle=angle,shadow=snapshot.shadow))
        capture_window(page,out/f'direction-{angle}.png',pump)
    scroll.ensureWidgetVisible(page.style_shadow_spread,0,20);pump(.1)
    color=page.style_shadow_button;alpha=page.style_shadow_opacity
    report['control_geometry']={name:dict(rect=list(control.geometry().getRect()),
        top=control.mapToGlobal(QPoint()).y(),bottom=control.mapToGlobal(QPoint(0,control.height())).y())
        for name,control in [('color',color),('opacity',alpha),('distance',page.style_shadow_distance),
                            ('angle',page.style_shadow_angle_value),('disc',disc)]}
    check('disc_visible',disc.isVisible() and disc.width()>=64 and disc.height()>=64)
    check('color_height',color.height()==alpha.height())
    check('color_row_aligned',abs(color.mapToGlobal(QPoint()).y()-alpha.mapToGlobal(QPoint()).y())<=2)
    page.window().grab().save(str(out/'shadow-controls.png'))
    path=save_project(page.project,out/'edited.2byteproj')
    again=load_project(path)
    check('persist_fill_shadow',build_visual_cue_snapshot(again,'11').fill==snapshot.fill
          and build_visual_cue_snapshot(again,'11').shadow==snapshot.shadow)
    # Use the actual razor pointer route, snapped to the explicit playhead.
    page.select_cue('25');page._seek(73.410);pump(.1)
    original=next(c for c in page.project.cues if c.id=='25')
    text=original.text
    timeline=page.timeline
    timeline.set_visible_window(72500,3000)
    timeline.set_snap_enabled(True)
    timeline.set_tool_mode('razor');pump(.1)
    point=QPoint(round(timeline._time_to_x(73410)),round(timeline._active_cue_rect('25').center().y()))
    QTest.mousePress(timeline,Qt.LeftButton,pos=point);pump(.1)
    check('razor_pointer_preview',timeline._razor_preview() is not None)
    QTest.mouseRelease(timeline,Qt.LeftButton,pos=point);pump(.2)
    timeline.set_tool_mode('selection')
    parts=[c for c in page.project.cues if c.id=='25' or c.id.startswith('25-split-')]
    check('real_razor_text',len(parts)==2 and ''.join(c.text for c in parts)==text and parts[1].text.startswith('这'))
    check('real_razor_time',parts[1].start_ms==73410)
    page.undo_stack.undo();check('razor_undo',next(c for c in page.project.cues if c.id=='25').text==text)
    page.undo_stack.redo();save_project(page.project,out/'razor.2byteproj')
    report['razor_parts']=[dict(id=c.id,text=c.text,start=c.start_ms,end=c.end_ms) for c in parts]


def exercise_real_burn(page,out,report):
    """Burn the real cut and detect its first visible frame, not just ASS text."""
    import av
    import numpy as np
    from pathlib import Path
    from PySide6.QtGui import QImage
    from .studio_project import load_project
    from .export_timeline import write_export_ass
    from .video_export import capture_video_graph
    from .studio_render import RenderJob,RenderSettings
    from .advanced_renderer import AdvancedRendererBackend
    from .visual_snapshot import build_visual_cue_snapshot
    from .advanced_live_renderer import render_live_snapshot
    project=load_project(out/'razor.2byteproj')
    export=write_export_ass(project,out/'razor.ass',fps=60)
    job=RenderJob(project.media.path,str(out/'razor.ass'),str(out/'word-cut.mp4'),
        RenderSettings(encoder='h264_nvenc',preset='p4',width=1280,height=720,fps=60,audio_codec='aac'),
        start_seconds=72,duration_seconds=4,video_graph=capture_video_graph(project))
    traces=[];began=time.perf_counter()
    AdvancedRendererBackend().render(export,Path.cwd()/'tools/ffmpeg/bin/ffmpeg.exe',job,
        trace=lambda kind,value:traces.append(dict(kind=kind,value=value)))
    right=next(c for c in export.cues if c.id.startswith('25-split-'))
    left=next(c for c in export.cues if c.id=='25' or c.id.startswith('25#'))
    def pixels(cue):
        im=render_live_snapshot(build_visual_cue_snapshot(export,cue.id),width=1280,height=720).convertToFormat(QImage.Format_RGBA8888)
        return np.asarray(im.constBits()).reshape(im.height(),im.width(),4).copy()
    expected=pixels(right);prior=pixels(left)
    mask=(expected[:,:,3]>250)&(expected[:,:,:3].astype(int).sum(2)>350)&(prior[:,:,3]==0)
    require(mask.sum()>100, 'word pixel signature')
    rows=[];first=None
    for frame in av.open(job.output_path).decode(video=0):
        t=72+float(frame.pts*frame.time_base)
        rgb=frame.to_ndarray(format='rgb24')
        match=(np.abs(rgb.astype(int)-expected[:,:,:3].astype(int)).max(2)<40)[mask].mean()
        if 73.2<t<73.7:rows.append(dict(project_ms=t*1000,match=float(match)))
        if match>.6 and first is None:first=t*1000;frame.to_image().save(out/'word-first-visible.png')
    require(first is not None and 0<=first-right.start_ms<=1000/60+.1,(first,right.start_ms))
    report['word_burn']=dict(first_visible_ms=first,cue_start_ms=right.start_ms,
        extra_offset_ms=first-right.start_ms,frames=rows,elapsed_seconds=time.perf_counter()-began,traces=traces,
        audio_reference='audio/original-70.5s.wav; project = source + 1199 ms',
        acoustic_onset='ASR evidence only; mixed-game spectrum cannot independently identify the phoneme',human_listening='NOT VERIFIED')
