"""Isolated MainWindow regression for review ownership and viewport timing."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def child(args, window=None):
    sys.path.insert(0, str(args.module_root or ROOT))
    output = args.output
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output/'profile')
    from twobyteasr.test_isolation import install, install_pytest_network_guard
    install()
    install_pytest_network_guard()
    from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from twobyteasr.projects.studio_project import load_project, save_project, SubtitleProject, StudioCue, StudioMedia
    from twobyteasr.subtitle_rules.studio_review import store_review_risks
    from twobyteasr.subtitle_rules.current_issues import current_issue_view
    from twobyteasr.subtitle_rules.studio_qc import review_candidates
    from twobyteasr.recognition.speech_recovery_project import project_ranges
    from twobyteasr.recognition.asr_source_evidence import cue_source_hypotheses
    app = QApplication.instance() or QApplication([])
    p = load_project(args.project)
    before = time.perf_counter()
    store_review_risks(p)
    view = current_issue_view(p)
    a, b = (next(c for c in p.cues if c.id == key) for key in ('2000035', '2000036'))
    result = dict(cue_count=len(p.cues), qc_seconds=time.perf_counter()-before,
                  counts=view.counts(), issue_count=sum(len(v) for v in view.by_cue.values()),
                  speech_ranges=len({r['id'] for r in project_ranges(p)}),
                  speech_classes={kind: len({r['id'] for r in project_ranges(p) if r.get('classification') == kind})
                      for kind in ('supported_speech_gap','uncertain_speech','processing_failure')},
                  captions={c.id: dict(text=c.text, candidates=[vars(r) for r in review_candidates(p,c)],
                      issues=[dict(kind=r.kind,label=r.label,detail=r.detail) for r in view.for_cue(c.id)],
                      observations=[{k:r.get(k) for k in ('model','text','observed_text','reference','ownership',
                          'original_start_ms','original_end_ms')} for r in cue_source_hypotheses(p,c)]) for c in (a,b)})
    (output/'logic.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    if args.logic_only:
        return
    import subtitle_core as core
    from twobyteasr.app.ui import MainWindow, _register_bundled_fonts, _app_font
    from twobyteasr.providers.endpoint_editor_ui import EndpointEditor
    from twobyteasr.studio.studio_ai_flow import StudioAIFlowMixin
    from twobyteasr.design.theme_manager import apply_theme
    from twobyteasr.studio.speech_recovery_ui import open_recovery
    from twobyteasr.acceptance.blank_project_audit import _capture
    EndpointEditor._queue_model_discovery = lambda *a, **k: None
    StudioAIFlowMixin._start_ai_provider_probe = lambda *a, **k: None
    _register_bundled_fonts()
    app.setFont(_app_font())
    apply_theme('grape',app)
    win = window or MainWindow([],core,object(),None)
    win.resize(1600,1000)
    win.show()
    checks = []

    def check(name, value):
        checks.append(dict(name=name,passed=bool(value)))
        (output/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),'utf8')
        if not value:
            raise AssertionError(name)

    def settle(seconds=.1):
        end = time.perf_counter()+seconds
        while time.perf_counter() < end:
            app.processEvents()
            time.sleep(.003)

    def wait(predicate, seconds=60):
        end = time.perf_counter()+seconds
        while not predicate() and time.perf_counter() < end:
            settle(.02)
        check('bounded wait',predicate())

    try:
        fixture = save_project(p,output/'working.2byteproj')
        win.open_studio_project(str(fixture))
        wait(lambda: win.built_page('studio') and win.studio_page.project and win.studio_page.isVisible())
        page = win.studio_page
        wait(lambda: win.__dict__.get('_studio_loading_session') is None or not win._studio_loading_session.active)
        settle(1)
        page._refresh_review_risks(sync=True)
        page._sync_recognition_zero_state()
        check('terminal task hides cancel',page.recognition_cancel_button.isHidden())
        check('uncertain speech is not partial completion','部分完成' not in page.recognition_chip_label.text())
        page.select_cue(a.id)
        page._set_review_mode(True)
        page.select_cue(a.id)
        page._refresh_review_summary_strip()
        page._seek(a.start_ms/1000)
        settle(2)
        settle(.2)
        check('long caption offers preserved full context',any(c.text=='你毕竟你已经亮过散手了对吧'
              for c in page._review_candidates))
        _capture(win,output/'long-candidate.png')
        check('long caption screenshot',(output/'long-candidate.png').is_file())
        total = page._review_session.total
        page.select_cue(b.id)
        page._refresh_review_summary_strip()
        check('selection keeps review denominator',page._review_session.total==total)
        check('reply is not a replacement target',not any(c.text=='散手了对吧' and not c.context_only
              for c in page._review_candidates))
        check('reply screenshot',win.grab().save(str(output/'reply.png')))
        page.select_cue(a.id)
        page._refresh_review_summary_strip()
        mark = next(i for i,r in enumerate(page._review_suggestions) if r.original=='三'
                    and any(o.text=='散' for o in r.options))
        page._apply_review_suggestion(mark,0)
        check('adoption preserves long prefix',page._cue_lookup[a.id].text=='你毕竟你已经亮过散手了对吧')
        page.undo_stack.undo()
        check('adoption undo',page._cue_lookup[a.id].text==a.text)
        page.undo_stack.redo()
        check('adoption redo',page._cue_lookup[a.id].text=='你毕竟你已经亮过散手了对吧')
        page._set_review_mode(False)
        dialog = open_recovery(page)
        settle(.1)
        check('speech dialog screenshot',dialog.grab().save(str(output/'speech-ranges.png')))
        boxes=dialog.findChildren(QCheckBox,'speechGapSelect')
        for box in boxes[:2]:
            box.setChecked(True)
        original_count=len({r['id'] for r in project_ranges(page.project)})
        QTest.mouseClick(dialog.findChild(QPushButton,'speechGapConfirmNoSpeech'),Qt.MouseButton.LeftButton)
        settle(.15)
        check('batch confirms exactly two ranges',len({r['id'] for r in project_ranges(page.project)})==original_count-2)
        saved=save_project(page.project,output/'decisions.2byteproj')
        check('no speech persists on reopen',len({r['id'] for r in project_ranges(load_project(saved))})==original_count-2)
        page._speech_recovery_dialog.close()
        page.undo_stack.undo()
        check('batch undo restores both ranges',len({r['id'] for r in project_ranges(page.project)})==original_count)
        timeline, overview=page.timeline,page.timeline_overview
        overview._timer.stop()
        timeline.set_visible_window(1_300_000,12_000)
        app.processEvents()
        timings=[]
        for tick in range(120):
            start=time.perf_counter()
            timeline._follow_scroll(1_300_000+tick*33)
            app.processEvents()
            check('same-frame viewport '+str(tick),overview._marker_key==overview._key(page.project))
            timings.append((time.perf_counter()-start)*1000)
        check('follow screenshot',win.grab().save(str(output/'follow.png')))
        for visible in (60_000,1000,12_000):
            timeline.set_visible_window(1_305_000,visible)
            app.processEvents()
            check('zoom alignment '+str(visible),abs(overview._x(1_306_783)-timeline._time_to_x(1_306_783))<.01)
        before_key=overview._marker_key
        timeline.set_playhead(1_307_000)
        app.processEvents()
        check('stationary viewport markers stay fixed',overview._marker_key==before_key)
        page._seek(1305.0)
        timeline.set_visible_window(1_300_000,12_000)
        settle(.3)
        for rate in (.5,1.,2.):
            page._set_speed(rate)
            position=timeline.playhead_ms
            page.video.set_paused(False)
            page._sync_play_button(False)
            settle(1.)
            page.video.set_paused(True)
            page._sync_play_button(True)
            check('real playback advances at '+str(rate),timeline.playhead_ms>position)
            app.processEvents()
            check('real playback viewport at '+str(rate),overview._marker_key[2:4]==
                  (timeline.visible_start_ms,timeline.visible_duration_ms))
        page._set_speed(1.)
        win.showMinimized()
        settle(.1)
        win.showNormal()
        settle(.1)
        check('window restoration retains viewport',overview._marker_key==overview._key(page.project))
        result['follow_ms']=dict(median=statistics.median(timings),p95=sorted(timings)[int(len(timings)*.95)],max=max(timings))
        result['scales']=[]
        page.save()
        wait(lambda: page.undo_stack.isClean())
        import subprocess
        from twobyteasr.media.media_service import MediaService
        media=output/'scale-fixture.mp4'
        subprocess.run([str(MediaService().ffmpeg_path),'-v','error','-y','-f','lavfi',
            '-i','color=c=0x263344:s=640x360:r=10:d=2','-c:v','libx264','-preset','ultrafast',
            str(media)],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        for hours,count in ((1,1000),(1,10000),(6,1000),(6,10000)):
            duration=hours*3600000
            step=duration//count
            scale=SubtitleProject(media=StudioMedia(str(media),duration_ms=duration),cues=[
                StudioCue(str(i),i*step,i*step+max(100,step//2),'规模回归字幕','S00') for i in range(count)])
            path=save_project(scale,output/f'scale-{hours}-{count}.2byteproj')
            win.open_studio_project(str(path))
            wait(lambda: page.project and len(page.project.cues)==count)
            wait(lambda: win.__dict__.get('_studio_loading_session') is None or not win._studio_loading_session.active)
            wait(lambda: page.isVisible() and page.timeline_overview.isVisible())
            settle(.3)
            timeline.set_visible_window(duration//2,12_000)
            app.processEvents()
            overview._timer.stop()
            paints=[]
            for tick in range(120):
                started=time.perf_counter()
                timeline._follow_scroll(duration//2+tick*33)
                app.processEvents()
                if overview._marker_key[2:4]!=(timeline.visible_start_ms,timeline.visible_duration_ms):
                    raise AssertionError(f'scale viewport lag {overview._marker_key} vs {overview._key(page.project)}')
                paints.append((time.perf_counter()-started)*1000)
            result['scales'].append(dict(hours=hours,cues=count,visible=len(timeline.visible_cues()),
                median_ms=statistics.median(paints),p95_ms=sorted(paints)[114],max_ms=max(paints)))
        result.update(passed=True,checks=len(checks),dpr=win.devicePixelRatioF(),external_calls=0)
    finally:
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        win.close()
        settle(1)
    # Match the application's native-library retirement after MainWindow cleanup.
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
    kernel.TerminateProcess(kernel.GetCurrentProcess(),0)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--module-root',type=Path)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--normal-entry',action='store_true')
    parser.add_argument('--logic-only',action='store_true')
    parser.add_argument('--child',action='store_true')
    args=parser.parse_args()
    args.project=args.project.resolve()
    args.output=args.output.resolve()
    if args.child:
        child(args)
        return 0
    args.output.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(ROOT/'scripts'))
    from isolated_windows_desktop import run_on_desktop
    env=dict(os.environ,QT_QPA_PLATFORM='windows',TWOBYTEASR_TEST_ROOT=str(args.output/'profile'),
             QT_SCREEN_SCALE_FACTORS='1',
             TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    command=[sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--child',
             '--project',str(args.project),'--output',str(args.output)]
    if args.exe or args.normal_entry:
        startup=args.output/'startup.2byteproj'
        shutil.copy2(args.project,startup)
        command=[str(args.exe.resolve())] if args.exe else [sys.executable,'-B',str(ROOT/'quick_start.py')]
        env.update(LOCALAPPDATA=str(args.output/'profile/local'),APPDATA=str(args.output/'profile/roaming'),
            TWOBYTEASR_ACCEPTANCE_DIR=str(args.output),TWOBYTEASR_ACCEPTANCE_SCENARIO='review-reliability',
            TWOBYTEASR_STARTUP_PROJECT=str(startup),TWOBYTEASR_INVOKER_CWD=str(ROOT))
        from audit_launch_bridge import run_audit_on_desktop
        code=run_audit_on_desktop(command,cwd=ROOT,env=env,output=args.output,
                                timeout=300,receipt=args.output/'result.json')
        print(json.dumps(dict(exit_code=code,output=str(args.output))))
        return code
    if args.module_root:
        command+=['--module-root',str(args.module_root.resolve())]
    if args.logic_only:
        command+=['--logic-only']
    code=run_on_desktop(command,cwd=ROOT,env=env,output=args.output/'process',timeout=300)
    print(json.dumps(dict(exit_code=code,output=str(args.output))))
    return code


if __name__=='__main__':
    raise SystemExit(main())
