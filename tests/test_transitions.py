"""Page and dialog transitions in the calm feel (2026-11-18).

User (2026-11-18): after the wheel and press motion there was still no visible motion; the
demo's page and dialog transitions were missing.
"""
from __future__ import annotations

import time

import pytest


@pytest.fixture(scope='module')
def app():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from twobyteasr.design import press_motion, transitions
    press_motion.install(app)
    transitions.install(app)
    return app


def _pump(app, seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.004)


def _stack():
    from PySide6.QtWidgets import QLabel, QStackedWidget
    stack = QStackedWidget()
    for text in ('首页', '模型工坊'):
        label = QLabel(text)
        label.setStyleSheet('background: #fafafa; font-size: 40px;')
        stack.addWidget(label)
    stack.resize(400, 300)
    stack.show()
    return stack


def test_the_old_page_fades_over_the_live_new_one_and_goes(app):
    from PySide6.QtCore import Qt
    from twobyteasr.design import transitions
    stack = _stack()
    _pump(app, 0.1)
    picture = transitions.capture_page(stack)
    assert picture is not None and not picture.isNull()
    stack.setCurrentIndex(1)                                   # the new page is live right away
    overlay = transitions.start_page_crossfade(stack, picture)
    assert overlay is not None and overlay.isVisible()
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    progress = []
    end = time.time() + 0.6
    while time.time() < end and stack.findChildren(transitions.PageCrossfade):
        app.processEvents()
        progress.append(overlay.progress)
        time.sleep(0.004)
    assert len(set(progress)) > 5 and progress == sorted(progress)
    _pump(app, 0.1)
    assert not stack.findChildren(transitions.PageCrossfade)
    assert stack.currentIndex() == 1
    stack.deleteLater()


def test_late_frames_end_the_fade_on_its_final_picture(app):
    """2026-11-18 evening (user: 5 fps, sluggish): a busy GUI gets no motion, never a slow one.
    2026-11-19: one late frame only holds it a frame; ``MAX_LATE_FRAMES`` of them end it."""
    from twobyteasr.design import motion_tokens, transitions
    stack = _stack()
    _pump(app, 0.05)
    overlay = transitions.start_page_crossfade(stack, transitions.capture_page(stack))
    _pump(app, 0.03)                                            # the clock has started
    assert overlay.isVisible()
    time.sleep(0.12)                                            # one long block: held, not cut
    _pump(app, 0.02)
    from shiboken6 import isValid
    assert isValid(overlay) and overlay.isVisible() and overlay.progress < 1.0
    for _ in range(motion_tokens.MAX_LATE_FRAMES):              # a page building itself
        time.sleep(0.12)
        _pump(app, 0.02)
    assert not isValid(overlay) or not overlay.isVisible()      # gone, not dragged out
    stack.deleteLater()


def test_page_fades_are_quick(app):
    from twobyteasr.design import motion_tokens
    assert motion_tokens.PAGE_CROSSFADE.ms <= 200 and motion_tokens.DIALOG_IN.response <= 0.3


def test_a_panel_slides_out_to_its_side_and_in_from_it(app):
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QWidget
    from twobyteasr.design import transitions
    host = QWidget()
    host.resize(800, 400)
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    video, panel = QFrame(), QFrame()
    panel.setStyleSheet('background: #c96;')
    row.addWidget(video, 1)
    row.addWidget(panel)
    panel.setFixedWidth(300)
    host.show()
    host.activateWindow()
    _pump(app, 0.1)
    if not host.isActiveWindow():
        pytest.skip('the test window cannot be made active here')
    with transitions.panel_slide_out(panel, 'right'):
        panel.hide()
    _pump(app, 0.05)
    slides = [w for w in QApplication.topLevelWidgets() if isinstance(w, transitions.PanelSlide) and w.isVisible()]
    assert len(slides) == 1 and not panel.isVisible()            # hidden at once, its picture moves
    _pump(app, 0.4)
    assert not [w for w in QApplication.topLevelWidgets() if isinstance(w, transitions.PanelSlide) and w.isVisible()]
    landed = []
    host.activateWindow()                  # the offscreen platform hands activation around
    _pump(app, 0.05)
    if not host.isActiveWindow():
        pytest.skip('the test window cannot be made active again here')
    assert transitions.slide_panel_in(panel, QRect(500, 0, 300, 400), 'right', lambda: landed.append(1))
    _pump(app, 0.5)
    assert landed == [1]
    host.deleteLater()


