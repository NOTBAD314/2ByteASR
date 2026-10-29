"""Real-window check: Studio 「识别字幕」 sheet, layout C (2026-10-23).

History: 2026-10-22 the 高级配置 rows were squeezed into one strip inside the
fixed-height modal card; three redesigns followed. 2026-10-23 the user chose
layout C: 识别方案 on one line at the top, the three model roles on the left
(the home card's logo, name, languages and readiness; a row opens the model
picker), 「这次识别」 on the right (glossary dropdown, translation instead of
the speaker selector, what is missing, the one start button), both columns
top and bottom aligned.

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=recognition-sheet`` (isolated
data, from ``scripts/verify_recognition_sheet_headed.py``; source or frozen).
Opens the runner's fixture project, opens the sheet at full and at minimum
card height and checks the layout, the glossary dropdown, the translation
lock, the MOSS Pro plan and the model picker round trip. Screenshots go to
the output folder. Nothing here contacts the network or AI services.
"""
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path


def start(window, output: Path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import (QAbstractButton, QApplication, QCheckBox, QComboBox, QDialog, QLabel,
                                   QPushButton, QScrollArea, QWidget)
    app = QApplication.instance()
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

    def open_fixture():
        fixture = os.environ['TWOBYTEASR_STARTUP_PROJECT']
        ready = {'v': False}
        window.open_studio_project(fixture, mode='edit', source='startup_audit',
                                   on_ready=lambda *a, **k: ready.__setitem__('v', True))
        wait_for(lambda: ready['v'], 60)
        settle(2500)
        return window._studio_page_instance

    def rect_in(widget, ancestor):
        top_left = widget.mapTo(ancestor, widget.rect().topLeft())
        return top_left.y(), top_left.y() + widget.height(), top_left.x(), top_left.x() + widget.width()

    def measure(tag, page):
        sheet = page._recognition_sheet
        controls = page._recognition_controls
        modal = window._modal_host
        scroll = sheet.findChild(QScrollArea, 'studioRecognitionScroll')
        body = scroll.widget() if scroll is not None else sheet
        squeezed = []
        for widget in body.findChildren(QWidget):
            if not widget.isVisible() or not isinstance(widget, (QLabel, QAbstractButton, QComboBox)):
                continue
            need = max(widget.minimumSizeHint().height(), widget.minimumHeight())
            if isinstance(widget, QLabel) and widget.wordWrap() and widget.width() > 0:
                need = max(need, widget.heightForWidth(widget.width()))
            if widget.height() + 1 < need:
                squeezed.append(dict(name=widget.objectName() or type(widget).__name__, height=widget.height(),
                                     need=need, text=(widget.text() if hasattr(widget, 'text') else '')[:30]))
        rows = controls['rows']
        model_rows = []
        for role, row in rows.items():
            top, bottom, left, right = rect_in(row, body)
            model_rows.append(dict(role=role, top=top, bottom=bottom, left=left, right=right, visible=row.isVisible(),
                                   name=row.name.text(), elided=row.name.is_elided(), status=row.status.text(),
                                   tone=row.status.property('tone'), has_model=row._model is not None,
                                   languages=row.languages.has_badges(), height=row.height(),
                                   need=row.minimumSizeHint().height(), natural=row.sizeHint().height(),
                                   badges=row.languages.layout_badges(row.languages.width())))
        columns = dict(left=rect_in(controls['left'], body), right=rect_in(controls['summary'], body),
                       plan=rect_in(controls['plan'], body), rows=rect_in(controls['advanced'], body))
        viewport = scroll.viewport() if scroll is not None else sheet
        bar = scroll.verticalScrollBar() if scroll is not None else None
        result['metrics'][tag] = dict(
            window=[window.width(), window.height()], card=[modal.card.width(), modal.card.height()],
            dpr=window.devicePixelRatioF(), viewport=[viewport.width(), viewport.height()],
            body=[body.width(), body.height()], scroll_max=bar.maximum() if bar else None,
            scroll_value=bar.value() if bar else None, model_rows=model_rows, columns=columns, squeezed=squeezed)
        check(f'{tag}: no text or control is squeezed below its height', not squeezed, squeezed)
        return dict(scroll=scroll, body=body, viewport=viewport, bar=bar, model_rows=model_rows, columns=columns)

    def run_case(tag, card_height, page):
        page.project.glossary_ids = ['洛克王国世界', '绝区零', '全局记忆', '瓦罗兰特']
        page._open_recognition_sheet()
        settle(800)
        modal = window._modal_host
        if card_height:
            geometry = modal.card.geometry()
            modal.card.setGeometry(geometry.x(), geometry.y(), geometry.width(), card_height)
            settle(600)
        controls = page._recognition_controls
        check(f'{tag}: sheet shown in the window', modal.isVisible() and page._recognition_sheet.isVisible())
        info = measure(f'{tag}_open', page)
        check(f'{tag}: sheet content sits in a scroll area', info['scroll'] is not None)
        if not card_height:
            check(f'{tag}: wide card', modal.card.width() >= min(1000, window.width() - 60),
                  [modal.card.width(), window.width()])
            check(f'{tag}: everything fits without scrolling', info['bar'] is not None and info['bar'].maximum() == 0,
                  info['bar'].maximum() if info['bar'] is not None else None)
        grab(modal.card, f'{tag}_1_open')
        rows, cols = info['model_rows'], info['columns']
        check(f'{tag}: three model role rows shown, top to bottom',
              len(rows) == 3 and all(r['visible'] for r in rows)
              and all(rows[i]['bottom'] <= rows[i + 1]['top'] for i in range(2)),
              [(r['role'], r['top'], r['bottom']) for r in rows])
        check(f'{tag}: rows keep their height', all(r['height'] + 1 >= r['need'] for r in rows),
              [(r['role'], r['height'], r['need']) for r in rows])
        check(f'{tag}: thin model rows (not stretched into cards)',
              all(r['height'] <= r['natural'] * 1.6 for r in rows), [(r['role'], r['height'], r['natural']) for r in rows])
        check(f'{tag}: plan above the model rows', cols['plan'][1] <= cols['rows'][0], cols)
        check(f'{tag}: left column and 这次识别 share top and bottom',
              abs(cols['left'][0] - cols['right'][0]) <= 1 and abs(cols['left'][1] - cols['right'][1]) <= 1, cols)
        check(f'{tag}: rows show the languages of their model',
              all(r['languages'] == r['has_model'] for r in rows) and any(r['languages'] for r in rows),
              [(r['role'], r['has_model'], r['languages'], r['badges']) for r in rows])
        check(f'{tag}: model names are not cut', not any(r['elided'] for r in rows),
              [(r['role'], r['name'], r['elided']) for r in rows])
        output_combo = controls['translation']
        lock = page._recognition_sheet.findChild(QPushButton, 'recognitionTranslationUnlock')
        ready = bool(window._ai_unlocked()) if hasattr(window, '_ai_unlocked') else False
        check(f'{tag}: translation follows the AI lock',
              (output_combo.model().item(output_combo.findData('bilingual')).isEnabled() == ready)
              and (ready or (output_combo.currentData() == 'original' and lock is not None and lock.isVisible())),
              dict(ready=ready, current=output_combo.currentData(), unlock=bool(lock and lock.isVisible())))
        glossary = page._recognition_sheet.findChild(QComboBox, 'recognitionGlossaryButton')
        if glossary is not None:
            glossary.showPopup()
            settle(400)
            menu = glossary.findChild(QWidget, 'recognitionGlossaryMenu')
            boxes = controls['glossaries'].findChildren(QCheckBox)
            check(f'{tag}: glossary dropdown lists the glossaries', menu is not None and menu.isVisible() and len(boxes) >= 4,
                  dict(menu=bool(menu and menu.isVisible()), boxes=len(boxes)))
            if boxes:
                boxes[0].click()
                settle(300)
                check(f'{tag}: ticking a glossary keeps the dropdown open', menu.isVisible() and boxes[0].isChecked())
            grab(modal.card, f'{tag}_2_glossary_menu')
            if menu is not None:
                try:
                    menu.grab().save(str(output / f'{tag}_2b_menu.png'))
                except Exception:  # noqa: BLE001
                    pass
                menu.hide()
            if boxes:
                boxes[0].setChecked(False)
            settle(300)
        bar = info['bar']
        if bar is not None:
            bar.setValue(bar.maximum())
            settle(400)
        start = controls['start']
        card = modal.card
        top, bottom, _l, _r = rect_in(start, card)
        check(f'{tag}: start button reachable inside the card', start.isVisible() and top >= -1 and bottom <= card.height() + 1,
              [top, bottom, card.height()])
        grab(modal.card, f'{tag}_3_scrolled_to_end')
        if not card_height:
            plan = controls['plan']
            plan.setCurrentIndex(plan.findData('moss_pro_qwen'))
            settle(500)
            primary = controls['rows']['primary']
            start_tip = controls['start'].toolTip()
            # 2026-10-23: the row's chip says what is missing; the start button repeats it on hover.
            check(f'{tag}: MOSS Pro plan names the cloud model and what is missing',
                  primary.name.text() == 'MOSS Pro 云端'
                  and (primary.status.property('tone') != 'warn' or primary.status.text() in start_tip),
                  dict(name=primary.name.text(), status=primary.status.text(), start_tip=start_tip))
            grab(modal.card, f'{tag}_4_moss_pro_plan')
            info = measure(f'{tag}_moss_pro', page)
            row = controls['rows']['timeline']
            row.setFocus()
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            QTest.keyClick(row, Qt.Key.Key_Space)
            picker_up = wait_for(lambda: modal.isVisible() and not page._recognition_sheet.isVisible(), 10)
            settle(600)
            grab(modal.card, f'{tag}_5_model_picker')
            check(f'{tag}: a role row opens the model picker', picker_up)
            modal._request_close()
            back = wait_for(lambda: page._recognition_sheet.isVisible(), 10)
            settle(600)
            check(f'{tag}: closing the picker brings the sheet back', back)
            check(f'{tag}: closing the picker unchanged keeps the chosen plan',
                  controls['plan'].currentData() == 'moss_pro_qwen' and 'MOSS Pro' in primary.name.text(),
                  dict(plan=controls['plan'].currentData(), primary=primary.name.text()))
            grab(modal.card, f'{tag}_6_back_from_picker')
        modal.hide_content()
        settle(400)

    def run_all():
        try:
            from ..design.theme_manager import apply_theme
            apply_theme(os.environ.get('TWOBYTEASR_RECOGNITION_SHEET_THEME', 'grape'), app)
            for dialog in [w for w in app.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]:
                QDialog.done(dialog, 0)
            window.showNormal()
            window.resize(1440, 900)
            settle(800)
            page = open_fixture()
            check('Studio opened', page is not None and page.project is not None)
            run_case('tall', 0, page)
            run_case('short', 360, page)  # shorter than the content: it scrolls
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
