"""Real-window acceptance for video seam transition looks (2026-10-17).

Drives a standalone Studio page on generated red/blue clips: Ctrl+D, the
look cards, direction and strength, undo/redo, default look, playback through
the seam, save/reload, a narrow window, and preview-vs-export frames.
Run through ``scripts/verify_video_transition_looks_headed.py``.
"""
from __future__ import annotations

import copy
import json
import threading
import time
import traceback
from pathlib import Path

SEAM_MS = 3000            # red-1 | blue on V2; Ctrl+D's default 500 ms spans 2750–3250
SECOND_SEAM_MS = 6000     # blue | red-2
SAMPLES_MS = (2800, 3000, 3200)


def make_fixture(output: Path, ffmpeg: Path) -> Path:
    from ..system.processes import run_hidden_subprocess
    from ..projects.studio_project import SubtitleProject, StudioMedia, StudioCue, VideoTrack, VideoClip, save_project
    from ..timeline.studio_media_pool import add_media_asset, sync_linked_av_contract
    from ..timeline.studio_edit_sequence import sequence_of
    tints = {'red': 'rr=1:rg=.4:rb=.4:gr=.12:gg=.12:gb=.12:br=.12:bg=.12:bb=.12',
             'blue': 'rr=.12:rg=.12:rb=.12:gr=.2:gg=.2:gb=.2:br=.4:bg=.4:bb=1'}
    paths = {}
    for name, mix in tints.items():
        paths[name] = output/f'{name}.mp4'
        if not paths[name].exists():
            run_hidden_subprocess([str(ffmpeg), '-v', 'error', '-y', '-f', 'lavfi', '-i',
                                   f'testsrc2=s=640x360:r=30:d=10,colorchannelmixer={mix}',
                                   '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(paths[name])],
                                  purpose='transition look fixture', check=True, timeout=60)
    project = SubtitleProject(media=StudioMedia(path=str(paths['red']), duration_ms=10000, width=640, height=360),
                              cues=[StudioCue('c1', 400, 1800, '转场效果验收', 'S1')])
    project.validate()
    # Like the selection audit: V1 (the recording projection) is off; the edit is on V2.
    project.video_tracks[0].locked = True
    project.video_tracks[0].enabled = False
    sequence_of(project).video_track_locked = True
    red = project.media_pool[0]
    red.offline = False
    red.video_metadata = dict(red.video_metadata or {}, width=640, height=360, fps=30, has_video=True)
    red.audio_metadata = dict(has_audio=False)
    blue = add_media_asset(project, str(paths['blue']), duration_ms=10000,
                           video_metadata=dict(width=640, height=360, fps=30, has_video=True),
                           audio_metadata=dict(has_audio=False))
    # VideoClip(id, asset, source_in, source_out, timeline_in, timeline_out)
    project.video_tracks.append(VideoTrack('V2', '剪辑', z_index=1, clips=[
        VideoClip('red-1', red.asset_id, 500, 3500, 0, SEAM_MS),
        VideoClip('blue', blue.asset_id, 2000, 5000, SEAM_MS, SECOND_SEAM_MS),
        VideoClip('red-2', red.asset_id, 6000, 9000, SECOND_SEAM_MS, 9000)]))
    sync_linked_av_contract(project)
    project.studio_state.update(project_name='转场效果验收', playhead_ms=1000)
    return save_project(project, output/'input.2byteproj')


def _small(image):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    import numpy as np
    scaled = image.convertToFormat(QImage.Format.Format_RGB32).scaled(
        160, 90, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    rows = np.frombuffer(scaled.constBits(), np.uint8, count=scaled.sizeInBytes()).reshape(90, scaled.bytesPerLine())
    bgra = rows[:, :160*4].reshape(90, 160, 4)
    return bgra[:, :, [2, 1, 0]].astype(np.float32)  # RGB


def run_window(output: Path, theme: str = 'grape', export: bool = True, *, embedded: bool = False):
    """``embedded``: inside a normal (frozen) app's event loop; the result
    is written on quit (scenario ``video-transition-looks``)."""
    import sys
    from PySide6.QtCore import QTimer, Qt, QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    import numpy as np
    from ..studio.studio_ui import SubtitleStudioPage
    from ..design.theme_manager import apply_application_theme
    from ..projects.studio_project import save_project, load_project
    from ..timeline.studio_transitions import (VIDEO_LOOKS, DEFAULT_LOOK_KEY, normalize_look, transition_records,
                                               set_transition)
    from ..system.platform_media import ffmpeg_tool
    from .blank_project_audit import _capture
    ffmpeg = ffmpeg_tool()
    app = QApplication.instance() or QApplication([])
    apply_application_theme(app, theme)
    source = make_fixture(output, ffmpeg)
    page = SubtitleStudioPage(); page.resize(1520, 960); page.show()
    result = dict(passed=False, theme=theme, checks=[], screenshots=[], preview=[], export=[],
                  frozen=bool(getattr(sys, 'frozen', False)), executable=sys.executable, ffmpeg=str(ffmpeg), scope=(
        'Standalone Studio page on a private desktop; generated red/blue testsrc2 clips; real Ctrl+D, card clicks, '
        'undo/redo, playback, save/reload; preview raster = the compositor image published to mpv; export = '
        'production run_render_job + decoded frames.'))
    previews = {}

    def check(name, value, detail=None):
        result['checks'].append(dict(name=name, passed=bool(value), detail=detail))

    def shot(widget, name):
        target = output/f'{theme}-{name}.png'
        _capture(widget, target)
        result['screenshots'].append(str(target))

    def records():
        return transition_records(page.project, 'video')

    def seam(ms):
        return next((t for t in records() if t.get('edge') == 'seam' and t['start_ms'] < ms < t['end_ms']), None)

    def frames_ready(ms):
        scene = page.video_compositor
        if abs(page.timeline.playhead_ms-ms) > 1 or len(page._multitrack_preview_layers(ms)) < 2 or len(scene._layers) < 2:
            return False
        for layer in scene._layers:
            runtime = scene._players.get(str(layer['clip_id']))
            image = getattr(runtime, 'image', None)
            if image is None or image.isNull() or abs(int(getattr(runtime, 'pts_ms', -999))-int(layer['source_ms'])) > 40:
                return False
        return True

    def raster():
        scene = page.video_compositor
        scene._render_composition()
        frame = scene._rendered_frames[0] if scene._rendered_frames else None
        return None if frame is None or frame.isNull() else frame.copy()

    def click(widget):
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, widget.rect().center())

    def steps():
        page.open_project(source, skip_dirty_guard=True)
        yield lambda: page.project is not None and page._readiness.ready and not page._readiness.active
        yield .8
        page.video.set_paused(True)
        page.volume_slider.setValue(0)
        t = page.timeline
        t.set_visible_window(0, 10000)
        yield .3
        # Like a user: click the clip before the cut (focuses V2), then park
        # the playhead on the cut.
        row = t._video_track_rect('V2')
        QTest.mouseClick(t, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(round(t._time_to_x(SEAM_MS-500)), round(row.center().y())))
        yield .3
        check('clicking the clip selects it on V2', t.selected_video_clip_id == 'red-1' or 'red-1' in t.selected_segment_ids,
              dict(clip=t.selected_video_clip_id, segments=sorted(t.selected_segment_ids)))
        page._seek(SEAM_MS/1000)
        yield lambda: abs(t.playhead_ms-SEAM_MS) <= 1
        yield .3
        before = page.undo_stack.count()
        t.setFocus(); QTest.keyClick(t, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
        yield .5
        made = seam(SEAM_MS)
        check('Ctrl+D on the cut creates one plain dissolve', made is not None and 'look' not in made and len(records()) == 1,
              records())
        if made is None:
            raise RuntimeError('No transition after Ctrl+D')
        check('Ctrl+D is one undo step', page.undo_stack.count() == before+1)
        page.transition_properties.setVisible(True)
        page.context_drawer.setCurrentIndex(page.video_transform_tab_index)
        yield .4
        tiles = page.transition_look_tiles
        check('inspector shows the seven look cards', set(tiles) == set(VIDEO_LOOKS) and all(x.isVisible() for x in tiles.values()))
        legibility = {}
        for key, tile in tiles.items():
            caption, picture = tile.caption.geometry(), tile.preview.geometry()
            legibility[key] = dict(overlap=caption.intersects(picture), inside=tile.rect().contains(caption),
                                   text_fits=caption.width() >= tile.caption.fontMetrics().horizontalAdvance(tile.caption.text()),
                                   text=tile.caption.text())
        check('card names sit below the pictures, fully visible and unclipped',
              all(not x['overlap'] and x['inside'] and x['text_fits'] for x in legibility.values()), legibility)
        check('dissolve card is selected; direction and strength hidden',
              tiles['cross_dissolve'].isChecked() and not page.transition_direction_row.isVisible()
              and not page.transition_strength_row.isVisible())
        shot(page, '01-dissolve-panel')
        # Look card, direction, strength: each one undo step, saved on the seam.
        count = page.undo_stack.count()
        click(tiles['push']); yield .4
        look = normalize_look(seam(SEAM_MS).get('look'))
        check('clicking the push card saves push/left', look == dict(id='push', intensity=1., direction='left'), look)
        check('direction row shows four arrows', page.transition_direction_row.isVisible() and
              [k for k, b in page.transition_direction_buttons.items() if b.isVisible()] == ['left', 'right', 'up', 'down'])
        click(page.transition_direction_buttons['right']); yield .4
        check('direction button saves right', seam(SEAM_MS)['look']['direction'] == 'right')
        page.transition_strength.setValue(130); yield .6
        check('strength slider saves 1.3 after the pause', seam(SEAM_MS)['look']['intensity'] == 1.3)
        check('card, direction and strength are three undo steps', page.undo_stack.count() == count+3,
              dict(before=count, after=page.undo_stack.count()))
        page.undo_stack.undo(); yield .3
        check('undo restores strength 1.0 and the panel follows', seam(SEAM_MS)['look']['intensity'] == 1.
              and page.transition_strength.value() == 100)
        page.undo_stack.redo(); yield .3
        check('redo returns to 1.3', seam(SEAM_MS)['look']['intensity'] == 1.3 and page.transition_strength.value() == 130)
        shot(page, '02-push-panel')
        # Every look, paused, at three moments of the seam. The look each card
        # actually saved (direction/strength carried over) is what we export.
        used = {}
        for key in VIDEO_LOOKS:
            click(tiles[key]); yield .4
            current = normalize_look(seam(SEAM_MS).get('look'))
            used[key] = current
            check(f'{key}: card saves the look', (current or {}).get('id', 'cross_dissolve') == key, current)
            for ms in SAMPLES_MS:
                page._seek(ms/1000)
                yield lambda ms=ms: frames_ready(ms)
                yield .15
                image = raster()
                if image is None:
                    check(f'{key} {ms}: preview raster exists', False)
                    continue
                target = output/f'{theme}-preview-{key}-{ms}.png'
                image.save(str(target))
                previews[(key, ms)] = _small(image)
                fx = [layer.get('transition_fx') for layer in page.video_compositor._layers]
                result['preview'].append(dict(look=key, ms=ms, file=str(target), size=[image.width(), image.height()],
                                              layers_with_fx=sum(1 for x in fx if x)))
            mid = previews.get((key, SEAM_MS))
            if mid is not None:
                left, right, whole = mid[:, :60].mean(axis=(0, 1)), mid[:, 100:].mean(axis=(0, 1)), mid.mean(axis=(0, 1))
                if key == 'cross_dissolve':
                    check('dissolve mid frame mixes red and blue', whole[0] > 60 and whole[2] > 60, whole.tolist())
                elif key in ('push', 'whip'):
                    moving_right = current.get('direction') == 'right'
                    red_side, blue_side = (right, left) if moving_right else (left, right)
                    check(f'{key} {current.get("direction")}: outgoing red and incoming blue on the expected halves',
                          red_side[0] > red_side[2] and blue_side[2] > blue_side[0],
                          dict(direction=current.get('direction'), left=left.tolist(), right=right.tolist()))
                elif key == 'flash':
                    check('flash mid frame is white', whole.min() > 235, whole.tolist())
                else:
                    plain = previews.get(('cross_dissolve', SEAM_MS))
                    check(f'{key} mid frame differs from the dissolve',
                          plain is not None and float(np.abs(mid-plain).mean()) > 8,
                          None if plain is None else float(np.abs(mid-plain).mean()))
            page._seek(SEAM_MS/1000)
            yield lambda: abs(t.playhead_ms-SEAM_MS) <= 1
        if page.video.controller is not None:
            for key in ('push', 'zoom_blur'):
                click(tiles[key]); yield .3
                page._seek(SEAM_MS/1000)
                yield lambda: frames_ready(SEAM_MS)
                yield .6
                target = output/f'{theme}-mpv-{key}.png'
                try:
                    page.video.controller.screenshot_to_file(target)
                    result['screenshots'].append(str(target))
                except Exception as exc:  # noqa: BLE001 - evidence only
                    result['mpv_screenshot_error'] = repr(exc)
        # Default look: the selected seam's look becomes Ctrl+D's default.
        click(tiles['push']); yield .3
        click(page.transition_direction_buttons['right']); yield .3
        click(page.transition_make_default); yield .3
        default = normalize_look(page.project.studio_state.get(DEFAULT_LOOK_KEY))
        check('设为默认 stores the selected look', default == normalize_look(seam(SEAM_MS)['look']), default)
        check('defaults section shows the look', page.default_video_transition_look.currentData() == 'push')
        QTest.mouseClick(t, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(round(t._time_to_x(SECOND_SEAM_MS-500)), round(row.center().y())))
        yield .3
        page._seek(SECOND_SEAM_MS/1000)
        yield lambda: abs(t.playhead_ms-SECOND_SEAM_MS) <= 1
        yield .3
        t.setFocus(); QTest.keyClick(t, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
        yield .5
        second = seam(SECOND_SEAM_MS)
        check('Ctrl+D on the second cut uses the default look', second is not None and normalize_look(second.get('look')) == default,
              second)
        # Timeline marks.
        t.set_visible_window(2000, 5000); yield .3
        row_v2 = t._video_track_rect('V2')
        marks = [r for _item, r in t._transition_rects()]
        check('transition marks sit in the lower half of the row, clear of clip names',
              marks and all(r.top() > row_v2.center().y() and r.bottom() <= row_v2.bottom() for r in marks),
              dict(row=[row_v2.top(), row_v2.bottom()], marks=[[r.top(), r.bottom()] for r in marks]))
        target = output/f'{theme}-timeline-marks.png'
        t.grab().save(str(target)); result['screenshots'].append(str(target))
        t.set_visible_window(0, 10000); yield .2
        # Playback through the heaviest look; preview resamples every tick.
        first = seam(SEAM_MS)
        rect = next(r for item, r in t._transition_rects() if item['id'] == first['id'])
        QTest.mouseClick(t, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center().toPoint())
        yield .3
        check('clicking the timeline mark selects that transition', t.selected_transition_id == first['id'])
        click(tiles['whip']); yield .3
        page._seek(2.0)
        yield lambda: abs(t.playhead_ms-2000) <= 1
        yield .5
        scene = page.video_compositor
        scene.reset_performance_samples()
        if scene._async_compositor is not None:
            scene._async_compositor.samples.clear()
        ticks = []
        page.video.set_paused(False)
        started = time.monotonic()
        while time.monotonic()-started < 2.2:
            ticks.append(dict(ms=int(t.playhead_ms), fx=any(x.get('transition_fx') for x in scene._layers)))
            yield .05
        page.video.set_paused(True)
        yield .4
        snapshot = scene.performance_snapshot()
        inside = [x for x in ticks if first['start_ms'] <= x['ms'] < first['end_ms']]
        result['playback'] = dict(snapshot=snapshot, ticks=ticks)
        # The audit samples every ~50-90 ms, so a 500 ms seam yields 4-6 samples.
        check('playback crosses the seam with the look applied on every sampled tick inside it',
              len(inside) >= 3 and all(x['fx'] for x in inside), dict(inside=len(inside), with_fx=sum(x['fx'] for x in inside)))
        p95 = snapshot.get('worker_composition_p95_ms') or snapshot.get('render_p95_ms')
        check('composition p95 within one 60 Hz frame (16.7 ms) during playback', p95 is not None and p95 <= 16.7, snapshot)
        # Save, reload.
        saved = copy.deepcopy(page.project.studio_state.get('clip_transitions'))
        path = save_project(page.project, output/f'{theme}-saved.2byteproj')
        loaded = load_project(path)
        check('save/reload keeps looks and default', loaded.studio_state.get('clip_transitions') == saved and
              normalize_look(loaded.studio_state.get(DEFAULT_LOOK_KEY)) == default)
        # A narrow window keeps every card inside the panel.
        page.resize(1100, 720); yield .6
        box = page.transition_properties
        inside_box = all(box.rect().contains(tile.mapTo(box, tile.rect().bottomRight())) for tile in tiles.values())
        check('narrow window: cards wrap inside the panel', box.isVisible() and inside_box, dict(box=box.width()))
        shot(page, '03-narrow')
        page.resize(1520, 960); yield .3
        if export:
            # Preview vs production export at the same project times.
            jobs = []
            from ..exports.video_export import capture_video_graph
            from ..rendering.ass_compiler import compile_ass
            result['looks_used'] = used
            duration = seam(SEAM_MS)['duration_ms']  # Ctrl+D used the project default (500 ms)
            for key in VIDEO_LOOKS:
                working = copy.deepcopy(page.project)
                set_transition(working, 'video', 'V2', 'red-1', 'blue', duration_ms=duration, look=used.get(key))
                ass = output/f'export-{key}.ass'
                ass.write_text(compile_ass(working), encoding='utf-8-sig')
                jobs.append((key, capture_video_graph(working), working.media.path, ass))
            state = dict(done=False, error=None)

            def work():
                try:
                    from ..exports.studio_render import RenderJob, RenderSettings, run_render_job
                    from ..system.processes import run_hidden_subprocess
                    for key, graph, media, ass in jobs:
                        movie = output/f'export-{key}.mp4'
                        job = RenderJob(media, str(ass), str(movie), RenderSettings(encoder='libx264', width=640, height=360,
                                        fps=30, audio_codec='none', preset='ultrafast', quality=12),
                                        start_seconds=2.7, duration_seconds=.6, video_graph=graph)
                        run_render_job(str(ffmpeg), job)
                        for ms in SAMPLES_MS:
                            frame = round((ms-2700)*30/1000)
                            png = output/f'export-{key}-{ms}.png'
                            run_hidden_subprocess([str(ffmpeg), '-v', 'error', '-y', '-i', str(movie), '-vf',
                                                   f'select=eq(n\\,{frame})', '-frames:v', '1', str(png)],
                                                  purpose='decode transition export frame', check=True, timeout=30)
                            state.setdefault('frames', []).append((key, ms, png))
                except Exception:  # noqa: BLE001 - reported in the result
                    state['error'] = traceback.format_exc()
                state['done'] = True
            threading.Thread(target=work, daemon=True, name='transition-export-audit').start()
            yield lambda: state['done']
            check('production export of every look succeeds', state['error'] is None, state['error'])
            from PySide6.QtGui import QImage
            for key, ms, png in state.get('frames', []):
                exported = _small(QImage(str(png)))
                preview = previews.get((key, ms))
                if preview is None:
                    continue
                difference = float(np.abs(exported-preview).mean())
                result['export'].append(dict(look=key, ms=ms, file=str(png), mean_abs_difference=difference))
            limit = 14.
            worst = max((x['mean_abs_difference'] for x in result['export']), default=None)
            check(f'preview and export frames agree (mean abs difference <= {limit} of 255)',
                  worst is not None and worst <= limit, worst)
        result['passed'] = all(x['passed'] for x in result['checks'])

    plan = steps()
    state = dict(wait=0., deadline=time.monotonic()+60, code=1, busy=False)

    def tick():
        if state['busy']:
            return
        state['busy'] = True
        try:
            now = time.monotonic()
            if now > state['deadline']:
                raise TimeoutError('step timed out')
            waiting = state['wait']
            if callable(waiting):
                if not waiting():
                    return
            elif now < waiting:
                return
            step = next(plan)
            state['wait'] = step if callable(step) else now+float(step)
            state['deadline'] = time.monotonic()+(240 if callable(step) else 60)
        except StopIteration:
            state['code'] = 0 if result['passed'] else 1
            finish()
        except Exception:  # noqa: BLE001 - reported in the result
            result['error'] = traceback.format_exc()
            try:
                shot(page, 'failure')
            except Exception:  # noqa: BLE001
                pass
            finish()
        finally:
            state['busy'] = False

    def write():
        (output/f'result-{theme}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    def finish():
        timer.stop()
        write()
        # The production close path stops mpv and the secondary decoders.
        page.undo_stack.setClean(); page.close_page(); page.close()
        QTimer.singleShot(400, app.quit)

    timer = QTimer(page); timer.timeout.connect(tick); timer.start(40)
    if embedded:
        # Keep the isolated test page alive inside the normal app's event loop.
        app._transition_acceptance_page = page

        def shutdown():
            result['gui_shutdown'] = True
            write()
        app.aboutToQuit.connect(shutdown)
        return None
    app.exec()
    result['gui_shutdown'] = True
    write()
    return state['code']
