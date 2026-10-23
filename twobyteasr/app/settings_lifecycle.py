"""Single-owner settings windows and lifecycle diagnostics, without saved content."""
from __future__ import annotations

import functools
import logging

log = logging.getLogger(__name__)


def trace(stage, kind, **fields):
    log.info('settings_window %s %s %s', kind, stage, fields)
    try:
        from ..diagnostics.editor_diagnostics import record
        record('settings_window', stage=stage, surface=kind, **fields)
    except (ImportError, AttributeError, TypeError):
        pass


def activate(dialog):
    from shiboken6 import isValid
    if dialog is None or not isValid(dialog):
        return False
    if dialog.isMinimized():
        dialog.showNormal()
    dialog.show()
    from .window_constraints import constrain
    constrain(dialog, within_parent=True)
    dialog.raise_()
    dialog.activateWindow()
    return True


def owned_settings(kind):
    """Guard construction too: showing a nested window may process queued clicks."""
    def decorate(function):
        @functools.wraps(function)
        def open_once(parent, *args, **kwargs):
            from PySide6.QtCore import QThread
            from PySide6.QtWidgets import QApplication, QMessageBox
            from ..i18n import tr
            app = QApplication.instance()
            if app is None or QThread.currentThread() != app.thread():
                raise RuntimeError('Settings windows must be opened on the GUI thread')
            owner = parent.window()
            name = f'_{kind}_settings_dialog'
            opening = f'_{kind}_settings_opening'
            trace('click', kind)
            if getattr(owner, opening, False):
                activate(getattr(owner, name, None))
                trace('existing', kind)
                return False
            if activate(getattr(owner, name, None)):
                trace('existing', kind)
                return False
            setattr(owner, opening, True)
            try:
                trace('creating', kind)
                return function(parent, *args, **kwargs)
            except Exception as exc:
                log.exception('Cannot open/save %s settings', kind)
                trace('error', kind, error_type=type(exc).__name__)
                dialog = getattr(owner, name, None)
                if dialog is not None:
                    from shiboken6 import isValid
                    if isValid(dialog):
                        if kind == 'ai':
                            panel = getattr(owner, 'ai_panel', None)
                            host = getattr(owner, 'settings_page_widget', None)
                            if panel is not None and host is not None and dialog.isAncestorOf(panel):
                                panel.setParent(host)
                                panel.hide()
                        dialog.hide()
                        dialog.deleteLater()
                setattr(owner, name, None)
                QMessageBox.warning(owner, tr('设置未能完成'),
                                    tr('设置窗口发生错误：{error}。请重试；诊断日志已记录失败阶段。',
                                       error=f'{type(exc).__name__}: {exc}'))
                return False
            finally:
                setattr(owner, opening, False)
        return open_once
    return decorate


def retain(owner, dialog, kind):
    name = f'_{kind}_settings_dialog'
    setattr(owner, name, dialog)
    dialog.finished.connect(lambda result: trace('closed', kind, result=int(result)))
    def destroyed(*_):
        if getattr(owner, name, None) is dialog:
            setattr(owner, name, None)
        trace('destroyed', kind)
    dialog.destroyed.connect(destroyed)
    trace('created', kind)


def normalized_preferences(value):
    """Repair only invalid known fields in memory; Cancel never rewrites a file."""
    prefs = dict(value) if isinstance(value, dict) else {}
    changes = []
    for key, default, allowed in (
        ('autosave_interval_seconds', 60, {30, 60, 120, 300}),
        ('recent_project_count', 9, set(range(1, 101))),
        ('speaker_main_tracks', 2, {1, 2, 3, 5, 8}),
    ):
        try:
            raw = prefs.get(key, default)
            number = int(raw) if not isinstance(raw, bool) else default
            if number not in allowed:
                number = default
        except (ValueError, TypeError, OverflowError):
            number = default
        if key in prefs and prefs[key] != number:
            changes.append(key)
        prefs[key] = number
    return prefs, changes
