"""Real-window check: home model-card names at a non-100% interface zoom (2026-10-21).

User report (interface zoom 120%, theme grape): after coming back to home
from Subtitle Studio the three recognition cards drew their model names in a
larger font over the line below (「• moss-transcribe-…」, 「Aligner」 and
「已关闭」 on top of their descriptions). The stepped-down name size was scaled
by the zoom pass a second time.

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=home-plan-zoom`` (isolated
data, from ``scripts/verify_home_plan_zoom_headed.py``; source or frozen).
The runner saves a primary model with a long name (MOSS Pro 云端 API) and the
zoom. Home is narrowed until the names step down, then Studio opens the
runner's fixture project, the theme changes there and home is shown again,
twice. Each time every card's name keeps the size the plan chose and ends
above its description line. Screenshots go to the output folder.

Nothing here contacts the network or AI services.
"""
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path


def start(window, output: Path):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QApplication, QDialog
    from PySide6.QtCore import Qt
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

    def wait_for(predicate, timeout=40.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            app.processEvents()
            try:
                if predicate():
                    return True
            except Exception:  # noqa: BLE001 - keep polling
                pass
            time.sleep(0.05)
        return False

    def grab(widget, name):
        try:
            widget.grab().save(str(output / f'{name}.png'))
        except Exception as exc:  # noqa: BLE001
            result['errors'].append(f'grab {name}: {exc!r}')

    def cards():
        return window.recognition_plan.cards

    def measure(tag):
        from ..app import ui_zoom
        rows = {}
        for role, card in cards().items():
            name, description = card.model_label, card.description_label
            top_left = name.mapTo(card, name.rect().topLeft())
            name_bottom = top_left.y() + name.height()
            description_top = description.mapTo(card, description.rect().topLeft()).y()
            metrics = QFontMetrics(name.font())
            text_height = metrics.boundingRect(0, 0, max(1, name.width()), 2000, Qt.TextFlag.TextWordWrap,
                                               name.text()).height()
            rows[role] = dict(text=name.text(), name_px=card._name_px, font_px=name.font().pixelSize(),
                              sheet=name.styleSheet(), name_height=name.height(), text_height=text_height,
                              name_bottom=name_bottom, description_top=description_top,
                              description=description.text(), card_height=card.height())
        result['metrics'][tag] = dict(zoom=ui_zoom.zoom_percent(), window=[window.width(), window.height()],
                                      cards=rows)
        stepped = [row for row in rows.values() if row['name_px']]
        check(f'{tag}: stepped-down names keep the size the plan chose',
              all(row['font_px'] == row['name_px'] and row['sheet'] == f"font-size: {row['name_px']}px;"
                  for row in stepped), {r: (v['name_px'], v['font_px'], v['sheet']) for r, v in rows.items()})
        check(f'{tag}: every name ends above its description line',
              all(row['name_bottom'] <= row['description_top'] + 1 for row in rows.values()),
              {r: (v['name_bottom'], v['description_top']) for r, v in rows.items()})
        check(f'{tag}: every name fits its slot',
              all(row['text_height'] <= row['name_height'] + 1 for row in rows.values()),
              {r: (v['text_height'], v['name_height']) for r, v in rows.items()})
        grab(window.recognition_plan, f'{tag}_plan')
        return rows

    def open_fixture():
        fixture = os.environ['TWOBYTEASR_STARTUP_PROJECT']
        ready = {'v': False}
        window.open_studio_project(fixture, mode='edit', source='startup_audit',
                                   on_ready=lambda *a, **k: ready.__setitem__('v', True))
        wait_for(lambda: ready['v'], 60)
        settle(2500)
        return window._studio_page_instance

    def run_all():
        try:
            from ..design.theme_manager import apply_theme
            theme = os.environ.get('TWOBYTEASR_HOME_ZOOM_THEME', 'grape')
            apply_theme(theme, app)
            for dialog in [w for w in app.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]:
                QDialog.done(dialog, 0)
            window.showNormal()
            settle(800)

            def users_plan():
                # MOSS Pro 云端 as an online API (its name is the longest one).
                models = window.legacy.RUNTIME_SETTINGS.setdefault("models", {})
                models.update(qwen_asr_api_provider="mosi_moss_pro", qwen_asr_api_protocol="mosi_transcriptions",
                              qwen_asr_api_model="moss-transcribe-diarize-pro",
                              qwen_asr_api_url="https://api.mosi.cn/v1")
                for combo, value in ((window.primary_asr_backend, "api"),
                                     (window.firered_asr_backend, "qwen_aligner"), (window.qwen_asr_backend, "off")):
                    if combo.findData(value) >= 0:
                        combo.setCurrentIndex(combo.findData(value))
                window._refresh_asr_summary()
                settle(800)

            users_plan()
            chosen = None
            for width in (1600, 1400, 1250, 1120, 1000):
                window.resize(width, 900)
                settle(1200)
                window.recognition_plan._sync_identity_height()
                settle(300)
                if any(card._name_px for card in cards().values()):
                    chosen = width
                    break
            result['metrics']['window_width'] = chosen
            primary = cards()['primary'].model_label.text()
            check('home shows the long primary name', 'moss-transcribe' in primary or 'MOSS Pro' in primary, primary)
            if chosen is None:
                result['skipped'].append('names never stepped down at the tried widths')
            measure('home_start')
            grab(window, 'home_start_window')
            for round_index, other in enumerate(('warm', theme), 1):
                page = open_fixture()
                check(f'round {round_index}: Studio opened', page is not None)
                apply_theme(other, app)       # a theme change while in Studio walks the hidden home too
                settle(1200)
                window._return_to_settings()
                settle(2500)
                measure(f'home_after_studio_{round_index}')
                grab(window, f'home_after_studio_{round_index}_window')
                # The long name again (the return restores the profile's choice), then
                # the zoom pass a page switch or resize runs over the home page.
                from ..app import ui_zoom
                users_plan()
                ui_zoom.apply_to(window.pages.currentWidget())
                settle(1200)
                measure(f'home_after_studio_{round_index}_long_name')
        except Exception:  # noqa: BLE001
            result['errors'].append(traceback.format_exc())
        result['passed'] = bool(result['checks']) and all(c['passed'] for c in result['checks']) and not result['errors']
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')
        studio = getattr(window, '_studio_page_instance', None)
        if studio is not None and getattr(studio, 'project', None) is not None:
            try:
                studio.save()  # the copy under the output folder; no save prompt on close
            except Exception as exc:  # noqa: BLE001
                result['errors'].append(f'save before close: {exc!r}')
        window.close()
        QTimer.singleShot(500, app.quit)

    def shutdown():
        result['gui_shutdown'] = True
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    app.aboutToQuit.connect(shutdown)
    QTimer.singleShot(2500, run_all)
