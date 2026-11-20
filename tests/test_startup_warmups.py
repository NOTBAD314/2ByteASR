"""2026-11-19 (startup, second part): the graphics-card check and the font database are prepared on
threads of their own, the application object carries no style sheet of its own, the theme key is
written only when it changes, and the saved window place is applied once."""
from __future__ import annotations

import sys
import threading

import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ------------------------------------------------------------------ graphics-card check
@pytest.fixture
def gpu(monkeypatch):
    from twobyteasr.system import gpu_probe_warmup
    monkeypatch.setattr(gpu_probe_warmup, '_STATE', {'thread': None, 'handle': None, 'ms': None, 'released': False})
    monkeypatch.delenv('TWOBYTEASR_GPU_WARMUP', raising=False)
    return gpu_probe_warmup


def test_the_graphics_check_runs_once_on_its_own_thread_and_is_let_go(gpu, monkeypatch):
    made, released = [], []

    def create():
        made.append(threading.current_thread().name)
        with gpu._LOCK:
            gpu._STATE['ms'] = 1.0
            gpu._STATE['handle'] = 1234

    monkeypatch.setattr(gpu, '_create', create)
    monkeypatch.setattr(gpu, '_release_handle', released.append)
    monkeypatch.setattr(sys, 'platform', 'win32')
    assert gpu.start() is True
    assert gpu.start() is False                         # once per process
    gpu._STATE['thread'].join(5)
    assert made == ['gpu-probe-warmup']
    assert gpu.elapsed_ms() == 1.0
    gpu.release()
    gpu.release()                                       # a second call has nothing left to release
    assert released == [1234]
    assert gpu.start() is False                         # not started again after the window is up


def test_a_check_that_finishes_after_the_window_is_up_lets_its_object_go_itself(gpu, monkeypatch):
    released = []
    monkeypatch.setattr(gpu, '_release_handle', released.append)

    class Library:
        class Direct3DCreate9:                          # noqa: N801 - the name of the Windows function
            restype = argtypes = None

            def __new__(cls, version):
                return 4321

    import ctypes
    monkeypatch.setattr(ctypes, 'WinDLL', lambda name, *, winmode: Library, raising=False)
    gpu.release()                                       # the window came first
    gpu._create()
    assert released == [4321] and gpu._STATE['handle'] is None


def test_the_graphics_check_can_be_switched_off_and_stays_off_other_systems(gpu, monkeypatch):
    monkeypatch.setattr(gpu, '_create', lambda: pytest.fail('must not run'))
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setenv('TWOBYTEASR_GPU_WARMUP', '0')
    assert gpu.start() is False
    monkeypatch.delenv('TWOBYTEASR_GPU_WARMUP')
    monkeypatch.setattr(sys, 'platform', 'linux')
    assert gpu.start() is False
    assert gpu._STATE['thread'] is None


@pytest.mark.skipif(sys.platform != 'win32', reason='Direct3D 9 exists on Windows only')
def test_the_real_direct3d_object_is_made_and_released(gpu):
    assert gpu.start() is True
    gpu._STATE['thread'].join(30)
    assert gpu.elapsed_ms() is not None
    gpu.release()                                       # with or without a graphics card: no error
    assert gpu._STATE['handle'] is None


# ------------------------------------------------------------------ font database
@pytest.fixture
def fonts(monkeypatch):
    from twobyteasr.design import font_warmup
    monkeypatch.setattr(font_warmup, '_STATE', {'thread': None, 'ms': None, 'registered': None})
    monkeypatch.delenv('TWOBYTEASR_FONT_WARMUP', raising=False)
    return font_warmup


def test_the_bundled_fonts_are_registered_once_whoever_asks(app, fonts, monkeypatch, tmp_path):
    from PySide6.QtGui import QFontDatabase
    files = [tmp_path / 'a.otf', tmp_path / 'b.ttf']
    added = []
    monkeypatch.setattr(fonts, 'bundled_font_files', lambda: files)
    monkeypatch.setattr(QFontDatabase, 'addApplicationFont', staticmethod(lambda path: added.append(path) or 0))
    assert fonts.register_bundled_fonts() == 2
    assert fonts.register_bundled_fonts() == 2
    assert added == [str(files[0]), str(files[1])]


