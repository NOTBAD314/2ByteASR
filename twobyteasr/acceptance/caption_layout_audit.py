"""Fixed caption fixtures and production-video evidence, never user projects.

The reference pictures use the production LIVE rasterizer, not a screenshot
claim. Actual Studio/EXE captures can be paired by the same case and timestamp.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def fixtures(folder):
    """Write immutable project inputs; source video is created when rendering."""
    from ..projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, SubtitleStyle, save_project
    from ..caption_design.visual_design_graph import graph_from_style_recipe
    from ..caption_style.style_recipe import StyleRecipe

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    chinese = '这句字幕需要自动换行，并完整保留每一个字；预览和最终导出必须采用相同的排版结果。'
    english = 'Every word and every space must survive automatic wrapping.\nManual breaks remain visible in the final encoded video.'
    specs = [
        ('native-chinese', 'native', chinese*2, (1920, 1080), (1920, 1080), False),
        ('native-english-manual', 'native', english, (1920, 1080), (1280, 720), False),
        ('static-bilingual-marks-name', 'static', chinese, (1920, 1080), (1920, 1080), True),
        ('dynamic-letter-stagger', 'legacy', chinese, (1920, 1080), (1920, 1080), False),
        ('dynamic-letter-stagger-half', 'legacy', chinese, (1920, 1080), (960, 540), False),
        ('dynamic-graph-rich', 'graph', english, (1920, 1080), (1920, 1080), False),
        ('portrait-native', 'native', '竖屏字幕也必须使用真实画布宽高。\n手动换行和自动换行同时保留。', (1080, 1920), (540, 960), False),
        ('portrait-dynamic', 'graph', '竖屏字幕不应使用十六比九高度，长句应在画面内继续换行并保留完整文字。', (1080, 1920), (540, 960), False),
        ('changed-aspect-native', 'native', '输出改为竖屏后，字幕应重新换行。', (1920, 1080), (540, 960), False),
        ('changed-aspect-bilingual', 'graph', '输出改为竖屏后，双语字幕重新换行。', (1920, 1080), (540, 960), True),
        ('native-bilingual-marks-rotated', 'native', chinese, (1920, 1080), (1920, 1080), True),
    ]
    cases = []
    for name, route, text, canvas, output, bilingual in specs:
        style = SubtitleStyle('default', 'Layout evidence', font_family='Microsoft YaHei',
                              font_size=88, primary_color='#FFFFFFFF', outline_width=2,
                              outline_color='#FF202020', shadow=0)
        p = SubtitleProject(
            media=StudioMedia(str(folder/f'media-{canvas[0]}x{canvas[1]}.mp4'), duration_ms=3000,
                              width=canvas[0], height=canvas[1]),
            styles=[style], speakers=[StudioSpeaker('speaker', '主播')],
            cues=[StudioCue('long', 0, 3000, text, speaker_id='speaker')],
            render_settings={'play_res_x': canvas[0], 'play_res_y': canvas[1]},
        )
        if route != 'native':
            recipe = StyleRecipe(name='Layout evidence', engine='remotion', motion={},
                typography={'fontFamily': style.font_family, 'fontSize': style.font_size},
                colors={'fill': '#FFFFFFFF'}, background={'enabled': False})
            if route == 'static':
                recipe.colors['fill'] = {'type': 'linear', 'angle': 0, 'stops': [
                    {'color': '#FFFFFFFF', 'pos': 0}, {'color': '#FF95DBEF', 'pos': 1}]}
            if route == 'legacy':
                recipe.motion = {'mode': 'explicit', 'entrance': {'type': 'letter_stagger', 'duration_ms': 400},
                                 'exit': {'type': 'fade', 'duration_ms': 300}}
            if route == 'graph':
                recipe.visual_graph = graph_from_style_recipe(recipe).to_dict()
                # Actual curated glyph choreography, without invented speech timing.
                p.cues[0].effect_id = 'layout-rich'
                p.effects['layout-rich'] = {'entry': {'type': 'char_rise', 'duration': 400},
                                            'exit': {'type': 'fade', 'duration': 250}}
            p.style_recipes['default'] = recipe.to_dict()
        if bilingual:
            p.studio_state.update(bilingual={'mode': 'bilingual'}, show_speaker_names=True)
            p.generation_metadata['translations'] = {'long': ('The output uses a new layout.' if name.startswith('changed-aspect')
                else 'The translated line also wraps inside the same design canvas.')}
            p.cues[0].appearance_override['text_marks'] = [{'start': 3, 'end': 14, 'bold': True, 'highlight': True}]
        if name == 'native-bilingual-marks-rotated':
            p.styles[0].position_y = 730
            p.styles[0].outline_width = 5
            p.styles[0].shadow = 4
            p.cues[0].transform.update(rotation=12., _canvas_transform=True, scale_x=100., scale_y=100.)
        path = folder/(name+'.2byteproj')
        save_project(p, path)
        cases.append(dict(id=name, route=route, project=str(path), canvas=list(canvas), output=list(output),
                          sample_ms=[150, 650, 1500, 2700], project_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    manifest = dict(version=1, duration_seconds=3, fps=30, cases=cases,
                    evidence='production export and decoded frames; LIVE reference is a raster, not a GUI capture')
    (folder/'cases.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), 'utf-8')
    return manifest


def _bands(image):
    """Visible glyph rows on the fixture's black background, in physical px."""
    import numpy as np
    pixels = np.asarray(image.convert('RGBA')).astype(np.float32)
    rgb = pixels[:, :, :3]*pixels[:, :, 3:4]/255
    mask = rgb.max(axis=2) > 100
    # Low-opacity entrances are still visible text. Strong-ink rows are only
    # compared at the settled sample; presence/bounds include the faded ink.
    visible = rgb.max(axis=2) > 5
    ys, xs = np.where(visible)
    if not len(xs):
        return {'bounds': None, 'bands': [], 'line_boxes': [], 'visible_pixels': 0}
    rows = np.where(mask.sum(axis=1) >= max(3, image.width*.001))[0]
    groups = []
    for row in rows:
        if not groups or row > groups[-1][-1]+4:
            groups.append([int(row)])
        else:
            groups[-1].append(int(row))
    boxes = []
    for row in groups:
        columns = np.where(mask[row[0]:row[-1]+1].any(axis=0))[0]
        boxes.append([int(columns.min()), row[0], int(columns.max()+1), row[-1]+1])
    return dict(bounds=[int(xs.min()), int(ys.min()), int(xs.max()+1), int(ys.max()+1)],
                bands=[[row[0], row[-1]+1] for row in groups], line_boxes=boxes,
                visible_pixels=int(visible.sum()))


