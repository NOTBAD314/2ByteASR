"""Owned-window baseline and regression measurements; never run on user projects."""
import cProfile
import json
import os
from pathlib import Path
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    output = Path(output)
    def execute():
        try:
            if os.environ.get('TWOBYTEASR_PERF_GEOMETRY')=='1':
                from .workbench_geometry_audit import run as run_geometry
                run_geometry(window,output)
            elif os.environ.get('TWOBYTEASR_PERF_EXPORTS')=='1':
                from .workbench_export_audit import run as run_exports
                run_exports(window,output)
            else:run(window, output)
        except Exception:
            (output / 'error.txt').write_text(traceback.format_exc(), 'utf8')
        window.studio_page.undo_stack.setClean()
        window.close()
    QTimer.singleShot(100, execute)


def run(window, output):
    from PySide6.QtCore import Qt, QPoint, QObject, QEvent, QTimer
    from PySide6.QtTest import QTest
    from ..projects.studio_project import SubtitleProject, StudioMedia, StudioCue, hydrate_media_contract, save_project
    from ..studio.studio_helpers import probe_media_identity
    from ..caption_style.caption_layer_transform import resolved_values
    from .blank_project_audit import _capture
    from .studio_splitter_audit import _native_rects, _picture_box
    result = {'support': [], 'drag': [], 'source': __file__, 'checks': []}
    def save():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')
    def wait(predicate, label, seconds=40):
        deadline = time.monotonic() + seconds
        while not predicate():
            if time.monotonic() > deadline:
                raise TimeoutError(label)
            QTest.qWait(5)
    media = Path(os.environ['TWOBYTEASR_PERF_MEDIA'])
    page = window.studio_page
    window.showNormal(); window.resize(1600, 950); window.show()
    for count in [int(n) for n in os.environ.get('TWOBYTEASR_PERF_COUNTS', '60,600,3000').split(',')]:
        p = SubtitleProject(media=StudioMedia(str(media), duration_ms=max(12000, count*500), width=1280, height=720),
            cues=[StudioCue(f'cue-{i}', i*500, i*500+480, f'字幕拖動測試 {i}') for i in range(count)],
            generation_metadata={'translations': {f'cue-{i}': f'Translation {i}' for i in range(count)}},
            studio_state={'bilingual': {'mode': 'bilingual'}})
        if os.environ.get('TWOBYTEASR_PERF_PIXELS')=='1':
            p.styles[0].position_x=500;p.styles[0].position_y=480
        hydrate_media_contract(p, probe_media_identity(str(media)))
        p.render_settings.update(play_res_x=1280, play_res_y=720, _cue_domain='timeline')
        path = save_project(p, output/f'fixture-{count}.2byteproj')
        page.undo_stack.setClean(); prior = page.project
        window.open_studio_project(str(path), mode='edit', source='workbench_performance_audit')
        wait(lambda: page.project is not prior and page._readiness.ready, 'project readiness', 90)
        QTest.qWait(500)
        page.video.set_paused(True); page._seek(.2); page.select_cue('cue-0')
        page.context_drawer.setCurrentIndex(1)
        panel = page.caption_transform_panel
        QTest.qWait(800)
        if count == 60:
            for attempt in range(3):
                paints = []
                class PaintWatch(QObject):
                    def eventFilter(self, obj, event):
                        if event.type() == QEvent.Type.Paint:
                            paints.append(time.perf_counter())
                        return False
                watch = PaintWatch()
                profile = cProfile.Profile()
                began = time.perf_counter(); profile.enable()
                page.report_problem_button.click()
                dialog = getattr(window, '_support_dialog', None) or page._support_dialog
                dialog.installEventFilter(watch)
                call_ms = (time.perf_counter()-began)*1000
                wait(lambda: dialog.isVisible(), 'report visible')
                dialog.description.setFocus()
                QTest.keyClicks(dialog.description, 'usable')
                QTest.qWait(20)
                interactive_ms = (time.perf_counter()-began)*1000
                profile.disable(); profile.dump_stats(str(output/f'support-{attempt}.prof'))
                result['support'].append(dict(attempt=attempt, callback_ms=call_ms,
                    first_paint_ms=(paints[0]-began)*1000 if paints else None,
                    input_ms=interactive_ms, typed=dialog.description.text(), jobs=dialog._jobs))
                _capture(dialog, output/f'support-{attempt}.png')
                dialog.close(); QTest.qWait(150)
                save()
        for global_mode in (False, True):
            switch = getattr(panel, 'global_link', getattr(page, 'style_apply_geometry', None))
            if switch is not None: switch.setChecked(global_mode)
            page.position_edit_button.setChecked(True)
            page.ensure_active_subtitle_renderer(reason='performance_baseline')
            panel.refresh(); QTest.qWait(400)
            if os.environ.get('TWOBYTEASR_PERF_PIXELS')=='1':
                from .workbench_drag_pixels import measure
                result['drag'].append(measure(page,panel,output,count,global_mode));save();continue
            overlay = page.position_overlay
            r = getattr(overlay, '_measured_bounds', None)
            point = r.center().toPoint() if r is not None and hasattr(r.center(),'toPoint') else r.center() if r is not None else overlay.rect().center()
            before = resolved_values(page.project, page.project.cues[0], 'original')
            profile = cProfile.Profile()
            samples=[]; previous_index=page.undo_stack.index()
            QTest.mousePress(overlay, Qt.LeftButton, pos=point)
            for i in range(1, 9):
                started=time.perf_counter(); profile.enable()
                QTest.mouseMove(overlay, point+QPoint(i*4, -i*2), delay=0)
                handler=(time.perf_counter()-started)*1000
                profile.disable()
                QTest.qWait(50)
                scene=getattr(page,'_caption_scene',None)
                samples.append(dict(handler_ms=handler, observation_ms=(time.perf_counter()-started)*1000,
                    revision=page._revision_store.render.visual_revision,
                    scene_token=scene.token if scene else None,
                    published=scene.published if scene else None))
                if i==4:
                    _capture(window,output/f'drag-{count}-{global_mode}-held.png')
                    _, native=_native_rects(page.video)
                    if native:
                        _picture_box(_native_rects.mpv_hwnd,(native[2],native[3]))
                        _picture_box.last_image.save(output/f'drag-{count}-{global_mode}-native.png')
            QTest.mouseRelease(overlay, Qt.LeftButton, pos=point+QPoint(32,-16))
            QTest.qWait(450)
            profile.dump_stats(str(output/f'drag-{count}-{global_mode}.prof'))
            after=resolved_values(page.project,page.project.cues[0],'original')
            result['drag'].append(dict(count=count,global_mode=global_mode,before=before,after=after,
                undo_steps=page.undo_stack.index()-previous_index,samples=samples,
                last_cue=resolved_values(page.project,page.project.cues[-1],'original')))
            save()
    result['completed']=True
    save()
