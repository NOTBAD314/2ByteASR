"""Real-window check: nothing in AI 文字服务设置 is cut off at the right (2026-10-25).

User (10-25, 0.8.5, 120 % interface zoom on a 175 % 4K screen): with 更多选项
open, the service box, the key box, 保存设置, the 协议 box and 断句提示词 ran
past the dialog's right edge — the form was wider than the dialog, and the
form's scroll area has no horizontal scroll bar, so the rest was simply cut.

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=ai-dialog-width`` (isolated
data, from ``scripts/verify_ai_dialog_width_headed.py``; source or frozen).
The user's state is made directly: DeepSeek API with a fake key in the
isolated store and a remembered passed test; nothing contacts the network.
For each interface language, main-window size and dialog state it records
the dialog, the visible form width and the form's own width, and names every
visible control whose right edge is outside the visible form.
"""
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path

FAKE_KEY = "sk-audit-not-a-real-key-0001"


def start(window, output: Path):
    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QDialog, QLabel, QLineEdit,
                                   QScrollArea, QWidget)
    from ..design.ui_widgets import SwitchControl
    app = QApplication.instance()
    state = os.environ.get('TWOBYTEASR_AI_WIDTH_STATE', 'ready')
    output.mkdir(parents=True, exist_ok=True)
    result = dict(checks=[], metrics={}, errors=[], passed=False, pid=os.getpid(),
                  executable=os.path.realpath(__import__('sys').executable))

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))

    def settle(ms=300):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    def grab(widget, name):
        try:
            widget.grab().save(str(output / f'{name}.png'))
        except Exception as exc:  # noqa: BLE001
            result['errors'].append(f'grab {name}: {exc!r}')

    def label_of(widget):
        for attr in ('text', 'currentText', 'placeholderText'):
            value = getattr(widget, attr, None)
            if callable(value):
                try:
                    value = value()
                except TypeError:
                    continue
                if value:
                    return str(value)[:40]
        return widget.objectName() or type(widget).__name__

    def rows_of():
        """Which rows ask for the width: each layout's minimum width."""
        def walk(layout, name, depth, out):
            if layout is None or depth > 3:
                return
            out[name] = layout.minimumSize().width()
            for index in range(layout.count()):
                item = layout.itemAt(index)
                if item.layout() is not None:
                    walk(item.layout(), f'{name}/{index}', depth + 1, out)
                elif item.widget() is not None and not item.widget().isHidden():
                    out[f'{name}/{index}:{label_of(item.widget())}'] = item.widget().minimumSizeHint().width()
        out = {}
        walk(window.ai_panel.content_layout, 'panel', 0, out)
        walk(window.ai_advanced_box.layout(), 'advanced', 0, out)
        main = window._primary_ai_editor()
        walk(main.advanced_box.layout(), 'editor_advanced', 0, out)
        walk(main.layout(), 'editor', 0, out)
        return out

    def measure(dialog, tag):
        scroll = dialog.findChild(QScrollArea, 'aiDialogScroll')
        viewport = scroll.viewport()
        body = scroll.widget()
        screen = dialog.screen().availableGeometry()
        frame = dialog.frameGeometry()
        cut = []
        for widget in body.findChildren(QWidget):
            if not widget.isVisible() or not isinstance(widget, (QAbstractButton, QComboBox, QLineEdit, QLabel)):
                continue
            if isinstance(widget, QLabel) and not widget.text():
                continue
            left = widget.mapTo(viewport, QPoint(0, 0)).x()
            right = left + widget.width()
            if right > viewport.width() + 1 or left < -1:
                cut.append(dict(widget=label_of(widget), cls=type(widget).__name__, left=left, right=right))
            elif isinstance(widget, QLabel) and not widget.wordWrap() \
                    and widget.sizeHint().width() > widget.width() + 2:
                cut.append(dict(widget=label_of(widget), cls='QLabel(squeezed)', hint=widget.sizeHint().width(),
                                width=widget.width()))
            elif isinstance(widget, SwitchControl) and widget.width() < widget.sizeHint().width() - 1:
                cut.append(dict(widget=label_of(widget), cls='SwitchControl(squeezed)',
                                hint=widget.sizeHint().width(), width=widget.width()))
            elif isinstance(widget, QAbstractButton) and widget.text() \
                    and widget.width() < widget.fontMetrics().horizontalAdvance(widget.text()) + 8:
                cut.append(dict(widget=label_of(widget), cls=f'{type(widget).__name__}(squeezed)',
                                text=widget.fontMetrics().horizontalAdvance(widget.text()), width=widget.width()))
        panel = window.ai_panel
        metrics = dict(
            dialog=[dialog.x(), dialog.y(), dialog.width(), dialog.height()],
            screen=[screen.x(), screen.y(), screen.width(), screen.height()],
            on_screen=screen.contains(frame),
            window=[window.width(), window.height()],
            viewport=viewport.width(), body=body.width(), body_min=body.minimumSizeHint().width(),
            panel_min=panel.minimumSizeHint().width(), guide_min=window.ai_guide.minimumSizeHint().width(),
            advanced_min=window.ai_advanced_box.minimumSizeHint().width()
            if window.ai_advanced_box.isVisible() else None,
            hbar=scroll.horizontalScrollBar().maximum(), vbar=scroll.verticalScrollBar().maximum(),
            rows=rows_of(), cut=cut)
        notes = [window.ai_advanced_summary, window.separate_group_note, *window._ai_duty_notes.values()]
        # Lines each note wraps into at its width (its height grows with the switch row, so not that).
        metrics['note_lines'] = {
            label.text(): round(label.heightForWidth(label.width())
                                / max(1, label.heightForWidth(label.sizeHint().width())), 1)
            for label in notes if label.isVisible()}
        result['metrics'][tag] = metrics
        from ..app.window_constraints import available_rect
        room = available_rect(dialog, within_parent=True).width()
        squeezed = [item for item in cut if 'squeezed' in item['cls']]
        if body.width() > viewport.width() and dialog.width() >= room - 1:
            # A main window narrower than the form: the dialog fills it and scrolls sideways.
            reach = viewport.width() + metrics['hbar']
            check(f'{tag}: the main window is narrower than the form; it scrolls sideways to every control',
                  not squeezed and metrics['hbar'] >= body.width() - viewport.width()
                  and all(item.get('right', 0) <= reach + 1 for item in cut),
                  dict(room=room, viewport=metrics['viewport'], body=metrics['body'], hbar=metrics['hbar'],
                       squeezed=squeezed))
        else:
            check(f'{tag}: the form is no wider than what the dialog shows',
                  body.width() <= viewport.width() and not cut,
                  dict(viewport=metrics['viewport'], body=metrics['body'], cut=cut[:12]))
        check(f'{tag}: the dialog is inside the screen', metrics['on_screen'],
              dict(dialog=metrics['dialog'], screen=metrics['screen']))
        if '_max_' in tag:
            # With the main window maximized there is room: the notes beside the switches and the
            # closed 更多选项 line stay on one line (the 断句另用一个服务 note may take two).
            single = [window.ai_advanced_summary, *window._ai_duty_notes.values()]
            lines = {label.text(): metrics['note_lines'][label.text()] for label in single
                     if label.text() in metrics['note_lines']}
            check(f'{tag}: the notes keep to one line when there is room',
                  all(value < 1.5 for value in lines.values()), metrics['note_lines'])
        grab(dialog, tag)
        return metrics

    def prepare_ready():
        from ..providers.ai_connection_record import remember
        from ..providers.llm_config import save_api_key_for
        main = window._primary_ai_editor()
        index = main.service.findData('deepseek')
        if index >= 0 and main.service.currentIndex() != index:
            main.service.setCurrentIndex(index)
        settle(300)
        values = main.values()
        save_api_key_for(values['provider'], values['base_url'], FAKE_KEY)
        for editor in (window.polish_editor, window.group_editor):
            editor.refresh_secret_status()
        window._sync_ai_switches_with_keys()   # the switches show on once a key is saved
        # Saved like the user's (no unsaved change), then the passed test of exactly that.
        window._save_ai_configuration(show_feedback=False)
        remember(window.legacy.RUNTIME_SETTINGS, 'polish', True)
        window._refresh_home_process_facts()
        settle(500)
        result['metrics']['state'] = dict(card=window.setting_tiles['ai'].view.state,
                                          service=main.values().get('service'),
                                          switches=[window.ai_grouping.is_shown_on(), window.ai_polish.is_shown_on()])
        check('the user\'s state: DeepSeek API connected, AI 断句 and 字幕校对 on',
              result['metrics']['state']['card'] == 'ready' and all(result['metrics']['state']['switches']),
              result['metrics']['state'])

    def open_dialog():
        window._open_ai_settings_dialog()
        settle(900)
        return window.__dict__.get('_ai_settings_dialog')

    def run_states(prefix):
        dialog = open_dialog()
        check(f'{prefix}: the AI settings open', dialog is not None and dialog.isVisible())
        if dialog is None:
            return
        simple = measure(dialog, f'{prefix}_simple')
        window.ai_advanced_toggle.setChecked(True)
        settle(700)
        advanced = measure(dialog, f'{prefix}_advanced')
        result['metrics'][f'{prefix}_width_jump'] = advanced['dialog'][2] - simple['dialog'][2]
        window.separate_group_service.setChecked(True)
        settle(700)
        measure(dialog, f'{prefix}_separate')
        dialog.reject()
        settle(700)

    def set_language(code):
        combo = window.language_combo
        index = combo.findData(code)
        if index >= 0 and combo.currentIndex() != index:
            combo.setCurrentIndex(index)
            settle(2500)
        return index >= 0

    def run_all():
        try:
            from ..design.theme_manager import apply_theme
            apply_theme(os.environ.get('TWOBYTEASR_AI_WIDTH_THEME', 'warm'), app)
            for dialog in [w for w in app.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]:
                QDialog.done(dialog, 0)
            if window.pages.currentWidget() is not window.__dict__.get('settings_scroll'):
                window._return_to_settings()   # a startup project may have opened Studio
            settle(800)
            if state == 'ready':
                prepare_ready()   # the user's: DeepSeek API connected
            languages = [c for c in os.environ.get('TWOBYTEASR_AI_WIDTH_LANGUAGES', 'zh').split(',') if c]
            for code in languages:
                if not set_language(code):
                    result['errors'].append(f'no UI language {code}')
                    continue
                # The user's case: the main window maximized on the 4K screen.
                window.showMaximized()
                settle(1500)
                run_states(f'{code}_max')
                window.showNormal()
                window.resize(1366, 760)
                settle(1500)
                run_states(f'{code}_1366')
            set_language('zh')
        except Exception:  # noqa: BLE001
            result['errors'].append(traceback.format_exc())
        result['passed'] = bool(result['checks']) and all(c['passed'] for c in result['checks']) and not result['errors']
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')
        window.close()
        QTimer.singleShot(500, app.quit)

    def shutdown():
        result['gui_shutdown'] = True
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    app.aboutToQuit.connect(shutdown)
    QTimer.singleShot(2500, run_all)
