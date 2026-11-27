"""2026-11-18: first opens within 0.2 s — idle preparation and the stalls it replaced."""
import inspect
import importlib.util
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QVBoxLayout, QWidget

ROOT = Path(__file__).parents[1]


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _drain(steps):
    count = 0
    for _ in steps:
        count += 1
    return count


# --- settings window -------------------------------------------------------

def test_prepared_settings_window_is_the_one_the_first_click_shows(app, monkeypatch):
    from twobyteasr.app import application_settings as settings
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    parent = QWidget()
    preferences = {'autosave_enabled': True}
    monkeypatch.setattr(settings, 'read_studio_preferences', lambda: dict(preferences))
    opened = []
    monkeypatch.setattr(ApplicationSettingsDialog, 'exec', lambda dialog: opened.append(dialog) or QDialog.Rejected)
    assert _drain(settings.prepare_application_settings_steps(parent)) >= 4
    prepared = parent._application_settings_cache
    assert prepared is not None and not prepared.isVisible()
    # Prepared is not "open": a click must still run the opening path.
    assert parent.__dict__.get('_application_settings_dialog') is None
    assert prepared.testAttribute(Qt.WidgetAttribute.WA_WState_Polished)
    settings.open_application_settings(parent)
    assert opened == [prepared]
    # Running the steps again keeps the cached window instead of building a second one.
    _drain(settings.prepare_application_settings_steps(parent))
    assert parent._application_settings_cache is prepared
    parent.deleteLater()


def test_prepared_settings_window_is_replaced_when_what_it_shows_changed(app, monkeypatch):
    from twobyteasr.app import application_settings as settings
    from twobyteasr.app.application_settings_ui import ApplicationSettingsDialog
    parent = QWidget()
    shown = ['theme A']   # stands for anything the stamp covers (preferences file, theme, language...)
    monkeypatch.setattr(settings, '_dialog_cache_stamp', lambda *args: shown[0])
    opened = []
    monkeypatch.setattr(ApplicationSettingsDialog, 'exec', lambda dialog: opened.append(dialog) or QDialog.Rejected)
    _drain(settings.prepare_application_settings_steps(parent))
    prepared = parent._application_settings_cache
    shown[0] = 'theme B'
    settings.open_application_settings(parent)
    assert opened[0] is not prepared
    parent.deleteLater()


def test_settings_preparation_leaves_an_open_window_alone(app, monkeypatch):
    from twobyteasr.app import application_settings as settings
    parent = QWidget()
    monkeypatch.setattr(settings, 'read_studio_preferences', lambda: {})
    parent._application_settings_dialog = QWidget()
    _drain(settings.prepare_application_settings_steps(parent))
    assert parent.__dict__.get('_application_settings_cache') is None
    parent.deleteLater()


# --- idle runner -----------------------------------------------------------

def test_idle_runner_takes_one_step_per_turn_waits_off_home_and_stops_on_error(app, monkeypatch):
    from twobyteasr.app.idle_prepare import IdlePreparation
    from twobyteasr.design import frame_clock
    monkeypatch.setattr(frame_clock, 'motion_active', lambda: False)   # (a 兔白 left by an earlier test)
    ran = []
    allowed = [False]

    def steps():
        ran.append(1)
        yield
        ran.append(2)
        yield
        raise RuntimeError('controlled')

    host = QWidget()
    runner = IdlePreparation(host, steps(), allowed=lambda: allowed[0])
    runner.start()
    QTest.qWait(60)
    assert ran == [] and not runner.done          # not idle: nothing runs
    allowed[0] = True
    QTest.qWait(700)
    assert ran == [1, 2] and runner.done          # error ends preparation quietly
    assert len(runner.timings) == 3
    host.deleteLater()


def test_idle_steps_wait_while_the_bunny_is_in_motion(app, monkeypatch):
    """2026-11-27 (user: when Home appears and while 兔白 plays with the page she stutters): a page
    building step held the GUI thread 30-200 ms between her frames; none runs while she moves."""
    from twobyteasr.app import idle_prepare
    from twobyteasr.design import frame_clock
    monkeypatch.setattr(frame_clock, '_hold_until', 0.0)
    monkeypatch.setattr(frame_clock, '_master', None)  # (timers left running by earlier tests)
    host = QWidget()
    timer = frame_clock.FrameTimer(host, 16, motion=True)
    calm = frame_clock.FrameTimer(host, 16)           # her breathing alone is no motion
    calm.start()
    assert not frame_clock.motion_active()
    timer.start()
    assert frame_clock.motion_active() and idle_prepare._dialog_or_motion()
    timer.stop()
    assert not frame_clock.motion_active()
    frame_clock.hold_motion(0.3)                      # her entrance
    assert frame_clock.motion_active()
    QTest.qWait(350)
    assert not frame_clock.motion_active()
    calm.stop()
    host.deleteLater()


def test_idle_preparation_never_competes_with_a_queued_studio_entry():
    from types import SimpleNamespace
    from twobyteasr.app.idle_prepare import _home_idle
    window = SimpleNamespace(_studio_idle_allowed=lambda: True)
    assert _home_idle(window)
    window._studio_entry_pending = ('project', {})
    assert not _home_idle(window)


