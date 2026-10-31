"""Real window: design B operation bar and viewport-filling completion preview.

Two generated, isolated tasks go through the production completion handler:
one with an unfinished AI pass and many review items of several categories,
one with a single speaker item and nothing to retry. The audit clicks the
real controls (fold headers, 查看全部, 逐类查看, a group's jump) and captures
the window in both themes and three languages. No provider is called.
"""
import json
import os
import shutil
import subprocess
import time
import traceback
from pathlib import Path


def _project(output, name, cues, report):
    from ..projects.studio_project import StudioCue, StudioMedia, StudioSpeaker, SubtitleProject, save_project
    path = output / f'{name}.2byteproj'
    media_path = output / f'{name}.mp4'
    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg is None:
        raise RuntimeError('The completion navigation audit requires local ffmpeg for isolated fixture media')
    subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-y', '-f', 'lavfi', '-i', 'color=c=0x19151c:s=320x180:r=2',
                    '-f', 'lavfi', '-i', 'anullsrc=r=16000:cl=mono', '-t', str((cues[-1][1]+2000)/1000),
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '35', '-c:a', 'aac', str(media_path)],
                   check=True, capture_output=True, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    project = SubtitleProject(media=StudioMedia(path=str(media_path), duration_ms=cues[-1][1] + 2000),
                              speakers=[StudioSpeaker('S00', '主播'), StudioSpeaker('S01', '嘉宾')],
                              generation_metadata={'speaker_recovery': {'roles': {'S00': 'unconfirmed', 'S01': 'unconfirmed'}}},
                              cues=[StudioCue(f'c{i}', start, end, text, speaker_id=speaker, evidence_refs=[f'segment:{i}'])
                                    for i, (start, end, text, speaker) in enumerate(cues)],
                              asr_evidence={f'segment:{i}': dict(text=text, start_ms=start, end_ms=end,
                                  speaker_id=speaker, caption_arbitration=dict(processing_identity=dict(polish_record_id=i),
                                  terminology_polish=dict(original_text=text, response_state='fallback' if name == 'busy' and i == 0 else 'validated')))
                                  for i, (start, end, text, speaker) in enumerate(cues)})
    save_project(project, path)
    report_path = output / f'{name}.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False), 'utf-8')
    return path, report_path


def build_tasks(output):
    lines = ['大家好，今天我们来看一下调色页面', '这个节点的设置比较关键', '好', '先把色彩管理打开',
             '然后选择 DaVinci YRGB Color Managed', '这一段说得比较快大家注意看一下这里的参数设置', '我们继续',
             '嗯', '这里要注意输出色彩空间', '最后检查一下整体效果']
    cues = []
    for index, text in enumerate(lines * 4):
        start = index * 2600
        end = start + (300 if text in ('好', '嗯') else 1400 if len(text) > 18 else 2200)
        cues.append((start, end, text, 'S01' if index % 7 == 3 else 'S00'))
    review = [dict(category='说话人重叠', cue_id=f'c{i}', text=cues[i][2], timestamp=cues[i][0]/1000, severity='review')
              for i in (3, 10, 17)]
    review += [dict(category='边界待看', cue_id=f'c{i}', text=cues[i][2], timestamp=cues[i][0]/1000, severity='review')
               for i in (1, 12)]
    review += [dict(category='多模型争议', cue_id=f'c{i}', text=cues[i][2], timestamp=cues[i][0]/1000, severity='review')
               for i in (4,)]
    review.append(dict(category='说话人需要确认', severity='review'))
    busy = dict(status='degraded_success', media=dict(name='DaVinci-Resolve-17-Color-AdvancedColor.mp4'),
                result=dict(cue_count=len(cues), audio_seconds=round(cues[-1][1]/1000, 3)),
                polishing_summary=dict(success_cues=len(cues) - 1, fallback_cues=1, fallback_batches=1, success_batches=3,
                                       fallback_ids=[0], success_ids=list(range(1, len(cues)))),
                terminology_summary=dict(status='disabled'), review_items=review,
                stages=[dict(label='MOSS 全局转写', status='completed', elapsed_seconds=155.1),
                        dict(label='云端模型受限校对', status='completed', elapsed_seconds=41.6)])
    small = [(0, 2400, 'I can see that problem', 'S00'), (2600, 5000, 'I can see that problem', 'S00'),
             (5200, 7400, '山上木', 'S01'), (7600, 9800, '山高水长', 'S01'), (10000, 12000, '拖拖拖往哪拖', 'S00')]
    quiet = dict(status='success', media=dict(name='北极熊 异人之下 New 6.mp3'),
                 result=dict(cue_count=len(small), audio_seconds=12.0),
                 polishing_summary=dict(success_cues=len(small), success_batches=1),
                 terminology_summary=dict(status='disabled'),
                 review_items=[dict(category='说话人需要确认', severity='review')])
    return (('busy',) + _project(output, 'busy', cues, busy)), (('quiet',) + _project(output, 'quiet', small, quiet))


