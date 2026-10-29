"""运行日志横向恒最左回归（2026-09-20 完成页日志滚到最右问题）。

机制（实证）：QTextEdit.append() 把光标停在长行末尾；任何后续
ensureCursorVisible（页面首次显示/详情行展开/窗口 resize）都会把横向
滚动条带到最右。修复 = 光标停回行首 + 显式钉 h=minimum。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import QApplication, QTextEdit

from twobyteasr.app.ui import (
    append_log_html_keep_left,
    keep_log_view_at_left,
    set_log_html_keep_left,
)


APP = QApplication.instance() or QApplication([])


def _console_edit() -> QTextEdit:
    edit = QTextEdit()
    edit.setReadOnly(True)
    edit.setWordWrapMode(QTextOption.WrapMode.NoWrap)
    edit.resize(420, 180)
    return edit


def _line_html(text: str) -> str:
    import html

    safe = html.escape(text).replace(" ", "&nbsp;")
    return (
        '<div style="color:#edf0e9; margin:1px 0; padding:2px 4px; '
        f'white-space:pre;">{safe}</div>'
    )


# 验收 A/B/C：普通行 + 超长行混合追加，横向恒 0、纵向追尾
def test_append_500_lines_with_long_single_lines_stay_left():
    edit = _console_edit()
    edit.show()
    APP.processEvents()
    for index in range(500):
        if index % 50 == 17:
            append_log_html_keep_left(edit, _line_html("run-signature " + "a" * 4000))
        else:
            append_log_html_keep_left(edit, _line_html(f"[阶段] 普通日志行 {index}"))
        if edit.horizontalScrollBar().value() != 0:
            pytest.fail(f"line {index}: horizontal drifted to {edit.horizontalScrollBar().value()}")
    APP.processEvents()
    assert edit.horizontalScrollBar().value() == 0
    assert edit.horizontalScrollBar().maximum() > 0, "长行必须仍可手动横向查看"
    assert edit.verticalScrollBar().value() == edit.verticalScrollBar().maximum()


# 复现原 bug 的形态：隐藏/零尺寸时追加，首次显示后必须仍在最左
def test_hidden_append_then_show_stays_left():
    edit = _console_edit()
    edit.resize(0, 0)
    append_log_html_keep_left(edit, _line_html("x" * 3000 + " tail"))
    edit.resize(420, 180)
    edit.show()
    APP.processEvents()
    assert edit.horizontalScrollBar().value() == 0
    assert edit.verticalScrollBar().maximum() >= 0


# 验收 D：整份日志重载默认从左侧显示
def test_set_html_reload_starts_left():
    edit = _console_edit()
    source = _console_edit()
    append_log_html_keep_left(source, _line_html("y" * 3000 + " END"))
    set_log_html_keep_left(edit, source.toHtml())
    edit.show()
    APP.processEvents()
    assert edit.horizontalScrollBar().value() == 0


# 验收 E：用户仍可手动横向滚动
def test_manual_horizontal_scroll_still_works():
    edit = _console_edit()
    append_log_html_keep_left(edit, _line_html("z" * 3000))
    edit.show()
    APP.processEvents()
    bar = edit.horizontalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum())
    assert bar.value() > 0
    keep_log_view_at_left(edit)
    assert bar.value() == 0


# 真实 MainWindow 路径：_append_console_line / 完成页填充
def test_main_window_console_paths_stay_left(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import twobyteasr.storage.settings as settings_module

    settings_module.stable_settings_root = lambda: tmp_path

    import subtitle_core as legacy
    import twobyteasr.app.ui as ui_module

    window = ui_module.MainWindow([], legacy, object(), None)
    window.resize(1200, 800)
    window.show()
    APP.processEvents()
    try:
        for index in range(120):
            if index % 30 == 7:
                window._append_console_line(
                    "Command: python -I moss_worker.py --run-signature " + "9f2c" * 500
                )
            else:
                window._append_console_line(f"[块 {index}/4] 已生成 {index * 100} tokens")
        APP.processEvents()
        assert window.console_log.horizontalScrollBar().value() == 0
        assert (
            window.console_log.verticalScrollBar().value()
            == window.console_log.verticalScrollBar().maximum()
        )
        set_log_html_keep_left(window.result_console, window.console_log.toHtml())
        window._switch_page(2)
        window.result_details_toggle.setChecked(True)
        APP.processEvents()
        assert window.result_console.horizontalScrollBar().value() == 0
    finally:
        window.close()
        window.deleteLater()