def test_the_font_thread_only_registers_and_the_window_code_only_waits(app, fonts, monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')
    from PySide6.QtGui import QFontDatabase
    order = []
    monkeypatch.setattr(fonts, 'bundled_font_files', lambda: ['one.otf'])
    monkeypatch.setattr(QFontDatabase, 'addApplicationFont',
                        staticmethod(lambda path: order.append(threading.current_thread().name) or 0))
    assert fonts.start() is True
    assert fonts.start() is False
    fonts._STATE['thread'].join(30)
    assert order == ['font-database-warmup']
    assert fonts.elapsed_ms() is not None
    import inspect
    assert 'horizontalAdvance' not in inspect.getsource(fonts._measure)
    from twobyteasr.app import ui
    ui._register_bundled_fonts()                        # the main window's own call adds nothing again
    assert order == ['font-database-warmup']


def test_the_font_thread_can_be_switched_off_and_the_window_code_registers_itself(app, fonts, monkeypatch):
    from PySide6.QtGui import QFontDatabase
    added = []
    monkeypatch.setattr(fonts, 'bundled_font_files', lambda: ['one.otf'])
    monkeypatch.setattr(QFontDatabase, 'addApplicationFont', staticmethod(lambda path: added.append(path) or 0))
    monkeypatch.setattr(sys, 'platform', 'linux')
    assert fonts.start() is False
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setenv('TWOBYTEASR_FONT_WARMUP', '0')
    assert fonts.start() is False and fonts._STATE['thread'] is None
    from twobyteasr.app import ui
    ui._register_bundled_fonts()
    assert added == ['one.otf']


def test_the_bundled_font_files_are_the_shipped_ones_in_a_fixed_order(fonts):
    files = fonts.bundled_font_files()
    assert files, 'the repository ships fonts under assets/fonts'
    assert all(path.suffix in ('.otf', '.ttf') for path in files)
    assert files == fonts.bundled_font_files()


# ------------------------------------------------------------------ theme
def test_the_application_itself_carries_no_style_sheet(app):
    """Windows own their sheets (theme_scopes). A sheet on the application, even a comment, made
    Qt re-resolve the style of every widget each time it was given a parent: 0.2 s of the start."""
    from twobyteasr.design import theme_manager
    app.__dict__.pop('_applied_theme_key', None)
    theme_manager.apply_application_theme(app)
    assert app.styleSheet() == ''
    assert getattr(app, '_theme_root_filter', None) is not None
    theme_manager.apply_application_theme(app)          # the same theme again: nothing to redo
    assert app.styleSheet() == ''


def test_the_theme_key_is_written_only_when_it_changes(app, monkeypatch):
    from twobyteasr.design import theme_manager
    current = theme_manager.theme_key()
    other = next(key for key in theme_manager.THEMES if key != current)
    writes = []

    class Settings:
        stored = current

        def value(self, name):
            return Settings.stored

        def setValue(self, name, value):                # noqa: N802 - Qt's name
            writes.append(value)
            Settings.stored = value

        def sync(self):
            writes.append('sync')

        def fileName(self):                             # noqa: N802 - Qt's name
            return 'test-settings'

    monkeypatch.setattr(theme_manager, '_settings', lambda: Settings())
    assert theme_manager.save_theme_key(current) == current
    assert writes == []
    assert theme_manager.save_theme_key(other) == other
    assert writes == [other, 'sync']
    assert theme_manager.save_theme_key(other) == other
    assert writes == [other, 'sync']


# ------------------------------------------------------------------ window place
def test_the_saved_window_place_is_applied_once():
    from twobyteasr.app.ui import MainWindow
    calls = []

    class Window:
        _apply_initial_geometry_once = MainWindow._apply_initial_geometry_once

        def _apply_sane_initial_geometry(self):
            calls.append(1)

    window = Window()
    window._apply_initial_geometry_once()               # before the first show
    window._apply_initial_geometry_once()               # the timer afterwards
    assert calls == [1]
