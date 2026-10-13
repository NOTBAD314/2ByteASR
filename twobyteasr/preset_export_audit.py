"""Opt-in normal-entry audit; runs only inside the guarded acceptance fixture."""
from copy import deepcopy
from dataclasses import asdict
import json
import threading
import time
import traceback

from PySide6.QtCore import QItemSelectionModel, QSignalBlocker, QTimer
from PySide6.QtWidgets import QApplication


def start(window, out):
    import os
    if os.environ.get('TWOBYTEASR_EXPORT_CANCEL_AUDIT') == '1':
        from .export_cancel_audit import start as start_cancel
        start_cancel(window, out)
        return
    page = window.studio_page
    result = {'passed': False, 'states': [], 'scopes': []}

    def pump(seconds):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            QApplication.processEvents()
            time.sleep(.005)

    def state(name):
        from .visual_snapshot import build_visual_cue_snapshot
        from .style_resolution import resolve_cue_visual
        from .ass_compiler import compile_ass
        from .advanced_renderer import compile_composition_data
        cue = page._cue_lookup['3']
        snap = build_visual_cue_snapshot(page.project, cue.id)
        payload = {'name': name, 'project': page.project.to_dict(),
                   'authored_style': asdict(resolve_cue_visual(page.project, cue).style),
                   'snapshot': snap.to_dict(), 'truth': page.render_truth_probe(force=True)}
        (out/(name+'.json')).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf8')
        (out/(name+'.ass')).write_text(compile_ass(page.project), encoding='utf8')
        (out/(name+'-props.json')).write_text(json.dumps(compile_composition_data(page.project,
            width=1920, height=1080, fps=60, start_seconds=0, duration_seconds=57.55),
            ensure_ascii=False, indent=2), encoding='utf8')
        window.grab().save(str(out/(name+'-window.png')))
        page.video.controller.screenshot_to_file(out/(name+'-video.png'))
        canvas = page.advanced_cue_overlay
        pixmap = getattr(canvas, '_source', None)
        if pixmap is not None and not pixmap.isNull():
            pixmap.save(str(out/(name+'-foreground.png')))
        result['states'].append({'name': name, 'font_size': snap.font_size,
            'family': snap.font_family, 'weight': snap.font_weight,
            'caption': snap.resolved_caption.to_dict(), 'glyph_hash': snap.glyph_hash()})
        assert snap.font_size == 90 and snap.font_weight == 900
        assert not snap.resolved_caption.requires_split
        return snap

    def run():
        try:
            from .style_presets import StylePresetStore
            from .studio_project import save_project, load_project
            from .visual_snapshot import build_visual_cue_snapshot
            from .style_resolution import resolve_cue_visual
            page.volume_slider.setValue(0)
            page.video.controller.set_volume(0)
            page.video.set_paused(True)
            window.raise_(); window.activateWindow()
            page.select_cue('3'); page._seek(5); pump(.8)
            preset_id = 'user-2f4ded66a113'
            preset = StylePresetStore().load_patch(preset_id)
            assert preset
            (out/'preset.json').write_text(json.dumps(preset, ensure_ascii=False, indent=2), encoding='utf8')
            state('before')
            original = [(c.id, c.text, c.start_ms, c.end_ms, deepcopy(c.transform)) for c in page.project.cues]
            for scope in ('current', 'selected', 'speaker', 'all'):
                page.select_cue('3')
                with QSignalBlocker(page.style_scope):
                    page.style_scope.setCurrentIndex(page.style_scope.findData(scope))
                if scope == 'selected':
                    selection = page.cue_table.selectionModel()
                    for cue_id in ('3', '4'):
                        row = page.cue_model.row_for_cue_id(cue_id)
                        selection.select(page.cue_model.index(row, 0),
                            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
                targets = page._style_target_ids()
                before = {c.id: asdict(resolve_cue_visual(page.project, c).style) for c in page.project.cues}
                page._apply_style(replace_preset=True)
                once = deepcopy(page.project.to_dict())
                page._apply_style(replace_preset=True)
                assert once == page.project.to_dict(), f'{scope}: non-idempotent'
                for cue in page.project.cues:
                    current = asdict(resolve_cue_visual(page.project, cue).style)
                    if cue.id not in targets:
                        assert current == before[cue.id], f'{scope}: changed non-target'
                    for key in ('position_x', 'position_y', 'scale_x', 'scale_y', 'margin_l', 'margin_r'):
                        assert current[key] == before[cue.id][key], f'{scope}: changed geometry {key}'
                result['scopes'].append({'scope': scope, 'targets': targets, 'idempotent': True})
                page._seek(5); pump(.45); state(scope)
            assert original == [(c.id, c.text, c.start_ms, c.end_ms, deepcopy(c.transform)) for c in page.project.cues]
            save_project(page.project, out/'saved.2byteproj')
            reopened = load_project(out/'saved.2byteproj')
            result['saved_hash'] = build_visual_cue_snapshot(reopened, '3').glyph_hash()
            assert result['saved_hash'] == result['states'][-1]['glyph_hash']
            page.undo_stack.setClean()
            page.open_project(out/'saved.2byteproj')
            deadline = time.monotonic() + 15
            while page._readiness.active and time.monotonic() < deadline: pump(.05)
            assert not page._readiness.active
            page.select_cue('3'); page._seek(5); pump(.8); state('reopened')
            from .preset_application import preset_command
            authored_before = deepcopy(page.project.to_dict())
            missing = preset_command(page.project, ['3'], {'id':'audit-missing','name':'Missing font probe',
                'font_family':'Missing acceptance font', 'font_weight':900, 'font_style_name':'Heavy'})
            missing.redo(); page._load_style_inspector(); pump(.1)
            warning = page.style_font_warning.text()
            assert 'Missing acceptance font' in warning and not page.style_font_warning.isHidden()
            assert resolve_cue_visual(page.project,page._cue_lookup['3']).style.font_family=='Missing acceptance font'
            window.grab().save(str(out/'missing-font-window.png'))
            missing.undo(); page._load_style_inspector()
            restored = page.project.to_dict()
            (out/'missing-font-transaction.json').write_text(json.dumps({'before':authored_before,
                'after':restored}, ensure_ascii=False, indent=2, default=str),encoding='utf8')
            for key in ('styles','style_recipes'):
                assert restored[key]==authored_before[key], key
            # Appearance generations are monotonic invalidation tokens on
            # redo/undo. Compare authored values without rolling those back.
            without_generation = lambda cues: [{k:v for k,v in cue.items() if k!='appearance_generation'} for cue in cues]
            assert without_generation(restored['cues'])==without_generation(authored_before['cues'])
            result['missing_font_warning'] = warning
            import os
            completion_audit = os.environ.get('TWOBYTEASR_COMPLETION_AUDIT') == '1'
            final_output = out / ('2ByteASR-完成页-真实压制验证-1920x1080-60fps-长文件名省略与完整提示验收.mp4' if completion_audit else 'verified.mp4')
            result['output_path'] = str(final_output)
            if os.environ.get('TWOBYTEASR_PRESET_AUDIT_EXPORT_MODE')=='html':
                html_path=os.environ['TWOBYTEASR_PRESET_AUDIT_HTML_PROJECT']
                reopened=load_project(html_path)
                page.open_project(html_path)
                deadline=time.monotonic()+15
                while page._readiness.active and time.monotonic()<deadline:pump(.05)
                assert not page._readiness.active
                page._seek(5);pump(.8);window.grab().save(str(out/'html-studio.png'))
            from .studio_export_ui import StudioExportWorkspace
            from .theme_manager import apply_theme
            apply_theme('slate',QApplication.instance())
            export_ui = StudioExportWorkspace(reopened, str(out/'reopened.ass'), out/'saved.2byteproj')
            export_ui._advanced_route = True
            export_ui.resize(1600, 950)
            export_ui.pages.setCurrentWidget(export_ui.exporting_page)
            export_ui.show()
            # Full real media render happens in the same source/frozen process.
            # Qt continues pumping so cancellation and playback resources stay live.
            def export():
                try:
                    from pathlib import Path
                    from .studio_render import RenderJob, RenderSettings
                    from .video_export import capture_video_graph
                    from .advanced_renderer import AdvancedRendererBackend
                    ffmpeg = Path(__file__).resolve().parents[1]/'tools/ffmpeg/bin/ffmpeg.exe'
                    job = RenderJob(reopened.media.path, str(out/'reopened.ass'), str(final_output),
                        settings=RenderSettings(encoder='h264_nvenc', preset='p4', quality=20),
                        duration_seconds=57.55, overwrite_existing=True, video_graph=capture_video_graph(reopened),
                        completion_preview_path=str(out/'completion.jpg'))
                    export_ui._last_job = job
                    export_ui._started_at=time.monotonic()
                    started = time.perf_counter()
                    events = []
                    def trace(event, value):
                        record = {'at':time.perf_counter()-started, 'event':event, 'value':value}
                        events.append(record)
                        with (out/'export-events.jsonl').open('a', encoding='utf8') as log:
                            log.write(json.dumps(record,ensure_ascii=False,default=str)+'\n')
                    import os
                    if os.environ.get('TWOBYTEASR_PRESET_AUDIT_EXPORT_MODE') == 'native':
                        from .ass_compiler import compile_ass
                        from .studio_render import run_render_job
                        ordinary = deepcopy(reopened)
                        ordinary.style_recipes = {}
                        (out/'reopened.ass').write_text(compile_ass(ordinary), encoding='utf8')
                        run_render_job(ffmpeg, job, progress=export_ui._progress, trace=trace)
                    else:
                        AdvancedRendererBackend().render(reopened, ffmpeg, job,
                            progress=export_ui._progress, trace=trace)
                    result['export'] = {'elapsed': time.perf_counter()-started, 'events':events}
                except Exception:
                    result['export_error'] = traceback.format_exc()
            worker = threading.Thread(target=export, name='acceptance-export')
            worker.start()
            seen = set()
            while worker.is_alive():
                pump(.05)
                stage = export_ui._progress_payload.get('stage')
                if stage and stage not in seen:
                    seen.add(stage)
                    export_ui.grab().save(str(out/('export-'+stage+'.png')))
            result['export_stages'] = sorted(seen)
            export_ui._progress_clock.stop()
            if 'export' in result:
                result['receipt'] = dict(export_ui._last_job.completion_metadata)
                shown=time.perf_counter();export_ui._show_success(str(final_output))
                result['completion_gui_ms']=(time.perf_counter()-shown)*1000
                pump(.2);export_ui.grab().save(str(out/'completion.png'))
                result['completion_preview']=not export_ui.success_page.preview.image.isNull()
                assert result['completion_preview'], 'validated export must supply its completion thumbnail'
                result['completion_values']={key:label.text() for key,label in export_ui.success_page.values.items()}
                assert result['completion_values']['帧率']=='60 fps', result['completion_values']
                assert result['completion_values']['分辨率']=='1920 × 1080', result['completion_values']
                assert result['completion_values']['平均码率'] != '—', result['completion_values']
                assert export_ui._last_job.completion_metadata['elapsed_seconds'] > 0
                if completion_audit:
                    from .export_completion_audit import verify
                    result['completion_audit'] = verify(export_ui, out)
                    assert result['completion_audit']['passed'], result['completion_audit']['checks']
            export_ui.close(); export_ui.deleteLater()
            assert 'export' in result, result.get('export_error')
            result['passed'] = True
        except Exception:
            result['error'] = traceback.format_exc()
        finally:
            page.undo_stack.setClean()
            (out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf8')
            QTimer.singleShot(200, window.close)
    QTimer.singleShot(300, run)
