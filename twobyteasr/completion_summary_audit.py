"""Whole-window normal-entry visual audit of a retained actual terminal result."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QObject, QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .completion_widgets import COMPLETION_MAIN_HEIGHT
    from .i18n import apply_ui_language
    from .service import MediaResult, QueueResult
    from .theme_manager import apply_theme

    output = Path(output)
    inputs = json.loads((output/'input.json').read_text('utf8'))
    report_path, project_path = Path(inputs['report']), Path(inputs['project'])
    report = json.loads(report_path.read_text('utf-8-sig'))
    protected = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (
        report_path, project_path, Path(inputs['source_project']), Path(inputs['source_report']))}
    item = MediaResult(media_path=report['media']['path'], status=report['status'],
        project_path=str(project_path), report_json_path=str(report_path),
        elapsed_seconds=float(report['result'].get('elapsed_seconds', 0)))

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.started = time.monotonic()
            self.result = dict(passed=False, checks=[], geometry=[], screenshots=[], inputs=inputs,
                terminal_origin='Retained actual terminal delivered to production _handle_result; no new ASR/provider request',
                layout_contract='2026-10-06 summary/full/collapsed; actual viewport logical height; real warning-first rows; bounded cards; preserve manual collapse',
                identity=load_build_identity().to_dict(), executable=sys.executable,
                dpr=window.devicePixelRatioF(), geometry_unit='Qt logical pixels; whole native window at actual DPR',
                protected=protected)
            self.steps = self.run()
            self.waiting = 0.
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(70)

        def write(self):
            (output/'result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf8')

        def check(self, name, passed, detail=None):
            self.result['checks'].append(dict(name=name, passed=bool(passed), detail=detail))
            self.write()
            if not passed:
                raise AssertionError(name+': '+str(detail))

        def tick(self):
            try:
                notification = getattr(window, '_completion_dialog', None)
                if notification and notification.isVisible():
                    QTest.mouseClick(notification.confirm_button, Qt.MouseButton.LeftButton)
                if time.monotonic() < self.waiting:
                    return
                delay = next(self.steps)
                self.waiting = time.monotonic()+delay
            except StopIteration:
                self.result['passed'] = True
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                try:
                    self.shot('failure')
                except Exception:
                    self.result['capture_error'] = traceback.format_exc()
                self.finish()

        def rect(self, widget, target):
            point = widget.mapTo(target, QPoint())
            return dict(x=point.x(), y=point.y(), width=widget.width(), height=widget.height())

        def shot(self, name):
            name += '.png'
            _capture(window, output/name)
            self.result['screenshots'].append(name)
            self.write()

        def measure(self, phase):
            scroll = window.pages.widget(2)
            viewport = scroll.viewport()
            panels = (window.result_files_panel, window.result_log_panel)
            grid = window.result_action_grid
            geometry = dict(phase=phase, window=self.rect(window, window), viewport=self.rect(viewport, window),
                summary=self.rect(window.result_summary_card, viewport),
                panels=[dict(mode=panel.mode, bounds=self.rect(panel, viewport),
                    row_texts=[getattr(row, '_full_name', row.text()) for row in panel.visible_summary_rows()],
                    rows=[dict(**self.rect(row, viewport), font_height=row.fontMetrics().height()) for row in panel.visible_summary_rows()],
                    extra_height=panel._extra_height, max_extra_height=panel.max_extra_height(),
                    detail_visible=panel.detail.isVisible(), summary_visible=panel.summary.isVisible()) for panel in panels],
                cards=[self.rect(card, viewport) for card in grid.cards],
                secondary=[self.rect(button, viewport) for button in grid.secondary_actions],
                columns=grid.columns, scroll_maximum=scroll.verticalScrollBar().maximum())
            bottom = grid.mapTo(viewport, QPoint()).y()+grid.height()
            geometry['bottom_space'] = viewport.height()-bottom
            self.result['geometry'].append(geometry)
            self.check(phase+': no horizontal scroll', scroll.horizontalScrollBar().maximum() == 0, geometry)
            self.check(phase+': top summary stays near navigation', window.result_summary_card.mapTo(viewport, QPoint()).y() == 28, geometry)
            if grid.columns == 3:
                self.check(phase+': shared equal action columns', all(abs(card.x()-button.x()) <= 1 and abs(card.width()-button.width()) <= 1
                    for card, button in zip(grid.cards, grid.secondary_actions)), geometry)
            self.check(phase+': cards retain readable bounded height', all(COMPLETION_MAIN_HEIGHT <= card.height() <= card.desired_height(card.width())+24 for card in grid.cards), geometry)
            self.check(phase+': real summary row cadence remains font-bounded', all(
                row.height() <= row.fontMetrics().height()+3+round(row.fontMetrics().height()*1.5)+1
                for panel in panels for row in panel.visible_summary_rows()), geometry)
            self.check(phase+': main/supporting rows keep common order', all(card.geometry().bottom() < button.geometry().top() for card, button in zip(grid.cards, grid.secondary_actions)), geometry)
            if all(panel.mode == 'summary' for panel in panels):
                compact = viewport.height() < 760
                self.check(phase+': actual task/log summary rows shown', len(panels[0].visible_summary_rows()) == (2 if compact else 4)
                    and 4 <= len(panels[1].visible_summary_rows()) <= (4 if compact else 6), geometry)
                self.check(phase+': summaries are distinct from full logs', all(panel.summary.isVisible() and panel.detail.isHidden() for panel in panels), geometry)
                capacity_reached = any(panel._extra_height == panel.max_extra_height() for panel in panels)
                if not compact and not scroll.verticalScrollBar().maximum() and not capacity_reached:
                    self.check(phase+': bottom breathing space 24-40 logical pixels', 24 <= geometry['bottom_space'] <= 40, geometry)
                elif not compact and capacity_reached and geometry['bottom_space'] > 40:
                    self.result.setdefault('layout_limits', []).append(dict(phase=phase,
                        reason='Extreme logical viewport exceeds truthful 4/6 summary-row and bounded-card capacity; extra blank space is not counted as successful height fill',
                        bottom_space=geometry['bottom_space'], viewport_height=viewport.height()))
            self.write()

        def run(self):
            apply_theme('grape')
            apply_ui_language(window, 'zh')
            available = window.screen().availableGeometry()
            normal = (min(2047, available.width()-30), min(1116, available.height()-30))
            window.resize(*normal)
            log_path = report_path.parent/'retained-run.log'
            if log_path.is_file():
                for line in log_path.read_text('utf8', errors='replace').splitlines():
                    window._append_console_line(line)
            else:
                for event in report.get('events', []):
                    window._append_console_line(json.dumps(event, ensure_ascii=False))
            window._last_run_options = None
            window._handle_result(QueueResult((item,), item.elapsed_seconds))
            yield .65
            self.result['actual_summary'] = asdict(window._completion_summary)
            self.measure('default-normal')
            self.shot('01-default-summary-whole-window')
            panels = (window.result_files_panel, window.result_log_panel)
            QTest.mouseClick(panels[0].header, Qt.MouseButton.LeftButton)
            QTest.mouseClick(panels[1].header, Qt.MouseButton.LeftButton)
            yield .5
            self.check('full details accessible and bounded', all(panel.mode == 'full' and panel.detail.isVisible()
                and panel.detail.height() <= 230 for panel in panels), [panel.mode for panel in panels])
            self.check('full technical log is retained', bool(window.result_console.toPlainText()) and bool(window._completion_log_lines))
            self.measure('full-normal'); self.shot('02-full-details-whole-window')
            for panel in panels:
                QTest.mouseClick(panel.collapse_button, Qt.MouseButton.LeftButton)
            yield .25
            self.check('explicit manual collapse hides both bodies', all(panel.mode == 'collapsed' and panel.summary.isHidden() and panel.detail.isHidden() for panel in panels))
            self.measure('manual-collapsed'); self.shot('03-manual-collapsed-whole-window')
            window.resize(max(740, normal[0]-180), max(520, normal[1]-160))
            yield .35
            self.check('resize preserves manual collapse', all(panel.mode == 'collapsed' for panel in panels))
            for panel in panels:
                QTest.mouseClick(panel.header, Qt.MouseButton.LeftButton)
            window.resize(*normal)
            yield .4
            self.check('collapsed headers reopen summary before full', all(panel.mode == 'summary' for panel in panels))
            window.showMaximized(); yield .5
            self.measure('default-maximized'); self.shot('04-default-maximized-whole-window')
            window.showNormal(); window.resize(580, 440); yield .5
            self.measure('default-narrow'); self.shot('05-default-narrow-whole-window')
            scroll = window.pages.widget(2)
            scroll.ensureWidgetVisible(window.result_more_button); yield .25
            self.check('narrow last operation remains reachable through scrolling',
                0 <= window.result_more_button.mapTo(scroll.viewport(), QPoint()).y() < scroll.viewport().height())
            self.shot('06-narrow-actions-reachable-whole-window')
            window.resize(*normal)
            scroll.verticalScrollBar().setValue(0)
            for language in ('en', 'ja', 'zh'):
                apply_ui_language(window, language)
                window._refresh_completion_summaries()
                yield .4
                self.measure('default-'+language)
                self.shot('07-default-'+language+'-whole-window')
            current = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in protected}
            self.check('source and copied immutable artifacts stay byte-identical', current == protected, current)
            from .blank_project_audit import _provider_calls, _blocked_external_connections
            self.check('no provider request', _provider_calls == 0, _provider_calls)
            self.check('no external connection attempted', not _blocked_external_connections, list(_blocked_external_connections))

        def finish(self):
            self.timer.stop()
            from .blank_project_audit import _provider_calls, _blocked_external_connections
            self.result['provider_calls'] = _provider_calls
            self.result['external_connections_blocked'] = list(_blocked_external_connections)
            self.result['elapsed_seconds'] = time.monotonic()-self.started
            window.result_exit_code = 0 if self.result['passed'] else 1
            self.write()
            def stopped():
                self.result['gui_shutdown'] = True
                self.write()
            QApplication.instance().aboutToQuit.connect(stopped)
            window.close()

    window._completion_summary_audit = Audit()