def _audit_fonts(project):
    """Offscreen Qt lacks the normal Windows entry's system font database.

    Register the authored file privately in this process and prove real glyphs
    exist before accepting any raster comparison. This is audit setup only.
    """
    from PySide6.QtGui import QFont, QFontDatabase, QRawFont
    from ..caption_style.font_metadata import resolve_local_face
    result = []
    from dataclasses import replace
    marked_bold = any(mark.get('bold') for cue in project.cues
                      for mark in (cue.appearance_override or {}).get('text_marks', []))
    styles = list(project.styles)
    if marked_bold:
        styles += [replace(style, font_weight=700, bold=True, font_style_name='') for style in project.styles]
    for style in styles:
        face, warning = resolve_local_face(style.font_family, style.font_weight, style.font_style_name,
                                            style.bold, style.font_file, style.font_face_index)
        font_id = QFontDatabase.addApplicationFont(face.file)
        font = QFont(face.family); font.setStyleName(face.style); font.setPixelSize(72)
        font.setWeight(QFont.Weight(face.weight))
        raw = QRawFont.fromFont(font)
        sample = '字幕Ag'
        valid = font_id >= 0 and raw.isValid() and all(raw.glyphIndexesForString(sample))
        if not valid:
            raise RuntimeError('Audit font has missing glyphs: '+face.file)
        result.append(dict(file=face.file, sha256=hashlib.sha256(Path(face.file).read_bytes()).hexdigest(),
                           family=raw.familyName(), registered_families=QFontDatabase.applicationFontFamilies(font_id),
                           glyphs_valid=valid, sample=sample, warning=warning))
    return result


