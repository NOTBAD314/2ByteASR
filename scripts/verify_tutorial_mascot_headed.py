"""Real-window check of the 说明 menu, the comparison-first tutorial and 兔白 (2026-11-11).

A normal MainWindow on a private Windows desktop with isolated data and no
network. It opens 说明 (screenshot, the five rows), starts 新手教学 from it
and checks that the cloud / local comparison is there before any tutorial
overlay exists; closes it with 先不换, then checks that step ① shows without
opening the comparison again, that its words are typed (the bunny talks,
silently: the private desktop has no listener), that a click on the bunny
shows a chat balloon, and goes on to step ②. Screenshots of each moment are
saved next to result.json.

usage: python -X utf8 scripts/verify_tutorial_mascot_headed.py --output tmp/<fresh folder>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def child(output: Path, theme: str) -> int:
    os.environ['TWOBYTEASR_TEST_ROOT'] = str(output / 'profile')
    from twobyteasr.test_isolation import install, install_pytest_network_guard
    install()
    install_pytest_network_guard()
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    import subtitle_core as legacy
    from twobyteasr.app.ui import MainWindow, _app_font, _register_bundled_fonts
    from twobyteasr.app.help_menu import CuteMenu, CuteMenuAction
    from twobyteasr.app.home_tour import GuidedTour
    from twobyteasr.app.quick_setup import QuickSetupDialog
    app = QApplication.instance() or QApplication([])
    _register_bundled_fonts()
    app.setFont(_app_font())
    from twobyteasr.design.theme_manager import apply_theme, save_theme_key
    save_theme_key(theme)
    apply_theme(theme, app)
    checks, notes = [], {}
    loop_done = {'code': None}

    def check(name, passed, detail=None):
        checks.append(dict(name=name, passed=bool(passed), detail=detail))

    def shot(name, widget=None):
        """The window with every visible window above it (a private desktop has no screen to grab)."""
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QPainter
        if widget is not None:
            widget.grab().save(str(output / f'{name}.png'))
            return
        base = win.grab()
        painter = QPainter(base)
        origin = win.mapToGlobal(QPoint(0, 0))
        for top in QApplication.topLevelWidgets():
            if top is win or not top.isVisible() or top.width() < 2:
                continue
            at = top.mapToGlobal(QPoint(0, 0)) - origin
            painter.drawPixmap(at, top.grab())
        painter.end()
        base.save(str(output / f'{name}.png'))

    win = MainWindow([], legacy, object(), None)
    win.resize(1440, 900)
    win.show()

    def live_tour():
        tour = win.findChild(GuidedTour)
        return tour if tour is not None and getattr(tour, 'mode', '') != 'closed' else None

    def compare_window():
        return next((top for top in QApplication.topLevelWidgets()
                     if isinstance(top, QuickSetupDialog) and top.isVisible() and getattr(top, 'compare', False)), None)

    def script():
        yield 3.0
        # ---- 说明
        menus = []

        def capture_exec(menu, position, *args, **kwargs):
            menus.append(menu)
            menu.popup(position)   # the same placement, without a nested loop under this script
        CuteMenu.exec = capture_exec
        QTimer.singleShot(0, win._show_help_menu)
        yield lambda: bool(menus) and menus[0].isVisible()
        yield 0.4
        menu = menus[0]
        rows = [a.text() for a in menu.actions() if isinstance(a, CuteMenuAction)]
        check('说明 has the five rows', rows == ['新手教学', '打开范例工程', '选择识别方式…', '回报问题／导出诊断…',
                                              '重新显示工作台操作提示'], rows)
        check('说明 is a translucent round card', menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        shot('01-help-menu')
        shot('01-help-menu-card', menu)
        tour_row = next(a for a in menu.actions() if isinstance(a, CuteMenuAction) and a.text() == '新手教学')
        # ---- 新手教学: the comparison first
        overlay_at_compare = []
        menu.close()
        QTimer.singleShot(0, tour_row.trigger)
        yield lambda: compare_window() is not None
        yield 0.6
        overlay_at_compare.append(live_tour())
        check('the comparison opens before any tutorial overlay', overlay_at_compare[0] is None)
        shot('02-compare-first')
        dialog = compare_window()
        QTest.mouseClick(dialog.later_button, Qt.MouseButton.LeftButton)    # 先不换
        yield lambda: live_tour() is not None and live_tour().mode == 'shown' and live_tour().bubble.isVisible()
        tour = live_tour()
        check('step ① comes after the comparison', tour.index == 0, tour.index)
        early_typing = tour._typer.running and 'transparent' in tour.text.text()
        shot('03-step1-typing')
        check('step ① words are being typed', early_typing)
        yield 1.6
        check('the comparison does not open again over step ①', compare_window() is None)
        check('兔白 is beside the card', tour.bubble.mascot is not None and tour.bubble.mascot.isVisible())
        check('the voice switch is in the bubble', tour.voice_button.isVisible())
        yield lambda: not tour._typer.running
        yield 0.3
        shot('04-step1-typed')
        notes['step1_text'] = tour.text.text()
        check('marked words use the bright marker', '#ffe27a' in tour.text.text() or '#f7cf4a' in tour.text.text())
        yield lambda: tour.chat.isVisible() or True
        yield 1.0
        shot('05-greeting')
        tour._greeted = True
        QTest.mouseClick(tour.bubble.mascot, Qt.MouseButton.LeftButton)
        yield 0.15
        shot('06-hop')
        yield 1.2
        check('a click on the bunny shows a chat line', tour.chat.isVisible(), tour.chat.text()[:120])
        shot('07-chat')
        QTest.mouseClick(tour.next, Qt.MouseButton.LeftButton)
        yield lambda: tour.index == 1 and tour.mode == 'shown' and tour.bubble.isVisible()
        yield 2.5
        shot('08-step2')
        notes['step2_side'] = tour.bubble.side
        # 2026-11-11: drag 兔白 and flick it; it slides, bounces off an edge and the window shakes.
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent
        check('no tooltip on the bunny', not tour.bubble.mascot.toolTip())
        mascot = tour.bubble.mascot

        # Through the overlay's own window (the system's routing, grabs included): one press picks it up.
        handle = tour.windowHandle() if tour.floating else win.windowHandle()
        base = tour if tour.floating else win

        def local(point):
            return base.mapFromGlobal(point.toPoint())
        origin = QPointF(mascot.mapToGlobal(mascot.rect().center()))
        positions = set()
        shake_watch = QTimer()
        shake_watch.timeout.connect(lambda: positions.add((win.pos().x(), win.pos().y())))
        shake_watch.start(10)
        before = win.pos()
        QTest.mousePress(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, local(origin))
        for step in range(1, 4):
            yield 0.016
            QTest.mouseMove(handle, local(origin + QPointF(step * 10, -step * 2)))
        yield 0.05
        check('one press picks the bunny up (no second click)', not tour.bubble.docked and tour._grab_target is not None
              and tour._drag is not None and tour._drag['moved'])
        held = QPointF(tour._puck_pos)
        for step in range(4, 10):
            yield 0.016
            QTest.mouseMove(handle, local(origin + QPointF(step * 30, -step * 8)))
        check('it follows the pointer while held', abs(tour._puck_pos.x() - held.x()) > 60, [held.x(), tour._puck_pos.x()])
        check('held up, it stretches a little', mascot.stretch > 0.03, mascot.stretch)
        for step in range(10, 13):   # still moving when let go: a throw
            yield 0.016
            QTest.mouseMove(handle, local(origin + QPointF(step * 30, -step * 8)))
        QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                           local(origin + QPointF(390, -104)))
        shot('09-thrown')
        check('let go, it flies', not tour.bubble.docked and tour._puck.isActive() and tour._grab_target is None)
        # 2026-11-11 round 2: DVD-logo bounces off every edge, each glows; no re-typing, no babble.
        hits = []
        sides = set()
        typed_before = tour._typed_for
        babble = []
        tour._typer.spoke.connect(lambda char: babble.append(char))
        def watch_hits():
            flash = tour._flash
            if flash is not None and (not hits or hits[-1] != flash[3]):
                hits.append(flash[3])
                sides.add(flash[4])
        hit_watch = QTimer()
        hit_watch.timeout.connect(watch_hits)
        hit_watch.start(8)
        yield 0.25
        shot('10-sliding')
        yield lambda: bool(hits) or not tour._puck.isActive()
        shot('10b-edge-glow')
        yield lambda: not tour._puck.isActive() and tour._shake_origin is None
        yield 0.3
        hit_watch.stop()
        shake_watch.stop()
        limits = tour._puck_limits()
        check('it bounced off several edges, each one glowing', len(hits) >= 2, [len(hits), sorted(sides)])
        check('then it slowed down and stopped, still in the window and out on its own',
              limits.adjusted(-1, -1, 1, 1).contains(tour._puck_pos) and not tour.bubble.docked and mascot.isVisible(),
              [tour._puck_pos.x(), tour._puck_pos.y()])
        check('the window shivered and stood exactly where it was again', len(positions) > 2 and win.pos() == before,
              sorted(positions)[:6])
        shifts = [abs(x - before.x()) + abs(y - before.y()) for x, y in positions]
        check('the shiver is small (at most 4 px)', max(shifts) <= 4, max(shifts))
        check('no words typed again and no babble while it bounced', not babble and tour._typed_for == typed_before
              and not tour._typer.running, ''.join(babble))
        shot('11-after-slide')
        QTest.mouseClick(tour.skip, Qt.MouseButton.LeftButton)
        yield lambda: live_tour() is None
        loop_done['code'] = 0 if all(c['passed'] for c in checks) else 1

    steps = script()

    def drive():
        if loop_done['code'] is not None:
            return
        try:
            wanted = next(steps)
        except StopIteration:
            return
        except Exception as exc:  # noqa: BLE001
            import traceback
            notes['error'] = traceback.format_exc()
            check(f'no error ({exc})', False)
            loop_done['code'] = 1
            return
        if callable(wanted):
            deadline = time.monotonic() + 25

            def wait():
                if wanted():
                    QTimer.singleShot(20, drive)
                elif time.monotonic() > deadline:
                    check('bounded wait', False, getattr(wanted, '__name__', ''))
                    loop_done['code'] = 1
                else:
                    QTimer.singleShot(30, wait)
            QTimer.singleShot(0, wait)
        else:
            QTimer.singleShot(int(float(wanted) * 1000), drive)

    QTimer.singleShot(0, drive)
    deadline = time.monotonic() + 150
    while loop_done['code'] is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    result = dict(passed=loop_done['code'] == 0, checks=checks, notes=notes,
                  dpr=app.primaryScreen().devicePixelRatio())
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    win.close()
    return 0 if result['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--theme', default='sand')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'tmp'):
        parser.error('output must stay inside repository tmp')
    if args.child:
        code = child(output, args.theme)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)
    output.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM='windows', TWOBYTEASR_TEST_ROOT=str(output / 'profile'),
               TWOBYTEASR_SKIP_FIRST_RUN_WIZARD='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONUTF8='1')
    sys.path.insert(0, str(ROOT / 'scripts'))
    from isolated_windows_desktop import run_on_desktop
    code = run_on_desktop([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), '--child', '--output', str(output),
                           '--theme', args.theme],
                          cwd=ROOT, env=env, output=output / 'process', timeout=240)
    print(json.dumps(dict(exit_code=code, result=json.loads((output / 'result.json').read_text('utf-8'))
                          if (output / 'result.json').exists() else None), ensure_ascii=False, indent=1))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
