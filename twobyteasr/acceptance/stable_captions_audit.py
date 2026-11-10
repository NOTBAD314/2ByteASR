"""Synthetic equivalent of the screenshot, through normal MainWindow entry."""
from copy import deepcopy
import json
import os
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.build_identity import load_build_identity
    import sys

    def execute():
        code = 1
        try:
            code = run(output, window=window)
        except Exception:
            (output/'audit-error.txt').write_text(traceback.format_exc(), 'utf8')
            window.close()
        path = output/'result.json'
        result = json.loads(path.read_text('utf8')) if path.is_file() else {}
        checks = result.get('checks', [])
        result.update(passed=code == 0 and bool(checks) and all(r['passed'] for r in checks),
            checks_passed=sum(r['passed'] for r in checks), executable=sys.executable,
            pid=os.getpid(), identity=load_build_identity().to_dict())
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        QApplication.instance().exit(code)

    QTimer.singleShot(600, execute)


def run(output, window=None):
    from ..test_isolation import install_pytest_network_guard
    install_pytest_network_guard()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..app.ui import MainWindow, _register_bundled_fonts, _app_font
    from ..design.theme_manager import apply_theme
    from ..projects.studio_project import (SubtitleProject, StudioMedia, StudioSpeaker,
        StudioCue, SubtitleStyle, save_project, load_project)
    from ..system.processes import run_hidden_subprocess
    from ..providers.endpoint_editor_ui import EndpointEditor
    from ..studio.studio_ai_flow import StudioAIFlowMixin
    from ..subtitle_rules.current_issues import current_issue_view, invalidate
    from ..subtitle_rules.studio_qc import QCResult, QCIssue, QCSeverity, QCCategory
    from ..rendering.ass_compiler import compile_ass
    from ..caption_style.collision_layout import project_layout_schedule
    from ..exports.studio_render import RenderSettings, RenderJob, run_render_job
    from ..acceptance.blank_project_audit import _capture
    import subtitle_core as core
    from pathlib import Path
    from ..runtime_paths import detect_install_root
    root = detect_install_root()
    ffmpeg = root/'tools/ffmpeg/bin/ffmpeg.exe'
    app = QApplication.instance() or QApplication([])
    EndpointEditor._queue_model_discovery = lambda *a, **k: None
    StudioAIFlowMixin._start_ai_provider_probe = lambda *a, **k: None
    _register_bundled_fonts(); app.setFont(_app_font()); apply_theme('grape', app)
    checks, traces, metrics = [], [], {}
    win = window

    def check(name, value, detail=None):
        checks.append(dict(name=name, passed=bool(value), detail=detail))
        (output/'progress.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),'utf8')
        if not value:
            raise AssertionError(name + ' ' + str(detail))

    def pump(seconds=.05):
        until = time.monotonic()+seconds
        while time.monotonic()<until:
            app.processEvents(); time.sleep(.005)

    def wait(predicate, seconds=25):
        until = time.monotonic()+seconds
        while not predicate() and time.monotonic()<until:
            pump(.02)
        if not predicate():
            raise TimeoutError(str(predicate))

    def seed_qc(p):
        p._qc_result = QCResult({c.id: (QCIssue('test_current_check',
            QCSeverity.CRITICAL if i == 0 else QCSeverity.WARNING,
            QCCategory.TEXT, c.id, '检查当前字幕', '人工保留当前字幕'),)
            for i,c in enumerate(p.cues)})
        invalidate(p)

    try:
        media = output/'fixture.mp4'
        run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-f','lavfi','-i',
            'color=c=0x334155:s=960x540:r=30:d=7','-c:v','libx264','-preset','ultrafast',str(media)],
            check=True,capture_output=True,timeout=30,purpose='stable caption fixture')
        p = SubtitleProject(media=StudioMedia(str(media),duration_ms=7000,width=960,height=540),
            styles=[SubtitleStyle('default','Default',font_family='Source Han Sans SC Heavy',
                font_size=70,outline_width=4,shadow=0,margin_v=65)],
            speakers=[StudioSpeaker('A'),StudioSpeaker('B'),StudioSpeaker('C')],
            cues=[StudioCue('damage',0,5000,'一发四发一百一十九的伤害',speaker_id='A'),
                  StudioCue('four',1000,4500,'四发打不死啊',speaker_id='B'),
                  StudioCue('yes',1500,2000,'是的',speaker_id='C')])
        fixture=save_project(p, output/'fixture.2byteproj')
        win=window or MainWindow([],core,object(),None); win.resize(1440,920); win.show()
        metrics['device_pixel_ratio']=win.devicePixelRatioF()
        win.open_studio_project(str(fixture))
        wait(lambda: win.built_page('studio') is not None and win.studio_page.project is not None)
        page=win.studio_page
        wait(lambda: win.__dict__.get('_studio_loading_session') is None or
             (not win._studio_loading_session.active and not win._studio_loading_session.view.isVisible()))
        pump(.8); page.volume_slider.setValue(0); page.video.set_paused(True)
        p=page.project

        def scene(at, expected, name):
            page.video.set_paused(True);page._seek(at/1000);pump(.15)
            def ready():
                value=getattr(page,'_caption_scene',None)
                if value is None:return False
                trace=value.trace()
                return set(trace.get('rendered_cue_ids',()))==set(expected) and trace['visible'] and value.still_current(value.token)
            wait(ready)
            wait(lambda: not page.video.playback_position_snapshot().seeking)
            pump(.6)
            trace=deepcopy(page._caption_scene.trace());traces.append(dict(name=name,trace=trace))
            page._caption_scene.published.image.save(str(output/(name+'-scene.png')))
            _capture(win,output/(name+'-window.png'))
            shot=output/(name+'-mpv.png');page.video.controller.screenshot_to_file(shot)
            wait(shot.is_file,3);check(name+' actual mpv image',not QImage(str(shot)).isNull())
            from PIL import Image
            import numpy as np
            rgb=np.array(Image.open(shot).convert('RGB'))
            ys=np.where((rgb.min(2)>210).sum(1)>4)[0]
            bands=[]
            for y in ys:
                if bands and y-bands[-1][-1]<4:bands[-1].append(int(y))
                else:bands.append([int(y)])
            check(name+' actual visible text rows',len(bands)==len(expected),[(b[0],b[-1]) for b in bands])
            return {r['cue_id']:r['position'] for r in trace['cue_pixels']}

        three=scene(1800,['damage','four','yes'],'01-three')
        after=scene(2200,['damage','four'],'02-after-yes')
        check('short yes ends without moving either survivor',all(after[k]==three[k] for k in after),[three,after])
        back=scene(1800,['damage','four','yes'],'03-back')
        check('backward seek repeats exact positions',back==three)
        page.select_cue('four');pump(.2)
        selected=scene(2200,['damage','four'],'04-selected')
        check('selection does not affect position',selected==after)
        page.select_cue('');pump(.1)
        check('selection cancellation preserves position',scene(2200,['damage','four'],'05-unselected')==after)
        page.video.set_paused(False);pump(.5);page.video.set_paused(True)
        check('normal playback preserves positions',scene(2900,['damage','four'],'06-played')==after)
        for width,height in ((1280,820),(1600,980)):
            win.resize(width,height);pump(.3)
            resized=scene(2900,['damage','four'],'resize-'+str(width))
            check('window resize preserves video coordinates '+str(width),resized==after)
        schedule=project_layout_schedule(p)
        from ..caption_style.visual_snapshot import build_visual_cue_snapshot
        check('preview and export share full-instance schedule',all(
            len(schedule[c.id])==1 and abs(three[c.id][1]-(build_visual_cue_snapshot(p,c.id).position_y-schedule[c.id][0][2]))<.01
            for c in p.cues),schedule)

        # Drive the visible button while search narrows the list to ONE cue.
        page._qc_scan_token=getattr(page,'_qc_scan_token',0)+1
        timer=getattr(page,'_qc_scan_timer',None)
        if timer:timer.stop()
        page._qc_full_scan_pending=False;page._pending_qc_cue_ids.clear()
        seed_qc(p);page.cue_model.refresh();page._refresh_cue_list_summary()
        page.cue_search.setText('是的');pump(.05)
        page._refresh_cue_list_summary()
        check('whole-project count ignores search', '3' in page.confirm_all_reviews_button.text())
        original=deepcopy(p.to_dict());steps=page.undo_stack.count()
        _capture(win,output/'07-before-bulk.png')
        begin=time.perf_counter();QTest.mouseClick(page.confirm_all_reviews_button,Qt.LeftButton);pump(.05)
        metrics['bulk_three_ms']=(time.perf_counter()-begin)*1000
        check('one undo command for entire project',page.undo_stack.count()==steps+1)
        check('all red yellow tasks cleared',current_issue_view(p).counts()=={'critical':0,'priority':0})
        check('bulk preserves cue content timing style speaker',p.to_dict()['cues']==original['cues'])
        check('bulk disables zero-count action',not page.confirm_all_reviews_button.isEnabled())
        page.timeline_overview.repaint();pump(.05);_capture(win,output/'08-after-bulk.png')
        page.undo_stack.undo();pump(.05)
        check('undo restores both review levels',current_issue_view(p).counts()=={'critical':1,'priority':2})
        page.undo_stack.redo();pump(.05)
        check('redo clears all review levels',not current_issue_view(p).by_cue)
        saved=save_project(p,output/'reviewed.2byteproj')
        reopened=load_project(saved);seed_qc(reopened)
        check('saved decisions survive identical reanalysis',not current_issue_view(reopened).by_cue)
        reopened.cues[0].text+='新';seed_qc(reopened)
        check('local change only reopens related check',set(current_issue_view(reopened).by_cue)=={'damage'})

        ass=output/'captions.ass';ass.write_text(compile_ass(p),encoding='utf-8-sig')
        settings=RenderSettings(encoder='libx264',preset='ultrafast',audio_codec='none',
            width=960,height=540,fps=30,font_directory=str(root/'assets/fonts'))
        video=run_render_job(ffmpeg,RenderJob(str(media),str(ass),str(output/'native.mp4'),
            settings=settings,overwrite_existing=True))
        check('production native burn-in completed',video.is_file())
        for at in (1.8,2.2,2.9):
            frame=output/f'native-{at}.png'
            run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-ss',str(at),'-i',str(video),
                '-frames:v','1',str(frame)],capture_output=True,check=True,timeout=20,purpose='stable caption decoded export')
            check('decoded export '+str(at),not QImage(str(frame)).isNull())
        from ..exports.static_caption_export import render_static_graph, static_graph_project
        advanced=deepcopy(p)
        advanced.style_recipes['default']={'name':'Static','engine':'remotion','motion':{'mode':'none'}}
        check('advanced fixture uses production static route',static_graph_project(advanced))
        for width,height in ((960,540),(1920,1080)):
            from dataclasses import replace
            job=RenderJob(str(media),str(ass),str(output/f'advanced-{width}.mp4'),
                settings=replace(settings,width=width,height=height),overwrite_existing=True)
            produced=render_static_graph(advanced,ffmpeg,job)
            check('production advanced export '+str(width),produced.is_file())
            for at in (1.8,2.2):
                frame=output/f'advanced-{width}-{at}.png'
                run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-ss',str(at),'-i',str(produced),
                    '-frames:v','1',str(frame)],capture_output=True,check=True,timeout=20,purpose='stable advanced decoded export')
                check('decoded advanced '+str(width)+' '+str(at),not QImage(str(frame)).isNull())
        mixed=deepcopy(advanced)
        mixed.cues[0].style_id='native'
        mixed.styles.append(deepcopy(mixed.styles[0]));mixed.styles[-1].id='native'
        mixed_video=render_static_graph(mixed,ffmpeg,RenderJob(str(media),str(ass),
            str(output/'mixed.mp4'),settings=settings,overwrite_existing=True))
        check('production mixed native advanced export',mixed_video.is_file())
        mixed_frame=output/'mixed-2.2.png'
        run_hidden_subprocess([str(ffmpeg),'-v','error','-y','-ss','2.2','-i',str(mixed_video),
            '-frames:v','1',str(mixed_frame)],capture_output=True,check=True,timeout=20,purpose='stable mixed decoded export')
        check('decoded mixed export',not QImage(str(mixed_frame)).isNull())
        from ..projects.studio_runtime_state import state_for, DirtyDomain
        from PySide6.QtTest import QSignalSpy
        original_cues=list(p.cues)
        with state_for(p).transaction(p,action_id='large_fixture',
                dirty=DirtyDomain.CUE_MODEL|DirtyDomain.CUE_TIMING|DirtyDomain.TIMELINE_INDEX,
                affected_cue_ids=(),snapshot_cues=False):
            p.cues=[*original_cues,*[StudioCue('scale-'+str(i),7000+i*2000,8500+i*2000,
                '已有的长工程字幕',speaker_id='A') for i in range(9997)]]
        seed_qc(p);page._refresh_cue_list_summary();pump(.1)
        resets=QSignalSpy(page.cue_model.modelReset)
        before_steps=page.undo_stack.count();begin=time.perf_counter()
        QTest.mouseClick(page.confirm_all_reviews_button,Qt.LeftButton)
        metrics['bulk_10000_ms']=(time.perf_counter()-begin)*1000
        check('10000 bulk single undo',page.undo_stack.count()==before_steps+1)
        check('10000 bulk single model reset',resets.count()==1,resets.count())
        check('10000 all pending checks cleared',not current_issue_view(p).by_cue)
        check('10000 preserved full texts and timings',p.cues[:3]==original_cues and len(p.cues)==10000)
        _capture(win,output/'09-bulk-10000.png')
        page.undo_stack.setClean()
    except Exception:
        (output/'error.txt').write_text(traceback.format_exc(),'utf8')
        if win:win.grab().save(str(output/'failure.png'))
        raise
    finally:
        (output/'result.json').write_text(json.dumps(dict(checks=checks,traces=traces,metrics=metrics),
            ensure_ascii=False,indent=2),'utf8')
        if win:
            if win.studio_page.project:win.studio_page.undo_stack.setClean()
            win.close();pump(1.)
    return 0