def _live_frame(project, milliseconds, width, height):
    from types import SimpleNamespace
    from PySide6.QtGui import QColor, QImage, QPainter
    from ..caption_style.bilingual_layout import materialize_display_project
    from ..caption_style.visual_snapshot import build_visual_cue_snapshot
    from ..rendering.caption_scene import SceneRasterizer
    shown = materialize_display_project(project)
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor('#000000'))
    painter = QPainter(image)
    records = []
    raster = SceneRasterizer()
    try:
        for cue in shown.cues:
            if not cue.start_ms <= milliseconds < cue.end_ms:
                continue
            snapshot = build_visual_cue_snapshot(shown, cue.id, width=width, height=height, fps=30)
            painter.drawImage(0, 0, raster.native_frame(
                SimpleNamespace(snapshot=snapshot, snapshot_hash=snapshot.stable_hash()),
                milliseconds-cue.start_ms, width, height))
            records.append(dict(cue_id=cue.id, text=snapshot.text,
                                line_count=snapshot.resolved_caption.line_count,
                                layout=getattr(snapshot.resolved_caption, 'layout', {}),
                                snapshot_hash=snapshot.stable_hash()))
    finally:
        painter.end()
        raster.close()
    return image, records


def render_matrix(manifest_path, output, *, selected=None):
    """Call normal production exporters, fully decode, retain every evidence tier."""
    import subprocess
    import av
    from PIL import Image
    from PySide6.QtWidgets import QApplication
    from ..projects.studio_project import load_project
    from ..rendering.ass_compiler import compile_ass
    from ..rendering.advanced_renderer import AdvancedRendererBackend, compile_composition_data, split_renderer_cues
    from ..exports.static_caption_export import static_graph_project
    from ..exports.studio_render import RenderJob, RenderSettings, run_render_job
    from ..system.platform_media import ffmpeg_tool

    app = QApplication.instance() or QApplication([])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(Path(manifest_path).read_text('utf-8'))
    results = []
    ffmpeg = ffmpeg_tool('ffmpeg')
    for case in manifest['cases']:
        if selected and case['id'] not in selected:
            continue
        folder = output/case['id']; folder.mkdir()
        project = load_project(case['project'])
        fonts = _audit_fonts(project)
        source = Path(project.media.path)
        if not source.is_file():
            subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                f'color=c=black:s={project.media.width}x{project.media.height}:r=30:d=3',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(source)], check=True)
        width, height = case['output']
        ass = folder/'captions.ass'
        from ..exports.export_timeline import write_export_ass
        from inspect import signature
        if 'width' in signature(write_export_ass).parameters:
            project = write_export_ass(project, ass, width=width, height=height, require_layout_fit=True)
        else:
            project = write_export_ass(project, ass)
        movie = folder/'export.mp4'
        from ..exports.video_export import capture_video_graph
        job = RenderJob(str(source), str(ass), str(movie),
                        settings=RenderSettings(encoder='libx264', preset='ultrafast', width=width, height=height,
                                                fps=30, audio_codec='none'),
                        start_seconds=0, duration_seconds=3, overwrite_existing=False,
                        video_graph=capture_video_graph(project), export_project_data=project.to_dict(),
                        export_context={'caption_canvas': getattr(project, '_output_canvas', {})})
        advanced = bool(split_renderer_cues(project)[1])
        route = 'static-advanced' if advanced and static_graph_project(project) else 'dynamic-advanced' if advanced else 'ass'
        events = []
        if advanced:
            props = compile_composition_data(project, width=width, height=height, fps=30,
                                             start_seconds=0, duration_seconds=3)
            (folder/'composition.json').write_text(json.dumps(props, ensure_ascii=False, indent=2), 'utf-8')
            AdvancedRendererBackend().render(project, ffmpeg, job, trace=lambda event, value: events.append([event, value]))
        else:
            run_render_job(ffmpeg, job)
        selected_frames = {round(t/1000*30): t for t in case['sample_ms']}
        frames = 0; samples = []
        with av.open(str(movie)) as container:
            for index, frame in enumerate(container.decode(video=0)):
                frames += 1
                if index not in selected_frames:
                    continue
                milliseconds = float(frame.pts*frame.time_base*1000)
                rendered = frame.to_image()
                rendered.save(folder/f'export-{milliseconds:.0f}ms.png')
                live, snapshots = _live_frame(project, milliseconds, width, height)
                path = folder/f'live-raster-{milliseconds:.0f}ms.png'; live.save(str(path))
                with Image.open(path) as reference:
                    live_metrics, export_metrics = _bands(reference), _bands(rendered)
                settled = abs(milliseconds-1500) < 25
                deltas = [[b-a for a,b in zip(left,right)] for left,right in
                          zip(live_metrics['line_boxes'], export_metrics['line_boxes'])]
                samples.append(dict(ms=milliseconds, live=live_metrics, export=export_metrics, snapshots=snapshots,
                                    settled=settled,
                                    line_boundary_deltas_px=deltas,
                                    line_widths_match=all(abs(row[2]-row[0]) <= max(5, width*.01) for row in deltas),
                                    rows_equal=len(live_metrics['bands']) == len(export_metrics['bands']),
                                    text_present=bool(export_metrics['visible_pixels']),
                                    bounds_inside=bool(export_metrics['bounds'] and export_metrics['bounds'][0] > 0
                                        and export_metrics['bounds'][1] > 0 and export_metrics['bounds'][2] < width
                                        and export_metrics['bounds'][3] < height)))
        report = dict(id=case['id'], route=route, output=[width, height], decoded_frames=frames,
                      fonts=fonts,
                      movie=str(movie), movie_sha256=hashlib.sha256(movie.read_bytes()).hexdigest(), samples=samples,
                      functional_pass=frames == 90 and all(s['text_present'] and s['bounds_inside']
                          and (not s['settled'] or s['rows_equal'] and s['line_widths_match']) for s in samples),
                      functional_scope='decode, visible glyphs, settled line counts/widths and containment; complete-text visual review required',
                      gui_verified=False, measurement_valid=True)
        results.append(report)
        (folder/'events.json').write_text(json.dumps(events, ensure_ascii=False, indent=2, default=str), 'utf-8')
        (output/'result.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf-8')
        print(json.dumps({k: v for k, v in report.items() if k != 'samples'}, ensure_ascii=False), flush=True)
    return bool(results) and all(row['functional_pass'] for row in results)


