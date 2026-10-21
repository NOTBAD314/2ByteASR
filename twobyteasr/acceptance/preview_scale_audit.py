"""Playback preview 原画 / 1/2 / 1/4 in the real Studio window (2026-10-21).

Opens a project on a 4K clip, plays it and switches the toolbar box through
full -> 1/2 -> 1/4 -> full. Each step reads what mpv really outputs
(vf, video-out-params, video-params, hwdec), the GPU render pass time, frame
drops and the mpv process CPU, checks that the caption position frame keeps the
source size, and captures the window with PrintWindow. Then it captures the
open popup, checks toolbar geometry at the default and a narrow width, and the
per-machine setting in the isolated QSettings.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def execute():
        try:
            code = run(Path(output), window=window)
        except Exception:
            (Path(output) / 'result.json').write_text(json.dumps(dict(passed=False, error=traceback.format_exc())), 'utf8')
            code = 1
        window.result_exit_code = code

        def stopped():
            path = Path(output) / 'result.json'
            result = json.loads(path.read_text('utf8'))
            result['gui_shutdown'] = True
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(100, execute)


def run(output, *, window):
    from PySide6.QtCore import QRect, QSettings
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    import psutil
    from .blank_project_audit import _capture
    from ..design.theme_manager import apply_theme
    from ..diagnostics.build_identity import load_build_identity
    from ..playback.platform_mpv import preview_scale_value
    from ..projects.studio_project import StudioCue, StudioMedia, SubtitleProject, hydrate_media_contract, save_project
    from ..studio.studio_helpers import probe_media_identity

    output = Path(output).resolve()
    if output != Path(os.environ['TWOBYTEASR_TEST_ROOT']).resolve():
        raise RuntimeError('isolated root required')
    theme = os.environ.get('TWOBYTEASR_PREVIEW_THEME', 'grape')
    apply_theme(theme)
    media = Path(os.environ['TWOBYTEASR_PREVIEW_MEDIA']).resolve()
    result = dict(passed=False, checks=[], steps=[], theme=theme, media=str(media),
                  hwdec_mode=os.environ.get('TWOBYTEASR_DIAGNOSTIC_HWDEC', 'auto-safe'),
                  identity=load_build_identity().to_dict(), frozen=bool(getattr(sys, 'frozen', False)),
                  platform=QApplication.platformName(), pid=os.getpid(),
                  method='normal Windows window on a private desktop; combo choices via setCurrentIndex '
                         '(the same currentIndexChanged path as a click); mpv state read over its IPC')

    def receipt():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')

    def check(name, value, detail=None):
        result['checks'].append(dict(name=name, passed=bool(value), detail=detail))
        receipt()

    def wait(fn, label, seconds=60):
        end = time.monotonic() + seconds
        while not fn():
            if time.monotonic() > end:
                raise TimeoutError(label)
            QTest.qWait(20)

    page = window.studio_page
    identity = probe_media_identity(str(media))
    duration_ms = 10000
    texts = ('预览画质测试：字幕仍按窗口清晰绘制', 'Preview scale check — captions stay sharp', '1/2 和 1/4 只缩小画面')
    cues = [StudioCue(f'c{i}', i * 2000, i * 2000 + 1900, texts[i % 3]) for i in range(duration_ms // 2000)]
    project = SubtitleProject(media=StudioMedia(str(media), duration_ms=duration_ms, width=3840, height=2160), cues=cues)
    hydrate_media_contract(project, identity)
    project.validate()
    path = output / 'preview-scale.2byteproj'
    save_project(project, path)

    # Count filter posts: a re-post on each decoder report must not feed itself.
    applied = []
    original_apply = page.video._apply_preview_scale

    def counted_apply():
        applied.append(round(time.monotonic(), 3))
        original_apply()
    page.video._apply_preview_scale = counted_apply

    window.resize(1600, 1000)
    window.show()
    QTest.qWait(300)
    prior = page.project
    window.open_studio_project(str(path), mode='edit', source='preview_scale_audit')
    wait(lambda: page.project is not None and page.project is not prior and page._readiness.ready, 'project readiness')
    wait(lambda: page.video.controller is not None and page.video._video_display_size != (0, 0), 'video output')
    controller = page.video.controller
    box = page.preview_scale_box
    check('box visible next to speed', box.isVisible() and page.speed_box.isVisible(),
          dict(items=[box.itemText(i) for i in range(box.count())]))
    seeded = preview_scale_value(os.environ.get('TWOBYTEASR_PREVIEW_SEED') or 1.0)
    check("opens with this machine's choice", float(box.currentData()) == seeded,
          dict(box=box.currentData(), seeded=seeded, text=box.currentText()))

    def prop(name):
        try:
            return controller.get_property(name, None)
        except Exception as exc:  # property unavailable for this source/VO
            return f'error: {exc}'

    def render_ms():
        passes = prop('vo-passes')
        if not isinstance(passes, dict):
            return None
        return round(sum(float(item.get('avg', 0)) for item in passes.get('fresh', [])) / 1e6, 3)

    def drops():
        return {key: prop(key) for key in ('frame-drop-count', 'decoder-frame-drop-count', 'vo-delayed-frame-count')}

    def filter_family(vf):
        names = [item.get('name') for item in vf] if isinstance(vf, list) else []
        return names[0] if names else ''

    def expected_family(scale, hwdec):
        return '' if scale >= 1 else 'd3d11vpp' if hwdec == 'd3d11va' else 'scale'

    mpv_process = psutil.Process(controller._process.pid)
    source = (3840, 2160)
    # The remembered choice was posted before mpv knew its decoder; Studio
    # must re-post the filter that suits the decoder once it is reported.
    QTest.qWait(1500)
    out = prop('video-out-params') or {}
    opened = dict(out=f"{out.get('w')}x{out.get('h')}", vf=prop('vf'), hwdec=prop('hwdec-current'))
    result['opened'] = opened
    expected = f'{round(source[0] * seeded)}x{round(source[1] * seeded)}'
    check(f'opened: mpv outputs {expected}', opened['out'] == expected, opened)
    check('opened: filter suits the decoder',
          filter_family(opened['vf']) == expected_family(seeded, opened['hwdec']), opened)
    _capture(window, output / 'opened.png')
    opened['filter_posts'] = len(applied)
    QTest.qWait(2000)
    check('no repeated filter posts while nothing changes', len(applied) == opened['filter_posts'],
          dict(at_open=opened['filter_posts'], two_seconds_later=len(applied)))
    for name, scale in (('full', 1.0), ('half', 0.5), ('quarter', 0.25), ('full-again', 1.0)):
        page._seek(0.2)
        QTest.qWait(400)
        box.setCurrentIndex(box.findData(scale))
        if page.video._paused:
            page._toggle_playback()
        QTest.qWait(1200)
        before = drops()
        mpv_process.cpu_percent(None)
        renders = []
        for _ in range(8):
            QTest.qWait(300)
            renders.append(render_ms())
        cpu = mpv_process.cpu_percent(None)
        after = drops()
        posts_during_measure = len(applied)
        valid = sorted(value for value in renders if value is not None)
        out = prop('video-out-params') or {}
        src = prop('video-params') or {}
        step = dict(step=name, scale=scale, vf=prop('vf'), hwdec=prop('hwdec-current'),
                    out=f"{out.get('w')}x{out.get('h')}" if isinstance(out, dict) else out,
                    source=f"{src.get('w')}x{src.get('h')}" if isinstance(src, dict) else src,
                    render_ms=valid[len(valid) // 2] if valid else None, render_samples=renders,
                    drops_before=before, drops_after=after,
                    mpv_cpu_percent=round(cpu, 1), cpu_count=psutil.cpu_count(),
                    playing=not page.video._paused, time_pos=prop('time-pos'),
                    caption_frame=(page.position_overlay.video_width, page.position_overlay.video_height),
                    compositor_scale=page.video_compositor._preview_scale,
                    remembered=QSettings('2ByteASR', '2ByteASR').value('studio/preview_scale'),
                    filter_posts_total=len(applied))
        shot = output / f'{name}.png'
        _capture(window, shot)
        step['screenshot'] = shot.name
        result['steps'].append(step)
        check(f'{name}: no filter re-posts while playing', len(applied) == posts_during_measure, len(applied))
        expected = f'{round(source[0] * scale)}x{round(source[1] * scale)}'
        check(f'{name}: mpv outputs {expected}', step['out'] == expected, step['out'])
        check(f'{name}: decoder size unchanged', step['source'] == '3840x2160', step['source'])
        check(f'{name}: filter suits the decoder', filter_family(step['vf']) == expected_family(scale, step['hwdec']),
              dict(vf=step['vf'], hwdec=step['hwdec']))
        check(f'{name}: caption frame keeps source size', step['caption_frame'] == source, step['caption_frame'])
        # Unset (never changed on this machine) means 原画.
        check(f'{name}: remembered on this machine', preview_scale_value(step['remembered']) == scale, step['remembered'])
        check(f'{name}: still playing', step['playing'], step['time_pos'])

    # Paused change: the held frame should be re-filtered without playing.
    if not page.video._paused:
        page._toggle_playback()
    QTest.qWait(500)
    box.setCurrentIndex(box.findData(0.5))
    QTest.qWait(1200)
    out = prop('video-out-params') or {}
    paused_out = f"{out.get('w')}x{out.get('h')}"
    _capture(window, output / 'paused-half.png')
    result['paused_change'] = dict(out=paused_out, paused=page.video._paused)
    check('paused change applies to the held frame', paused_out == '1920x1080' and page.video._paused, paused_out)

    def toolbar_geometry(label):
        bar = box.parentWidget()
        rects = {}
        for key, widget in (('speed', page.speed_box), ('preview', box), ('volume', page.volume_slider)):
            top_left = widget.mapTo(bar, widget.rect().topLeft())
            rects[key] = QRect(top_left, widget.size())
        inside = all(bar.rect().contains(rect) for rect in rects.values())
        overlap = rects['speed'].intersects(rects['preview']) or rects['preview'].intersects(rects['volume'])
        info = dict(window=(window.width(), window.height()), bar=(bar.width(), bar.height()),
                    rects={k: (r.x(), r.y(), r.width(), r.height()) for k, r in rects.items()},
                    preview_text=box.currentText(), text_fits=box.width() >= box.sizeHint().width() - 1)
        result.setdefault('toolbar', {})[label] = info
        bar.grab().save(str(output / f'toolbar-{label}.png'))
        check(f'toolbar {label}: visible, inside, no overlap',
              box.isVisible() and inside and not overlap and info['text_fits'], info)

    toolbar_geometry('default')
    box.showPopup()
    QTest.qWait(400)
    popup = box.view().window()
    popup.grab().save(str(output / 'popup.png'))
    result['popup'] = dict(visible=popup.isVisible(), size=(popup.width(), popup.height()),
                           items=[box.itemText(i) for i in range(box.count())])
    check('popup opens with three choices', popup.isVisible() and box.count() == 3, result['popup'])
    box.hidePopup()
    QTest.qWait(200)
    window.resize(900, 860)  # Qt clamps to the window's own minimum width
    QTest.qWait(600)
    toolbar_geometry('narrow')
    _capture(window, output / 'narrow-window.png')

    result['passed'] = all(item['passed'] for item in result['checks'])
    receipt()
    return 0 if result['passed'] else 1