def start(window, output):
    if os.environ.get('TWOBYTEASR_UI_MERGE_AUDIT'):
        from .ui_daily_merge_audit import start as start_merge
        return start_merge(window, output)
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from ..design.theme_manager import apply_theme
    from ..recognition.service import MediaResult, QueueResult, RunOptions
    from ..test_isolation import require_isolated_paths
    from .completion_real_audit import secondary_control_measurement
    require_isolated_paths('completion-todo')
    result = dict(checks=[], shots=[], passed=False,
                  screens=[dict(name=screen.name(), available=screen.availableGeometry().getRect(),
                                dpr=screen.devicePixelRatio()) for screen in QApplication.screens()])

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))
        write()
        if not ok:
            shot('failure')
            raise AssertionError(name)

    def write():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    def settle():
        # Notices open a moment after the result; close each and let its
        # dimming overlay fade before anything is measured or captured.
        for _ in range(40):
            yield .1
            if any(type(widget).__name__ == 'CompletionDialog' and widget.isVisible() for widget in QApplication.topLevelWidgets()):
                close_notices()
                yield .8
                return
        yield .3

    def shot(name, popup=None):
        target = output / f'{name}.png'
        windows = [dict(type=type(widget).__name__, name=widget.objectName(), title=widget.windowTitle(), modal=widget.isModal())
                   for widget in QApplication.topLevelWidgets() if widget.isVisible() and widget is not window]
        result.setdefault('other_windows', {})[name] = windows
        content = window.result_content
        layout = content.layout()
        rows = [dict(type=type(item.widget()).__name__, y=item.widget().y(), height=item.widget().height())
                for item in (layout.itemAt(i) for i in range(layout.count()))
                if item.widget() is not None and not item.widget().isHidden()]
        preview = window.result_preview
        scroll = window.pages.widget(2)
        result.setdefault('layout', {})[name] = dict(window=window.size().toTuple(),
            content_height=content.height(), content_width=content.width(), bar_height=window.result_todo.height(),
            preview_height=preview.height(), list_height=preview.list.height(),
            preview_bottom_gap=scroll.viewport().height()-preview.mapTo(scroll.viewport(), QPoint()).y()-preview.height(),
            needed=layout.totalHeightForWidth(content.width()), rows=rows,
            viewport=scroll.viewport().height(), page_margins=content._page_layout.contentsMargins().top())
        _capture(window, target)
        result['shots'].append(str(target))
        if popup is not None:
            popup_target = output / f'{name}-popup.png'
            _capture(popup, popup_target)
            result['shots'].append(str(popup_target))

    tasks = tuple((name,) + tuple(output / f'{name}{suffix}' for suffix in ('.2byteproj', '.json')) for name in ('busy', 'quiet'))
    opened = []
    ready = []
    open_project = window._open_completion_project

    def tracked_open(path, **kwargs):
        opened.append(dict(path=str(path), mode=kwargs['mode'], source=kwargs['source']))
        callback = kwargs.pop('on_ready', None)

        def tracked_ready(studio):
            if callback is not None:
                callback(studio)
            ready.append(studio)
        open_project(path, on_ready=tracked_ready, **kwargs)
    window._open_completion_project = tracked_open

    def show(name):
        _label, project, report = next(task for task in tasks if task[0] == name)
        window._last_run_options = RunOptions()
        window._console_lines = [f'[QA fixture {name}] retained log line {index:03d}' for index in range(160)]
        window._console_fragments = [window._completion_plain_log_fragment(line) for line in window._console_lines]
        window._handle_result(QueueResult((MediaResult(str(output / f'{name}.mp4'), 'success', project_path=str(project),
                                                       report_json_path=str(report), elapsed_seconds=302.0),), 302.0))
        window._switch_page(2)
        window.pages.widget(2).verticalScrollBar().setValue(0)

    def bottom_check(name):
        scroll, preview = window.pages.widget(2), window.result_preview
        bar = scroll.verticalScrollBar()
        scrolling = bar.maximum() > 0
        if scrolling:
            # The user chose to preserve the original summary/main-action
            # sizes. A shorter viewport scrolls rather than compressing them.
            bar.setValue(bar.maximum())
            QApplication.processEvents()
        gap = scroll.viewport().height() - preview.mapTo(scroll.viewport(), QPoint()).y() - preview.height()
        check(f'{name}: preview reaches bottom or preserves six rows while scrolling', abs(gap - 28) <= 4
              and (not scrolling or preview.list.height() == 6*36),
              dict(gap=gap, list_height=preview.list.height(), page_height=scroll.viewport().height(), scrolling=scrolling))
        bar.setValue(0)
        QApplication.processEvents()

    def bar_check(name):
        todo = window.result_todo
        controls = [card for card in todo.cards if card.isVisible()] + [window.result_more_button]
        check(f'{name}: bar is one 52px row', todo.columns == 3 and abs(todo.height()-52) <= 2,
              dict(width=todo.width(), height=todo.height(), groups=[card.geometry().getRect() for card in controls]))
        check(f'{name}: fixed groups do not overlap',
              all(a.geometry().right() < b.geometry().left() for a, b in zip(controls, controls[1:])))
        measured = [secondary_control_measurement(card.action, expected_height=36) for card in todo.cards if card.isVisible()]
        measured.append(secondary_control_measurement(window.result_more_button, expected_height=36))
        check(f'{name}: all button labels fit at 36px', all(row['fits'] for row in measured), measured)
        labels = [label for card in todo.cards if card.isVisible() for label in (card.title, card.badge, card.note)
                  if not label.isHidden()]
        check(f'{name}: protected text fits', all(label.width() >= label.sizeHint().width() for label in labels),
              [(label.text(), label.width(), label.sizeHint().width()) for label in labels])
        chips = todo.review_card.chips
        check(f'{name}: category labels are whole', all(label.isHidden() or
              (label.width() == label.sizeHint().width() and chips.rect().contains(label.geometry())) for label in chips.labels),
              [(label.text(), label.isVisible(), label.geometry().getRect()) for label in chips.labels])

    def close_notices():
        # The real task notice opens first; the user reads it, then the page.
        for widget in QApplication.topLevelWidgets():
            if type(widget).__name__ == 'CompletionDialog' and widget.isVisible():
                widget.accept()

    def flow():
        window.showNormal()
        window.resize(1460, 940)
        yield .5
        if os.environ.get('TWOBYTEASR_COMPLETION_TODO_TALL_ONLY') == '1':
            result['scope'] = 'native 1460x1300 at process-local scale; narrow UI is verified at normal system DPI'
            apply_theme('grape')
            show('busy')
            yield from settle()
            window.resize(1460, 1300)
            yield .6
            check('tall-only: actual native window is 1460x1300', window.size().toTuple() == (1460, 1300), window.size().toTuple())
            bar_check('tall-only')
            bottom_check('tall-only')
            check('tall-only: more than six subtitle rows visible', window.result_preview.list.height() > 6*36,
                  window.result_preview.list.height())
            check('tall-only: default summaries are open and equal', window.result_files_panel.mode == window.result_log_panel.mode == 'summary'
                  and window.result_files_panel.height() == window.result_log_panel.height())
            shot('grape-busy-tall')
            result['passed'] = True
            window.close()
            return
        for theme in ('warm', 'grape'):
            apply_theme(theme)
            yield .3
            show('busy')
            yield from settle()
            todo = window.result_todo
            check(f'{theme}: busy task shows all three groups', all(card.isVisible() for card in todo.cards))
            check(f'{theme}: retry count is the real recoverable stage count', todo.retry_card.badge.text() == '1'
                  and todo.retry_card.badge.isVisible() and todo.retry_card.action.isEnabled(), todo.retry_card.badge.text())
            bar_check(f'{theme} busy')
            bottom_check(f'{theme} busy')
            check(f'{theme}: summary card carries no retry or review button',
                  not window.result_summary_card.isAncestorOf(window.retry_failed_button)
                  and not window.result_summary_card.isAncestorOf(window.result_review_status))
            chips = todo.review_card.chip_texts()
            check(f'{theme}: review chips name plain categories with counts', any('多人同时说话' in chip for chip in chips), chips)
            shot(f'{theme}-busy-default')
            files, log = window.result_files_panel, window.result_log_panel
            check(f'{theme}: both summaries open by default at equal height', files.mode == log.mode == 'summary'
                  and files.height() == log.height() and window.result_folds.columns == 2,
                  [files.geometry().getRect(), log.geometry().getRect()])
            QTest.mouseClick(todo.review_card.action, Qt.MouseButton.LeftButton)
            yield .3
            menu = todo._group_menu
            check(f'{theme}: menu lists every category and full list', menu.isVisible()
                  and len(menu.actions()) == len(todo._groups)+2 and len(todo._groups) >= 4,
                  [action.text() for action in menu.actions()])
            shot(f'{theme}-busy-menu', popup=menu)
            menu.close()
            # Verify real Studio navigation once; all other menu states use
            # the same production connections without changing the project.
            if theme == 'grape':
                index = next(i for i, (_label, _count, row) in enumerate(todo._groups) if row.get('cue_ids'))
                row = todo._groups[index][2]
                expected = next(cue.id for cue in window._completion_tasks[0][1].cues if cue.id in row['cue_ids'])
                QTest.mouseClick(todo.review_card.action, Qt.MouseButton.LeftButton)
                yield .2
                menu = todo._group_menu
                QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(menu.actions()[index]).center())
                for _ in range(100):
                    if ready:
                        break
                    yield .1
                check('category menu opens actual Studio and selects its first caption', bool(ready)
                      and window.pages.currentWidget() is ready[-1] and ready[-1].selected_cue_id == expected,
                      dict(expected=expected, selected=ready[-1].selected_cue_id if ready else None, opened=opened))
                shot('grape-category-studio')
                window._switch_page(2)
                yield .3
                # The speaker category must open the real manager dialog.
                observed = []
                closer = QTimer(window)
                closer.setInterval(100)
                def close_speaker():
                    for dialog in QApplication.topLevelWidgets():
                        if type(dialog).__name__ == 'SpeakerManagerDialog' and dialog.isVisible():
                            observed.append(dialog.windowTitle())
                            _capture(dialog, output / 'speaker-manager.png')
                            dialog.reject()
                            closer.stop()
                closer.timeout.connect(close_speaker)
                closer.start()
                QTimer.singleShot(15000, closer, closer.stop)
                index = next(i for i, (_label, _count, row) in enumerate(todo._groups) if row.get('target') == 'speakers')
                QTest.mouseClick(todo.review_card.action, Qt.MouseButton.LeftButton)
                yield .2
                menu = todo._group_menu
                QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(menu.actions()[index]).center())
                for _ in range(100):
                    if observed:
                        break
                    yield .1
                check('speaker category opens actual speaker manager', bool(observed), observed)
                window._switch_page(2)
                yield .3
                # Full list remains the existing current-review dialog.
                observed_full = []
                def close_full():
                    dialog = getattr(window, '_current_review_dialog', None)
                    if dialog is not None and dialog.isVisible():
                        observed_full.append(dialog._review_tabs.count())
                        _capture(dialog, output / 'current-review-dialog.png')
                        dialog.accept()
                QTest.mouseClick(todo.review_card.action, Qt.MouseButton.LeftButton)
                yield .2
                menu = todo._group_menu
                QTimer.singleShot(300, window, close_full)
                QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(menu.actions()[-1]).center())
                yield .3
                check('full menu action opens current-review dialog', observed_full == [3], observed_full)
            yield .2
            window.pages.widget(2).ensureWidgetVisible(files)
            QTest.mouseClick(files.header, Qt.MouseButton.LeftButton)
            yield .3
            window._refresh_completion_summaries()
            yield .2
            check(f'{theme}: one click collapses and refresh preserves it', files.mode == 'collapsed' and log.mode == 'summary')
            QTest.mouseClick(files.header, Qt.MouseButton.LeftButton)
            yield .3
            check(f'{theme}: second click reopens summary', files.mode == 'summary')
            QTest.mouseClick(files.detail_button, Qt.MouseButton.LeftButton)
            yield .3
            check(f'{theme}: 查看全部 shows the full details', files.mode == 'full' and files.detail.isVisible())
            window.pages.widget(2).ensureWidgetVisible(files)
            yield .2
            shot(f'{theme}-busy-files-full')
            QTest.mouseClick(files.header, Qt.MouseButton.LeftButton)
            yield .3
            check(f'{theme}: the next header click closes it', files.mode == 'collapsed' and files.detail.isHidden())
            QTest.mouseClick(files.header, Qt.MouseButton.LeftButton)
            yield .2
            QTest.mouseClick(log.detail_button, Qt.MouseButton.LeftButton)
            yield .3
            metrics = window.result_console.fontMetrics()
            check(f'{theme}: full log is scrollable monospace', log.mode == 'full'
                  and window.result_console.verticalScrollBar().maximum() > 0
                  and metrics.horizontalAdvance('iiiiiiii') == metrics.horizontalAdvance('WWWWWWWW'),
                  window.result_console.toPlainText()[:150])
            window.pages.widget(2).verticalScrollBar().setValue(0)
            window.result_console.verticalScrollBar().setValue(0)
            shot(f'{theme}-busy-log-full')
            QTest.mouseClick(log.header, Qt.MouseButton.LeftButton)
            yield .3
            check(f'{theme}: 运行日志 also opens and closes from its header', log.mode == 'collapsed')
            window.pages.widget(2).verticalScrollBar().setValue(0)
            show('quiet')
            yield from settle()
            check(f'{theme}: quiet task shows AI and review only', todo.ai_card.isVisible() and todo.review_card.isVisible()
                  and not todo.retry_card.isVisible() and todo.dividers[1].isHidden())
            check(f'{theme}: next completion opens both summaries again', files.mode == log.mode == 'summary')
            bar_check(f'{theme} quiet')
            bottom_check(f'{theme} quiet')
            shot(f'{theme}-quiet-default')
        # No review/no retry is a legitimate third state. Retain menu facts
        # before restoring the production task on the next run.
        todo.set_review(())
        yield .3
        check('no review and no retry: only AI and more remain', todo.ai_card.isVisible()
              and todo.review_card.isHidden() and todo.retry_card.isHidden()
              and all(divider.isHidden() for divider in todo.dividers))
        shot('grape-no-review-or-retry')
        for language in ('en', 'ja', 'zh'):
            window.language_combo.setCurrentIndex(window.language_combo.findData(language))
            window._apply_ui_language()
            show('busy')
            yield from settle()
            scroll = window.pages.widget(2)
            check(f'{language}: no horizontal overflow', scroll.horizontalScrollBar().maximum() == 0)
            bar_check(language)
            bottom_check(language)
            shot(f'grape-busy-{language}')
        first_list_height = window.result_preview.list.height()
        first_scroll_maximum = window.pages.widget(2).verticalScrollBar().maximum()
        first_viewport_height = window.pages.widget(2).viewport().height()
        window.resize(1460, 1300)
        yield .6
        bottom_check('tall')
        viewport_growth = window.pages.widget(2).viewport().height() - first_viewport_height
        check('taller window gives spare height to preview after clearing short-window overflow',
              abs(window.result_preview.list.height()-first_list_height-(viewport_growth-first_scroll_maximum)) <= 2,
              dict(before=first_list_height, after=window.result_preview.list.height(), short_scroll=first_scroll_maximum,
                   requested_window_height=1300, actual_window_height=window.height(), viewport_growth=viewport_growth))
        shot('grape-busy-tall')
        window.resize(820, 760)
        yield .5
        todo = window.result_todo
        check('narrow: cards and folds stack in one column', todo.columns == 1 and window.result_folds.columns == 1
              and window.pages.widget(2).horizontalScrollBar().maximum() == 0)
        shot('grape-busy-narrow-top')
        window.pages.widget(2).ensureWidgetVisible(window.result_files_panel)
        yield .3
        shot('grape-busy-narrow-folds')
        check('narrow: category labels hidden and actions remain full width', todo.review_card.chips.isHidden()
              and all(card.action.fontMetrics().horizontalAdvance(card.action.text())+28 <= card.action.width() for card in todo.cards))
        scroll = window.pages.widget(2)
        for button in (todo.ai_card.action, todo.review_card.action, todo.retry_card.action, window.result_more_button,
                       *window.result_action_grid.cards):
            scroll.ensureWidgetVisible(button)
            yield .1
            check(f'narrow: scroll reaches {button.text()}', scroll.viewport().rect().contains(button.mapTo(scroll.viewport(), QPoint())))
        check('short window keeps six preview rows', window.result_preview.list.height() >= 6*36)
        result['passed'] = True
        window.close()

    steps = flow()
    state = dict(until=0., ticking=False)
    timer = QTimer(window)
    timer.setInterval(20)

    def tick():
        if state['ticking'] or time.monotonic() < state['until']:
            return
        state['ticking'] = True
        try:
            state['until'] = time.monotonic() + next(steps)
        except StopIteration:
            timer.stop(); write(); QApplication.instance().quit()
        except BaseException:
            result['error'] = traceback.format_exc()
            timer.stop(); write(); QApplication.instance().quit()
        finally:
            state['ticking'] = False

    def shutdown():
        result['gui_shutdown'] = True
        write()
    QApplication.instance().aboutToQuit.connect(shutdown)
    timer.timeout.connect(tick)
    timer.start()