def select_combo_value(combo, value):
    """Select by value, not PySide's opaque Python-object QVariant identity."""
    def matches(item):
        if isinstance(value, (tuple, list)):
            return isinstance(item, (tuple, list)) and tuple(item) == tuple(value)
        return item == value
    index = next((i for i in range(combo.count()) if matches(combo.itemData(i))), -1)
    if index < 0:
        raise AssertionError(f'Combo value {value!r} not found: {[combo.itemData(i) for i in range(combo.count())]!r}')
    combo.setCurrentIndex(index)
    if not matches(combo.currentData()):
        raise AssertionError(f'Combo selection did not persist: {combo.currentData()!r}')
    return dict(index=index, value=combo.currentData(), value_type=type(combo.currentData()).__name__)


def select_output_resolution(workspace, width, height):
    workspace.custom_resolution_width.setValue(width)
    workspace.custom_resolution_height.setValue(height)
    selection = select_combo_value(workspace.resolution, (-1, -1))
    settings = workspace._render_settings(commit=False)
    if (settings.width, settings.height) != (width, height):
        raise AssertionError(f'Output controls requested {width}x{height}, actual settings {settings.width}x{settings.height}')
    return dict(selection, requested=[width, height], settings=[settings.width, settings.height])


def snapshot_layout_receipt(snapshots):
    return [dict(cue_id=s.cue_id, text=s.text, snapshot_hash=s.stable_hash(), resolution=list(s.resolution),
                 style_hash=s.resolved_caption.style_hash, layout=s.resolved_caption.layout,
                 position=[s.position_x, s.position_y], word_animation=s.word_animation) for s in snapshots]


def check_video_dimensions(metadata, expected):
    video = next((s for s in metadata.get('streams', []) if s.get('codec_type') == 'video'), None)
    return bool(video and [video.get('width'), video.get('height')] == list(expected))