def test_a_resize_ends_the_page_fade_at_once(app):
    from twobyteasr.design import transitions
    stack = _stack()
    _pump(app, 0.05)
    transitions.start_page_crossfade(stack, transitions.capture_page(stack))
    stack.resize(500, 320)
    _pump(app, 0.05)
    assert not stack.findChildren(transitions.PageCrossfade)
    stack.deleteLater()


def _dialog_with_button():
    from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget
    host = QWidget()
    host.resize(600, 400)
    button = QPushButton('设置', host)
    button.setGeometry(20, 20, 90, 32)
    host.show()
    dialog = QDialog(host)
    QVBoxLayout(dialog).addWidget(QLabel('设置内容'))
    dialog.resize(320, 220)
    return host, button, dialog


def test_a_dialog_grows_out_of_the_pressed_button_and_shrinks_back(app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from twobyteasr.design import transitions
    host, button, dialog = _dialog_with_button()
    QTest.mousePress(button, Qt.MouseButton.LeftButton)
    QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
    dialog.show()
    assert dialog.windowOpacity() == 0.0                       # usable, the ghost is what shows
    _pump(app, 0.05)
    ghosts = [w for w in QApplication.topLevelWidgets() if isinstance(w, transitions._Ghost) and w.isVisible()]
    assert len(ghosts) == 1
    first = next(iter(app._dialog_motion._flights.values())).start
    assert first.width() < dialog.width() * 0.8                # starts smaller, toward the button
    origin = button.mapToGlobal(button.rect().center())
    final = dialog.frameGeometry().center()
    expect_x = final.x() + (origin.x() - final.x()) * 0.4
    assert abs(first.center().x() - expect_x) < 4
    _pump(app, 1.0)
    assert dialog.windowOpacity() == 1.0
    assert not [w for w in QApplication.topLevelWidgets() if isinstance(w, transitions._Ghost) and w.isVisible()]
    dialog.hide()                                              # closing: a ghost shrinks back
    _pump(app, 0.03)
    closing = [w for w in QApplication.topLevelWidgets() if isinstance(w, transitions._Ghost) and w.isVisible()]
    assert len(closing) == 1 and not dialog.isVisible()
    _pump(app, 0.5)
    assert not [w for w in QApplication.topLevelWidgets() if isinstance(w, transitions._Ghost) and w.isVisible()]
    host.deleteLater()


def test_motion_frames_keep_automatic_garbage_collection_waiting(app, monkeypatch):
    """2026-11-19 (user: animations stutter the first time a page or dialog opens): building it
    crossed the collector's thresholds and the heap scan landed inside the motion after it. Each
    frame counts as interaction for the GUI-thread collector, which then waits (bounded)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from twobyteasr.design import transitions
    from twobyteasr.playback import playback_gc_budget
    frames = []
    monkeypatch.setattr(playback_gc_budget, 'note_gui_interaction', lambda: frames.append('frame'))
    monkeypatch.setattr(transitions, '_heap_quiet', None)
    host, button, dialog = _dialog_with_button()
    QTest.mousePress(button, Qt.MouseButton.LeftButton)
    QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
    dialog.show()
    # Already on show: after a long build the collector's timer is due before the first frame.
    assert frames
    _pump(app, 0.15)
    assert len(frames) >= 3                                    # the dialog's flight
    dialog.hide()
    _pump(app, 0.5)
    host.deleteLater()
    frames.clear()
    stack = _stack()
    _pump(app, 0.1)
    picture = transitions.capture_page(stack)
    stack.setCurrentIndex(1)
    transitions.start_page_crossfade(stack, picture)
    _pump(app, 0.15)
    assert len(frames) >= 3                                    # a page fade
    _pump(app, 0.5)
    stack.deleteLater()


def test_a_dialog_can_never_stay_invisible(app, monkeypatch):
    from twobyteasr.design import transitions
    monkeypatch.setattr(transitions, 'GHOST_SAFETY_MS', 200)
    monkeypatch.setattr(transitions.DialogMotion, '_launch_open', lambda self, d, o: None)   # the ghost never flies
    host, _button, dialog = _dialog_with_button()
    dialog.show()
    assert dialog.windowOpacity() == 0.0
    _pump(app, 0.4)
    assert dialog.windowOpacity() == 1.0
    dialog.hide()
    host.deleteLater()


def test_switched_off_the_dialog_is_left_alone(app, monkeypatch):
    monkeypatch.setenv('TWOBYTEASR_TRANSITIONS', '0')
    host, _button, dialog = _dialog_with_button()
    dialog.show()
    assert dialog.windowOpacity() == 1.0
    dialog.hide()
    host.deleteLater()


def test_spring_dialogs_hand_their_old_fade_to_the_app_wide_motion(app):
    from PySide6.QtWidgets import QWidget
    from twobyteasr.design.main_ui_dialogs import SpringDialog
    from twobyteasr.design.transitions import handles
    host = QWidget()
    host.resize(700, 500)
    host.show()
    dialog = SpringDialog(host, backdrop=False)
    dialog.resize(300, 200)
    assert handles(dialog)
    dialog.show()
    assert getattr(dialog, '_entrance_motion', None) is None    # its own fade-and-rise stood down
    assert dialog.windowOpacity() == 0.0
    _pump(app, 1.0)
    assert dialog.windowOpacity() == 1.0
    dialog.done(0)
    assert not dialog.isVisible()                               # closes at once; the ghost shows the exit
    host.deleteLater()


def test_any_stacked_page_switch_fades_by_itself(app):
    """Tabs and stacked pages anywhere (workshop sections, drawers, settings) fade without wiring."""
    from twobyteasr.design import transitions
    stack = _stack()
    _pump(app, 0.1)
    stack.setCurrentIndex(1)
    _pump(app, 0.03)
    overlays = stack.findChildren(transitions.PageCrossfade)
    assert len(overlays) == 1 and stack.currentIndex() == 1
    _pump(app, 0.6)
    assert not stack.findChildren(transitions.PageCrossfade)
    stack.deleteLater()


def test_the_main_window_switch_is_not_faded_twice(app):
    from twobyteasr.design import transitions
    stack = _stack()
    _pump(app, 0.1)
    picture = transitions.capture_page(stack)              # the main window owns this switch
    stack.setCurrentIndex(1)
    transitions.start_page_crossfade(stack, picture)
    _pump(app, 0.03)
    assert len(stack.findChildren(transitions.PageCrossfade)) == 1
    _pump(app, 0.6)
    stack.deleteLater()


def test_a_small_or_hidden_stack_switches_plainly(app):
    from PySide6.QtWidgets import QLabel, QStackedWidget
    from twobyteasr.design import transitions
    small = QStackedWidget()
    small.addWidget(QLabel('a'))
    small.addWidget(QLabel('b'))
    small.resize(40, 20)
    small.show()
    _pump(app, 0.05)
    small.setCurrentIndex(1)
    _pump(app, 0.03)
    assert not small.findChildren(transitions.PageCrossfade)
    hidden = _stack()
    hidden.hide()
    hidden.setCurrentIndex(1)
    _pump(app, 0.03)
    assert not hidden.findChildren(transitions.PageCrossfade)
    small.deleteLater()
    hidden.deleteLater()


def test_content_change_fades_the_old_content_over_the_new(app):
    from PySide6.QtWidgets import QLabel
    from twobyteasr.design import transitions
    label = QLabel('主力转写')
    label.resize(300, 200)
    label.show()
    _pump(app, 0.1)
    with transitions.content_change(label):
        label.setText('字幕时间轴')
    assert label.text() == '字幕时间轴'                       # the new content is there at once
    assert len(label.findChildren(transitions.PageCrossfade)) == 1
    _pump(app, 0.6)
    assert not label.findChildren(transitions.PageCrossfade)
    label.deleteLater()


def _card_list(count=6):
    from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget
    area = QScrollArea()
    host = QWidget()
    layout = QVBoxLayout(host)
    for i in range(count):
        card = QFrame()
        card.setObjectName('modelCard')
        card.setFixedHeight(60)
        card.setStyleSheet('background: #ddd;')
        layout.addWidget(card)
    area.setWidget(host)
    area.setWidgetResizable(True)
    area.resize(400, 300)
    area.setStyleSheet('QScrollArea, QScrollArea > QWidget > QWidget { background: #fafafa; }')
    area.show()
    return area


def test_cards_come_in_one_after_another(app):
    from twobyteasr.design import motion_tokens, transitions
    area = _card_list()
    _pump(app, 0.1)
    veils = transitions.stagger_list(area)
    assert veils is not None and len(veils.rects) >= 3
    _pump(app, 0.06)
    alphas = [veils._alpha(i) for i in range(len(veils.rects))]
    assert alphas == sorted(alphas)                            # later cards still more hidden
    assert alphas[0] < alphas[-1]
    _pump(app, 0.8)
    assert not area.viewport().findChildren(transitions.StaggerVeils)
    area.deleteLater()


def test_scrolling_ends_the_entrance_at_once(app):
    from twobyteasr.design import transitions
    area = _card_list(12)
    _pump(app, 0.1)
    veils = transitions.stagger_list(area)
    assert veils is not None
    area.verticalScrollBar().setValue(40)
    _pump(app, 0.03)
    assert not [v for v in area.viewport().findChildren(transitions.StaggerVeils) if v.isVisible()]
    area.deleteLater()


def test_a_floating_fade_is_a_click_through_window_above_its_target(app):
    from PySide6.QtCore import Qt
    from twobyteasr.design import transitions
    stack = _stack()
    _pump(app, 0.05)
    picture = stack.grab()
    overlay = transitions.PageCrossfade(stack, picture, floating=True)
    overlay.start()
    assert overlay.isWindow() and overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert overlay.geometry().topLeft() == stack.mapToGlobal(stack.rect().topLeft())
    _pump(app, 0.6)
    assert not [w for w in __import__('PySide6.QtWidgets', fromlist=['QApplication']).QApplication.topLevelWidgets()
                if isinstance(w, transitions.PageCrossfade) and w.isVisible()]
    stack.deleteLater()


def test_the_loading_card_is_set_to_fade_in_and_out():
    import inspect
    from twobyteasr.studio import studio_loading
    assert 'fade_on_show_and_hide(self)' in inspect.getsource(studio_loading.StudioLoadingView.__init__)


def test_menus_and_tooltips_follow_reduced_motion(app):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    assert QApplication.isEffectEnabled(Qt.UIEffect.UI_FadeMenu)
    assert QApplication.isEffectEnabled(Qt.UIEffect.UI_FadeTooltip)
    app.setProperty("reduceMotion", True)
    try:
        assert not QApplication.isEffectEnabled(Qt.UIEffect.UI_FadeMenu)
        assert not QApplication.isEffectEnabled(Qt.UIEffect.UI_FadeTooltip)
    finally:
        app.setProperty("reduceMotion", False)
    assert QApplication.isEffectEnabled(Qt.UIEffect.UI_FadeMenu)


def test_a_dialog_grows_out_of_the_clicked_card(app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialog, QFrame, QLabel, QVBoxLayout, QWidget
    host = QWidget()
    host.resize(600, 400)
    card = QFrame(host)
    card.setObjectName('historyCard')
    card.setGeometry(300, 200, 200, 120)
    label = QLabel('一条识别记录', card)
    label.move(10, 10)
    host.show()
    _pump(app, 0.05)
    QTest.mouseClick(label, Qt.MouseButton.LeftButton)
    origin = app._dialog_motion._origin()
    assert origin is not None and origin.size() == card.size()     # the card, not the label
    dialog = QDialog(host)
    dialog.resize(300, 200)
    dialog.show()
    _pump(app, 0.03)
    flight = next(iter(app._dialog_motion._flights.values()))
    centre = card.mapToGlobal(card.rect().center())
    final = dialog.frameGeometry().center()
    assert abs(flight.start.center().x() - (final.x() + (centre.x() - final.x()) * 0.4)) < 4
    _pump(app, 1.0)
    dialog.hide()
    _pump(app, 0.5)
    host.deleteLater()


def test_the_run_progress_bar_glides_to_its_value(app):
    from twobyteasr.app.progress_widgets import StageProgressBar
    bar = StageProgressBar()
    bar.resize(400, 12)
    bar.show()
    _pump(app, 0.05)
    bar.setValue(600)
    assert bar.value() == 600                                   # the real value at once
    shown = []
    end = time.time() + 1.2
    while time.time() < end and bar._glide.isActive():
        app.processEvents()
        shown.append(bar._shown)
        time.sleep(0.004)
    assert len(set(round(s) for s in shown)) > 5 and shown == sorted(shown)    # glides up, no overshoot
    assert not bar._glide.isActive() and bar._shown == 600
    bar.setValue(0)                                             # a new run: straight back to empty
    assert bar._shown == 0 and not bar._glide.isActive()
    bar.deleteLater()


def test_the_real_app_turns_dialog_motion_on_and_pages_fade():
    import inspect
    from pathlib import Path
    from twobyteasr.app import ui
    source = (Path(__file__).resolve().parents[1] / 'quick_start.py').read_text('utf-8')
    assert 'install_dialog_motion(app)' in source
    switch = inspect.getsource(ui.MainWindow._switch_page)
    assert 'capture_page(self.pages)' in switch and 'start_page_crossfade(self.pages' in switch
    # Under the loading cover the cover fades; into or out of Studio the picture goes up in the
    # kept cover before the switch (2026-11-19).
    assert 'elif not native_cover_mode' in switch and 'cover_page(self.pages' in switch


def test_pictures_go_on_as_plain_copies_at_fractional_screen_scales(app):
    """2026-11-19 (user: the motion looks below 15 fps; screen 3840x2160 at 175 %): at a fractional
    device pixel ratio a picture is drawn in device pixels, the same pixels as before, with the
    painter's transform back as it was."""
    from PySide6.QtCore import QPoint, QPointF, QRect, QRectF
    from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
    from twobyteasr.design.transitions import _source, draw_picture
    ratio = 1.75
    image = QImage(int(300 * ratio), int(200 * ratio), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor('#203040'))
    marks = QPainter(image)
    marks.fillRect(20, 30, 90, 40, QColor(220, 60, 120, 200))
    marks.fillRect(200, 120, 60, 50, QColor('#f0e0a0'))
    marks.end()
    picture = QPixmap.fromImage(image)
    picture.setDevicePixelRatio(ratio)

    def render(paint):
        target = QImage(int(320 * ratio), int(220 * ratio), QImage.Format.Format_ARGB32_Premultiplied)
        target.setDevicePixelRatio(ratio)
        target.fill(0)
        painter = QPainter(target)
        painter.translate(4, 2)
        painter.setOpacity(0.6)
        paint(painter)
        transform = painter.worldTransform()
        painter.end()
        return target, (transform.dx(), transform.dy(), transform.m11())

    expected, _ = render(lambda p: p.drawPixmap(QPoint(0, 8), picture))
    drawn, transform = render(lambda p: draw_picture(p, QPoint(0, 8), picture))
    assert drawn == expected and transform == (4, 2, 1.0)
    part = QRect(16, 24, 120, 60)
    expected, _ = render(lambda p: p.drawPixmap(QRectF(part).translated(6, 0), picture, _source(part, ratio)))
    drawn, _ = render(lambda p: draw_picture(p, QPointF(part.x() + 6, part.y()), picture, _source(part, ratio)))
    assert drawn == expected
    # A scaled draw (a page stepping back) stays Qt's own.
    expected, _ = render(lambda p: (p.scale(0.97, 0.97), p.drawPixmap(QPoint(0, 0), picture)))
    drawn, _ = render(lambda p: (p.scale(0.97, 0.97), draw_picture(p, QPoint(0, 0), picture)))
    assert drawn == expected
