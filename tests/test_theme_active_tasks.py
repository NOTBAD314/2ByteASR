"""识别页“并行运行中”信息框必须跟随主题切换。

回归背景（2026-09-18 VIII）：MainWindow 曾定义两个同名
``refresh_theme_palette``，后者把前者覆盖——刷新 ``active_tasks_label``
内联样式的版本成了死代码，深色主题下该框永远停留在建页时的浅色底。
"""

import inspect
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication


@pytest.fixture
def app(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    from twobyteasr.design import theme_manager

    monkeypatch.setattr(
        theme_manager,
        "_settings",
        lambda: QSettings(str(tmp_path / "theme.ini"), QSettings.Format.IniFormat),
    )
    return app


def _make_window(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    import subtitle_core as legacy
    from twobyteasr.app.ui import MainWindow

    return MainWindow([], legacy, object(), None)


def test_main_window_defines_refresh_theme_palette_once():
    from twobyteasr.app.ui import MainWindow

    source = inspect.getsource(MainWindow)
    assert source.count("def refresh_theme_palette") == 1, (
        "同名方法会静默覆盖刷新逻辑；把新的刷新收进唯一定义里"
    )


def test_active_tasks_label_follows_theme_switch(app, tmp_path, monkeypatch):
    from twobyteasr.design import theme_manager
    from twobyteasr.design.ui_theme import THEMES

    win = _make_window(tmp_path, monkeypatch)
    try:
        win._style_active_tasks_label()
        assert THEMES["warm"].panel.lower() in win.active_tasks_label.styleSheet().lower()

        win.show()
        app.processEvents()
        theme_manager.apply_application_theme(app=app, key="grape")
        app.processEvents()
        sheet = win.active_tasks_label.styleSheet().lower()
        assert THEMES["grape"].panel.lower() in sheet, sheet
        assert THEMES["warm"].panel.lower() not in sheet

        # 状态文案更新不清掉样式；任务进行中切主题不丢内容。
        win.active_tasks_label.setText("并行运行中\n在线 ASR API 主力转写")
        theme_manager.apply_application_theme(app=app, key="plum")
        app.processEvents()
        assert THEMES["plum"].panel.lower() in win.active_tasks_label.styleSheet().lower()
        assert win.active_tasks_label.text().startswith("并行运行中")
    finally:
        win.deleteLater()
        app.processEvents()
        theme_manager.apply_application_theme(app=app, key="warm")