def layout_sample_schedule(case, *, fps=30, duration_ms=3000):
    """Bind requested sample times to encoded frame numbers before GUI capture."""
    import math
    if not math.isfinite(float(fps)) or fps <= 0:
        raise ValueError('A positive finite sample FPS is required')
    result = []
    for requested in case.get('sample_ms') or [150, 650, 1500, 2700]:
        value = float(requested)
        if not math.isfinite(value) or not 0 <= value < duration_ms:
            raise ValueError('Sample time must be inside the fixture duration')
        frame = round(value * fps / 1000)
        if frame >= round(duration_ms * fps / 1000):
            raise ValueError('Sample rounds beyond the final encoded frame')
        result.append(dict(requested_ms=value, frame=frame))
    return result


def semantic_layout_receipt(receipts):
    """Complete display semantics independent of raster size and animation alpha."""
    return [{key: row[key] for key in ('cue_id', 'text', 'layout', 'position', 'word_animation')}
            for row in receipts]


def decode_gui_layout_samples(movie, folder, case):
    """Decode every final frame; retain requested frames at their actual PTS."""
    import av
    plan = layout_sample_schedule(case)
    wanted = {item['frame'] for item in plan}
    actual = {}
    count = 0
    with av.open(str(movie)) as container:
        stream = container.streams.video[0]
        stream.thread_count = 2
        for index, frame in enumerate(container.decode(stream)):
            count += 1
            if index not in wanted:
                continue
            if frame.pts is None:
                raise ValueError('The final encoded sample has no timestamp')
            path = folder / f'gui-export-frame-{index:03d}.png'
            frame.to_image().save(path)
            actual[index] = dict(frame=index, pts=frame.pts, time_base=str(frame.time_base),
                actual_ms=float(frame.pts * frame.time_base * 1000),
                file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                rgb_sha256=hashlib.sha256(frame.to_ndarray(format='rgb24').tobytes()).hexdigest(),
                dimensions=[frame.width, frame.height])
    if set(actual) != wanted:
        raise ValueError('Final encoding is missing one or more requested samples')
    return dict(decoded_frames=count, movie_sha256=hashlib.sha256(Path(movie).read_bytes()).hexdigest(),
                samples=[dict(item, **actual[item['frame']]) for item in plan])


def scene_sample_receipt(page):
    scene = getattr(page, '_caption_scene', None)
    if not getattr(scene, 'active', False):
        return dict(active=False, owner='native-ass-or-legacy-preview')
    token = getattr(scene, 'token', None)
    trace = scene.trace()
    metric = scene.metrics[-1] if scene.metrics and getattr(scene, 'last_result_token', None) == token else {}
    return dict(trace, active=True, current=token is not None and scene.still_current(token),
                sample_ms=metric.get('sample_ms'), token=token)


def gui_layout_sample_ready(page, milliseconds):
    from ..studio.studio_readiness import player_surface_ready, caption_scene_ready
    if abs(page.timeline.playhead_ms - milliseconds) > 2 or not player_surface_ready(page):
        return False
    scene = scene_sample_receipt(page)
    if not scene['active']:
        return True
    # Early entrance/exit samples may be fully transparent. Readiness concerns
    # current rows/tokens, never a demand that every glyph is already visible.
    return bool(scene['current'] and caption_scene_ready(scene)
        and scene['sample_ms'] is not None and abs(float(scene['sample_ms']) - milliseconds) <= 2)


