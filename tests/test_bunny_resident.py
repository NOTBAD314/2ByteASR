"""兔白 in the window by default, speaking up on her own (2026-11-18, phase 3)."""
from __future__ import annotations

import time

import pytest

from twobyteasr.app import bunny_events


@pytest.fixture(autouse=True)
def fresh_choices():
    from twobyteasr.app.onboarding import load_state, save_state
    save_state({key: value for key, value in load_state().items() if key != bunny_events.KEY})
    yield
    save_state({key: value for key, value in load_state().items() if key != bunny_events.KEY})


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _text(label) -> str:
    import re
    return re.sub(r'<[^>]+>', '', label.source_html).replace(chr(0x2060), '')


def _spin(app, seconds=0.05):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)


# ------------------------------------------------------------------ the rules (no Qt)
def test_by_default_she_is_there_and_speaks_up():
    values = bunny_events.load()
    assert values['resident'] is True and values['mode'] == 'all' and bunny_events.resident_wanted(values)
    session = bunny_events.Session()
    assert bunny_events.decide('first_run', values, session).key == 'first_run'
    bunny_events.shown('first_run', session)
    assert bunny_events.load()['intro'] is True
    assert bunny_events.decide('first_run', bunny_events.load(), bunny_events.Session()) is None    # once, ever


def test_levels_cooldowns_and_the_cap_per_start():
    values = dict(bunny_events.load(), intro=True)
    session = bunny_events.Session()
    now = 1000.0
    assert bunny_events.decide('recognition_done', values, session, now) is not None
    bunny_events.shown('recognition_done', session, now)
    assert bunny_events.decide('idle_page', values, session, now + 5) is None                 # too soon after another
    assert bunny_events.decide('recognition_failed', values, session, now + 5) is not None    # trouble does not wait
    assert bunny_events.decide('idle_page', values, session, now + 60) is not None
    assert bunny_events.decide('recognition_done', values, session, now + 60) is None         # its own cooldown
    errors_only = dict(values, mode='errors')
    assert bunny_events.decide('recognition_done', errors_only, bunny_events.Session(), now) is None
    assert bunny_events.decide('error_dialog', errors_only, bunny_events.Session(), now) is not None
    assert bunny_events.decide('error_dialog', dict(values, mode='off'), bunny_events.Session(), now) is None
    full = bunny_events.Session(everyday=bunny_events.SESSION_CAP)
    assert bunny_events.decide('idle_page', values, full, now) is None
    assert bunny_events.decide('recognition_failed', values, full, now) is not None
    assert bunny_events.decide('nothing_like_this', values, session, now) is None
    for _ in range(bunny_events.HINTS['recognition_failed'].per_session):
        bunny_events.shown('recognition_failed', full, now)
    assert bunny_events.decide('recognition_failed', values, full, now + 4000) is None        # even trouble has a cap


def test_closed_twice_means_a_quiet_week_and_a_pressed_button_forgives():
    now = 5000.0
    bunny_events.dismissed('idle_page', now)
    assert bunny_events.decide('idle_page', bunny_events.load(), bunny_events.Session(), now + 1) is not None
    bunny_events.dismissed('idle_page', now + 2)
    values = bunny_events.load()
    assert bunny_events.decide('idle_page', values, bunny_events.Session(), now + 3600) is None
    assert bunny_events.decide('recognition_done', values, bunny_events.Session(), now + 3600) is not None
    after_week = now + bunny_events.CLOSED_TWICE_QUIET_S + 10
    assert bunny_events.decide('idle_page', values, bunny_events.Session(), after_week) is not None
    bunny_events.used('idle_page')
    assert 'idle_page' not in bunny_events.load()['closed']


def test_away_today_and_away_for_good():
    bunny_events.save({'quiet_day': bunny_events.today()})
    values = bunny_events.load()
    assert not bunny_events.resident_wanted(values)
    assert bunny_events.decide('recognition_failed', values, bunny_events.Session()) is None
    bunny_events.save({'quiet_day': '2000-01-01'})
    assert bunny_events.resident_wanted()
    bunny_events.save({'resident': False})
    assert not bunny_events.resident_wanted() and bunny_events.load()['mode'] == 'all'


