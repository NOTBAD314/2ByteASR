"""Real-window screenshots of the 导出字幕视频 page (design A, 2026-10-23).

User (10-23): redesign the export page; picked design A (two columns tidied:
output file / picture and encoding cards, advanced encoding and subtitle-file
export as fold rows, the range on the preview's timeline, facts as pills).
This scenario opens the sample project in Studio, enters the export page and
records it in the given themes: the default state, then everything open
(quality 自定义 with advanced encoding, an in / out range, AAC, the subtitle
fold), then other interface languages. It also exports subtitle files from
the fold's header button into the project's exports folder.

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=export-page`` (isolated data,
from ``scripts/verify_export_page_headed.py``; source or frozen). Offline; no AI.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path


def start(window, output: Path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QAbstractButton, QApplication
    app = QApplication.instance()
    output.mkdir(parents=True, exist_ok=True)
    result = dict(checks=[], skipped=[], metrics={}, errors=[], passed=False, pid=os.getpid(),
                  executable=os.path.realpath(sys.executable))

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))

    def settle(ms=300):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    def wait(fn, label, seconds=60):
        end = time.monotonic() + seconds
        while not fn():
            if time.monotonic() > end:
                raise TimeoutError(label)
            settle(50)

    def grab(widget, name):
        try:
            widget.grab().save(str(output / f'{name}.png'))
        except Exception as exc:  # noqa: BLE001
            result['errors'].append(f'grab {name}: {exc!r}')

    def clipped_buttons(workspace):
        """Visible buttons whose words need more room than they got."""
        found = []
        for button in workspace.setup_page.findChildren(QAbstractButton):
            if not button.isVisible() or len(button.text()) < 2:
                continue
            if button.width() + 1 < button.sizeHint().width():
                found.append([type(button).__name__, button.objectName(), button.text(),
                              button.width(), button.sizeHint().width()])
        return found

    def layout_facts(workspace):
        return dict(
            left_scroll=workspace.settings_scroll.verticalScrollBar().maximum(),
            left_overflow=workspace.settings_scroll.horizontalScrollBar().maximum(),
            right_scroll=workspace.preview_scroll.verticalScrollBar().maximum(),
            right_overflow=workspace.preview_scroll.horizontalScrollBar().maximum(),
            range_stacked=getattr(workspace, '_range_stacked', None),
            size=[workspace.width(), workspace.height()],
            left=[workspace.settings_scroll.width(), workspace.settings_scroll.height()])

    def capture(name, workspace):
        settle(500)
        grab(window, f'{name}_window')
        facts = layout_facts(workspace)
        facts['clipped'] = clipped_buttons(workspace)
        result['metrics'][name] = facts
        return facts

    def open_everything(workspace, page):
        workspace.quality.setCurrentIndex(workspace.quality.findData('custom'))
        workspace.expert_button.setChecked(True)
        workspace.audio.setCurrentIndex(workspace.audio.findData('aac'))
        duration = workspace._duration_ms()
        workspace.preview_scrub.setValue(int(duration * 0.3))
        workspace._set_in()
        workspace.preview_scrub.setValue(int(duration * 0.7))
        workspace._set_out()
        workspace.preview_scrub.setValue(int(duration * 0.4))
        workspace.subtitle_card.set_expanded(True)

    def close_everything(workspace):
        workspace._clear_range()
        workspace.subtitle_card.set_expanded(False)
        workspace.expert_button.setChecked(False)
        workspace.audio.setCurrentIndex(workspace.audio.findData('copy'))
        workspace.preset.setCurrentIndex(workspace.preset.findData('recommended'))
        workspace.quality.setCurrentIndex(workspace.quality.findData('recommended'))
        workspace.advanced_card.set_expanded(False)

    def run_all():
        try:
            from ..design.theme_manager import apply_theme
            page = window.studio_page
            project = Path(os.environ['TWOBYTEASR_STARTUP_PROJECT'])
            width, height = (int(v) for v in os.environ.get('TWOBYTEASR_EXPORT_PAGE_SIZE', '1600x830').split('x'))
            window.showNormal()
            window.resize(width, height)
            window.open_studio_project(str(project), mode='edit', source='export_page_audit')
            wait(lambda: page.project is not None and page._readiness.ready, 'project readiness')
            settle(1500)
            if not page.video._paused:   # opening a project starts playback
                page._toggle_playback()
            settle(500)
            wait(lambda: page._preview_path is not None, 'preview subtitles')
            page._open_render_dialog()
            wait(lambda: page.export_workspace is not None and page.export_workspace.isVisible(), 'export page')
            workspace = page.export_workspace
            settle(1200)
            themes = os.environ.get('TWOBYTEASR_EXPORT_PAGE_THEME', 'sand,grape').split(',')
            for key in dict.fromkeys(themes):
                apply_theme(key, app)
                facts = capture(f'{key}_default', workspace)
                check(f'{key}: left column fits without scrolling', facts['left_scroll'] == 0, facts)
                check(f'{key}: nothing wider than its column',
                      facts['left_overflow'] == 0 and facts['right_overflow'] == 0, facts)
                check(f'{key}: no button cut short', not facts['clipped'], facts['clipped'])
                open_everything(workspace, page)
                facts = capture(f'{key}_open', workspace)
                grab(workspace.settings_scroll.widget(), f'{key}_open_left_full')
                check(f'{key} open: nothing wider than its column',
                      facts['left_overflow'] == 0 and facts['right_overflow'] == 0, facts)
                check(f'{key} open: range drawn on the timeline',
                      workspace.export_range.currentData() == 'in_out'
                      and workspace.preview_scrub._range_start > 0, workspace.export_range.currentData())
                check(f'{key} open: advanced encoding shown',
                      workspace.advanced_panel.isVisible() and workspace.expert_panel.isVisible())
                close_everything(workspace)
                settle(300)
            # The narrow window the old layout was tested at.
            window.resize(1024, 700)
            facts = capture(f'{themes[-1]}_narrow', workspace)
            check('narrow window: nothing wider than its column',
                  facts['left_overflow'] == 0 and facts['right_overflow'] == 0, facts)
            check('narrow window: range choice above the points', facts['range_stacked'] is True, facts)
            window.resize(width, height)
            settle(500)
            # Subtitle files from the fold's header button, into the project exports folder.
            workspace.subtitle_destination_modes['project'].setChecked(True)
            workspace.subtitle_format_checks['ass'].setChecked(True)
            settle(200)
            workspace.subtitle_export_button.click()
            settle(800)
            written = [str(item.path) for item in workspace._last_subtitle_artifacts]
            grab(window, f'{themes[-1]}_subtitle_exported_window')
            check('subtitle fold: header button exports and opens the fold',
                  len(written) == 2 and workspace.subtitle_card.is_expanded()
                  and workspace.subtitle_open_folder.isVisible(), dict(files=written,
                                                                      status=workspace.subtitle_export_status.text()))
            result['metrics']['subtitle_summary'] = workspace.subtitle_card.summary.text()
            workspace.subtitle_card.set_expanded(False)
            # Other interface languages: longer words in the same controls.
            for code in [c for c in os.environ.get('TWOBYTEASR_EXPORT_PAGE_LANGS', '').split(',') if c]:
                index = window.language_combo.findData(code)
                if index < 0:
                    result['skipped'].append(f'language {code}')
                    continue
                window.language_combo.setCurrentIndex(index)
                settle(2500)
                facts = capture(f'{themes[-1]}_{code}', workspace)
                check(f'{code}: nothing wider than its column',
                      facts['left_overflow'] == 0 and facts['right_overflow'] == 0, facts)
                check(f'{code}: no button cut short', not facts['clipped'], facts['clipped'])
                open_everything(workspace, page)
                facts = capture(f'{themes[-1]}_{code}_open', workspace)
                grab(workspace.settings_scroll.widget(), f'{themes[-1]}_{code}_open_left_full')
                check(f'{code} open: no button cut short', not facts['clipped'], facts['clipped'])
                close_everything(workspace)
            if os.environ.get('TWOBYTEASR_EXPORT_PAGE_LANGS'):
                window.language_combo.setCurrentIndex(max(0, window.language_combo.findData('zh')))
                settle(1500)
            page._close_export_workspace()
            settle(500)
            page.save()   # the range edits marked the copied project; close without a prompt
            settle(500)
            result['passed'] = not result['errors'] and all(c['passed'] for c in result['checks'])
        except Exception:  # noqa: BLE001
            result['errors'].append(traceback.format_exc())
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')
        window.close()
        QTimer.singleShot(500, app.quit)

    def stopped():
        result['gui_shutdown'] = True
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')
    app.aboutToQuit.connect(stopped)
    QTimer.singleShot(2500, run_all)