def capture_gui_layout_samples(window, page, folder, case, output_project, expected_receipt, decoded, check):
    """Capture actual Studio at the final file's PTS, with explicit canvas tier."""
    from ..projects.studio_project import save_project
    from ..exports.output_caption_layout import layout_snapshots
    from ..studio.studio_readiness import player_wait_snapshot
    from .ai_cleanup_extended_audit import observe_project_open_entry
    from .blank_project_audit import _capture
    original = page.project
    original_canvas = [original.render_settings.get('play_res_x', 1920), original.render_settings.get('play_res_y', 1080)]
    output_canvas = [output_project.render_settings.get('play_res_x', 1920), output_project.render_settings.get('play_res_y', 1080)]
    derived = original_canvas != output_canvas
    reopening = dict(required=derived, performed=False, before_generation=page.session.generation,
                     old_object_id=id(original), entry_calls=[])
    if derived:
        # The visible export card is explicitly static; do not mislabel four
        # copies of that card as animated preview. Open the exact derived
        # caption canvas as an isolated project through normal GUI hydration.
        path = save_project(output_project, folder / 'derived-output-preview.2byteproj')
        controller = page.project_controller
        with observe_project_open_entry(controller) as entry_calls:
            window.open_studio_project(str(path))
            yield lambda: (page.project is not None and page.project is not original
                and str(page.project_path) == str(Path(path).resolve())
                and page._readiness.ready and not page._readiness.active)
        reopening.update(performed=True, entry_calls=list(entry_calls), project_path=str(Path(page.project_path).resolve()),
                         reopened_generation=page.session.generation, new_object_id=id(page.project))
    current_canvas = [page.project.render_settings.get('play_res_x', 1920), page.project.render_settings.get('play_res_y', 1080)]
    check(case['id']+' sampled preview uses output design canvas', current_canvas == output_canvas,
          dict(actual=current_canvas, expected=output_canvas, derived_project=derived))
    if current_canvas != output_canvas:
        raise AssertionError('Refusing a different-canvas animated preview comparison')
    expected = semantic_layout_receipt(expected_receipt)
    samples = []
    for index, encoded in enumerate(decoded['samples']):
        milliseconds = encoded['actual_ms']
        page.video.set_paused(True)
        page.select_cue('long')
        page._seek(milliseconds / 1000)
        yield lambda at=milliseconds: gui_layout_sample_ready(page, at)
        receipt = snapshot_layout_receipt(layout_snapshots(page.project))
        complete_semantics = semantic_layout_receipt(receipt) == expected
        check(case['id']+f' sample {index}: complete layout semantics', complete_semantics)
        truth = page.render_truth_probe(force=True)
        scene = scene_sample_receipt(page)
        preview = folder / f'studio-preview-sample-{index:02d}.png'
        page.video.controller.screenshot_to_file(preview)
        _capture(window, folder / f'studio-window-sample-{index:02d}.png')
        if not preview.is_file():
            raise AssertionError('The actual composed Studio sample was not captured')
        from PIL import Image
        with Image.open(preview) as picture:
            rgb = picture.convert('RGB')
            preview_pixels = dict(preview_dimensions=list(rgb.size),
                preview_rgb_sha256=hashlib.sha256(rgb.tobytes()).hexdigest())
        row = dict(encoded, requested_preview_ms=milliseconds, actual_playhead_ms=page.timeline.playhead_ms,
            preview=preview.name, preview_sha256=hashlib.sha256(preview.read_bytes()).hexdigest(),
            preview_kind='actual Studio/mpv screenshot of derived output project' if derived else 'actual Studio/mpv screenshot',
            original_canvas=original_canvas, sampled_canvas=current_canvas, render_truth=truth,
            gui_reopen=dict(reopening), **preview_pixels,
            scene=scene, player=player_wait_snapshot(page), layout=receipt,
            complete_layout_semantics=complete_semantics,
            visible_text_rule='Do not require all glyphs during entrance/exit; review phase against the paired encoded frame.',
            visual_review='PENDING')
        samples.append(row)
        (folder / 'gui-animation-samples.json').write_text(json.dumps(samples, ensure_ascii=False, indent=2, default=str), 'utf8')
    return samples