def test_her_words_are_local_and_an_error_box_cannot_break_them():
    for hint in bunny_events.HINTS.values():
        assert hint.lines and len(hint.buttons) <= 2
    line, buttons = bunny_events.wording(bunny_events.HINTS['error_dialog'],
                                         {'title': '导出失败', 'said': '导出失败：{0} {name} ' + '很长' * 200})
    assert '导出失败' in line and len(buttons) == 2 and buttons[1][1] == ''
    assert '{' not in buttons[0][1] and len(buttons[0][1]) < bunny_events.SAID_LIMIT + 40
    assert bunny_events.wording(bunny_events.HINTS['recognition_review'], {}) == ('', ())      # a missing fact: nothing
    assert bunny_events.outcome_event('failed') == ('recognition_failed', {})
    assert bunny_events.outcome_event('completed', 3) == ('recognition_review', {'count': 3})
    assert bunny_events.outcome_event('completed') == ('recognition_done', {})
    assert bunny_events.outcome_event('running') == ('', {})


def test_she_does_not_start_by_herself_under_test_isolation(monkeypatch):
    from twobyteasr.app import bunny_resident
    monkeypatch.delenv(bunny_resident.FORCE_ENV, raising=False)
    monkeypatch.setenv('TWOBYTEASR_TEST_ROOT', 'x')
    assert not bunny_resident.auto_start_allowed()
    monkeypatch.setenv(bunny_resident.FORCE_ENV, '1')
    assert bunny_resident.auto_start_allowed()
    monkeypatch.delenv('TWOBYTEASR_TEST_ROOT')
    monkeypatch.delenv('QT_QPA_PLATFORM', raising=False)
    monkeypatch.setenv(bunny_resident.FORCE_ENV, '0')
    assert not bunny_resident.auto_start_allowed()


# ------------------------------------------------------------------ the widget
class _Chat:
    def __init__(self):
        self.asked = []
        self.visible = False

    def isVisible(self):  # noqa: N802 - Qt's name
        return self.visible

    def ask_now(self, question):
        self.asked.append(question)


@pytest.fixture
def resident(app, monkeypatch):
    from PySide6.QtCore import QObject
    from PySide6.QtWidgets import QWidget
    from twobyteasr.app import bunny_chat, bunny_resident
    monkeypatch.setattr(bunny_chat.BunnyChat, 'FLOATING', False)
    monkeypatch.setattr(bunny_resident.BunnyResident, '_app_in_front', staticmethod(lambda: True))
    window = QWidget()
    window.resize(1100, 720)
    chat = _Chat()
    opened = []

    def open_chat():
        opened.append(True)
        chat.visible = True
        window._bunny_chat = chat
        return chat
    window._open_bunny_chat = open_chat
    window.show()
    app.processEvents()
    made = bunny_resident.install(window, hello=False)
    assert made is not None and bunny_resident.install(window) is made
    made.test_chat, made.test_opened = chat, opened
    app.processEvents()
    yield made
    made._timer.stop()
    app.removeEventFilter(made)
    window.close()
    window.deleteLater()
    app.processEvents()
    assert isinstance(made, QObject)


