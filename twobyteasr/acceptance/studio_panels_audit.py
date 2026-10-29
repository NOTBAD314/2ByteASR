"""Real-window screenshots of the Studio tool panel and command bar (2026-10-23).

User (10-23): redesign the 动效 / AI / 视频 / 剪辑 panels, the dropdowns and
input boxes across Studio, and the command bar (压制成片 row) in the soft
filled look of the home page. This scenario records how they look now and
after a change: the whole window, the command bar, and every tool panel tab at
its full length, in the given themes (default 「sand」 and 「grape」).

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=studio-panels`` (isolated data,
from ``scripts/verify_studio_panels_headed.py``; source or frozen). Offline;
no AI.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path


def start(window, output: Path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QAbstractButton, QApplication, QPushButton, QScrollArea
    app = QApplication.instance()
    output.mkdir(parents=True, exist_ok=True)
    result = dict(checks=[], skipped=[], metrics={}, errors=[], passed=False, pid=os.getpid(),
                  executable=os.path.realpath(sys.executable))

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))

    def settle(ms=300):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    def wait(fn, label, seconds=60):
        end = time.monotonic() + seconds
        while not fn():
            if time.monotonic() > end:
                raise TimeoutError(label)
            settle(50)

    def grab(widget, name):
        try:
            widget.grab().save(str(output / f'{name}.png'))
        except Exception as exc:  # noqa: BLE001
            result['errors'].append(f'grab {name}: {exc!r}')

    def caption_and_stage_checks(theme):
        """2026-10-24 (user): 应用到 leads the 样式 tab, caption 位置与变换
        is on the 视频 tab, motion previews take their stage from the theme."""
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QColor
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        from ..caption_style.caption_layer_transform import resolved_values
        from ..caption_style.caption_transform_panel import CaptionTransformPanel
        from ..caption_style.motion_inspector_ui import MotionEffectTile
        from ..design.soft_qss import preview_stage
        from ..design.ui_theme import blend_hex, theme_definition
        page = window.studio_page
        drawer = page.context_drawer
        project = page.project
        drawer.setCurrentIndex(1)
        settle(300)
        style = drawer.widget(1).widget()
        first = style.layout().itemAt(0).widget()
        check(f'{theme}: 样式 starts with 应用到', first is not None and first.objectName() == 'styleScopeBar'
              and first.isVisible() and page.style_apply_geometry.isVisible())
        check(f'{theme}: no 位置与变换 on 样式', not style.findChildren(CaptionTransformPanel))
        cue = project.cues[0]
        drawer.setCurrentIndex(page.video_transform_tab_index)
        page.select_cue(cue.id)
        settle(500)
        panel = page.caption_transform_panel
        check(f'{theme}: caption card on 视频', drawer.currentIndex() == page.video_transform_tab_index
              and panel.isVisible() and not page.video_clip_controls.isVisible(),
              page.video_transform_selection_label.text())
        grab(page.context_panel, f'{theme}_video_caption_panel')
        # Drag the small canvas's dot through the window: one undo step.
        width = float(project.render_settings.get('play_res_x', 1920))
        height = float(project.render_settings.get('play_res_y', 1080))
        before = resolved_values(project, cue, 'original')
        index = page.undo_stack.index()  # a redo left by an earlier theme is replaced
        pad = panel.pad
        frame = pad._frame()
        start = pad.mapTo(window, frame.center().toPoint())
        end = pad.mapTo(window, QPoint(round(frame.left() + frame.width() * .3), round(frame.top() + frame.height() * .7)))
        handle = window.windowHandle()
        QTest.mouseMove(handle, start)
        QTest.mousePress(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        for step in range(1, 5):
            QTest.mouseMove(handle, QPoint(round(start.x() + (end.x() - start.x()) * step / 4),
                                           round(start.y() + (end.y() - start.y()) * step / 4)))
            settle(40)
        QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
        settle(600)
        after = resolved_values(project, cue, 'original')
        moved = (abs(after['position_x'] - width * .3) < width * .03 and abs(after['position_y'] - height * .7) < height * .03)
        check(f'{theme}: caption dot drag moves the caption', moved,
              dict(before=[before['position_x'], before['position_y']], after=[after['position_x'], after['position_y']]))
        check(f'{theme}: caption drag is one undo step', page.undo_stack.index() == index + 1,
              [index, page.undo_stack.index()])
        grab(page.context_panel, f'{theme}_video_caption_dragged')
        grab(window, f'{theme}_video_caption_window')
        page.undo_stack.undo()
        settle(400)
        undone = resolved_values(project, cue, 'original')
        check(f'{theme}: undo restores caption position',
              (undone['position_x'], undone['position_y']) == (before['position_x'], before['position_y']))
        # Motion stages: the pixels at the top of the preview and a tile.
        top, bottom = preview_stage(theme_definition(theme))
        drawer.setCurrentIndex(page.motion_tab_index)
        settle(800)

        def stage_pixel(widget, fx, fy, name):
            image = widget.grab().toImage()
            got = image.pixelColor(int(image.width() * fx), int(image.height() * fy))
            want = QColor(blend_hex(top, bottom, fy))
            near = max(abs(got.red() - want.red()), abs(got.green() - want.green()), abs(got.blue() - want.blue())) <= 24
            check(f'{theme}: {name} stage follows theme', near, dict(got=got.name(), want=want.name()))

        stage_pixel(page.motion_sample, .04, .12, '本条预览')
        tiles = [tile for tile in page.motion_inspector.findChildren(MotionEffectTile)
                 if tile.isVisible() and not tile.isChecked()]
        if tiles:
            stage_pixel(tiles[0].preview, .5, .08, 'effect tile')
        else:
            result['skipped'].append(f'{theme}: no visible unchosen effect tile')

    def capture(theme):
        page = window.studio_page
        toolbar = page._studio_command_layout.parentWidget()
        settle(600)
        grab(window, f'{theme}_window')
        grab(toolbar, f'{theme}_toolbar')
        drawer = page.context_drawer
        names = ('ai', 'style', 'motion', 'video', 'clip', 'media')
        for index, name in enumerate(names[:drawer.count()]):
            drawer.setCurrentIndex(index)
            settle(500)
            grab(page.context_panel, f'{theme}_{name}_panel')
            tab = drawer.widget(index)
            areas = [tab] if isinstance(tab, QScrollArea) else tab.findChildren(QScrollArea)
            for number, area in enumerate(a for a in areas if a.widget() is not None):
                inner = area.widget()
                grab(inner, f'{theme}_{name}_full{number}')
                result['metrics'][f'{theme}_{name}_full{number}'] = [inner.width(), inner.height()]
        # The 剪辑 tab with two shown candidates (display only, never saved)
        # and its second tool, 压缩口播停顿.
        clip_panel = getattr(page, 'highlight_panel', None)
        if clip_panel is not None:
            from ..timeline.studio_edit_sequence import HighlightCandidate
            samples = [
                HighlightCandidate('audit-a', '开场就去找派门', 5200, 24000, score=.86, grade='',
                                   hook='开场就去找派门', clip_reason='开场直接进入目标，节奏紧凑。',
                                   event_summary='主播开播后马上去找派门，定好方向出发。'),
                HighlightCandidate('audit-b', '“好的出发吧”收尾', 8400, 13000, score=.71, status='accepted',
                                   hook='“好的出发吧”收尾', clip_reason='犹豫后果断出发，可接在上一段后面。'),
            ]
            drawer.setCurrentIndex(page.highlight_tab_index)
            clip_panel.reload_candidates(samples)
            settle(500)
            grab(page.context_panel, f'{theme}_clip_candidates_panel')
            clip_panel.set_tool('pauses')
            settle(300)
            grab(page.context_panel, f'{theme}_clip_pauses_panel')
            clip_panel.set_tool('clips')
            clip_panel.reload_candidates([])
            settle(200)
        result['metrics'][f'{theme}_sizes'] = dict(
            window=[window.width(), window.height()], toolbar=[toolbar.width(), toolbar.height()],
            panel=[page.context_panel.width(), page.context_panel.height()])
        # The 视频 tab with a picture clip selected (its fields filled in).
        track = next((t for t in page.project.video_tracks if t.clips), None)
        if track is not None:
            clip = track.clips[0]
            if track.locked:  # the sample's main track starts locked: the lock row first
                page.timeline.selected_video_clip_id = clip.id
                page._video_clip_selected(track.id, clip.id)
                drawer.setCurrentIndex(page.video_transform_tab_index)
                settle(400)
                grab(page.context_panel, f'{theme}_video_locked_panel')
                result['metrics'][f'{theme}_video_locked'] = dict(
                    notice=page.video_lock_notice.isVisible(), unlock=page.video_unlock_button.isVisible(),
                    fields_enabled=page.video_position_x.isEnabled())
            track.locked = False  # then show the fields enabled
            page.timeline.selected_video_clip_id = clip.id
            page._video_clip_selected(track.id, clip.id)
            drawer.setCurrentIndex(page.video_transform_tab_index)
            settle(500)
            grab(page.context_panel, f'{theme}_video_clip_panel')
            # Room inside each box for its widest value, and whether 旋转 and
            # 锚点 share a line: [text room, value width, top of the box].
            room = {}
            for name, sample in (('video_rotation', '-360.00'), ('video_anchor_x', '100.00'),
                                 ('video_anchor_y', '100.00')):
                spin = getattr(page, name)
                box = spin.parentWidget()
                room[name] = [spin.lineEdit().width() - 4, spin.fontMetrics().horizontalAdvance(sample),
                              box.mapTo(page.context_panel, box.rect().topLeft()).y()]
            result['metrics'][f'{theme}_video_value_room'] = room
            area = drawer.widget(page.video_transform_tab_index)
            if isinstance(area, QScrollArea) and area.widget() is not None:
                grab(area.widget(), f'{theme}_video_clip_full')
                cards = [getattr(page, name, None) for name in
                         ('video_blend_card', 'video_chroma_card', 'default_transition_card')]
                for card in cards:
                    if card is not None:
                        card.set_expanded(True)
                settle(400)
                grab(area.widget(), f'{theme}_video_open_full')
                for card in cards:
                    if card is not None:
                        card.set_expanded(False)
            page.select_cue(page.project.cues[0].id)
            settle(300)
        if page.project.cues and not str(theme).count('_'):  # once per theme, not per language
            caption_and_stage_checks(theme)

    def run_all():
        try:
            from ..design.theme_manager import apply_theme
            page = window.studio_page
            project = Path(os.environ['TWOBYTEASR_STARTUP_PROJECT'])
            width, height = (int(v) for v in os.environ.get('TWOBYTEASR_STUDIO_PANELS_SIZE', '1920x1040').split('x'))
            window.showNormal()
            window.resize(width, height)
            window.open_studio_project(str(project), mode='edit', source='studio_panels_audit')
            wait(lambda: page.project is not None and page._readiness.ready, 'project readiness')
            settle(1500)
            if not page.video._paused:   # opening a project starts playback
                page._toggle_playback()
            cues = page.project.cues
            if cues:
                page.select_cue(cues[0].id)
            settle(800)
            themes = os.environ.get('TWOBYTEASR_STUDIO_PANELS_THEME', 'sand,grape').split(',')
            for key in dict.fromkeys(themes):
                apply_theme(key, app)
                capture(key)
            # Other interface languages: longer words in the same controls.
            for code in [c for c in os.environ.get('TWOBYTEASR_STUDIO_PANELS_LANGS', '').split(',') if c]:
                index = window.language_combo.findData(code)
                if index < 0:
                    result['skipped'].append(f'language {code}')
                    continue
                window.language_combo.setCurrentIndex(index)
                settle(2500)
                capture(f'{themes[-1]}_{code}')
                # Every tab, every kind of button with words (push, radio chips, tool).
                clipped, seen = [], set()
                for tab in range(page.context_drawer.count()):
                    page.context_drawer.setCurrentIndex(tab)
                    settle(300)
                    for button in (page.context_panel.findChildren(QAbstractButton)
                                   + page.studio_toolbar.findChildren(QAbstractButton)):
                        key = (id(button), button.text())
                        # One letter (B / I / U) sits centred; its hint is padding only.
                        if key in seen or not button.isVisible() or len(button.text()) < 2:
                            continue
                        seen.add(key)
                        if button.width() + 1 < button.sizeHint().width():
                            clipped.append([tab, type(button).__name__, button.text(), button.width(),
                                            button.sizeHint().width()])
                result['metrics'][f'{code}_narrow_buttons'] = clipped
            if os.environ.get('TWOBYTEASR_STUDIO_PANELS_LANGS'):
                window.language_combo.setCurrentIndex(max(0, window.language_combo.findData('zh')))
                settle(1500)
            check('captured every tool panel tab', page.context_drawer.count() >= 5, page.context_drawer.count())
            result['passed'] = not result['errors'] and all(c['passed'] for c in result['checks'])
        except Exception:  # noqa: BLE001
            result['errors'].append(traceback.format_exc())
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')
        window.close()
        QTimer.singleShot(500, app.quit)

    def stopped():
        result['gui_shutdown'] = True
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')
    app.aboutToQuit.connect(stopped)
    QTimer.singleShot(2500, run_all)