def start(window, output):
    """Capture the real source/frozen Studio and its output-layout controls."""
    import os
    import time
    import traceback
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.build_identity import load_build_identity
    from ..exports.output_caption_layout import layout_snapshots
    from .blank_project_audit import _capture

    output = Path(output)
    manifest = json.loads(Path(os.environ['TWOBYTEASR_LAYOUT_MANIFEST']).read_text('utf-8'))
    chosen = set(filter(None, os.environ.get('TWOBYTEASR_LAYOUT_CASES', '').split(',')))
    cases = [case for case in manifest['cases'] if not chosen or case['id'] in chosen]
    result = dict(passed=False, checks=[], cases=[], identity=load_build_identity().to_dict(),
                  executable=__import__('sys').executable, pid=os.getpid())
    def save():
        (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')
    def check(name, passed, detail=None):
        result['checks'].append(dict(name=name, passed=bool(passed), detail=detail))
        save()
    page = window.studio_page
    def steps():
        window.showNormal(); window.resize(1540, 1000)
        for case in cases:
            folder = output/case['id']; folder.mkdir()
            decoded = None
            window.open_studio_project(case['project'])
            yield lambda: (page.project is not None and str(page.project_path) == str(Path(case['project']).resolve())
                           and page._readiness.ready and not page._readiness.active)
            page.video.set_paused(True)
            page.select_cue('long'); page._seek(1.5)
            yield 1.2
            check(case['id']+' actual preview position', abs(page.timeline.playhead_ms-1500) <= 34,
                  {'requested_ms': 1500, 'actual_ms': page.timeline.playhead_ms})
            before = [(cue.id, cue.text, cue.start_ms, cue.end_ms) for cue in page.project.cues]
            original_layout = snapshot_layout_receipt(layout_snapshots(page.project))
            original_canvas = [page.project.render_settings.get('play_res_x', 1920), page.project.render_settings.get('play_res_y', 1080)]
            _capture(window, folder/'studio-window.png')
            page.video.controller.screenshot_to_file(folder/'studio-mpv-composed.png')
            truth = page.render_truth_probe(force=True)
            (folder/'render-truth.json').write_text(json.dumps(truth, ensure_ascii=False, indent=2, default=str), 'utf-8')
            QTest.mouseClick(page.studio_render_button, Qt.MouseButton.LeftButton)
            yield lambda: page.export_workspace is not None and page.export_workspace.isVisible()
            workspace = page.export_workspace
            selection = select_output_resolution(workspace, *case['output'])
            check(case['id']+' output controls selected', tuple(workspace.resolution.currentData() or ()) == (-1, -1), selection)
            workspace._seek_preview(1500)
            yield .4
            changed = case['output'][0]*original_canvas[1] != case['output'][1]*original_canvas[0]
            card = workspace.output_layout_preview
            check(case['id']+' layout card visibility', card.isVisible() == changed)
            if changed:
                workspace.preview_scroll.ensureWidgetVisible(card)
                yield .2
                check(case['id']+' layout pixels', card.image.pixmap() is not None and not card.image.pixmap().isNull())
                card.grab().save(str(folder/'output-layout-card.png'))
            _capture(window, folder/'export-setup-window.png')
            frozen = workspace._output_layout_project
            snapshots = layout_snapshots(frozen)
            preview_receipt = snapshot_layout_receipt(snapshots)
            info = getattr(frozen, '_output_canvas', {})
            expected_design = [round(original_canvas[1]*case['output'][0]/case['output'][1]), original_canvas[1]] if changed else original_canvas
            canvas_correct = info.get('output') == case['output'] and info.get('design') == expected_design and info.get('relayout') == changed
            check(case['id']+' derived output canvas', canvas_correct, {'actual': info, 'expected_design': expected_design})
            if not canvas_correct:
                raise AssertionError('Refusing to export a different output canvas than the requested fixture')
            if changed:
                old_lines = {row['cue_id']: row['text'] for row in original_layout}
                check(case['id']+' fixture line breaks actually reflowed',
                      any(old_lines.get(row['cue_id']) != row['text'] for row in preview_receipt),
                      {'before': old_lines, 'after': {row['cue_id']: row['text'] for row in preview_receipt}})
            (folder/'output-layout.json').write_text(json.dumps(
                [s.to_dict() for s in snapshots], ensure_ascii=False, indent=2, default=str), 'utf-8')
            (folder/'preview-layout-receipt.json').write_text(json.dumps(preview_receipt, ensure_ascii=False, indent=2), 'utf-8')
            check(case['id']+' canonical design preserved', original_canvas == [
                page.project.render_settings.get('play_res_x', 1920), page.project.render_settings.get('play_res_y', 1080)])
            check(case['id']+' canonical text preserved', before == [(cue.id, cue.text, cue.start_ms, cue.end_ms) for cue in page.project.cues])
            if os.environ.get('TWOBYTEASR_LAYOUT_RENDER') == '1':
                workspace.directory.setText(str(folder))
                workspace.filename.setText('gui-export')
                workspace.filename_prefix.setText(''); workspace.filename_suffix.setText('')
                select_combo_value(workspace.encoder, 'libx264')
                select_combo_value(workspace.fps, 30.0)
                select_combo_value(workspace.audio, 'none')
                final_settings = workspace._render_settings(commit=False)
                settings_correct = [final_settings.width, final_settings.height] == case['output']
                check(case['id']+' settings immediately before export',
                      settings_correct,
                      {'resolution_data': workspace.resolution.currentData(), 'actual': [final_settings.width, final_settings.height]})
                if not settings_correct:
                    raise AssertionError('Output resolution changed before export; refusing an unintended video')
                workspace.export_button.click()
                yield lambda: not workspace._running
                movie = folder/'gui-export.mp4'
                check(case['id']+' actual GUI export', movie.is_file(), workspace._last_failure)
                if movie.is_file():
                    exported_receipt = snapshot_layout_receipt(layout_snapshots(workspace._export_project))
                    check(case['id']+' preview/export snapshot and breaks', preview_receipt == exported_receipt)
                    (folder/'export-layout-receipt.json').write_text(json.dumps(exported_receipt, ensure_ascii=False, indent=2), 'utf-8')
                    from ..system.processes import run_hidden_subprocess
                    probe = run_hidden_subprocess([str(workspace.ffmpeg.with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')),
                        '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(movie)],
                        purpose='read actual GUI caption export dimensions', capture_output=True, check=True, timeout=15)
                    metadata = json.loads(probe.stdout)
                    (folder/'ffprobe.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), 'utf-8')
                    check(case['id']+' final encoded dimensions', check_video_dimensions(metadata, case['output']),
                          {'expected': case['output'], 'streams': metadata.get('streams', [])})
                    run_hidden_subprocess([str(workspace.ffmpeg), '-hide_banner', '-loglevel', 'error', '-y', '-ss', '1.5',
                        '-i', str(movie), '-frames:v', '1', str(folder/'gui-export-1500ms.png')],
                        purpose='decode corresponding GUI caption export frame', check=True, timeout=20)
                    decoded = decode_gui_layout_samples(movie, folder, case)
                    check(case['id']+' complete final video decode', decoded['decoded_frames'] == 90, decoded)
            page._close_export_workspace()
            yield .2
            animation_samples = []
            if decoded is not None:
                animation_samples = yield from capture_gui_layout_samples(window, page, folder, case,
                    frozen, preview_receipt, decoded, check)
            result['cases'].append(dict(id=case['id'], original_canvas=original_canvas,
                                       selected_controls=selection,
                                       output_canvas=getattr(frozen, '_output_canvas', {}),
                                       preview='mpv composed screenshot and actual Qt export layout card',
                                       animation_samples=len(animation_samples), visual_review='PENDING',
                                       decoded_frames=decoded['decoded_frames'] if decoded else None,
                                       movie_sha256=decoded['movie_sha256'] if decoded else None))
        check('all requested cases ran', len(result['cases']) == len(cases))

    pending = None; deadline = 0.; began = time.monotonic(); busy = False
    sequence = steps()
    timer = QTimer(window); timer.setInterval(25)
    def finish(error=None):
        timer.stop()
        try:
            sequence.close()  # Release any class-level entry observer on timeout/cancel too.
        except Exception:
            result.setdefault('cleanup_errors', []).append(traceback.format_exc())
        if error:
            result['error'] = error
        result['passed'] = (bool(result['checks']) and not error and not result.get('cleanup_errors')
                            and all(row['passed'] for row in result['checks']))
        save()
        if page.export_workspace is not None and not page.export_workspace._running:
            page._close_export_workspace()
        page.undo_stack.setClean(); window.close()
        QTimer.singleShot(200, QApplication.instance().quit)
    def tick():
        nonlocal pending, deadline, busy
        if busy:
            return
        busy = True
        try:
            if time.monotonic()-began > 900:
                raise TimeoutError('Caption layout GUI acceptance timed out')
            if callable(pending):
                if not pending():
                    return
            elif time.monotonic() < deadline:
                return
            value = next(sequence)
            pending = value if callable(value) else None
            deadline = time.monotonic()+(float(value) if not callable(value) else 0)
        except StopIteration:
            finish()
        except Exception:
            finish(traceback.format_exc())
        finally:
            busy = False
    def shutdown():
        result['gui_shutdown'] = True; save()
    QApplication.instance().aboutToQuit.connect(shutdown)
    timer.timeout.connect(tick); timer.start()
    window._caption_layout_audit_timer = timer
