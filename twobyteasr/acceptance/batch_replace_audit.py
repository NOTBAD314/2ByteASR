"""批量替换 redesign in the real Studio window (2026-10-21).

User report: the 字幕文本工具 dialog was awkward, mostly empty space, with tabs
nobody needed. Plan B: one compact find/replace dialog; ↓ from 查找 to 替换,
Enter applies; AI 清理 beside AI 校对; 简繁 only in a menu (since 2026-10-22 the
「双语 / 翻译」 one); 回报问题 with words, right of 双语 in the banded bar (2026-10-24 port).
This opens a project, checks the toolbar and cue-list header, then drives the
dialogs with real key events and captures each surface.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    def execute():
        try:
            code = run(Path(output), window=window)
        except Exception:
            (Path(output) / 'result.json').write_text(json.dumps(dict(passed=False, error=traceback.format_exc())), 'utf8')
            code = 1
        window.result_exit_code = code

        def stopped():
            path = Path(output) / 'result.json'
            result = json.loads(path.read_text('utf8'))
            result['gui_shutdown'] = True
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
        QApplication.instance().aboutToQuit.connect(stopped)
        window.close()
    QTimer.singleShot(100, execute)


def run(output, *, window):
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QToolButton
    from .blank_project_audit import _capture
    from ..design.theme_manager import apply_theme
    from ..diagnostics.build_identity import load_build_identity
    from ..projects.studio_project import (StudioCue, StudioMedia, StudioSpeaker, SubtitleProject,
                                           hydrate_media_contract, save_project)
    from ..studio.studio_find_replace import AiCleanupDialog, FindReplaceDialog
    from ..studio.studio_helpers import probe_media_identity

    output = Path(output).resolve()
    if output != Path(os.environ['TWOBYTEASR_TEST_ROOT']).resolve():
        raise RuntimeError('isolated root required')
    theme = os.environ.get('TWOBYTEASR_BATCH_THEME', 'grape')
    apply_theme(theme)
    widths = [int(value) for value in os.environ.get('TWOBYTEASR_BATCH_WIDTHS', '1440,1600,1920').split(',')]
    media = Path(os.environ['TWOBYTEASR_BATCH_MEDIA']).resolve()
    result = dict(passed=False, checks=[], widths=[], theme=theme,
                  identity=load_build_identity().to_dict(), frozen=bool(getattr(sys, 'frozen', False)),
                  platform=QApplication.platformName(), pid=os.getpid())

    def receipt():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf8')

    def check(name, value, detail=None):
        result['checks'].append(dict(name=name, passed=bool(value), detail=detail))
        receipt()

    def wait(fn, label, seconds=60):
        end = time.monotonic() + seconds
        while not fn():
            if time.monotonic() > end:
                raise TimeoutError(label)
            QTest.qWait(20)

    def rect_in(widget, ancestor):
        origin = widget.mapTo(ancestor, widget.rect().topLeft())
        return (origin.x(), origin.y(), widget.width(), widget.height())

    def with_dialog(cls, act, opener):
        """``opener`` blocks in exec(); ``act(dialog)`` runs inside that loop, then the dialog closes."""
        done = {'tries': 0}

        def drive():
            dialog = next((w for w in QApplication.topLevelWidgets() if isinstance(w, cls) and w.isVisible()), None)
            if dialog is None:
                done['tries'] += 1
                if done['tries'] < 100:
                    QTimer.singleShot(100, drive)
                return
            try:
                QTest.qWait(500)
                act(dialog)
            except Exception:
                done['error'] = traceback.format_exc()
            finally:
                done['closed'] = True
                if dialog.isVisible():
                    dialog.reject()

        QTimer.singleShot(300, drive)
        opener()
        QTest.qWait(300)
        if done.get('error'):
            result.setdefault('dialog_errors', []).append(done['error'])
        check(f'{cls.__name__} opened and closed without error', done.get('closed') and not done.get('error'),
              done.get('error'))
        return done

    texts = ['尼奈这波打得好', '我觉得尼奈应该先撤，尼奈血不多了', '对面打野在上路，小心', '尼奈的大招还有十秒',
             '这把稳了，推掉中路', '尼奈 nice！', '先回城补装备', '最后一波团战尼奈开团']
    project = SubtitleProject(media=StudioMedia(str(media), duration_ms=10000, width=1280, height=720),
                              cues=[StudioCue(f'c{i}', i * 1200, i * 1200 + 1100, text,
                                              speaker_id='S01' if i % 2 else 'S02') for i, text in enumerate(texts)])
    project.speakers = [StudioSpeaker(id='S01', name='mio'), StudioSpeaker(id='S02', name='mai')]
    hydrate_media_contract(project, probe_media_identity(str(media)))
    project.validate()
    path = output / 'batch-replace.2byteproj'
    save_project(project, path)

    window.resize(1600, 1000)
    window.show()
    QTest.qWait(300)
    page = window.studio_page
    prior = page.project
    window.open_studio_project(str(path), mode='edit', source='batch_replace_audit')
    wait(lambda: page.project is not None and page.project is not prior and page._readiness.ready, 'project readiness')
    wait(lambda: page.video.controller is not None, 'player')
    QTest.qWait(800)
    if not page.video._paused:
        page._toggle_playback()
    QTest.qWait(300)
    original = [cue.text for cue in page.project.cues]

    # ---- toolbar and cue-list header -------------------------------------------------
    bar = page.studio_toolbar
    report = page.report_problem_button
    # 2026-10-22 (user, later than this round): 简繁 is a submenu of 双语 / 翻译.
    script_menu = page.chinese_script_menu
    for width in widths:
        window.resize(width, 1000)
        QTest.qWait(700)
        shown = [w for w in bar.findChildren(type(report)) if w.isVisible() and bar.isAncestorOf(w)]
        entry = dict(width=window.width(), report=rect_in(report, window) if report.isVisible() else None,
                     report_text=report.text(), collapsed=[w.text() for w in getattr(page, '_studio_toolbar_collapsed', ())])
        def overlapping():
            return [(a.text(), b.text()) for i, a in enumerate(shown) for b in shown[i + 1:]
                    if rect_in(a, window)[1] == rect_in(b, window)[1]
                    and rect_in(a, window)[0] < rect_in(b, window)[0] + b.width()
                    and rect_in(b, window)[0] < rect_in(a, window)[0] + a.width()]
        overlaps = overlapping()
        if overlaps:
            # A resize can still be settling; judge what stays on screen.
            entry['overlaps_first_look'] = overlaps
            QTest.qWait(1500)
            overlaps = overlapping()
        entry['overlaps'] = overlaps
        if os.environ.get('TWOBYTEASR_BATCH_TOOLBAR_ITEMS') == '1':
            stale = [(w.text(), w.geometry().getRect()) for w in shown]
            bar.layout().activate()
            QTest.qWait(50)
            entry['after_activate'] = [(w.text(), w.geometry().getRect()) for w in shown]
            entry['before_activate'] = stale
        result['widths'].append(entry)
        _capture(window, output / f'window-{window.width()}.png')
        bar.grab().save(str(output / f'toolbar-{window.width()}.png'))
        entry['buttons'] = sorted((rect_in(w, window)[0], rect_in(w, window)[2], w.text() or w.toolTip()) for w in shown)
        entry['bar_needs'] = bar.layout().minimumSize().width()
        entry['page_width'] = page.width()
        if os.environ.get('TWOBYTEASR_BATCH_TOOLBAR_ITEMS') == '1':
            layout = bar.layout()
            entry['items'] = []
            for index in range(layout.count()):
                item = layout.itemAt(index)
                w = item.widget()
                if w is None or w.isHidden():
                    entry['items'].append(dict(kind='spacer' if w is None else 'hidden', geo=item.geometry().getRect()))
                    continue
                entry['items'].append(dict(name=w.objectName(), text=getattr(w, 'text', lambda: '')(), cls=type(w).__name__,
                                           geo=w.geometry().getRect(), item_geo=item.geometry().getRect(),
                                           min=(w.minimumWidth(), w.minimumSizeHint().width()), hint=w.sizeHint().width(),
                                           item_min=item.minimumSize().width(), item_hint=item.sizeHint().width(),
                                           policy=int(w.sizePolicy().horizontalPolicy().value)))
        if os.environ.get('TWOBYTEASR_BATCH_TOOLBAR_ONLY') == '1':
            receipt()
            continue
        check(f'{window.width()}: 回报问题 on the bar with its words', report.isVisible() and report.text() == '回报问题'
              and report.width() >= report.sizeHint().width(), entry)
        check(f'{window.width()}: no 简繁 button on the bar', not any('简繁' in (w.text() or '') for w in shown),
              [w.text() for w in shown])
        check(f'{window.width()}: toolbar buttons do not overlap', not overlaps, overlaps)
        # 2026-10-21 (user): 回报问题 right of 双语; 压制成片 is the last command before the window buttons.
        order = [w for w in sorted(shown, key=lambda w: rect_in(w, window)[0])]
        names = [w.text() or w.toolTip() for w in order]
        render = page.studio_render_button
        bilingual = page.bilingual_toggle_button
        right_of_bilingual = (bilingual.isVisible() and report.isVisible()
                              and order.index(report) == order.index(bilingual) + 1)
        entry['order'] = names
        check(f'{window.width()}: 回报问题 right of 双语, 压制成片 last', right_of_bilingual and order[-1] is render
              and rect_in(render, window)[0] > max(rect_in(b, window)[0] for b in bar.findChildren(QToolButton)
                                                  if b.isVisible() and bar.isAncestorOf(b)
                                                  and b.parentWidget() is bar), names)
    window.resize(1600, 1000)
    QTest.qWait(700)
    if os.environ.get('TWOBYTEASR_BATCH_TOOLBAR_ONLY') == '1':
        # Same toolbar measurement on a build without this round (comparison only).
        result['passed'] = True
        receipt()
        return 0
    header = page.cue_proofread_button.parentWidget()
    proof, clean = rect_in(page.cue_proofread_button, header), rect_in(page.cue_cleanup_button, header)
    check('AI 清理 sits right of AI 校对 on one line', page.cue_cleanup_button.isVisible() and proof[1] == clean[1]
          and clean[0] >= proof[0] + proof[2], dict(proofread=proof, cleanup=clean))
    page.cue_proofread_button.parentWidget().grab(page.cue_proofread_button.parentWidget().rect()).save(
        str(output / 'cue-list-panel.png'))
    overflow = next(b for b in bar.findChildren(QToolButton) if b.property('commandSource') == '更多工作区操作')
    menu = overflow.menu()
    menu.popup(overflow.mapToGlobal(QPoint(0, overflow.height())))
    QTest.qWait(500)
    entries = [action.text() for action in menu.actions()]
    submenus = [action.text() for action in menu.actions() if action.menu() is not None]
    result['overflow_menu'] = dict(entries=entries, submenus=submenus)
    menu.grab().save(str(output / 'overflow-menu.png'))
    menu.hide()
    QTest.qWait(200)
    bilingual_menu = page.bilingual_toggle_button.menu()
    bilingual_menu.popup(page.bilingual_toggle_button.mapToGlobal(QPoint(0, page.bilingual_toggle_button.height())))
    QTest.qWait(500)
    bilingual_menu.grab().save(str(output / 'bilingual-menu.png'))
    check('「双语 / 翻译」 has the 字幕简繁转换 submenu with both scripts',
          script_menu.menuAction() in bilingual_menu.actions()
          and len([a for a in script_menu.actions() if a.isCheckable()]) == 2,
          [a.text() for a in bilingual_menu.actions()])
    bilingual_menu.hide()
    QTest.qWait(200)

    # ---- 批量替换 -----------------------------------------------------------------------
    found = {}

    def replace(dialog):
        found['size'] = (dialog.width(), dialog.height())
        _capture(dialog, output / 'dialog-empty.png')
        dialog.find_edit.setFocus()
        dialog.find_edit.insert('尼奈')       # typing (keyClicks with Chinese crashes Qt)
        QTest.keyClick(dialog.find_edit, Qt.Key.Key_Down)
        found['down'] = dialog.focusWidget() is dialog.replace_edit
        QTest.keyClick(dialog.replace_edit, Qt.Key.Key_Up)
        found['up'] = dialog.focusWidget() is dialog.find_edit
        QTest.keyClick(dialog.find_edit, Qt.Key.Key_Down)
        dialog.replace_edit.insert('她')
        QTest.qWait(600)                      # the live preview
        found['rows'] = dialog.preview.count()
        found['status'] = dialog.status_label.text()
        found['list_share'] = round(dialog.preview.height() / dialog.height(), 2)
        chips = [dialog.case_box, dialog.word_box, dialog.regex_box, dialog.body_box, dialog.lock_box,
                 dialog.project_entity_box]
        host = chips[0].parentWidget()
        chip_rects = [rect_in(chip, host) for chip in chips]
        found['chips'] = chip_rects
        found['chips_fit'] = all(chip.isVisible() and chip.width() >= chip.sizeHint().width()
                                 and r[0] >= 0 and r[0] + r[2] <= host.width() for chip, r in zip(chips, chip_rects))
        found['chips_overlap'] = [(i, j) for i, a in enumerate(chip_rects) for j, b in enumerate(chip_rects[i + 1:], i + 1)
                                  if a[1] == b[1] and a[0] < b[0] + b[2] and b[0] < a[0] + a[2]]
        found['labels_fit'] = {button.text(): button.width() >= button.sizeHint().width()
                               for button in (dialog.next_button, dialog.all_button)}
        found['hint_fits'] = dialog.key_hint.width() >= dialog.key_hint.sizeHint().width()
        _capture(dialog, output / 'dialog-preview.png')
        dialog.preview.item(1).setCheckState(Qt.CheckState.Unchecked)
        QTest.qWait(200)
        _capture(dialog, output / 'dialog-one-unchecked.png')
        undo = page.undo_stack.count()
        QTest.keyClick(dialog.replace_edit, Qt.Key.Key_Return)
        QTest.qWait(400)
        found['after_enter'] = [cue.text for cue in page.project.cues]
        found['undo_steps'] = page.undo_stack.count() - undo
        found['after_status'] = dialog.status_label.text()
        found['find_selected'] = dialog.find_edit.selectedText()
        found['left_unticked'] = (dialog.preview.count() == 1
                                  and dialog.preview.item(0).checkState() == Qt.CheckState.Unchecked)
        QTest.keyClick(dialog.find_edit, Qt.Key.Key_Return)   # a second Enter
        QTest.qWait(300)
        found['second_enter'] = [cue.text for cue in page.project.cues]
        dialog.find_edit.selectAll()
        _capture(dialog, output / 'dialog-after-enter.png')
        # Enter straight after typing, before the live preview refreshes.
        dialog.find_edit.setText('nice')
        dialog.replace_edit.setText('好')
        found['timer_active'] = dialog._search_timer.isActive()
        QTest.keyClick(dialog.replace_edit, Qt.Key.Key_Enter)
        QTest.qWait(300)
        found['fast_enter'] = page.project.cues[5].text
        QTest.keyClick(dialog.find_edit, Qt.Key.Key_Escape)
        QTest.qWait(300)
        found['esc_closed'] = not dialog.isVisible()

    with_dialog(FindReplaceDialog, replace, page._open_find_replace)
    result['find_replace'] = found
    check('↓ moves from 查找 to 替换, ↑ back', found.get('down') and found.get('up'), found)
    check('live preview lists every occurrence', found.get('rows') == 6, found.get('rows'))
    check('the preview list takes over half the dialog', found.get('list_share', 0) >= 0.5, found.get('list_share'))
    check('option chips fit, wrap without overlapping', found.get('chips_fit') and not found.get('chips_overlap'),
          dict(chips=found.get('chips'), overlap=found.get('chips_overlap')))
    check('footer labels fit', all(found.get('labels_fit', {}).values()) and found.get('hint_fits'),
          dict(labels=found.get('labels_fit'), hint=found.get('hint_fits')))
    expected = [text.replace('尼奈', '她') for text in original]
    expected[1] = '我觉得尼奈应该先撤，她血不多了'
    check('Enter applies the checked rows as one undo step',
          found.get('after_enter') == expected and found.get('undo_steps') == 1,
          dict(after=found.get('after_enter'), undo=found.get('undo_steps'), status=found.get('after_status')))
    check('the unticked row stays unticked; a second Enter changes nothing', found.get('left_unticked')
          and found.get('second_enter') == found.get('after_enter'), found.get('second_enter'))
    check('after Enter the find text is selected for the next pair', found.get('find_selected') == '尼奈',
          found.get('find_selected'))
    check('Enter before the live preview applies what was typed', found.get('timer_active')
          and found.get('fast_enter') == '她 好！', found.get('fast_enter'))
    check('Esc closes', found.get('esc_closed'))
    while page.undo_stack.canUndo():
        page.undo_stack.undo()
    QTest.qWait(200)
    check('undo restores the text', [cue.text for cue in page.project.cues] == original)

    # ---- AI 清理 (opened, not run: no network in this audit) ---------------------------
    cleanup = {}

    def look(dialog):
        cleanup['size'] = (dialog.width(), dialog.height())
        cleanup['options'] = [box.text() for box in dialog.ai_option_boxes.values()]
        cleanup['checked'] = [key for key, box in dialog.ai_option_boxes.items() if box.isChecked()]
        cleanup['local'] = {key: box.isChecked() for key, box in dialog.local_boxes.items()}
        _capture(dialog, output / 'ai-cleanup.png')

    with_dialog(AiCleanupDialog, look, lambda: QTest.mouseClick(page.cue_cleanup_button, Qt.MouseButton.LeftButton))
    result['ai_cleanup'] = cleanup
    # 2026-10-26 design A: four AI steps, two local ones (re-break needs a word-timed language).
    check('AI 清理 opens from the cue list with its options', len(cleanup.get('options', ())) == 4
          and cleanup.get('checked') == ['fillers', 'repeats', 'punctuation']
          and cleanup.get('local') == {'labels': True, 'regroup': False}, cleanup)

    page.save()
    QTest.qWait(500)
    result['passed'] = all(item['passed'] for item in result['checks'])
    receipt()
    return 0 if result['passed'] else 1
