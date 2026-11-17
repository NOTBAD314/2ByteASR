"""The tutorial never locks the program (2026-11-16).

User: in the first tutorial, step 15 「开始生成字幕」 turned the whole window grey and nothing
could be clicked; the only way out was to kill the program, and the next start brought the
required tutorial back. Two causes:

* since 2026-11-15 a result only brings its page forward while the progress page is in front,
  and the tutorial's pretend result is started from the home page, so the result page the
  next step waits for never came;
* while a step waits for its page the whole window is under the shade, without bubble, and a
  required first tutorial had no 跳过教学 and ignored Esc.

Now the demo shows the result page itself, a step whose page does not come gives the window
back after ``STUCK_MS`` (only a chip: 跳过这一步 / 结束教学), and 跳过教学 / Esc always leave -
also a required first tutorial, which then counts as done.
"""
import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QStackedWidget, QWidget

from twobyteasr.app.home_tour import GuidedTour, TourStep


@pytest.fixture(params=[True, False], ids=['tool-window', 'child-widget'], autouse=True)
def overlay_kind(request, monkeypatch):
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


def _window():
    window = QWidget()
    window.resize(1400, 900)
    first = QPushButton('第一步', window)
    first.setGeometry(100, 100, 160, 44)
    last = QPushButton('第三步', window)
    last.setGeometry(400, 400, 160, 44)
    window.edit = QLineEdit(window)                    # something with the keyboard focus
    window.edit.setGeometry(100, 600, 300, 40)
    window.show()
    window.activateWindow()
    window.edit.setFocus()
    return window, first, last


def test_a_step_whose_page_never_comes_gives_the_window_back(monkeypatch):
    _app()
    monkeypatch.setattr(GuidedTour, 'STUCK_MS', 300)
    window, first, last = _window()
    tour = GuidedTour(window, [TourStep('看这里', lambda: first),
                               TourStep('做好啦！', lambda: None, ready=lambda: False),   # the page never comes
                               TourStep('最后', lambda: last)])
    tour.start()
    _until(lambda: _shown(tour))
    tour.next.click()
    _until(lambda: tour.mode == 'away')
    # Only the chip takes clicks: the rest of the window works again.
    assert tour.chip.isVisible() and not tour.chip_next.isHidden() and tour.chip_resume.isHidden()
    assert not tour.chip_end.isHidden()
    assert not tour.mask().isEmpty() and tour.mask().boundingRect().width() < 700
    assert tour.chip_text.text() == '这一步的画面没出现'
    tour.chip_next.click()
    _until(lambda: _shown(tour) and tour.index == 2)
    assert tour.chip.isHidden() and tour.chip_text.text() == '教学已暂停'
    tour.close_tour(True)
    window.close()


def test_the_page_coming_late_brings_the_step_back(monkeypatch):
    _app()
    monkeypatch.setattr(GuidedTour, 'STUCK_MS', 300)
    window, first, last = _window()
    late = QPushButton('结果', window)
    late.setGeometry(600, 200, 160, 44)
    late.hide()
    tour = GuidedTour(window, [TourStep('看这里', lambda: first), TourStep('结果出来了', lambda: late)])
    tour.start()
    _until(lambda: _shown(tour))
    tour.next.click()
    _until(lambda: tour.mode == 'away')
    late.show()
    _until(lambda: _shown(tour))
    assert tour.index == 1 and not tour.chip.isVisible()
    tour.close_tour(True)
    window.close()


def test_the_way_out_of_a_stuck_step_ends_the_tutorial(monkeypatch):
    _app()
    monkeypatch.setattr(GuidedTour, 'STUCK_MS', 300)
    window, first, _last = _window()
    finished, skipped = [], []
    tour = GuidedTour(window, [TourStep('看这里', lambda: first), TourStep('等不到', lambda: None, ready=lambda: False)])
    tour.finished.connect(finished.append)
    tour.skipped.connect(lambda: skipped.append(True))
    tour.set_required(True)
    tour.start()
    _until(lambda: _shown(tour))
    tour.next.click()
    _until(lambda: tour.mode == 'away')
    tour.chip_end.click()
    assert tour.mode == 'closed' and finished == [False] and skipped == [True]
    window.close()


def test_escape_leaves_even_while_a_step_is_still_waited_for(monkeypatch):
    _app()
    monkeypatch.setattr(GuidedTour, 'STUCK_MS', 60000)
    window, first, _last = _window()
    skipped = []
    tour = GuidedTour(window, [TourStep('看这里', lambda: first),
                               TourStep('在这里打字', lambda: None, ready=lambda: False, interactive=True)])
    tour.skipped.connect(lambda: skipped.append(True))
    tour.set_required(True)
    tour.start()
    _until(lambda: _shown(tour))
    tour.next.click()
    _until(lambda: tour.mode == 'wait' and tour.index == 1)
    QTest.keyClick(window.edit, Qt.Key.Key_Escape)
    _until(lambda: tour.mode == 'closed')
    assert skipped == [True]
    window.close()


