"""Real-window check of the redesigned 填充 editor (plan B "调色工作台", 2026-11-03).

Opens the sample project in Studio and, per theme, opens the Fill editor
from the style panel's fill swatch with a real click, then drives it with
real mouse input: mode pills, a gradient preset, double-click to add a stop,
drag a stop off the rail, the hue ring, the square, the opacity strip and an
angle chip. Records the dialog over the app (screen pixels, so the rounded
corners and shadow show) and checks OK writes one undo step / Cancel none.

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=fill-editor`` (isolated data,
from ``scripts/verify_fill_editor_headed.py``; source or frozen). Offline; no AI.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path


def start(window, output: Path):
    from PySide6.QtCore import QPoint, Qt, QTimer
    from PySide6.QtGui import QColor, QPainter
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialogButtonBox, QScrollArea

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

    def screen_shot(dialog, name):
        """The dialog's own rendering (alpha kept) laid over the main window's.

        The private verification desktop cannot be read back with
        ``QScreen.grabWindow`` (it returns black), so both top-level windows
        are grabbed and composited where they sit; the card's rounded corners
        and shadow then show over the real Studio pixels.
        """
        base = window.grab()
        ratio = base.devicePixelRatio() or 1.0
        offset = window.mapFromGlobal(dialog.mapToGlobal(QPoint(0, 0)))
        painter = QPainter(base)
        painter.drawPixmap(offset, dialog.grab())
        painter.end()
        base.save(str(output / f'{name}_over_window.png'))
        crop = base.copy(round(offset.x() * ratio), round(offset.y() * ratio),
                         round(dialog.width() * ratio), round(dialog.height() * ratio))
        crop.save(str(output / f'{name}.png'))
        return crop.toImage()

    def corner_facts(dialog, image):
        """The card corner shows what is behind it; the card edge just inside shows the surface."""
        from ..design.theme_manager import theme_key
        from ..design.ui_theme import theme_definition
        ratio = image.devicePixelRatio() or 1.0
        card = dialog.card.geometry()
        surface = QColor(theme_definition(theme_key()).surface)
        corner = image.pixelColor(round((card.left() + 2) * ratio), round((card.top() + 2) * ratio))
        edge = image.pixelColor(round((card.left() + 30) * ratio), round((card.top() + 3) * ratio))
        def distance(a, b):
            return abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())
        return dict(corner=corner.name(), edge=edge.name(), surface=surface.name(),
                    corner_distance=distance(corner, surface), edge_distance=distance(edge, surface))

    def centre(widget):
        return widget.rect().center()

    def run_dialog(page, steps, timeout=30):
        """Click the fill swatch; ``steps(dialog)`` runs once the modal dialog is up."""
        state = dict(dialog=None, done=False, error=None)

        def drive():
            dialog = QApplication.activeModalWidget()
            if dialog is None or type(dialog).__name__ != 'FillEditorDialog':
                if time.monotonic() - state.setdefault('since', time.monotonic()) < timeout:
                    QTimer.singleShot(100, drive)
                else:
                    state['error'] = 'fill editor did not open'
                return
            state['dialog'] = dialog
            try:
                settle(700)   # entrance fade
                steps(dialog)
            except Exception:  # noqa: BLE001
                state['error'] = traceback.format_exc()
                dialog.reject()
            state['done'] = True

        QTimer.singleShot(150, drive)
        QTest.mouseClick(page.style_fill_button, Qt.MouseButton.LeftButton)
        if state['error']:
            raise RuntimeError(state['error'])
        return state['dialog']

    def solid_and_gradient_steps(key):
        def steps(dialog):
            from ..design.fill_picker import SwatchButton
            check(f'{key}: dialog has no system title bar', bool(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint))
            image = screen_shot(dialog, f'{key}_1_solid')
            facts = corner_facts(dialog, image)
            result['metrics'][f'{key}_corner'] = facts
            check(f'{key}: rounded corner shows the app behind, edge shows the card',
                  facts['corner_distance'] > 24 and facts['edge_distance'] < 24, facts)
            tabs = {k: tab.isVisible() for k, tab in dialog._palette_tabs.items()}
            check(f'{key}: solid swatch box shows 常用 / 最近 only', tabs == dict(common=True, recent=True, gradient=False), tabs)
            yellow = next(b for b in dialog._swatches if isinstance(b, SwatchButton) and b.color.name().upper() == '#FFE45E')
            QTest.mouseClick(yellow, Qt.MouseButton.LeftButton, pos=centre(yellow))
            check(f'{key}: clicking a common swatch sets the color', dialog.picker.color().name().upper() == '#FFE45E')
            QTest.mouseClick(dialog.mode_segment.button(1), Qt.MouseButton.LeftButton)
            settle(600)
            check(f'{key}: linear mode shows the gradient card and angle row',
                  dialog._gradient_card.isVisible() and dialog._angle_host.isVisible())
            preset = next(b for b in dialog._swatches if b.stops and b.stops[0] == '#FF7EB6')
            QTest.mouseClick(preset, Qt.MouseButton.LeftButton, pos=centre(preset))
            settle(200)
            bar = dialog.gradient.bar
            strip = dialog.gradient._strip_rect()
            middle = QPoint(strip.left() + strip.width() // 2, strip.center().y())
            QTest.mouseDClick(bar, Qt.MouseButton.LeftButton, pos=middle)
            settle(200)
            check(f'{key}: double-click on the rail adds a stop', len(dialog.gradient._stops) == 3, len(dialog.gradient._stops))
            wheel = dialog.picker.wheel
            mid = int(wheel._outer() - wheel.BAND / 2)
            QTest.mouseClick(wheel, Qt.MouseButton.LeftButton, pos=QPoint(wheel.width() // 2 + mid, wheel.height() // 2))
            square = dialog.picker.sv_square.plane_rect()
            QTest.mouseClick(dialog.picker.sv_square, Qt.MouseButton.LeftButton,
                             pos=QPoint(round(square.left() + square.width() * 0.7), round(square.top() + square.height() * 0.2)))
            settle(200)
            stop = QColor(dialog.gradient._selected.color)
            check(f'{key}: ring + square edit the selected stop',
                  abs(stop.hsvHue() - 90) <= 3 and stop.hsvSaturation() > 150, stop.name(QColor.NameFormat.HexArgb))
            QTest.mouseClick(dialog._angle_chips[1], Qt.MouseButton.LeftButton)
            settle(300)
            screen_shot(dialog, f'{key}_2_linear')
            check(f'{key}: angle chip sets 45°', dialog.value()['angle'] == 45.0, dialog.value()['angle'])
            QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=middle)
            QTest.mouseMove(bar, middle + QPoint(0, 70))
            QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=middle + QPoint(0, 70))
            settle(200)
            check(f'{key}: dragging a stop off the rail deletes it', len(dialog.gradient._stops) == 2, len(dialog.gradient._stops))
            alpha = dialog.picker.alpha_slider
            QTest.mouseClick(alpha, Qt.MouseButton.LeftButton, pos=QPoint(alpha.width() // 2, alpha.height() // 2))
            settle(200)
            alpha_value = QColor(dialog.gradient._selected.color).alpha()
            check(f'{key}: opacity strip sets the stop opacity', 110 <= alpha_value <= 145, alpha_value)
            QTest.mouseClick(dialog.mode_segment.button(2), Qt.MouseButton.LeftButton)
            settle(600)
            screen_shot(dialog, f'{key}_3_radial')
            check(f'{key}: radial mode hides the angle row', dialog._gradient_card.isVisible() and not dialog._angle_host.isVisible())
            QTest.mouseClick(dialog.mode_segment.button(1), Qt.MouseButton.LeftButton)
            settle(400)
            result['metrics'][f'{key}_accepted_value'] = dialog.value()
            ok = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
            QTest.mouseClick(ok, Qt.MouseButton.LeftButton)
        return steps

    def cancel_steps(key):
        def steps(dialog):
            QTest.mouseClick(dialog.mode_segment.button(0), Qt.MouseButton.LeftButton)
            settle(500)
            QTest.mouseClick(dialog.picker.sv_square, Qt.MouseButton.LeftButton, pos=dialog.picker.sv_square.rect().center())
            screen_shot(dialog, f'{key}_4_cancel_solid')
            cancel = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Cancel)
            QTest.mouseClick(cancel, Qt.MouseButton.LeftButton)
        return steps

    def run_all():
        try:
            from ..caption_style.visual_snapshot import build_visual_cue_snapshot
            from ..design.theme_manager import apply_theme
            page = window.studio_page
            project = Path(os.environ['TWOBYTEASR_STARTUP_PROJECT'])
            window.showNormal()
            window.resize(1600, 900)
            window.open_studio_project(str(project), mode='edit', source='fill_editor_audit')
            wait(lambda: page.project is not None and page._readiness.ready, 'project readiness')
            settle(1500)
            if not page.video._paused:
                page._toggle_playback()
            cue_id = page.project.cues[1].id
            page._toggle_context_panel(True)
            drawer = page.context_drawer
            style_tab = next(i for i in range(drawer.count()) if drawer.widget(i).isAncestorOf(page.style_fill_button))
            drawer.setCurrentIndex(style_tab)
            page.select_cue(cue_id)
            page.style_scope.setCurrentIndex(page.style_scope.findData('current'))
            settle(800)
            themes = os.environ.get('TWOBYTEASR_FILL_EDITOR_THEME', 'grape,lavender,warm').split(',')
            for key in dict.fromkeys(themes):
                apply_theme(key, app)
                settle(800)
                scroll = page.style_fill_button.parentWidget()
                while scroll is not None and not isinstance(scroll, QScrollArea):
                    scroll = scroll.parentWidget()
                if scroll is not None:
                    scroll.ensureWidgetVisible(page.style_fill_button)
                settle(200)
                before = page.undo_stack.index()
                run_dialog(page, solid_and_gradient_steps(key))
                settle(800)
                fill = build_visual_cue_snapshot(page.project, cue_id).fill
                accepted = result['metrics'].get(f'{key}_accepted_value', {})
                check(f'{key}: OK applies the gradient with one undo step',
                      isinstance(fill, dict) and fill.get('type') == 'linear-gradient' and fill.get('angle') == 45.0
                      and len(fill.get('stops', [])) == 2 and page.undo_stack.index() == before + 1,
                      dict(fill=fill, accepted=accepted, undo=[before, page.undo_stack.index()]))
                window.grab().save(str(output / f'{key}_5_applied_window.png'))
                before = page.undo_stack.index()
                run_dialog(page, cancel_steps(key))
                settle(600)
                check(f'{key}: Cancel leaves the fill and undo stack alone',
                      build_visual_cue_snapshot(page.project, cue_id).fill == fill and page.undo_stack.index() == before)
                page.undo_stack.undo()
                settle(500)
                check(f'{key}: undo restores the previous fill',
                      build_visual_cue_snapshot(page.project, cue_id).fill != fill)
            page.save()
            settle(500)
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
