"""Real-window check: the home page widgets (2026-10-23).

User (10-23): the AI card was a frame inside the AI band (remove the inner
frame); the 识别方案 controls touched the top edge (centre them in the gap
above the drop zone); the home cards, 字幕语言与输出 and the header buttons
(模型工坊 …) get a redesign that matches the app's buttons.

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=home-widgets`` (isolated data,
from ``scripts/verify_home_widgets_headed.py``; source or frozen). The AI is
made ready with a fake key and a remembered test (no network). Screenshots of
the whole window and the settings card go to the output folder for the
runner's theme and the light 「warm」 theme, connected and not connected.
"""
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path

FAKE_KEY = "sk-audit-not-a-real-key-0001"


def start(window, output: Path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QWidget
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

    def box(widget):
        corner = widget.mapTo(window, widget.rect().topLeft())
        return [corner.x(), corner.y(), widget.width(), widget.height()]

    def save_key(value):
        from ..providers.llm_config import save_api_key_for
        values = window._primary_ai_editor().values()
        save_api_key_for(values['provider'], values['base_url'], value)
        for editor in (window.polish_editor, window.group_editor):
            editor.refresh_secret_status()

    def remember(ok):
        from ..providers.ai_connection_record import remember as keep
        keep(window.legacy.RUNTIME_SETTINGS, 'polish', ok)

    def measure(tag):
        """Where the plan toolbar sits between the page top and the drop zone."""
        plan = window.plan_controls
        media = window.media_frame
        page = window.settings_page_widget
        plan_top = plan.mapTo(page, plan.rect().topLeft()).y()
        media_top = media.mapTo(page, media.rect().topLeft()).y()
        card = window.setting_tiles['ai']
        result['metrics'][tag] = dict(
            window=[window.width(), window.height()], plan=box(plan), media=box(media),
            gap_above=plan_top, gap_below=media_top - (plan_top + plan.height()),
            ai_card=box(card), ai_band=box(window.home_process_card),
            ai_card_frame=[card.property('aiLock'), card.styleSheet()[:80]],
            settings_card=box(window.home_settings_card), header=box(window.model_workshop_button.parentWidget()))
        grab(window, f'{tag}_window')
        grab(window.home_settings_card, f'{tag}_card')
        grab(window.settings_page_widget, f'{tag}_page')

    def home(tag):
        window._refresh_home_process_facts()
        settle(800)
        measure(tag)
        design_a(tag)

    def design_a(tag):
        """Design A (user, 10-23): tonal widgets, one status pill per model card,
        filled language fields with the caption inside, a header that fits."""
        header = window.model_workshop_button.parentWidget()
        visible = [w for w in header.findChildren(QWidget) if w.isVisible() and w.parentWidget() is header]
        right = max((w.mapTo(window, w.rect().topRight()).x() for w in visible), default=0)
        check(f'{tag}: the header buttons fit in the window', right <= window.width(), [right, window.width()])
        cards = window.recognition_plan.cards if hasattr(window.recognition_plan, 'cards') else {}
        pills = {}
        for role, card in dict(cards).items():
            pill = card.status_pill
            pills[role] = dict(visible=pill.isVisible(), tone=pill.property('tone'),
                               kind=card.kind_badge.text() if card.kind_badge.isVisible() else '',
                               status=card.status_badge.text() if card.status_badge.isVisible() else '',
                               separator=card.status_separator.isVisible(),
                               hidden=[card.kind_badge.isHidden(), card.status_badge.isHidden(), pill.isHidden(),
                                       card.recovery.isHidden()],
                               texts=[card.kind_badge.text(), card.status_badge.text(), card.recovery.text()],
                               pill_box=box(pill), card_box=box(card),
                               inside=card.rect().contains(pill.geometry().translated(pill.parentWidget().mapTo(card, pill.parentWidget().rect().topLeft()))))
        result['metrics'][f'{tag}_pills'] = pills
        # One pill per card; beside a fix button a narrow card may drop it (the
        # button's tooltip then names the state), as the old chips did.
        def pill_ok(p):
            shown = not p['hidden'][2]
            words = bool(p['kind'] or p['status'])
            fix = not p['hidden'][3]
            return (shown == words and (p['inside'] or not shown) and p['separator'] == bool(p['kind'] and p['status'])
                    and (shown or fix))
        check(f'{tag}: each model card shows its state as one pill inside the card (or only its fix button)',
              bool(pills) and all(pill_ok(p) for p in pills.values()), pills)
        fields = [window.spoken_language_field, window.punctuation_field, window.subtitle_output.parentWidget()]
        check(f'{tag}: the language dropdowns sit in filled fields with the caption inside',
              all(f.objectName() == 'homeLanguageField' and f.isAncestorOf(f.combo)
                  and f.caption.isVisible() and f.caption.geometry().bottom() <= f.combo.geometry().top() + 2
                  for f in fields), [box(f) for f in fields])
        locked = window.setting_tiles['ai'].view.locked
        output_field = window.subtitle_output.parentWidget()
        check(f'{tag}: 字幕显示 field lock look follows the AI ({locked})',
              bool(output_field.property('aiLock')) == locked, output_field.property('aiLock'))
        summary = window.subtitle_language_summary
        check(f'{tag}: the summary is one eye pill', summary.mark() == 'fa5s.eye' and summary.isVisible()
              and not summary.wordWrap(), summary.text())
        buttons = {name: getattr(window, attr, None) for name, attr in (
            ('AI 设置', 'ai_settings_button'), ('高级设置', 'home_task_settings_button'),
            ('管理术语库', 'add_glossary_button'), ('匹配文稿', 'script_match_button'),
            ('进入字幕工作台', 'studio_entry_open'))}
        short = {name: [b.width(), b.sizeHint().width()] for name, b in buttons.items()
                 if b is not None and b.isVisible() and b.width() + 1 < b.sizeHint().width()}
        check(f'{tag}: no restyled button is narrower than its text', not short, short)
        result['metrics'][f'{tag}_sizes'] = dict(
            plan_combo=box(window.recognition_mode_combo), more=box(window.project_profile_manage),
            settings=box(window.home_task_settings_button), nav=box(window.model_workshop_button),
            language=box(window.language_combo), field=box(window.spoken_language_field),
            features=[box(chip) for chip in window.setting_tiles['ai'].features.values()])

    def user_plan_look(tag):
        """The user's plan as their 10-23 screenshot shows it (MOSS Pro online and
        configured, FireRed local and ready, review off), painted onto the cards
        for a picture only: nothing is saved and no model is touched."""
        cards = window.recognition_plan.cards
        cards['primary'].set_state('MOSS Pro 云端 · moss-transcribe-diarize-pro', '在线', '已配置', 'good', '')
        cards['timeline'].set_state('FireRedASR2-AED', '本地', '已就绪', 'good', '')
        cards['review'].set_state('已关闭', '', '已关闭', 'muted', '')
        settle(600)
        pills = {role: [card.kind_badge.isVisible(), card.status_separator.isVisible(), card.status_badge.isVisible()]
                 for role, card in cards.items()}
        result['metrics'][f'{tag}_user_plan_pills'] = pills
        check(f'{tag}: with the user\'s plan the cards read 在线 · 已配置 / 本地 · 已就绪 / 已关闭',
              pills['primary'][2] and pills['timeline'] == [True, True, True] and pills['review'] == [False, False, True],
              pills)
        grab(window, f'{tag}_user_plan_window')
        grab(window.home_settings_card, f'{tag}_user_plan_card')

    def field_click():
        field = window.spoken_language_field
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        QTest.mouseClick(field, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(field.caption.geometry().center().x(), field.caption.geometry().center().y()))
        settle(500)
        popup = getattr(field.combo, '_popup', None) or field.combo.view()   # FramelessPopupCombo's own popup
        opened = popup.isVisible()
        grab(window, 'field_click_open')
        field.combo.hidePopup()
        settle(300)
        check('a click on a field caption opens its dropdown', opened)

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
            size = [int(v) for v in os.environ.get('TWOBYTEASR_HOME_WIDGETS_SIZE', '1700x1080').split('x')]
            window.resize(*size)
            settle(1500)
            save_key(FAKE_KEY)
            remember(True)
            home(f'{theme}_ready')
            check('ready: the AI card is connected', window.setting_tiles['ai'].view.state == 'ready',
                  window.setting_tiles['ai'].view.state)
            field_click()
            user_plan_look(theme)
            window._refresh_asr_summary()   # the real states again
            settle(600)
            from ..providers.llm_config import delete_api_key_for
            values = window._primary_ai_editor().values()
            delete_api_key_for(values['provider'], values['base_url'])
            for editor in (window.polish_editor, window.group_editor):
                editor.refresh_secret_status()
            home(f'{theme}_no_key')
            apply_theme('warm', app)
            settle(1200)
            home('warm_no_key')
            save_key(FAKE_KEY)
            remember(True)
            home('warm_ready')
            window.resize(1366, 760)
            settle(1500)
            home('warm_ready_compact')
            window.resize(*size)
            settle(1200)
            user_plan_look('warm')
            # Another interface language: longer captions and button words.
            for code in [c for c in os.environ.get('TWOBYTEASR_HOME_WIDGETS_LANGS', '').split(',') if c]:
                index = window.language_combo.findData(code)
                if index < 0:
                    continue
                window.language_combo.setCurrentIndex(index)
                settle(2500)
                home(f'warm_{code}')
                window.resize(1366, 760)
                settle(1500)
                home(f'warm_{code}_compact')
                window.resize(*size)
                settle(1200)
            if os.environ.get('TWOBYTEASR_HOME_WIDGETS_LANGS'):
                window.language_combo.setCurrentIndex(max(0, window.language_combo.findData('zh')))
                settle(1500)
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
