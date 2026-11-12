"""Normal-entry audit of the 当前字幕 pill (2026-11-12, user draft B).

Checks the real window: pill order and actions, the transport still centred
under the video, save-frame / cover still on the bar, both themes and sizes.
"""
from __future__ import annotations
import json
import time
import traceback


def start(window, output):
    import os
    from PySide6.QtCore import QTimer
    target = measure_only if os.environ.get('TWOBYTEASR_CUE_PILL_MEASURE_ONLY') == '1' else run
    QTimer.singleShot(400, lambda: target(window, output))


def geometry(page):
    """Transport/video centres and every group's rect in window pixels."""
    window = page.window()

    def rect(widget):
        origin = widget.mapTo(window, widget.rect().topLeft())
        return [origin.x(), origin.y(), widget.width(), widget.height()]

    groups = [dict(role=group.property('commandGroup'), visible=group.isVisible(), rect=rect(group))
              for group in page._timeline_group_widgets]
    transport = next(group for group in page._timeline_group_widgets if group.property('commandGroup') == 'transport')
    video = rect(page.video)
    bar = rect(page._timeline_command_bar)
    t = rect(transport)
    return dict(window=[window.width(), window.height()], video=video, bar=bar, groups=groups,
                transport_centre=t[0] + t[2] / 2, video_centre=video[0] + video[2] / 2,
                rows=len({g['rect'][1] + g['rect'][3] // 2 for g in groups if g['visible']}))


def measure_only(window, output):
    """Geometry and pictures only, usable against a build without the pill."""
    from PySide6.QtWidgets import QApplication
    from ..design import theme_manager as themes
    app = QApplication.instance(); shots = []

    def settle(seconds):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            app.processEvents(); time.sleep(.003)
    try:
        window.showNormal(); window.resize(1920, 1040)
        window.open_studio_project(str(output / 'fixture.2byteproj'))
        until = time.perf_counter() + 40
        while time.perf_counter() < until and not (
                window.built_page('studio') is not None and window.built_page('studio').project is not None
                and getattr(window.studio_page.video, '_startup_state', '') == 'READY'):
            settle(.05)
        page = window.studio_page; page.video.set_paused(True); settle(1.0)
        for theme in ('warm', 'graphite'):
            themes.apply_theme(theme, app); settle(.8)
            for size in ((1920, 1040), (1560, 980), (1280, 800)):
                window.resize(*size); settle(.6)
                label = f'{theme}-{size[0]}x{size[1]}'
                page._timeline_command_bar.grab().save(str(output / f'{label}-bar.png'))
                shots.append(dict(label=label, **geometry(page)))
        error = None
    except Exception:
        error = traceback.format_exc()
    (output / 'result.json').write_text(json.dumps(dict(passed=error is None, measure_only=True, shots=shots,
                                                         error=error), ensure_ascii=False, indent=2), 'utf8')
    window.close(); app.quit()


def run(window, output):
    from PySide6.QtWidgets import QApplication
    from ..design import theme_manager as themes
    app = QApplication.instance(); checks = []; shots = []; error = None

    def persist():
        (output / 'result.json').write_text(json.dumps(dict(
            passed=error is None and bool(checks) and all(c['passed'] for c in checks),
            checks=checks, shots=shots, error=error), ensure_ascii=False, indent=2, default=str), 'utf8')

    def check(name, passed, detail=None):
        checks.append(dict(name=name, passed=bool(passed), detail=detail)); persist()
        if not passed:
            raise AssertionError(name + ': ' + str(detail))

    def settle(seconds=.05):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            app.processEvents(); time.sleep(.003)

    def wait(predicate, timeout=20):
        until = time.perf_counter() + timeout
        while not predicate() and time.perf_counter() < until:
            settle(.015)
        if not predicate():
            raise TimeoutError(str(predicate))

    page = None
    try:
        window.showNormal(); window.resize(1920, 1040)
        window.open_studio_project(str(output / 'fixture.2byteproj'))
        wait(lambda: window.built_page('studio') is not None and window.built_page('studio').project is not None)
        page = window.studio_page
        wait(lambda: getattr(window, '_studio_loading_session', None) is None or
             not window._studio_loading_session.active and not window._studio_loading_session.view.isVisible(), 35)
        wait(lambda: getattr(page.video, '_startup_state', '') == 'READY', 35)
        page.video.set_paused(True); app.setActiveWindow(window); settle(.4)
        roles = [g.property('commandGroup') for g in page._timeline_group_widgets]
        check('pill between editing and transport',
              roles.index('editing') + 1 == roles.index('cue') == roles.index('transport') - 1, roles)
        page.cue_controller.cancel_selection(); settle(.2)
        check('no selection: number empty and actions disabled', page.cue_capsule_badge.text() == '#—'
              and not any(b.isEnabled() for b in page._cue_capsule_buttons), page.cue_capsule_badge.text())
        page.select_cue('b'); settle(.3)
        check('selection names list number', page.cue_capsule_badge.text() == '#2', page.cue_capsule_badge.text())
        requests = []
        original = page._seek

        def seek(seconds, **kwargs):
            requests.append(round(seconds * 1000)); return original(seconds, **kwargs)

        page._seek = seek
        page.cue_end_button.click(); settle(.3); page.cue_start_button.click(); settle(.3)
        check('end then start buttons seek exact edges', requests[-2:] == [16000, 13000], requests)
        for theme in ('warm', 'graphite'):
            themes.apply_theme(theme, app); settle(.8)
            for size in ((1920, 1040), (1560, 980), (1280, 800)):
                window.resize(*size); settle(.6)
                g = geometry(page)
                label = f'{theme}-{size[0]}x{size[1]}'
                window.grab().save(str(output / f'{label}-window.png'))
                page._timeline_command_bar.grab().save(str(output / f'{label}-bar.png'))
                shots.append(dict(label=label, **g)); persist()
                cue = next(x for x in g['groups'] if x['role'] == 'cue')
                output_group = next(x for x in g['groups'] if x['role'] == 'output')
                # Narrow bars fold the pill like zoom/display; its commands stay in 「…」.
                check(f'{label} pill (unless narrow), save-frame and cover visible',
                      (cue['visible'] or size[0] < 1500) and output_group['visible']
                      and page.save_frame_button.isVisible() and page.make_cover_button.isVisible(), g)
                # Before: one row at 1920/1560; 1280 already wrapped to two.
                check(f'{label} rows no more than before', g['rows'] <= (2 if size[0] == 1280 else 1), g)
                # Before the pill (same commit, real window): 0.5 / 0.5 / 50.5 px.
                allowed = {1920: 2, 1560: 2, 1280: 52}[size[0]]
                check(f'{label} transport under video no worse than before (<={allowed}px)',
                      abs(g['transport_centre'] - g['video_centre']) <= allowed,
                      dict(transport=g['transport_centre'], video=g['video_centre']))
        themes.apply_theme('warm', app); window.resize(1920, 1040); settle(.4)
        page.undo_stack.setClean()
    except Exception:
        error = traceback.format_exc()
        (output / 'error.txt').write_text(error, 'utf8')
        window.grab().save(str(output / 'failure.png'))
    finally:
        persist()
        if page is not None and page.project:
            page.undo_stack.setClean()
        window.close(); app.quit()