def test_she_hears_the_whole_app_through_the_shared_hub(app, resident):
    """2026-11-19 (user: every page and dialog stutters the first time): her own application
    filter was a Python call for every event of every widget; the hub calls her for input and
    message boxes only, and she still knows when the person typed anywhere."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication, QLineEdit
    from twobyteasr.app import bunny_resident
    from twobyteasr.design import app_events
    assert app_events.hub().listening(resident)
    assert QEvent.Type.Paint not in bunny_resident._APP_EVENT_TYPES
    field = QLineEdit(resident.window_)
    field.show()
    resident._typed_at = 0.0
    QApplication.sendEvent(field, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, 'a'))
    assert resident._typed_at > 0.0
    field.deleteLater()


def test_she_sits_in_the_corner_and_a_click_opens_the_chat(app, resident):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    window = resident.window_
    assert resident.isVisible() and not resident.bubble.isVisible()
    assert resident.geometry().right() <= window.width() and resident.geometry().bottom() <= window.height()
    assert resident.geometry().right() > window.width() - 60 and resident.geometry().bottom() > window.height() - 60

    def mouse(kind, at, held=True):
        return QMouseEvent(kind, QPointF(10, 10), QPointF(at), Qt.MouseButton.LeftButton,
                           Qt.MouseButton.LeftButton if held else Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    # Dragged: she stays where she was put, and it is remembered.
    start = QPointF(resident.body.mapToGlobal(resident.body.rect().center()))
    resident.eventFilter(resident.body, mouse(QEvent.Type.MouseButtonPress, start))
    resident.eventFilter(resident.body, mouse(QEvent.Type.MouseMove, start + QPointF(-300, -200)))
    resident.eventFilter(resident.body, mouse(QEvent.Type.MouseButtonRelease, start + QPointF(-300, -200), held=False))
    assert not resident.test_opened and resident.geometry().right() < window.width() - 250
    assert bunny_events.load()['place'] == [resident._offset.x(), resident._offset.y()]
    # A plain click opens the chat; while it is open she is not there twice.
    here = QPointF(resident.body.mapToGlobal(resident.body.rect().center()))
    resident.eventFilter(resident.body, mouse(QEvent.Type.MouseButtonPress, here))
    resident.eventFilter(resident.body, mouse(QEvent.Type.MouseButtonRelease, here, held=False))
    assert resident.test_opened and not resident.isVisible()
    resident.test_chat.visible = False
    resident.sync()
    assert resident.isVisible()


def test_a_burst_of_drag_moves_and_window_resizes_places_her_once(app, resident):
    """2026-11-19 (user: opening a project in the workbench froze for up to 1.6 s; the samples were
    in SetWindowPos from her drag, one native move per mouse move, inside the event filter)."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QWidget
    window = resident.window_
    placed, moved = [], []
    apply = resident._placer._apply
    resident._placer._apply = lambda: (placed.append(1), apply())
    resident.move = lambda *args: (moved.append(args), QWidget.move(resident, *args))

    def mouse(kind, at, held=True):
        return QMouseEvent(kind, QPointF(10, 10), QPointF(at), Qt.MouseButton.LeftButton,
                           Qt.MouseButton.LeftButton if held else Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    start = QPointF(resident.body.mapToGlobal(resident.body.rect().center()))
    resident.eventFilter(resident.body, mouse(QEvent.Type.MouseButtonPress, start))
    for step in range(300):
        resident.eventFilter(resident.body, mouse(QEvent.Type.MouseMove, start + QPointF(-step, -step / 2)))
    assert placed == [] and moved == []                     # nothing moved inside the events
    _spin(app, 0.1)
    assert len(placed) == 1 and len(moved) == 1             # one place, for the newest point
    assert resident._offset.x() <= -250
    assert abs(resident.geometry().right() + 1 - (window.width() + resident._offset.x())) <= 1
    resident.eventFilter(resident.body, mouse(QEvent.Type.MouseButtonRelease, start + QPointF(-299, -149), held=False))
    assert len(moved) == 1 and not resident.test_opened
    # The window changing size many times: one place after them.
    placed.clear()
    for step in range(40):
        window.resize(1100 + step, 720)
    assert placed == []
    _spin(app, 0.1)
    assert 1 <= len(placed) <= 2
    # Nothing changed: no move at all.
    count = len(moved)
    resident.place()
    resident.place()
    assert len(moved) == count


def test_a_hint_comes_with_buttons_and_only_a_button_asks_the_ai(app, resident):
    resident.notify('first_run')
    assert resident.bubble.isVisible() and resident.hint_key == 'first_run'
    assert '兔白' in _text(resident.bubble.label) and len(resident.bubble.buttons) == 2
    assert not resident.test_chat.asked and not resident.test_opened        # showing a hint asks nobody
    assert resident.geometry().left() >= 0 and resident.geometry().right() <= resident.window_.width()
    resident.bubble.buttons[1].click()                                      # 「先不用」
    assert not resident.bubble.isVisible() and not resident.test_opened
    resident.notify('recognition_failed')
    assert resident.hint_key == 'recognition_failed'
    resident.bubble.buttons[0].click()                                      # 「帮我看看原因」
    assert resident.test_opened and not resident.bubble.isVisible()
    _spin(app, 0.5)
    assert resident.test_chat.asked and '失败' in resident.test_chat.asked[0]


def test_she_waits_while_the_user_is_busy_and_stays_quiet_when_told(app, resident, monkeypatch):
    resident._typed_at = time.monotonic()                                   # typing right now
    resident.notify('recognition_failed')
    assert not resident.bubble.isVisible() and resident._queue
    resident._typed_at = 0.0
    resident._tick()
    assert resident.hint_key == 'recognition_failed'                        # said once the typing stopped
    resident.bubble.close_button.click()
    resident.notify('recognition_review', count=2)
    assert '2' in _text(resident.bubble.label)
    resident.bubble.close_button.click()
    resident.set_mode('errors')
    resident.session = bunny_events.Session()
    resident.notify('recognition_done')
    assert not resident.bubble.isVisible()
    resident.set_mode('off')
    resident.notify('recognition_failed')
    assert not resident.bubble.isVisible()


def test_a_closed_error_box_is_offered_for_explaining(app, resident):
    from PySide6.QtWidgets import QMessageBox
    question = QMessageBox(QMessageBox.Icon.Warning, '删除', '真的要删除吗？',
                           QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, resident.window_)
    question.show()
    _spin(app)
    question.hide()
    _spin(app, 0.7)
    assert not resident.bubble.isVisible()                                  # a question to the user is not a report
    box = QMessageBox(QMessageBox.Icon.Critical, '导出失败', '显卡编码器 h264_nvenc 不可用（-40） token=example-value',
                      QMessageBox.StandardButton.Ok, resident.window_)
    box.show()
    _spin(app)
    assert not resident.bubble.isVisible()                                  # not over the box itself
    box.hide()
    _spin(app, 0.8)
    assert resident.hint_key == 'error_dialog' and '导出失败' in _text(resident.bubble.label)
    resident.bubble.buttons[0].click()
    _spin(app, 0.5)
    assert 'h264_nvenc' in resident.test_chat.asked[0]
    assert 'example-value' not in resident.test_chat.asked[0]
    box.deleteLater()
    question.deleteLater()


def test_dialog_diagnostics_permission_applies_at_capture_and_click(app, resident, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from twobyteasr.app import bunny_permissions

    access = {'read_diagnostics': False}
    monkeypatch.setattr(bunny_permissions, 'load', lambda: access)
    box = QMessageBox(QMessageBox.Icon.Warning, '导出失败', '编码器不可用',
                      QMessageBox.StandardButton.Ok, resident.window_)
    box.show()
    _spin(app)
    box.hide()
    _spin(app, 0.7)
    assert not resident.bubble.isVisible()

    access['read_diagnostics'] = True
    resident.notify('error_dialog', title='导出失败', said='编码器不可用')
    assert resident.bubble.isVisible()
    access['read_diagnostics'] = False
    resident.bubble.buttons[0].click()
    assert not resident.test_chat.asked and not resident.test_opened
    box.deleteLater()


def test_right_click_choices_send_her_away_and_settings_bring_her_back(app, resident):
    from twobyteasr.app import bunny_resident
    resident.away_today()
    assert not resident.isVisible() and bunny_events.load()['quiet_day'] == bunny_events.today()
    bunny_events.save({'quiet_day': ''})
    bunny_resident.refresh(resident.window_)
    assert resident.isVisible()
    resident.away_for_good()
    assert not resident.isVisible() and bunny_events.load()['resident'] is False
    resident._tick()
    assert not resident.isVisible()                                         # she does not come back on her own
    bunny_events.save({'resident': True})
    bunny_resident.refresh(resident.window_)
    assert resident.isVisible()
    resident._menu(resident.body.mapToGlobal(resident.body.rect().center()))
    labels = [action.text() for action in resident.menu.actions() if action.text()]
    assert '今天先别出来' in labels and '以后不要自动出现' in labels
    resident.menu.close()


def test_the_settings_page_has_both_switches(app, tmp_path):
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    dialog = ApplicationSettingsDialog(None, {}, tmp_path / 'projects', browse=lambda *a: None,
                                       clear_recent=lambda: None, reset_layout=lambda: None)
    try:
        labels = [dialog.navigation.item(i).text() for i in range(dialog.navigation.count())]
        dialog.navigation.setCurrentRow(labels.index('兔白权限'))
        app.processEvents()
        assert dialog.bunny_resident.isChecked() and dialog.bunny_hint_mode.currentData() == 'all'
        assert not dialog._values()
        dialog.bunny_resident.setChecked(False)
        dialog.bunny_hint_mode.setCurrentIndex(dialog.bunny_hint_mode.findData('errors'))
        dialog._save_bunny_permissions()
        saved = bunny_events.load()
        assert saved['resident'] is False and saved['mode'] == 'errors'
    finally:
        dialog._input_baseline = dict(dialog._input_values())
        dialog.reject()
        dialog.deleteLater()
