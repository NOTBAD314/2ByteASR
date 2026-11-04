"""Tutorial overlay: one calm move per step, live outlines, nothing left behind; timeline card by language (2026-10-14)."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QStackedWidget, QWidget

import pytest

from twobyteasr.app.home_tour import GuidedTour, TourAction, TourStep


@pytest.fixture(params=[True, False], ids=['tool-window', 'child-widget'], autouse=True)
def overlay_kind(request, monkeypatch):
    """Windows uses a tool window, macOS a child widget: the same steps must hold for both."""
    monkeypatch.setattr(GuidedTour, 'FLOATING', request.param)
    return request.param


def _app():
    return QApplication.instance() or QApplication([])


def _until(condition, seconds=4.0):
    app = _app()
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert condition()


def _shown(tour):
    return tour.mode == 'shown' and tour.reveal >= 1.0


def _window(width=1400, height=900):
    window = QWidget()
    window.resize(width, height)
    return window


def test_windows_overlay_is_its_own_tool_window_and_never_takes_the_focus():
    _app()
    window = _window()
    target = QPushButton('目标', window)
    target.setGeometry(100, 100, 120, 40)
    window.show()
    tour = GuidedTour(window, [TourStep('看这里', lambda: target)])
    tour.start()
    _until(lambda: _shown(tour))
    assert tour.isWindow() == GuidedTour.FLOATING
    assert tour.focusPolicy() == Qt.FocusPolicy.NoFocus
    tour.close_tour(False)
    window.close()


def test_changing_step_hides_the_bubble_glides_the_outline_then_shows_the_bubble_once():
    _app()
    window = _window()
    first = QPushButton('一', window)
    first.setGeometry(80, 80, 120, 40)
    second = QPushButton('二', window)
    second.setGeometry(900, 650, 120, 40)
    window.show()
    tour = GuidedTour(window, [TourStep('第一步', lambda: first), TourStep('第二步', lambda: second)])
    tour.start()
    _until(lambda: _shown(tour))

    seen = []

    class Watch(QObject):
        def eventFilter(self, _obj, event):  # noqa: N802 - Qt override
            if event.type() == QEvent.Type.Paint:
                # 2026-10-22: while it fades in, the overlay draws a picture of the bubble.
                drawn = tour.bubble.isVisible() or tour._reveal_pixmap is not None
                seen.append((tour.mode, drawn, tour.bubble.geometry().topLeft(), tour.reveal))
            return False

    watch = Watch()
    tour.installEventFilter(watch)
    tour.go(1)
    _until(lambda: tour.index == 1 and _shown(tour))
    assert not any(visible for mode, visible, _pos, _reveal in seen if mode in ('wait', 'glide'))
    final = tour.bubble.geometry().topLeft()
    shown = [pos for mode, visible, pos, _reveal in seen if visible]
    assert shown and all((pos - final).manhattanLength() <= 12 for pos in shown)   # only the short fade-in slide
    bubble = QRectF(tour.bubble.geometry())
    gap = max(tour.hole.left() - bubble.right(), bubble.left() - tour.hole.right(),
              tour.hole.top() - bubble.bottom(), bubble.top() - tour.hole.bottom())
    assert 0 < gap <= GuidedTour.GAP + 1 and tour.pointer is not None
    tour.close_tour(False)
    window.close()


def test_a_step_with_a_demo_click_runs_it_instead_of_reaching_the_page():
    _app()
    window = _window()
    start = QPushButton('开始生成字幕', window)
    start.setGeometry(1000, 780, 260, 60)
    window.show()
    real, demo = [], []
    start.clicked.connect(lambda: real.append(True))
    tour = GuidedTour(window, [
        TourStep('现在点一下看演示结果', lambda: start, [TourAction('看演示结果', lambda: demo.append(1), advance=True)],
                 show_next=False, click=TourAction('', lambda: demo.append(1), advance=True)),
        TourStep('完成'),
    ])
    tour.start()
    _until(lambda: _shown(tour))
    assert tour.mask().isEmpty()            # the outline is not a hole for clicks: they come to the tutorial
    QTest.mouseClick(tour, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, tour.hole.center().toPoint())
    _until(lambda: tour.index == 1)
    assert demo == [1] and not real
    tour.close_tour(True)
    window.close()


def test_an_in_window_dialog_over_the_target_puts_the_tutorial_on_its_chip_until_it_closes():
    _app()
    window = _window()
    card = QPushButton('主力转写', window)
    card.setGeometry(300, 200, 300, 200)
    window.show()
    tour = GuidedTour(window, [TourStep('点卡片可换模型', lambda: card), TourStep('完成')])
    tour.start()
    _until(lambda: _shown(tour))
    picker = QWidget(window)                 # like the model picker: a child panel over the page
    picker.setGeometry(0, 0, 1400, 900)
    picker.show()
    picker.raise_()
    _until(lambda: tour.mode == 'away')
    assert tour.chip.isVisible() and not tour.bubble.isVisible() and tour.hole.isNull()
    assert not tour.mask().isEmpty() and tour.mask().boundingRect().width() < 600   # only the chip takes clicks
    picker.hide()
    _until(lambda: _shown(tour))
    assert tour.index == 0 and not tour.chip.isVisible()
    tour.close_tour(False)
    window.close()


def test_a_click_that_opens_another_page_leaves_no_outline_or_bubble_behind():
    _app()
    window = _window()
    window.pages = QStackedWidget(window)
    window.pages.setGeometry(0, 0, 1400, 900)
    result, studio = QWidget(), QWidget()
    window.pages.addWidget(result)
    window.pages.addWidget(studio)
    opener = QPushButton('打开字幕工作台', result)
    opener.setGeometry(500, 400, 300, 80)
    ready = []
    opener.clicked.connect(lambda: window.pages.setCurrentWidget(studio))
    window.show()
    tour = GuidedTour(window, [
        TourStep('点这里打开字幕工作台', lambda: opener, interactive=True, show_next=False, done=lambda: bool(ready)),
        TourStep('完成'),
    ])
    tour.start()
    _until(lambda: _shown(tour))
    opener.click()
    _app().processEvents()                   # the page switch is seen at once, not on the next poll
    assert tour.mode == 'pending' and not tour.bubble.isVisible() and tour.hole.isNull()
    assert tour.anim._movie is None
    ready.append(True)                       # the workbench finished loading
    _until(lambda: tour.index == 1 and _shown(tour))
    tour.close_tour(True)
    window.close()


def test_keys_go_to_the_tutorial_only_on_its_own_steps():
    _app()
    window = _window()
    edit = QLineEdit(window)
    edit.setGeometry(100, 100, 300, 40)
    window.show()
    window.activateWindow()
    tour = GuidedTour(window, [
        TourStep('看这里', lambda: edit),
        TourStep('在这里打字', lambda: edit, interactive=True, show_next=False, focus=lambda: edit,
                 done=lambda: edit.text() == 'ab'),
        TourStep('完成'),
    ])
    tour.start()
    _until(lambda: _shown(tour))
    QTest.keyClick(edit, Qt.Key.Key_X)       # a tutorial step: the page does not get it
    assert edit.text() == ''
    QTest.keyClick(edit, Qt.Key.Key_Return)  # Enter = 下一步
    _until(lambda: tour.index == 1 and _shown(tour))
    QTest.keyClicks(edit, 'ab')              # the page's step: keys reach the field
    _until(lambda: tour.index == 2)
    tour.close_tour(True)
    window.close()


# ---------------------------------------------------------------- home timeline card


def _main_window(monkeypatch, *, ctc_installed=True, ctc_on=True):
    _app()
    import subtitle_core as legacy
    import twobyteasr.app.ui as ui_mod
    from twobyteasr.recognition import ctc_alignment
    from twobyteasr.app.ui import MainWindow
    models = legacy.RUNTIME_SETTINGS.setdefault("models", {})
    for key, value in {"primary_asr_backend": "moss", "qwen_asr_backend": "local", "firered_asr_backend": "local"}.items():
        monkeypatch.setitem(models, key, value)
    monkeypatch.setitem(legacy.RUNTIME_SETTINGS.setdefault("switches", {}), ctc_alignment.SWITCH, ctc_on)
    monkeypatch.setattr(ui_mod, "installed_model_keys", lambda _root: {
        "moss", "firered_vad", "speaker_embedding", "qwen_asr", "firered_aed", "qwen_aligner"})
    monkeypatch.setattr(ctc_alignment, "model_dir", lambda: "C:/models/ctc" if ctc_installed else None)
    return MainWindow([], legacy, object(), None)


def _speak(win, code):
    win.recognition_language.setCurrentIndex(win.recognition_language.findData(code))


def test_timeline_card_names_what_runs_for_the_spoken_language(monkeypatch):
    win = _main_window(monkeypatch)
    card = win.recognition_plan.cards["timeline"]
    _speak(win, "zh")
    assert card.model_label.text() == "FireRedASR2-AED" and "已就绪" in card.status_badge.text()
    _speak(win, "ja")       # Japanese never uses the Chinese timeline model; the CTC aligner adds line starts
    assert card.model_label.text() == "Qwen3 对齐 + 日语 CTC" and "已就绪" in card.status_badge.text()
    assert "日语 CTC" in win.subtitle_language_hint.text()
    _speak(win, "en")
    assert card.model_label.text() == "Qwen3 对齐"
    win.close()


def test_timeline_card_leaves_out_ctc_when_it_is_off_or_missing(monkeypatch):
    win = _main_window(monkeypatch, ctc_on=False)
    _speak(win, "ja")
    assert win.recognition_plan.cards["timeline"].model_label.text() == "Qwen3 对齐"
    assert "CTC" not in win.subtitle_language_hint.text()
    win.close()
    win = _main_window(monkeypatch, ctc_installed=False)
    _speak(win, "ja")
    assert win.recognition_plan.cards["timeline"].model_label.text() == "Qwen3 对齐"
    win.close()
