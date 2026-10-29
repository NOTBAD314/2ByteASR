"""Real-window check: the home AI card, the frosted 内容与术语 and the one-page AI settings (2026-10-22).

User (10-22, design B): the AI card stands beside the recognition cards; while
no AI is connected it and 内容与术语 are blue-grey, only the way to set it up
is readable and the content columns sit under frosted glass; once connected
both return to the page colours. The AI settings dialog is one page: service,
key and test first, 「让 AI 负责」, then a closed 高级设置.

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=home-ai-card`` (isolated data,
from ``scripts/verify_home_ai_card_headed.py``; source or frozen). Each AI
state is made directly (a fake key in the isolated store and a remembered
test result); nothing contacts the network or an AI service. Screenshots of
every state go to the output folder, in the theme given by the runner and in
the light 「warm」 theme.
"""
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path

FAKE_KEY = "sk-audit-not-a-real-key-0001"
OTHER_KEY = "sk-audit-not-a-real-key-0002"


def start(window, output: Path):
    from PySide6.QtCore import QPoint, Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QLabel
    from ..app import ui_zoom
    app = QApplication.instance()
    output.mkdir(parents=True, exist_ok=True)
    result = dict(checks=[], skipped=[], metrics={}, errors=[], passed=False, pid=os.getpid(),
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

    def card():
        return window.setting_tiles['ai']

    layouts = {}

    def dialog_layout(dialog, tag):
        """Where the dialog's buttons sit: the same in every state (user, 10-23)."""
        main = window._ai_main_editor
        save = window.ai_dialog_save_button

        def box(widget):
            corner = widget.mapTo(dialog, widget.rect().topLeft())
            return [corner.x(), corner.y(), widget.width(), widget.height()]
        cancel = next(w for w in dialog.findChildren(type(save)) if w.property('aiDialogAction') and w is not save)
        layouts[tag] = dict(dialog=[dialog.width(), dialog.height()], test=box(main.test_button),
                            cancel=box(cancel), save=box(save), guide=box(window.ai_guide))
        result['metrics'][f'layout_{tag}'] = layouts[tag]
        button = main.test_button
        result['metrics'][f'test_button_{tag}'] = dict(
            text=button.text(), hint=button.sizeHint().width(), min_hint=button.minimumSizeHint().width(),
            min=button.minimumWidth(), max=button.maximumWidth(), advance=button.fontMetrics().horizontalAdvance(button.text()),
            font=[button.font().family(), button.font().pixelSize(), button.font().pointSizeF(), button.font().weight()])

    def frost():
        return window.content_frost

    def refresh():
        window._refresh_home_process_facts()
        settle(700)

    def home_state(tag, expected, locked):
        refresh()
        view = card().view
        frame_lock = [bool(f.property('aiLock')) for f in (window.home_process_card, window.content_profile_card)]
        frosted = frost().isVisible()
        geometry = (frost().geometry() == window.content_terms_body.geometry())
        result['metrics'][tag] = dict(state=view.state, title=card().title_label.text(),
                                      summary=card().summary_label.text(), chip=card().state_chip.text(),
                                      frame_lock=frame_lock, frosted=frosted, card_height=card().height(),
                                      buttons={name: not getattr(card(), name).isHidden()
                                               for name in ('connect_button', 'test_button', 'settings_button',
                                                            'help_button')},
                                      terms_enabled=window.terms.isEnabled(),
                                      window=[window.width(), window.height()])
        check(f'{tag}: card state is {expected}', view.state == expected, view.state)
        check(f'{tag}: AI card and 内容与术语 {"blue-grey" if locked else "in page colours"}',
              frame_lock == [locked, locked], frame_lock)
        check(f'{tag}: content columns {"under" if locked else "without"} frosted glass',
              frosted == locked and (geometry or not locked), dict(frosted=frosted, geometry=geometry))
        if locked:
            # User, 10-23 (design G): the big lock, a heading and 「连接 AI」, then the three
            # locked features side by side; 字幕显示 is locked shut on 「只显示原文」.
            panel = frost()
            tiles = panel.tiles
            inside = all(panel.rect().contains(t.geometry()) for t in tiles)
            clipped = [t.label.text() for t in tiles if t.label.sizeHint().width() > t.label.width() + 1
                       and not t.label.wordWrap()]
            output = window.subtitle_output
            check(f'{tag}: the lock panel shows the lock, heading, button and three features in view',
                  panel.lock.isVisible() and panel.note.isVisible() and panel.button.isVisible()
                  and len(tiles) == 3 and all(t.isVisible() for t in tiles) and inside and not clipped
                  and panel.note.fontInfo().pixelSize() >= ui_zoom.px(16),
                  [panel.note.text(), panel.button.text(), panel.height(), [t.label.text() for t in tiles], clipped])
            check(f'{tag}: 字幕显示 is locked on 只显示原文 in the lock colour',
                  not output.isEnabled() and output.currentData() == 'original' and output.property('aiLock') is True
                  and not output.itemIcon(output.currentIndex()).isNull(),
                  [output.isEnabled(), output.currentData(), output.property('aiLock')])
        grab(window, f'{tag}_window')
        grab(window.home_settings_card, f'{tag}_card')

    def dialog_texts(dialog):
        return [label.text() for label in dialog.findChildren(QLabel) if label.isVisible() and label.text()]

    def save_key(value):
        from ..providers.llm_config import save_api_key_for
        values = window._primary_ai_editor().values()
        save_api_key_for(values['provider'], values['base_url'], value)
        for editor in (window.polish_editor, window.group_editor):
            editor.refresh_secret_status()

    def remember(ok):
        from ..providers.ai_connection_record import remember as keep
        keep(window.legacy.RUNTIME_SETTINGS, 'polish', ok)

    def run_all():
        try:
            from ..design.theme_manager import apply_theme
            theme = os.environ.get('TWOBYTEASR_HOME_AI_THEME', 'grape')
            apply_theme(theme, app)
            for dialog in [w for w in app.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]:
                QDialog.done(dialog, 0)
            window.showNormal()
            if window.pages.currentWidget() is not window.__dict__.get('settings_scroll'):
                window._return_to_settings()   # a startup project may have opened Studio
            window.resize(1700, 1080)
            settle(1500)

            # 1. No key: blue-grey, only the way to set it up, frosted columns.
            home_state('no_key', 'no_key', True)
            check('no_key: 「连接 AI」 and 「API Key 是什么？」 are the only actions',
                  result['metrics']['no_key']['buttons'] == dict(connect_button=True, test_button=False,
                                                                 settings_button=False, help_button=True),
                  result['metrics']['no_key']['buttons'])
            check('no_key: 术语库校对 stays locked under the glass', not window.terms.isEnabled())

            # 2. A click on the frosted glass opens the AI settings.
            QTest.mouseClick(frost(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                             frost().rect().center())
            settle(900)
            dialog = window.__dict__.get('_ai_settings_dialog')
            check('a click on the frosted glass opens the AI settings', dialog is not None and dialog.isVisible())
            if dialog is not None:
                texts = dialog_texts(dialog)
                result['metrics']['dialog_simple'] = dict(size=[dialog.width(), dialog.height()], texts=texts)
                check('dialog: no English section labels in sight',
                      not any(t in texts for t in ('Provider', 'Account / Auth', 'Connection', 'Model')), texts)
                check('dialog: 高级设置 starts closed', not window.ai_advanced_box.isVisible())
                main = window.__dict__.get('_ai_main_editor')
                check('dialog: the shared service is the one form on top',
                      main is window.group_editor and window.group_editor.isVisible()
                      and not window.polish_editor.isVisible())
                check('dialog: state tag says 未连接', window.ai_dialog_state_label.text() in ('未连接',),
                      window.ai_dialog_state_label.text())
                check('dialog: 申请教程 is the one pink button, in the guide column; 测试连接 waits for a key',
                      main.guide_button.property('emphasis') == 'primary'
                      and window.ai_guide.isAncestorOf(main.guide_button)
                      and main.test_button.property('emphasis') == 'secondary' and not main.test_button.isEnabled()
                      and window.ai_guide.property('state') == 'no_key',
                      [main.guide_button.property('emphasis'), main.test_button.property('emphasis'),
                       main.test_button.isEnabled(), window.ai_guide.property('state')])
                dialog_layout(dialog, 'no_key')
                grab(dialog, 'dialog_simple')
                grab(window.ai_panel, 'dialog_simple_panel')
                main.key.setText('sk-typed-not-a-real-key')
                settle(500)
                check('dialog: with a key typed 测试连接 turns pink and the guide says test next',
                      main.test_button.property('emphasis') == 'primary' and main.test_button.isEnabled()
                      and main.guide_button.property('emphasis') == 'secondary'
                      and window.ai_guide.property('state') == 'untested',
                      [main.test_button.property('emphasis'), window.ai_guide.property('state')])
                dialog_layout(dialog, 'untested')
                check('dialog: typing a key moves and resizes nothing (only colours change)',
                      layouts['untested'] == layouts['no_key'], [layouts['no_key'], layouts['untested']])
                grab(dialog, 'dialog_key_typed')
                main.key.clear()
                settle(300)
                window.ai_advanced_toggle.setChecked(True)
                settle(600)
                check('dialog: 高级设置 shows model, address and protocol of the top form',
                      window.ai_advanced_box.isVisible() and main.advanced_box.isVisible()
                      and window.ai_advanced_box.isAncestorOf(main.advanced_box)
                      and main.model.isVisible() and main.base_url.isVisible())
                grab(dialog, 'dialog_advanced')
                grab(window.ai_panel, 'dialog_advanced_panel')
                window.separate_group_service.setChecked(True)
                settle(600)
                check('dialog: 断句另用一个服务 puts the 断句 form in 高级设置 and 校对 on top',
                      window.ai_advanced_box.isAncestorOf(window.group_editor) and window.group_editor.isVisible()
                      and window.polish_editor.isVisible() and not window.unified_glm.isChecked()
                      and window.ai_advanced_box.isAncestorOf(window.polish_editor.advanced_box))
                grab(window.ai_panel, 'dialog_separate_panel')
                dialog.reject()
                settle(800)
                check('cancel puts everything back',
                      window.unified_glm.isChecked() and not window.separate_group_service.isChecked()
                      and not window.ai_advanced_box.isAncestorOf(window.group_editor)
                      and window.__dict__.get('_ai_settings_dialog') is None)

            # 3. Key saved, never tested → 测试连接 on the card.
            save_key(FAKE_KEY)
            home_state('untested', 'untested', True)
            check('untested: 测试连接 and AI 设置 on the card',
                  result['metrics']['untested']['buttons'] == dict(connect_button=False, test_button=True,
                                                                   settings_button=True, help_button=False),
                  result['metrics']['untested']['buttons'])
            # 4. A failed test.
            remember(False)
            home_state('failed', 'failed', True)
            check('failed: the card offers 重新测试', card().test_button.text() == '重新测试', card().test_button.text())
            # 5. Connected.
            remember(True)
            home_state('ready', 'ready', False)
            check('ready: the card names the service and the passed test',
                  '·' in card().title_label.text() and '测试通过' in card().summary_label.text(),
                  [card().title_label.text(), card().summary_label.text()])
            check('ready: feature tags shown, 术语库校对 unlocked',
                  card().feature_row.isVisible() and window.terms.isEnabled())
            window._open_ai_settings_dialog()
            settle(900)
            dialog = window.__dict__.get('_ai_settings_dialog')
            if dialog is not None:
                check('dialog (ready): state tag says 已连接', window.ai_dialog_state_label.text() == '已连接',
                      window.ai_dialog_state_label.text())
                check('dialog (ready): the guide says what is unlocked and 保存设置 is the pink button',
                      window.ai_guide.property('state') == 'ready'
                      and window.ai_dialog_save_button.property('buttonRole') == 'primary',
                      [window.ai_guide.property('state'), window.ai_dialog_save_button.property('buttonRole')])
                guide = window.ai_guide
                tiles = list(guide.win_tiles.values())
                foot_gap = guide.height() - guide.win_next.mapTo(guide, guide.win_next.rect().bottomLeft()).y()
                check('dialog (ready): success card with four one-line tiles and the last step at its foot',
                      guide.win_box.isVisible() and guide.win_badge.isVisible() and len(tiles) == 4
                      and all(tile.label.sizeHint().width() <= tile.label.width() for tile in tiles)
                      and foot_gap <= ui_zoom.px(26),
                      [[[tile.label.text(), tile.label.sizeHint().width(), tile.label.width()] for tile in tiles], foot_gap])
                dialog_layout(dialog, 'ready')
                check('dialog (ready): same size and button places as before connecting',
                      layouts.get('ready') == layouts.get('no_key'), [layouts.get('no_key'), layouts.get('ready')])
                grab(dialog, 'dialog_ready')
                # A test that passes now (from 还没测试): the check pops in and the tiles light up.
                main = window._ai_main_editor
                guide.set_state('untested')
                main.last_connection_ok = True
                window._refresh_ai_dialog_state()
                settle(300)
                check('dialog (fresh pass): the pop-in is running',
                      guide.win_badge.scale != 1.0 or any(tile.graphicsEffect() is not None for tile in tiles),
                      guide.win_badge.scale)
                grab(dialog, 'dialog_ready_pop')
                settle(1200)
                check('dialog (fresh pass): says 刚刚 and the animation leaves no effect behind',
                      '刚刚' in guide.win_meta.text() and guide.win_badge.scale == 1.0
                      and all(tile.graphicsEffect() is None for tile in tiles), guide.win_meta.text())
                grab(dialog, 'dialog_ready_fresh')
                main.last_connection_ok = None
                dialog.reject()
                settle(600)
            # 6. AI switched off.
            switches = window.legacy.RUNTIME_SETTINGS.setdefault('switches', {})
            saved = dict(enable_ai_polish=switches.get('enable_ai_polish', True),
                         use_ai_grouping=switches.get('use_ai_grouping', True))
            switches.update(enable_ai_polish=False, use_ai_grouping=False)
            home_state('off', 'off', True)
            check('off: 「打开 AI」 on the card', card().connect_button.text() == '打开 AI', card().connect_button.text())
            switches.update(saved)
            # 7. A short window: the compact card.
            window.resize(1366, 760)
            settle(1500)
            home_state('ready_compact', 'ready', False)
            check('compact: no role line and no feature row', card().role_label.isHidden()
                  and card().feature_row.isHidden())
            window.resize(1700, 1080)
            settle(1200)
            # 8. The light theme: connected, then no key again.
            apply_theme('warm', app)
            settle(1200)
            home_state('warm_ready', 'ready', False)
            window._open_ai_settings_dialog()
            settle(900)
            dialog = window.__dict__.get('_ai_settings_dialog')
            if dialog is not None:
                grab(dialog, 'warm_dialog_ready')
                dialog.reject()
                settle(600)
            save_key(OTHER_KEY)   # another key: never tested
            home_state('warm_untested', 'untested', True)
            from ..providers.llm_config import delete_api_key_for
            values = window._primary_ai_editor().values()
            delete_api_key_for(values['provider'], values['base_url'])
            for editor in (window.polish_editor, window.group_editor):
                editor.refresh_secret_status()
            home_state('warm_no_key', 'no_key', True)
            window._open_ai_settings_dialog()
            settle(900)
            dialog = window.__dict__.get('_ai_settings_dialog')
            if dialog is not None:
                window.ai_advanced_toggle.setChecked(True)
                settle(600)
                grab(dialog, 'warm_dialog_advanced')
                grab(window.ai_panel, 'warm_dialog_advanced_panel')
                dialog.reject()
                settle(600)
            apply_theme(theme, app)
            settle(800)
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