def test_escape_works_when_the_main_window_itself_has_the_focus():
    """Real run: after the plan window closes the focus is on the main window itself."""
    _app()
    window, first, _last = _window()
    window.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    window.setFocus()
    _until(lambda: QApplication.focusWidget() is window)
    skipped = []
    tour = GuidedTour(window, [TourStep('看这里', lambda: first), TourStep('下一步', lambda: _last),
                               TourStep('完成')])
    tour.skipped.connect(lambda: skipped.append(True))
    tour.start()
    _until(lambda: _shown(tour))
    QTest.keyClick(window, Qt.Key.Key_Return)          # Enter = 下一步, also here
    _until(lambda: tour.index == 1 and _shown(tour))
    QTest.keyClick(window, Qt.Key.Key_Escape)
    _until(lambda: tour.mode == 'closed')
    assert skipped == [True]
    window.close()


def test_a_required_tutorial_shows_the_skip_and_escape_leaves_it():
    _app()
    window, first, _last = _window()
    skipped = []
    tour = GuidedTour(window, [TourStep('看这里', lambda: first), TourStep('完成')])
    tour.skipped.connect(lambda: skipped.append(True))
    tour.set_required(True)
    tour.start()
    _until(lambda: _shown(tour))
    assert tour.skip.isVisible() and 'Esc' in tour.skip.text()
    QTest.keyClick(window.edit, Qt.Key.Key_Escape)
    _until(lambda: tour.mode == 'closed')
    assert skipped == [True]
    window.close()


# ---------------------------------------------------------------- the main window's side

def test_the_demo_result_brings_the_result_page_from_the_home_page(monkeypatch, tmp_path):
    """The tutorial clicks 开始生成字幕 on the home page; the step after waits for the result page."""
    _app()
    from twobyteasr.app import sample_project
    from twobyteasr.app.ui import MainWindow
    from twobyteasr.exports import studio_subtitle_export
    from twobyteasr.projects import studio_project
    media = tmp_path / '教学影片.mp4'
    media.write_bytes(b'')
    monkeypatch.setattr(sample_project, 'ensure_tutorial_project', lambda: tmp_path / 'tutorial.2byteasr')
    monkeypatch.setattr(sample_project, 'tutorial_root', lambda: tmp_path)
    monkeypatch.setattr(studio_project, 'load_project', lambda _path: SimpleNamespace(cues=[]))
    monkeypatch.setattr(studio_subtitle_export, 'compile_srt', lambda _cues: '')
    pages = QStackedWidget()
    home, progress, completion = QWidget(), QWidget(), QWidget()
    completion.setObjectName('completionScroll')
    for page in (home, progress, completion):
        pages.addWidget(page)
    handled = []
    # Like _handle_result since 2026-11-15: from the home page it does not switch pages.
    window = SimpleNamespace(pages=pages, _handle_result=handled.append, _tutorial_demo_media=lambda: media,
                             _switch_page=pages.setCurrentWidget)
    MainWindow._tutorial_demo_completion(window)
    assert len(handled) == 1 and handled[0].results[0].status == 'success'
    assert pages.currentWidget() is completion
    assert window._tutorial_demo_result is False


def test_skipping_the_required_first_tutorial_releases_the_program(monkeypatch):
    _app()
    from twobyteasr.app import home_tour, onboarding
    from twobyteasr.app.ui import MainWindow
    state = {'fresh': True, 'guide': True, 'tour_done': False, 'first_task_done': False}
    monkeypatch.setattr(onboarding, 'load_state', lambda: dict(state))
    monkeypatch.setattr(onboarding, 'save_state', lambda new: state.update(new))
    calls = []

    def fake_start(window, on_finished=None, part='all', *, required=False, on_skipped=None):
        calls.append(dict(on_finished=on_finished, required=required, on_skipped=on_skipped))
    monkeypatch.setattr(home_tour, 'start_home_tour', fake_start)
    home = QWidget()
    pages = QStackedWidget()
    pages.addWidget(home)
    finished = []
    window = SimpleNamespace(pages=pages, settings_scroll=home, _tutorial_plan_chosen=True,
                             _first_run_required=True, findChild=lambda _cls: None,
                             _tutorial_finish=finished.append)
    MainWindow._start_home_tour(window)
    assert calls and calls[0]['required'] is True and callable(calls[0]['on_skipped'])
    assert onboarding.first_run_required(dict(state))     # still required while it runs
    calls[0]['on_skipped']()                               # 跳过教学 / 结束教学 / Esc
    calls[0]['on_finished'](False)
    assert state['tour_done'] is True and window._first_run_required is False
    assert not onboarding.first_run_required(dict(state))  # the next start does not bring it back
    assert finished == [False]


def test_closing_the_app_midway_keeps_the_first_tutorial_for_next_time(monkeypatch):
    _app()
    from twobyteasr.app import home_tour, onboarding
    from twobyteasr.app.ui import MainWindow
    state = {'fresh': True, 'guide': True, 'tour_done': False, 'first_task_done': False}
    monkeypatch.setattr(onboarding, 'load_state', lambda: dict(state))
    monkeypatch.setattr(onboarding, 'save_state', lambda new: state.update(new))
    calls = []
    monkeypatch.setattr(home_tour, 'start_home_tour',
                        lambda window, on_finished=None, part='all', **kw: calls.append(on_finished))
    home = QWidget()
    pages = QStackedWidget()
    pages.addWidget(home)
    window = SimpleNamespace(pages=pages, settings_scroll=home, _tutorial_plan_chosen=True,
                             _first_run_required=True, findChild=lambda _cls: None, _tutorial_finish=lambda _c: None)
    MainWindow._start_home_tour(window)
    calls[0](False)                                       # closed without the person choosing to leave
    assert not state['tour_done'] and onboarding.first_run_required(dict(state))