def test_studio_warm_up_starts_idle_preparation():
    from twobyteasr.app import ui
    source = inspect.getsource(ui.MainWindow._warm_studio_module)
    assert '_start_idle_preparation(self)' in source


# --- theme scopes ------------------------------------------------------------

def test_managed_window_reads_class_and_instance_dict(app):
    from twobyteasr.design.theme_scopes import managed_window
    plain = QWidget()
    assert not managed_window(plain)
    named = QWidget()
    named.setObjectName('applicationSettings')
    assert managed_window(named)
    fake = QWidget()
    fake.built_page = lambda name: None
    assert not managed_window(fake)               # needs pages too
    fake.pages = object()
    assert managed_window(fake)

    class Window(QWidget):
        def built_page(self, name):
            return None

    window = Window()
    window.pages = object()
    assert managed_window(window)
    for widget in (plain, named, fake, window):
        widget.deleteLater()


def test_prepare_steps_polishes_leaf_first_in_slices(app, monkeypatch):
    from twobyteasr.design import gui_slices, theme_scopes
    monkeypatch.setattr(gui_slices.GuiSlice, 'due', lambda self: True)
    root = QWidget()
    root.setObjectName('applicationSettings')
    root.setStyleSheet('QPushButton { padding: 4px; }')
    layout = QVBoxLayout(root)
    buttons = [QPushButton(str(i)) for i in range(30)]
    for button in buttons:
        layout.addWidget(button)
    steps = theme_scopes.prepare_steps(root)
    next(steps)
    polished_after_first = sum(b.testAttribute(Qt.WidgetAttribute.WA_WState_Polished) for b in buttons)
    assert polished_after_first == 0              # styling the root does not polish the tree at once
    yields = 1 + _drain(steps)
    assert yields >= len(buttons)
    assert all(b.testAttribute(Qt.WidgetAttribute.WA_WState_Polished) for b in buttons)
    root.deleteLater()


# --- Studio ----------------------------------------------------------------

def test_studio_preload_covers_construction_modules_before_studio_ui():
    from twobyteasr.app import studio_module_preload as preload
    assert preload.MODULES[-1] == 'studio.studio_ui'
    assert set(preload.BUILD_MODULES) <= set(preload.MODULES)
    missing = [name for name in preload.MODULES if importlib.util.find_spec('twobyteasr.' + name) is None]
    assert missing == []
    for name in ('studio.studio_workspace', 'studio.gui_thread_handoff', 'cover.cover_studio'):
        assert name in preload.BUILD_MODULES


def test_studio_preload_imports_through_the_import_statement_hook(monkeypatch):
    import builtins
    from twobyteasr.app import studio_module_preload as preload
    seen = []
    original = builtins.__import__

    def spy(name, *args, **kwargs):
        seen.append(name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', spy)
    module = preload.import_module('twobyteasr.app.idle_prepare')
    assert module is sys.modules['twobyteasr.app.idle_prepare']
    assert 'twobyteasr.app.idle_prepare' in seen
    assert preload.StudioModulePreloader().importer is preload.import_module


def test_studio_construction_uses_the_complete_sheet_and_no_dictionary_warmup():
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    source = inspect.getsource(SubtitleStudioPage.__init__)
    assert 'warm_text_analysis()' not in source
    assert 'apply_scope(self)' in source
    assert 'setStyleSheet(SHELL_QSS)' not in source


# --- model workshop ----------------------------------------------------------

@pytest.fixture
def isolated_models(tmp_path, monkeypatch):
    from twobyteasr.runtime_paths import reset_runtime_paths, MODEL_ROOT_ENV, USER_DATA_ENV
    monkeypatch.setenv('TWOBYTEASR_TEST_ROOT', str(tmp_path))
    monkeypatch.setenv(MODEL_ROOT_ENV, str(tmp_path / 'models'))
    monkeypatch.setenv(USER_DATA_ENV, str(tmp_path / 'local'))
    reset_runtime_paths()
    yield
    reset_runtime_paths()


def test_workshop_builds_hidden_in_steps_and_a_visit_finishes_any_rest(app, isolated_models):
    from twobyteasr.local_models.model_workshop import ModelWorkshopPage
    page = ModelWorkshopPage(ROOT, {'models': {}}, defer_ui=True)
    try:
        steps = page.prepare_hidden_steps()
        next(steps)                                 # UI built, refresh still pending
        assert page._ui_built and page._ui_refresh_pending
        page.ensure_ui()                            # a click in between completes it
        assert not page._ui_refresh_pending
        _drain(steps)
        assert page.testAttribute(Qt.WidgetAttribute.WA_WState_Polished)
        assert page.sidebar.testAttribute(Qt.WidgetAttribute.WA_WState_Polished)
        assert not page.isVisible()
        page.resize(1440, 900)
        page.show()
        app.processEvents()
        assert page.sidebar.isVisible()
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()


def test_workshop_preparation_stops_once_the_page_is_shown(app, isolated_models):
    from twobyteasr.local_models.model_workshop import ModelWorkshopPage
    page = ModelWorkshopPage(ROOT, {'models': {}}, defer_ui=True)
    try:
        page.ensure_ui()
        page.show()
        app.processEvents()
        assert _drain(page.prepare_hidden_steps()) == 0
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()
