"""Normal Qt delivery audit replaying an immutable real task report.

No ASR/provider request is sent. Synthetic terminal states are explicitly UI
coverage. Every screenshot captures the whole normally launched window.
"""
from __future__ import annotations
from dataclasses import asdict, replace
import copy
import faulthandler
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import traceback


def completion_panel_geometry(panel, header, content, margins):
    """Exact logical-pixel contract of the existing bordered InfoPanel.

    The outer panel owns the full content row. Its header occupies the inner
    row after the fixed one-pixel border, not the outer panel's width. The
    expanded summary/detail is below the header, so the header's bottom need
    not equal the panel's bottom. All four layout margins remain exactly one.
    """
    def coordinates(rect):
        return [rect[key] for key in ('x', 'y', 'width', 'height')] if isinstance(rect, dict) else list(rect)
    panel, header, content, margins = coordinates(panel), coordinates(header), coordinates(content), list(margins)
    px, py, pw, ph = panel
    hx, hy, hw, hh = header
    cx, cy, cw, ch = content
    legacy = abs(hx-cx) <= 1 and abs(hw-cw) <= 1
    outer = px == cx and pw == cw and pw > 2 and ph > 2
    border = margins == [1, 1, 1, 1]
    inner = hx == px+1 and hy == py+1 and hw == pw-2 and hh > 0 and hy+hh <= py+ph-1
    return dict(panel=panel, header=header, content=content, margins=margins,
        expected_margins=[1, 1, 1, 1], panel_full_row_contract=outer,
        header_inner_border_contract=inner, layout_margin_contract=border,
        designed_panel_contract=outer and inner and border, legacy_full_row_contract=legacy,
        panel_to_content=dict(left=px-cx, right=(cx+cw)-(px+pw)),
        header_to_panel=dict(left=hx-px, top=hy-py, right=(px+pw)-(hx+hw), bottom=(py+ph)-(hy+hh)))


def secondary_control_measurement(button):
    """Audit actual geometry after theme/i18n polish, including legal minima."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton
    if isinstance(button, QPushButton):
        option = QStyleOptionButton()
        button.initStyleOption(option)
        available = button.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, option, button)
        if not button.icon().isNull():
            available.adjust(button.iconSize().width()+6, 0, 0, 0)
    else:
        available = button.content_rects()[0].toRect()
    from .completion_widgets import COMPLETION_SECONDARY_HEIGHT
    text = button.fontMetrics().boundingRect(available,
        int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextSingleLine), button.text())
    return dict(text=button.text(), width=button.width(), height=button.height(),
        minimum_width=button.minimumWidth(), maximum_width=button.maximumWidth(),
        minimum_height=button.minimumHeight(), maximum_height=button.maximumHeight(),
        font_pixels=button.font().pixelSize(),
        text_bounds=dict(x=text.x(),y=text.y(),width=text.width(),height=text.height()),
        available=dict(x=available.x(),y=available.y(),width=available.width(),height=available.height()),
        fits=(button.minimumWidth() <= button.width() <= button.maximumWidth()
            and button.minimumHeight() <= button.height() <= button.maximumHeight()
            and button.height() == COMPLETION_SECONDARY_HEIGHT and 13 <= button.font().pixelSize() <= 16
            and text.width() <= available.width() and text.height() <= available.height()))


def start(window, output):
    from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Qt
    from PySide6.QtGui import QColor, QFontMetrics
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox, QPushButton, QWidget
    from .blank_project_audit import _capture
    from .build_identity import load_build_identity
    from .completion_export import CompletionExportDialog
    from .recognition_history import parse_recognition_report, RecognitionHistoryDetail
    from .recognition_outcome import normalize_recognition_outcome
    from .service import MediaResult, QueueResult, RunOptions
    from .studio_edit_sequence import projected_cues
    from .studio_project import load_project, parse_subtitle_timecode_ms
    from .theme_manager import apply_theme
    from .i18n import apply_ui_language, current_language, translate

    output = Path(output)
    inputs = json.loads((output/'input.json').read_text('utf8'))
    if inputs.get('summary_layout'):
        from .completion_summary_audit import start as summary_start
        return summary_start(window, output)
    report_path, project_path = Path(inputs['report']), Path(inputs['project'])
    report_bytes, project_bytes = report_path.read_bytes(), project_path.read_bytes()
    source_project_bytes = Path(inputs['source_project']).read_bytes()
    source_report_bytes = Path(inputs['source_report']).read_bytes()
    report = json.loads(report_bytes)
    retained_project = load_project(project_path)
    retained_cues = projected_cues(retained_project)
    cue_count = len(retained_cues)
    speaker_count = len({cue.speaker_id for cue in retained_cues})
    outcome = normalize_recognition_outcome(report)
    actual = MediaResult(media_path=report['media']['path'], status=report['status'],
        project_path=str(project_path), report_json_path=str(report_path),
        elapsed_seconds=float(report['result'].get('elapsed_seconds', 0)))
    retained = QueueResult((actual,), actual.elapsed_seconds)

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.started = time.monotonic()
            self.result = dict(passed=False, checks=[], screenshots=[], geometry=[], inputs=inputs,
                layout_contract='2026-10-05 updated request: 88% viewport width, actual navigation gap 24-32px, readable native fonts, shared three-column grid; prior contract retained in before snapshot',
                scope=inputs['verification_scope'], terminal_origin='Retained real report replay; no new ASR or provider request',
                identity=load_build_identity().to_dict(), executable=sys.executable, pid=os.getpid(),
                dpr=window.devicePixelRatioF(), requested_scale=inputs.get('requested_scale', '1'),
                geometry_unit='Qt logical pixels; native captures retain actual DPR', pixel_source='Whole-window native PrintWindow of normal production Qt app',
                real_outcome=asdict(outcome), entry='frozen' if getattr(sys, 'frozen', False) else 'quick_start.main')
            self.debug_stack_stream = (output/'audit-wait-stacks.log').open('w', encoding='utf8')
            faulthandler.dump_traceback_later(35, repeat=True, file=self.debug_stack_stream)
            self.steps = self.run()
            self.waiting = 0.
            self.deadline = self.started + 50
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(60)

        def check(self, name, value, detail=None):
            self.result['checks'].append(dict(name=name, passed=bool(value), detail=detail))
            self.write()
            if not value:
                raise AssertionError(name + ': ' + str(detail))

        def tick(self):
            try:
                if getattr(self, 'modal_error', ''):
                    raise RuntimeError(self.modal_error)
                modal = QApplication.activeModalWidget()
                if isinstance(modal, QMessageBox) and self.save_owned_modal(modal):
                    return
                if isinstance(modal, QMessageBox):
                    error = modal.text() + ' ' + modal.informativeText()
                    modal.reject()
                    raise RuntimeError(error)
                now = time.monotonic()
                if callable(self.waiting):
                    if not self.waiting():
                        if now > self.deadline:
                            raise TimeoutError('Completion GUI readiness timed out')
                        return
                elif now < self.waiting:
                    return
                step = next(self.steps)
                # A step may capture a whole window before its final click.
                # The yielded delay starts after that work, so native layout
                # settling always receives the intended post-action interval.
                after_step = time.monotonic()
                self.waiting = step if callable(step) else after_step + float(step)
                self.deadline = after_step + 50
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

        def shot(self, name, surface=None):
            name += '.png'
            self.result.setdefault('capture_context', []).append(dict(name=name,
                visible_top_levels=[dict(type=type(widget).__name__, object_name=widget.objectName()) for widget in QApplication.topLevelWidgets() if widget.isVisible()],
                visible_backdrops=[dict(parent_type=type(widget.parent()).__name__, object_name=widget.objectName()) for widget in window.findChildren(QWidget, 'modalBackdrop') if widget.isVisible()]))
            _capture(surface or window, output/name)
            self.result['screenshots'].append(name)

        def click(self, button):
            self.check('visible enabled action ' + button.text(), button.isVisible() and button.isEnabled())
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)

        def save_owned_modal(self, modal):
            button = modal.button(QMessageBox.StandardButton.Save)
            if button is None or not str(self.page.project_path):
                return False
            target = Path(self.page.project_path).resolve()
            if not target.is_relative_to(output.resolve()):
                return False
            self.result.setdefault('owned_save_dialogs', []).append(dict(message=modal.text(), project=str(target), scope='Only disposable audit output project'))
            self.write()
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            return True

        def close_save_dialog(self):
            modal = QApplication.activeModalWidget()
            if isinstance(modal, QMessageBox):
                self.save_owned_modal(modal)

        def queue_click(self, button):
            self.check('visible enabled queued action ' + button.text(), button.isVisible() and button.isEnabled())
            QTimer.singleShot(0, self.guarded_modal(lambda: QTest.mouseClick(button, Qt.MouseButton.LeftButton)))

        def complete(self, result):
            window._handle_result(result)
            dialog = getattr(window, '_completion_dialog', None)
            if dialog and dialog.isVisible():
                QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
            QApplication.processEvents()

        def notifications_closed(self):
            return not any(type(widget).__name__ == 'CompletionDialog' and widget.isVisible()
                           for widget in QApplication.topLevelWidgets())

        def guarded_modal(self, callback):
            def run():
                try:
                    callback()
                except Exception:
                    self.modal_error = traceback.format_exc()
                    for dialog in QApplication.topLevelWidgets():
                        if isinstance(dialog, QDialog) and dialog.isVisible():
                            dialog.reject()
            return run

        def ready(self):
            self.result['last_readiness'] = dict(ready=self.page._readiness.ready, active=self.page._readiness.active,
                project_state=str(self.page._project_view_state), project_path=str(self.page.project_path),
                profile=dict(self.page._readiness.profile))
            self.write()
            return bool(self.page.project is not None and self.page._readiness.ready
                        and not self.page._readiness.active and self.page._project_view_state == 'open')

        def box(self, widget, target):
            point = widget.mapTo(target, QPoint())
            return QRect(point.x(), point.y(), widget.width(), widget.height())

        def rect(self, value):
            return dict(x=value.x(), y=value.y(), width=value.width(), height=value.height())

        def layout_checks(self, phase, center_required=True):
            scroll = window.pages.widget(2)
            viewport = scroll.viewport()
            cards = window.result_action_grid.cards
            self.check(phase + ': exactly three visible primary cards', len(cards) == 3 and all(c.isVisible() for c in cards))
            self.check(phase + ': return is third full primary card', cards[2] is window.result_return_button)
            self.check(phase + ': equal readable card heights with font-aware minimum', len({c.height() for c in cards}) == 1
                and all(c.height() >= max(180, c.desired_height(c.width())) for c in cards))
            self.check(phase + ': common cards stay within target height unless measured copy requires more',
                all(c.height() <= max(210, max(card.desired_height(card.width()) for card in cards))
                    for c in cards),
                [dict(height=c.height(), copy_minimum=c.desired_height(c.width())) for c in cards])
            self.check(phase + ': equal widths', max(c.width() for c in cards)-min(c.width() for c in cards) <= 1)
            content_ratio = window.result_content.width()/max(1, viewport.width())
            self.check(phase + ': common desktop body occupies 85 to 90 percent or uses the ultrawide cap',
                .85 <= content_ratio <= .90 if viewport.width() <= 4000 else window.result_content.width() == 3400,
                dict(viewport=viewport.width(), content=window.result_content.width(), ratio=content_ratio))
            self.check(phase + ': no horizontal scrollbar', scroll.horizontalScrollBar().maximum() == 0,
                dict(maximum=scroll.horizontalScrollBar().maximum(), viewport_width=viewport.width(), page_width=scroll.widget().width(), content_width=window.result_content.width(), minimum_hint=window.result_content.minimumSizeHint().width()))
            self.check(phase + ': no duplicate small return button', sum(button.text() == window.result_return_button.text()
                for button in scroll.findChildren(QPushButton)) == 1)
            self.check(phase + ': no render operation on completion', not any('压制字幕视频' in button.text() or 'Burn subtitle' in button.text()
                for button in scroll.findChildren(QPushButton)) and not any('压制' in action.text() or 'Burn' in action.text()
                for action in window.result_more_menu.actions()))
            bounds = self.box(cards[0], viewport)
            for card in cards[1:]:
                bounds = bounds.united(self.box(card, viewport))
            ratio = (bounds.y()+bounds.height()/2) / max(1, viewport.height())
            geometry = dict(phase=phase, window=self.rect(window.rect()), viewport=self.rect(viewport.rect()),
                viewport_in_window=self.rect(self.box(viewport, window)), content=self.rect(self.box(window.result_content, viewport)),
                header_in_window=self.rect(self.box(window.app_header, window)),
                summary_in_window=self.rect(self.box(window.result_summary_card, window)),
                content_viewport_width_ratio=content_ratio,
                cards=[self.rect(self.box(c, viewport)) for c in cards], primary_union=self.rect(bounds),
                center_ratio=ratio, columns=window.result_action_grid.columns, dpr=window.devicePixelRatioF(),
                scroll_max=scroll.verticalScrollBar().maximum(), scroll_value=scroll.verticalScrollBar().value())
            geometry.update(self.measure_layout(viewport))
            self.result['geometry'].append(geometry)
            self.write()
            if center_required:
                self.check(phase + ': primary actions visible or reachable through natural short-window scrolling',
                    viewport.rect().contains(bounds) or scroll.verticalScrollBar().maximum() > 0, geometry)
            self.check(phase + ': details independently collapsed', not window.result_files_toggle.isChecked()
                and not window.result_log_toggle.isChecked() and window.result_files.isHidden() and window.result_console.isHidden())
            summary = self.box(window.result_title, viewport)
            files = self.box(window.result_files_toggle, viewport)
            log = self.box(window.result_log_toggle, viewport)
            self.check(phase + ': stacked full-width details under summary and above main actions',
                files.y() > summary.y() and files.bottom() < log.y() and log.bottom() < bounds.y(),
                dict(summary=self.rect(summary), files=self.rect(files), log=self.rect(log)))
            self.surface_checks(phase, geometry, bounds)
            self.balance_checks(phase, geometry, bounds, center_required)
            self.write()
            for card in cards:
                self.check(phase + ': keyboard focus enabled ' + card.text(), card.focusPolicy() == Qt.FocusPolicy.StrongFocus)
                title_font = card.title_font()
                text_flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap)
                icon_rect, title_rect, description_rect = (rect.toRect() for rect in card.content_rects())
                title_bounds = QFontMetrics(title_font).boundingRect(title_rect, text_flags, card.text())
                description_font = card.description_font()
                description = translate(card.description, current_language())
                description_bounds = QFontMetrics(description_font).boundingRect(description_rect,
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap), description)
                self.check(phase + ': card title and description fit without clipping ' + card.text(),
                    title_bounds.height() <= title_rect.height() and description_bounds.height() <= description_rect.height()
                    and all(card.rect().contains(rect) for rect in (icon_rect,title_rect,description_rect))
                    and icon_rect.bottom() < title_rect.top() and title_rect.bottom() < description_rect.top(),
                    dict(title_height=title_bounds.height(), description_height=description_bounds.height(),
                        icon_rect=self.rect(icon_rect), title_rect=self.rect(title_rect), description_rect=self.rect(description_rect),
                        title_font_pixels=title_font.pixelSize(), description_font_pixels=description_font.pixelSize()))
                self.check(phase + ': readable main card title and body fonts ' + card.text(),
                    28 <= title_font.pixelSize() <= 32 and 15 <= description_font.pixelSize() <= 17)
                self.check(phase + ': enlarged card group is centered ' + card.text(),
                    abs(icon_rect.center().x()-card.rect().center().x()) <= 1
                    and abs((icon_rect.top()+description_rect.bottom())/2-card.rect().center().y()) <= 1,
                    dict(icon=self.rect(icon_rect), description=self.rect(description_rect)))
                if card.isEnabled():
                    image = card.grab().toImage()
                    color = image.pixelColor(round((card.width()-25)*card.devicePixelRatioF()), round((card.height()-25)*card.devicePixelRatioF()))
                    colors = (card._theme.accent, card._theme.accent_hover, card._theme.accent_pressed)
                    self.check(phase + ': equal theme emphasis ' + card.text(), color in [QColor(c) for c in colors], color.name())
            secondary = window.result_secondary_bar.buttons
            for button in secondary:
                if button.isVisible():
                    self.check(phase + ': readable secondary click target ' + button.text(), 48 <= button.height() <= 56
                        and 15 <= button.font().pixelSize() <= 17
                        and button.fontMetrics().horizontalAdvance(button.text())+40 <= button.width(),
                        dict(width=button.width(), height=button.height(), text_width=button.fontMetrics().horizontalAdvance(button.text())))

        def measure_layout(self, viewport):
            """Record all surfaces before strict gates can stop a tight layout."""
            def measured(widget):
                value = dict(type=type(widget).__name__, name=widget.objectName(),
                    visible=widget.isVisible(), bounds=self.rect(self.box(widget,viewport)),
                    contents=self.rect(widget.contentsRect()), minimum_width=widget.minimumWidth(),
                    maximum_width=widget.maximumWidth(), minimum_height=widget.minimumHeight(),
                    maximum_height=widget.maximumHeight(), radius=widget.property('completionRadius'),
                    font_pixels=widget.font().pixelSize(), font_points=widget.font().pointSizeF(),
                    font_height=widget.fontMetrics().height())
                if hasattr(widget,'text'):
                    value['text'] = widget.text()
                return value
            labels = {}
            for name in ('result_title','result_summary','result_single_filename','result_task_selector',
                         'result_review_status','result_review_summary','result_exception_summary','result_task_summary'):
                widget = getattr(window,name)
                value = measured(widget)
                if hasattr(widget,'text') and widget.text():
                    value['text_bounds'] = self.rect(widget.fontMetrics().boundingRect(widget.contentsRect(),
                        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),widget.text()))
                labels[name] = value
            headers = []
            for header in (window.result_files_toggle,window.result_log_toggle):
                value = measured(header)
                title,arrow = (rect.toRect() for rect in header.content_rects())
                value.update(title=self.rect(title),arrow=self.rect(arrow),arrow_type=header.arrowType().name,
                    text_bounds=self.rect(header.fontMetrics().boundingRect(title,
                        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine),header.text())))
                headers.append(value)
            summary_layout = window.result_summary_card.layout()
            margins = summary_layout.contentsMargins()
            group = window.result_secondary_bar
            return dict(measured_before_center_gate=True,summary=self.rect(self.box(window.result_summary_card,viewport)),
                summary_frame=measured(window.result_summary_card),summary_labels=labels,
                measured_primary=[dict(bounds=self.rect(self.box(card,viewport)), text=card.text(),
                    title_font_pixels=card.title_font().pixelSize(), body_font_pixels=card.description_font().pixelSize(),
                    content_rects=[self.rect(rect.toRect()) for rect in card.content_rects()],
                    desired_height=card.desired_height(card.width())) for card in window.result_action_grid.cards],
                summary_layout=dict(margins=dict(left=margins.left(),top=margins.top(),right=margins.right(),bottom=margins.bottom()),
                    spacing=summary_layout.spacing(),copy_spacing=window.result_content._summary_copy.spacing()),
                measured_headers=headers,measured_bodies=[measured(window.result_files),measured(window.result_console)],
                measured_secondary=[measured(button) for button in group.buttons],
                secondary_bar=dict(bounds=self.rect(self.box(group,viewport)),columns=group._columns,
                    horizontal_spacing=group.grid.horizontalSpacing(),vertical_spacing=group.grid.verticalSpacing()))

        def surface_checks(self, phase, geometry, primary):
            from .completion_widgets import COMPLETION_RADIUS_MAIN, COMPLETION_RADIUS_SMALL, CompletionAccordionHeader, CompletionInfoPanel
            viewport = window.pages.widget(2).viewport()
            content = self.box(window.result_content, viewport)
            headers = (window.result_files_toggle, window.result_log_toggle)
            surfaces = (window.result_summary_card, *headers, *window.result_action_grid.cards)
            self.check(phase + ': all main surfaces share the rendering radius',
                COMPLETION_RADIUS_MAIN == 12 and all(widget.property('completionRadius') == COMPLETION_RADIUS_MAIN for widget in surfaces),
                [dict(type=type(widget).__name__, radius=widget.property('completionRadius')) for widget in surfaces])
            self.check(phase + ': exactly two production accordion headers',
                all(isinstance(header, CompletionAccordionHeader) for header in headers)
                and len(window.result_content.findChildren(CompletionAccordionHeader)) == 2)
            fold_geometry = []
            for header in headers:
                bounds = self.box(header, viewport)
                panel = window.result_files_panel if header is window.result_files_toggle else window.result_log_panel
                panel_bounds = self.box(panel, viewport)
                margins = panel.layout_box.contentsMargins()
                contract = completion_panel_geometry(self.rect(panel_bounds), self.rect(bounds), self.rect(content),
                    (margins.left(), margins.top(), margins.right(), margins.bottom()))
                title, arrow = (rect.toRect() for rect in header.content_rects())
                text_bounds = header.fontMetrics().boundingRect(title,
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine), header.text())
                self.check(phase + ': disclosure outer panel owns full row and header respects exact 1px border ' + header.text(),
                    isinstance(panel, CompletionInfoPanel) and header.parentWidget() is panel
                    and contract['designed_panel_contract'] and 46 <= header.height() <= 54, contract)
                self.check(phase + ': disclosure title left arrow right and text fits ' + header.text(),
                    header.rect().contains(title) and header.rect().contains(arrow)
                    and title.x() >= 14 and title.right()+8 < arrow.left() and arrow.right() >= header.width()-32
                    and text_bounds.width() <= title.width() and text_bounds.height() <= title.height(),
                    dict(title=self.rect(title), arrow=self.rect(arrow), text=self.rect(text_bounds)))
                self.check(phase + ': disclosure keyboard and collapsed arrow ' + header.text(),
                    header.focusPolicy() in (Qt.FocusPolicy.TabFocus, Qt.FocusPolicy.StrongFocus, Qt.FocusPolicy.WheelFocus) and header.arrowType() == Qt.ArrowType.RightArrow)
                fold_geometry.append(dict(bounds=self.rect(bounds), title=self.rect(title), arrow=self.rect(arrow), panel_contract=contract))
            summary = window.result_summary_card
            self.check(phase + ': summary title and body retain readable font sizes',
                28 <= window.result_title.font().pixelSize() <= 32 and 14 <= window.result_summary.font().pixelSize() <= 16)
            for label in (window.result_title, window.result_summary, window.result_exception_summary, window.result_task_summary):
                if label.isVisible() and label.text():
                    available = label.contentsRect()
                    required = label.fontMetrics().boundingRect(available,
                        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap), label.text())
                    self.check(phase + ': summary copy fits its real logical text rectangle ' + label.text()[:24],
                        required.height() <= available.height() and required.width() <= available.width(),
                        dict(available=self.rect(available), required=self.rect(required)))
            visible = [button for button in window.result_secondary_bar.buttons if button.isVisible()]
            status = [window.result_review_status] if window.result_review_status.isVisible() else []
            self.check(phase + ': secondary actions and status use smaller rendering radius',
                COMPLETION_RADIUS_SMALL == 8 and COMPLETION_RADIUS_SMALL < COMPLETION_RADIUS_MAIN
                and all(button.property('completionRadius') == COMPLETION_RADIUS_SMALL for button in visible+status),
                [dict(text=button.text(), radius=button.property('completionRadius')) for button in visible+status])
            rows = []
            for button in sorted(visible, key=lambda button:(self.box(button,viewport).y(),self.box(button,viewport).x())):
                rect = self.box(button, viewport)
                if rows and abs(rows[-1][0].y()-rect.y()) <= 2:
                    rows[-1].append(rect)
                else:
                    rows.append([rect])
            secondary = QRect()
            for row in rows:
                row_bounds = row[0]
                for rect in row[1:]: row_bounds = row_bounds.united(rect)
                secondary = secondary.united(row_bounds)
                for left, right in zip(row, row[1:]):
                    gap = right.x()-left.right()-1
                    self.check(phase + ': secondary horizontal edge gap follows the 18-pixel gutter', gap == 18,
                        dict(gap=gap, left=self.rect(left), right=self.rect(right)))
            self.check(phase + ': secondary group has usable visible targets', bool(visible))
            vertical_gap = secondary.y()-primary.bottom()-1
            self.check(phase + ': primary to secondary edge gap is 16 logical pixels', vertical_gap == 16,
                dict(gap=vertical_gap, primary=self.rect(primary), secondary=self.rect(secondary)))
            self.check(phase + ': primary and supporting operations use the same production grid',
                window.result_secondary_layout is window.result_action_grid.grid)
            if window.result_secondary_bar._columns == 1:
                self.check(phase + ': narrow secondary controls occupy one full-width column',
                    len(rows) == len(visible) and all(len(row) == 1 for row in rows), [list(map(self.rect,row)) for row in rows])
                if len(rows) > 1:
                    self.result.setdefault('secondary_wrap_evidence', []).append(dict(phase=phase,
                        row_count=len(rows), bar_width=window.result_secondary_bar.width(), dpr=window.devicePixelRatioF()))
            else:
                expected_rows = 2 if window.retry_failed_button.isVisible() else 1
                self.check(phase + ': three supporting columns plus an optional separate retry row', len(rows) == expected_rows)
            aligned = window.result_action_grid.secondary_actions
            for card, button in zip(window.result_action_grid.cards, aligned):
                if button.isVisible():
                    card_rect, button_rect = self.box(card,viewport), self.box(button,viewport)
                    self.check(phase + ': same-column left and right edges agree ' + button.text(),
                        abs(card_rect.x()-button_rect.x()) <= 1 and abs(card_rect.width()-button_rect.width()) <= 1,
                        dict(primary=self.rect(card_rect), secondary=self.rect(button_rect)))
            widths = [button.width() for button in aligned if button.isVisible()]
            heights = [button.height() for button in visible]
            self.check(phase + ': secondary buttons use equal flexible columns and equal 52-pixel heights',
                max(widths)-min(widths) <= 1 and all(value == 52 for value in heights),
                dict(widths=widths, heights=heights))
            # Theme/i18n polish may reduce the minimum to 50 while actual and
            # maximum stay 52. Only the painted geometry and valid constraints
            # are a product contract; min == max is not required.
            measured_controls = [secondary_control_measurement(button) for button in visible]
            self.check(phase + ': actual secondary text geometry and legal constraints fit their shared column',
                all(row['fits'] for row in measured_controls), measured_controls)
            title, arrow = window.result_more_button.content_rects()
            self.check(phase + ': more popup arrow is centered vertically',
                abs(arrow.center().y()-window.result_more_button.height()/2) <= 1)
            self.check(phase + ': both operation rows share 18-pixel columns and 16-pixel rows',
                window.result_secondary_bar.grid.horizontalSpacing() == 18 and window.result_secondary_bar.grid.verticalSpacing() == 16)
            geometry.update(summary=self.rect(self.box(summary,viewport)), folds=fold_geometry,
                secondary=self.rect(secondary), secondary_rows=[list(map(self.rect,row)) for row in rows],
                primary_secondary_gap=vertical_gap, main_radius=COMPLETION_RADIUS_MAIN, small_radius=COMPLETION_RADIUS_SMALL)

        def balance_checks(self, phase, geometry, primary, center_required):
            """Measure top padding and compact row gaps; spare room belongs below."""
            viewport = window.pages.widget(2).viewport()
            body = self.box(window.result_summary_card, viewport)
            for widget in (window.result_files_toggle, window.result_log_toggle,
                           *window.result_action_grid.cards, *window.result_secondary_bar.buttons):
                if widget.isVisible():
                    body = body.united(self.box(widget, viewport))
            height = max(1,viewport.height())
            center = (body.y()+body.height()/2)/height
            top_blank = body.y()
            bottom_blank = height-body.y()-body.height()
            header = self.box(window.app_header, window)
            summary_window = self.box(window.result_summary_card, window)
            navigation_gap = summary_window.y()-header.bottom()-1
            geometry.update(body=self.rect(body), body_center_ratio=center, navigation_gap=navigation_gap,
                top_blank=top_blank, bottom_blank=bottom_blank,
                body_viewport_height=height, secondary_column_count=window.result_secondary_bar._columns)
            if center_required:
                self.check(phase + ': actual navigation bottom to summary top is 24 to 32 logical pixels',
                    24 <= navigation_gap <= 32, dict(header=self.rect(header), summary=self.rect(summary_window), gap=navigation_gap))
                self.check(phase + ': collapsed body is visible or naturally scrollable without reducing fonts',
                    (viewport.rect().contains(body) and bottom_blank >= 0) or window.pages.widget(2).verticalScrollBar().maximum() > 0,
                    dict(top_blank=top_blank,bottom_blank=bottom_blank))
                self.check(phase + ': internal disclosure-to-card group remains a compact 12 logical pixels',
                    primary.y()-self.box(window.result_log_toggle,viewport).bottom()-1 == 12)
            if phase in ('real-normal','real-maximized') and inputs.get('layout_baseline'):
                baseline = inputs.get('layout_baseline') or {}
                scale = str(inputs.get('requested_scale','1'))
                stored = (baseline.get('scales') or {}).get(scale) or {}
                previous_geometry = stored.get('geometry') or baseline.get('geometry') or []
                old = next((row for row in previous_geometry if row['phase'] == phase), None)
                self.check(phase + ': before comparison uses the same logical window and actual DPR',
                    old is not None and (stored.get('dpr') or baseline.get('dpr')) == window.devicePixelRatioF()
                    and old['window'] == geometry['window'],
                    dict(before_viewport=old.get('viewport') if old else None, after_viewport=geometry['viewport'],
                        intentional_change='Completion parent top margin 12px removed; viewport height can increase by 12px'))
                before_top = (old.get('body') or old.get('summary'))['y']
                old_header = old.get('header_in_window') or geometry['header_in_window']
                before_gap = old.get('navigation_gap', old['viewport_in_window']['y'] + before_top
                    - old_header['y'] - old_header['height'])
                geometry.update(before_top_blank=before_top, before_navigation_gap=before_gap,
                    navigation_gap_reduction=before_gap-navigation_gap,
                    before_header_scope='Recorded before header' if old.get('header_in_window') else 'Same unchanged header measured in after window; old audit recorded viewport and summary offsets')
                self.check(phase + ': actual navigation whitespace follows the updated range against the same before window',
                    24 <= navigation_gap <= 32 and navigation_gap <= before_gap,
                    dict(before_navigation_gap=before_gap, after_navigation_gap=navigation_gap,
                        before_viewport_top=before_top, after_viewport_top=top_blank))
            if phase in ('language-en','language-ja','language-zh','maximized-en','maximized-ja','maximized-zh'):
                key = 'maximized' if phase.startswith('maximized') else 'normal'
                outline = [dict(x=self.box(button,viewport).x(),width=button.width(),height=button.height())
                    for button in window.result_secondary_bar.buttons if button.isVisible()]
                if not hasattr(self,'language_outlines'):self.language_outlines = {}
                before = self.language_outlines.setdefault(key,dict(viewport_width=viewport.width(),outline=outline))
                # Wrapped summary copy can introduce a vertical scrollbar. The
                # contract is equal main/support columns within each language;
                # never shrink fonts to keep an identical scrollbar-free box.
                self.check(phase + ': translated operations keep the same equal-column structure',
                    window.result_action_grid.columns == 3 and (before['viewport_width'] != viewport.width()
                        or outline == before['outline']), dict(before=before,after=outline,viewport_width=viewport.width()))

        def layout_snapshot(self):
            """Content-relative controls separate true drift from scrollbar motion."""
            widgets = (window.result_summary_card, window.result_files_toggle, window.result_log_toggle,
                *window.result_action_grid.cards, *window.result_secondary_bar.buttons)
            return [dict(name=widget.objectName(), type=type(widget).__name__,
                geometry=self.rect(self.box(widget, window.result_content))) for widget in widgets if widget.isVisible()]

        def fold_cycles(self, phase, count=3):
            baseline = self.layout_snapshot()
            scroll = window.pages.widget(2)
            for cycle in range(count):
                self.click(window.result_files_toggle)
                yield .15
                self.check(phase + ': output header owns expanded body ' + str(cycle), window.result_files.isVisible()
                    and window.result_files.height() <= 210 and window.result_files_toggle.arrowType() == Qt.ArrowType.DownArrow
                    and self.box(window.result_files,window.result_content).y() > self.box(window.result_files_toggle,window.result_content).bottom()
                    and self.box(window.result_files,window.result_content).bottom() < self.box(window.result_log_toggle,window.result_content).y())
                # Scrolling the page is allowed during expansion; a control is
                # brought back into view before native clicking it.
                scroll.ensureWidgetVisible(window.result_log_toggle)
                yield .1
                self.click(window.result_log_toggle)
                yield .2
                self.check(phase + ': log header owns expanded body ' + str(cycle), window.result_console.isVisible()
                    and window.result_console.height() <= 230 and window.result_log_toggle.arrowType() == Qt.ArrowType.DownArrow
                    and self.box(window.result_console,window.result_content).y() > self.box(window.result_log_toggle,window.result_content).bottom())
                if cycle == 0:
                    self.shot(phase+'-expanded-whole-window')
                self.click(window.result_log_toggle)
                scroll.ensureWidgetVisible(window.result_files_toggle)
                yield .1
                self.click(window.result_files_toggle)
                scroll.verticalScrollBar().setValue(0)
                yield .2
                current = self.layout_snapshot()
                self.check(phase + ': collapse releases both bodies and preserves all layout rectangles ' + str(cycle),
                    window.result_files.isHidden() and window.result_console.isHidden() and current == baseline,
                    dict(before=baseline, after=current))

        def keyboard_checks(self, phase):
            cards = window.result_action_grid.cards
            for index, card in enumerate(cards):
                card.setFocus(Qt.FocusReason.TabFocusReason)
                self.check(phase + ': keyboard reaches primary card ' + str(index), card.hasFocus())
                if index < len(cards)-1:
                    QTest.keyClick(card, Qt.Key.Key_Tab)
                    self.check(phase + ': Tab traverses to next primary card ' + str(index), cards[index+1].hasFocus())
            window.export_result_button.setFocus(Qt.FocusReason.TabFocusReason)

        def state_agreement(self, state_path, expected, phase):
            record = parse_recognition_report(state_path)
            self.check(phase + ': history and shared outcome agree', record.status == expected.core_status
                and record.outcome.core_status == expected.core_status, dict(record=record.status, outcome=expected.core_status))
            self.check(phase + ': completion title agrees with shared outcome', window.result_title.text() == expected.title,
                dict(actual=window.result_title.text(), expected=expected.title))
            self.result.setdefault('state_agreement', []).append(dict(phase=phase, report=str(state_path),
                history=record.status, completion=window.result_title.text(), normalized=asdict(expected)))

        def synthetic(self, folder, name, *, status='success', quality=False, partial=False, usable=True, save_failed=False):
            payload = copy.deepcopy(report)
            payload['status'] = status
            payload['started_at'] = '2026-10-04T00:00:00+08:00'
            payload['events'] = []
            payload['stages'] = []
            payload['review_items'] = copy.deepcopy(report.get('review_items', [])) if quality else []
            payload['review_severity_counts'] = dict(error=0, warning=1 if quality else 0, review=10 if quality else 0)
            payload['review_summary'] = report.get('review_summary', {}) if quality else {}
            payload.setdefault('settings', {})['config_warnings'] = []
            payload['result']['cue_count'] = cue_count if usable else 0
            payload['result']['outputs'] = {'project': str(project_path) if usable else '', 'txt': ''}
            payload['polishing_summary'] = dict(success_batches=1, fallback_batches=1 if partial else 0,
                success_cues=22 if partial else outcome.processed_records, fallback_cues=9 if partial else 0,
                failure_categories={'timeout': 9} if partial else {}, term_context={'accepted_edits': outcome.accepted_edits})
            payload['terminology_summary'] = dict(status='disabled', verified_count=0, unverified_count=0)
            if save_failed:
                payload['events'].append(dict(event='studio_project_save_failed', error='UI coverage: project save failed'))
            path = folder/(name+'.json')
            path.write_text(json.dumps(payload, ensure_ascii=False), 'utf8')
            item = replace(actual, status=status, report_json_path=str(path), project_path=str(project_path) if usable else '',
                error='UI coverage: project save failed' if save_failed else 'UI coverage: core recognition failed' if status == 'failed' else '')
            return payload, path, item

        def srt_rows(self, path):
            rows = []
            for block in re.split(r'\n\s*\n', path.read_text('utf-8-sig').strip()):
                lines = block.splitlines()
                self.check('exported SRT has ordinal and timestamp', len(lines) >= 3 and '-->' in lines[1], path.name)
                start, end = lines[1].split('-->', 1)
                rows.append((parse_subtitle_timecode_ms(start.strip()), parse_subtitle_timecode_ms(end.strip()), '\n'.join(lines[2:])))
            return rows

        def run(self):
            available = window.screen().availableGeometry()
            normal_width, normal_height = min(1320, available.width()-30), min(850, available.height()-30)
            window.resize(normal_width, normal_height)
            apply_theme('grape')
            apply_ui_language(window, 'zh')
            log_path = report_path.parent/'retained-run.log'
            for line in log_path.read_text('utf8', errors='replace').splitlines() if log_path.is_file() else ['Retained task replay; no new ASR/provider request.']:
                window._append_console_line(line)
            self.complete(retained)
            yield self.notifications_closed
            yield .15
            self.layout_checks('real-normal')
            normal_grid_width = window.result_action_grid.width()
            normal_columns = window.result_action_grid.columns
            normal_action_widths = [button.width() for button in window.result_action_grid.secondary_actions]
            window.resize(max(740, normal_width-160), normal_height)
            yield .2
            self.layout_checks('real-resized', center_required=window.result_action_grid.columns == 3)
            resized_widths = [button.width() for button in window.result_action_grid.secondary_actions]
            self.check('real resize changes operation widths through the shared responsive grid',
                window.result_action_grid.width() < normal_grid_width
                and (window.result_action_grid.columns != normal_columns
                    or all(after < before for before, after in zip(normal_action_widths, resized_widths))),
                dict(before_grid_width=normal_grid_width, after_grid_width=window.result_action_grid.width(),
                    before_columns=normal_columns, after_columns=window.result_action_grid.columns,
                    before_widths=normal_action_widths, after_widths=resized_widths))
            window.resize(normal_width, normal_height)
            yield .2
            self.check('restoring the normal window restores shared operation widths',
                [button.width() for button in window.result_action_grid.secondary_actions] == normal_action_widths)
            self.state_agreement(report_path, outcome, 'real-report')
            self.check('real source count matches project', outcome.final_cues == cue_count)
            rendered = window._completion_task_evidence[window._completion_task_key(actual)]['outcome']
            count_fields = ('processed_records', 'final_cues', 'accepted_edits', 'fallback_records', 'review_issue_count')
            self.check('real retained counts follow this input report rather than a fixed historical task',
                all(getattr(rendered, key) == getattr(outcome, key) for key in count_fields),
                dict(source={key:getattr(outcome,key) for key in count_fields}, rendered={key:getattr(rendered,key) for key in count_fields}))
            self.check('real core proofread and search states follow this input report',
                (rendered.core_status, rendered.polish_status, rendered.search_status) ==
                (outcome.core_status, outcome.polish_status, outcome.search_status), asdict(rendered))
            expected_retry = bool((outcome.polish_retryable or outcome.search_retryable or outcome.core_status == 'failed')
                and getattr(window, '_last_run_options', None))
            self.check('real retry visibility follows report retryability and available run options',
                window.retry_failed_button.isVisible() == expected_retry)
            self.check('real review visibility outside collapsed logs follows actual review count',
                window.result_review_status.isVisible() == outcome.has_review)
            self.check('completion summary retains actual accepted edit and subtitle counts',
                f'采纳 {outcome.accepted_edits} 处文字修改' in window.result_summary.text()
                and f'{outcome.final_cues} 条字幕' in window.result_summary.text(), window.result_summary.text())
            self.check('single input uses concise filename with full tooltip', window.result_single_filename.isVisible()
                and not window.result_task_selector.isVisible() and Path(actual.media_path).name in window.result_single_filename.toolTip())
            self.shot('01-real-completion-whole-window')
            # The normal history page and its normal detail dialog retain the same core conclusion.
            history = window.history_page
            history.report_root = report_path.parent
            history.extra_roots = []
            history._record_cache.clear()
            history.refresh()
            window._switch_page(history)
            yield .3
            record = next(row for row in history.records if row.path.resolve() == report_path.resolve())
            self.check('real history card keeps report result and true quality counts', record.status == outcome.core_status
                and record.outcome.severity_count('error') == outcome.severity_count('error')
                and record.outcome.review_issue_count == outcome.review_issue_count)
            self.shot('01c-real-history-whole-window')
            isolated_payload = copy.deepcopy(record.payload)
            isolated_payload['result']['outputs']['project'] = str(project_path)
            isolated_record = replace(record, payload=isolated_payload)
            def history_modal():
                dialog = next((w for w in QApplication.topLevelWidgets() if w.isVisible() and w.findChild(RecognitionHistoryDetail)), None)
                detail = dialog.findChild(RecognitionHistoryDetail) if dialog else None
                self.check('real history detail separates core, proofread and search status', detail is not None
                    and detail.record.outcome.core_status == outcome.core_status and detail.record.outcome.polish_status == outcome.polish_status
                    and detail.record.outcome.search_status == outcome.search_status)
                self.shot('01d-real-history-detail-whole-dialog', dialog)
                self.click(detail.open_result_button)
            self.timer.stop(); QTimer.singleShot(350, self.guarded_modal(history_modal))
            try:
                history._show_detail(isolated_record)
            finally:
                self.timer.start(60)
            dialog = getattr(window, '_completion_dialog', None)
            if dialog and dialog.isVisible():QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
            yield self.notifications_closed
            yield .15
            self.check('history detail opens completion through normal result callback', window.pages.currentIndex() == 2
                and Path(window._last_studio_project).resolve() == project_path.resolve())
            self.state_agreement(report_path, outcome, 'real-history-reopened-completion')
            window.export_result_button.setFocus()
            yield .15
            self.check('whole-card keyboard focus reaches export', window.export_result_button.hasFocus())
            self.shot('01b-keyboard-focus')
            window.showMaximized()
            yield .4
            self.layout_checks('real-maximized')
            self.shot('02-maximized-whole-window')
            window.showNormal()
            window.resize(normal_width, normal_height)
            yield .25
            base_geometry = [self.rect(self.box(c, window.pages.widget(2).viewport())) for c in window.result_action_grid.cards]
            self.click(window.result_files_toggle)
            yield .2
            self.check('task output expands with bounded scrolling', window.result_files.isVisible() and window.result_files.height() <= 210)
            self.check('details preserve distinct real statistical units', all(str(value) in window.result_files.toPlainText()
                for value in (outcome.processed_records, outcome.final_cues, outcome.accepted_edits)))
            self.check('details retain optional search reason', outcome.search_reason in window.result_files.toPlainText())
            self.click(window.result_log_toggle)
            yield .4
            self.check('logs remain saved and readable in bounded region', window.result_console.isVisible() and window.result_console.height() <= 230
                and bool(window.result_console.toPlainText()) and bool(window._completion_log_lines))
            from PySide6.QtGui import QPalette
            block = window.result_console.document().begin()
            fragment = block.begin().fragment()
            foreground = fragment.charFormat().foreground().color()
            background = window.result_console.palette().color(QPalette.ColorRole.Base)
            def luminance(color):
                channels = (color.redF(), color.greenF(), color.blueF())
                linear = tuple(value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in channels)
                return sum(weight * value for weight, value in zip((.2126, .7152, .0722), linear))
            light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
            contrast = (light + .05) / (dark + .05)
            self.check('real history log body contrast is readable', foreground.isValid() and contrast >= 4.5,
                dict(foreground=foreground.name(), background=background.name(), contrast=contrast))
            self.shot('03-details-and-log-expanded-whole-window')
            for cycle in range(3):
                self.click(window.result_files_toggle); self.click(window.result_log_toggle)
                yield .2
                self.check('collapse releases space without persistent layout drift ' + str(cycle),
                    [self.rect(self.box(c, window.pages.widget(2).viewport())) for c in window.result_action_grid.cards] == base_geometry)
                if cycle < 2:
                    self.click(window.result_files_toggle); self.click(window.result_log_toggle)
                    yield .2
            self.layout_checks('after-three-expansion-cycles')
            window.resize(740, min(620, normal_height))
            yield .3
            self.layout_checks('narrow-low-window', center_required=False)
            scroll = window.pages.widget(2)
            self.check('narrow cards wrap without tiny text', window.result_action_grid.columns == 1 and all(c.width() >= 500 for c in window.result_action_grid.cards))
            self.check('narrow low height scrolls naturally', scroll.verticalScrollBar().maximum() > 0)
            self.shot('04-narrow-top-whole-window')
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
            yield .2
            viewport = scroll.viewport()
            self.check('narrow third action can be scrolled into view', viewport.rect().intersects(self.box(window.result_return_button, viewport)))
            self.check('narrow secondary controls remain fully reachable by natural scroll',
                all(viewport.rect().contains(self.box(button,viewport)) for button in window.result_secondary_bar.buttons if button.isVisible()))
            self.shot('04b-narrow-bottom-whole-window')
            scroll.verticalScrollBar().setValue(0)
            window.resize(normal_width, normal_height)
            yield .25
            static_copy = []
            for index, card in enumerate(window.result_action_grid.cards):
                static_copy.append(('primary title ' + str(index), str(card.property('i18nText')), lambda card=card:card.text()))
                static_copy.append(('primary description ' + str(index), card.description,
                                    lambda card=card:translate(card.description, current_language())))
            for button in (window.open_priority_review_button, window.repolish_current_glossary_button,
                           window.result_more_button, window.result_files_toggle, window.result_log_toggle):
                static_copy.append(('secondary or disclosure', button.text(), lambda button=button:button.text()))
            static_copy.append(('current glossary tooltip', window.repolish_current_glossary_button.toolTip(),
                                lambda:window.repolish_current_glossary_button.toolTip()))
            for action in window.result_more_menu.actions():
                if not action.isSeparator():
                    static_copy.append(('completion menu', action.text(), lambda action=action:action.text()))
            for language in ('en', 'ja', 'zh'):
                window.language_combo.setCurrentIndex(window.language_combo.findData(language))
                window._apply_ui_language()
                yield .2
                self.keyboard_checks('language-normal-' + language)
                self.layout_checks('language-' + language)
                if language != 'zh':
                    for role, raw, read_actual in static_copy:
                        expected = translate(raw, language)
                        self.check('language-' + language + ': static copy translated ' + role + ' ' + raw,
                            bool(raw) and expected != raw and read_actual() == expected,
                            dict(raw=raw, actual=read_actual(), expected=expected))
                self.shot('05-language-' + language + '-whole-window')
                if language != 'zh':
                    language_geometry = [self.rect(self.box(c, window.pages.widget(2).viewport())) for c in window.result_action_grid.cards]
                    self.click(window.result_files_toggle); yield .2
                    evidence = window._completion_task_evidence[window._completion_task_key(window._completion_tasks[0][0])]
                    plain = window.result_files.toPlainText()
                    for label, target in evidence.get('path_entries', ()):
                        expected_label = translate(label, language)
                        valid_unchanged = language == 'ja' and label == '字幕'
                        self.check('language-' + language + ': output path prefix follows current language ' + label,
                            (expected_label != label or valid_unchanged) and expected_label + '：' + str(target) in plain,
                            dict(label=label, expected=expected_label))
                    self.shot('05b-language-' + language + '-details-whole-window')
                    self.click(window.result_files_toggle); yield .2
                    self.check('language-' + language + ': translated details collapse restores geometry',
                        [self.rect(self.box(c, window.pages.widget(2).viewport())) for c in window.result_action_grid.cards] == language_geometry)
                    window.pages.widget(2).verticalScrollBar().setValue(0)
                yield from self.fold_cycles('normal-'+language)
                self.layout_checks('normal-'+language+'-after-fold-cycles')
                self.shot('normal-'+language+'-collapsed-whole-window')
                window.showMaximized()
                yield .3
                self.keyboard_checks('language-maximized-'+language)
                self.layout_checks('maximized-'+language)
                self.shot('maximized-'+language+'-collapsed-whole-window')
                yield from self.fold_cycles('maximized-'+language)
                self.layout_checks('maximized-'+language+'-after-fold-cycles')
                window.showNormal()
                window.resize(normal_width,normal_height)
                yield .25
            # The real card opens the real exporter, producing actual SRT output.
            export_dir = output/'exports'; export_dir.mkdir()
            old_picker = QFileDialog.getExistingDirectory
            QFileDialog.getExistingDirectory = lambda *args, **kwargs: str(export_dir)
            def export_modal():
                dialog = QApplication.activeModalWidget()
                self.check('primary export opens production dialog for retained project', isinstance(dialog, CompletionExportDialog)
                    and dialog.project.project_id == retained_project.project_id)
                dialog.mode.setCurrentIndex(dialog.mode.findData('both'))
                dialog._export(); self.export_artifacts = dialog.artifacts
            self.timer.stop(); QTimer.singleShot(220, self.guarded_modal(export_modal))
            try:
                self.click(window.export_result_button)
            finally:
                QFileDialog.getExistingDirectory = old_picker; self.timer.start(60)
            yield .15
            self.check('real export creates combined and speaker SRTs', len(list(export_dir.glob('*.srt'))) == speaker_count+1)
            for artifact in self.export_artifacts:
                expected = sorted((c for c in retained_cues if not artifact.speaker_id or c.speaker_id == artifact.speaker_id), key=lambda c:(c.start_ms,c.end_ms,c.id))
                self.check('real SRT preserves text and timeline ' + artifact.path.name, self.srt_rows(artifact.path) ==
                    [(c.start_ms,c.end_ms,c.text.replace('\r\n','\n').replace('\r','\n')) for c in expected])
            self.queue_click(window.open_studio_result_button)
            yield self.ready
            self.check('Studio card opens correct saved project', Path(self.page.project_path).resolve() == project_path.resolve()
                and len(projected_cues(self.page.project)) == cue_count)
            window._switch_page(2)
            yield .25
            # UI state coverage uses report copies and never changes the real evidence.
            states = output/'ui-state-coverage'; states.mkdir()
            for name, kwargs in (('normal-completed', {}), ('quality-warning', {'quality':True}),
                    ('partial-ai-proofread', {'partial':True}), ('partial-ai-proofread-with-warning', {'partial':True,'quality':True}), ('core-failed', {'status':'failed','usable':False}),
                    ('save-failed', {'status':'failed','usable':False,'save_failed':True}),
                    ('cancelled', {'status':'cancelled','usable':False})):
                payload, path, item = self.synthetic(states, name, **kwargs)
                expected = normalize_recognition_outcome(payload)
                self.complete(QueueResult((item,), actual.elapsed_seconds))
                yield self.notifications_closed
                yield .15
                self.state_agreement(path, expected, name)
                self.check(name + ': details begin collapsed', not window.result_files_toggle.isChecked() and not window.result_log_toggle.isChecked())
                self.check(name + ': usable-result actions follow real core result', window.export_result_button.isEnabled() == expected.result_usable
                    and window.open_studio_result_button.isEnabled() == expected.result_usable)
                if name in {'partial-ai-proofread','partial-ai-proofread-with-warning','core-failed','save-failed'}:
                    self.check(name + ': true issue remains outside logs', window.result_exception_summary.isVisible())
                self.shot('coverage-' + name + '-whole-window')
                if name == 'partial-ai-proofread-with-warning':
                    # Explicit structural UI coverage: a valid partial result
                    # with real review items can expose all four secondary
                    # controls. No retry is invoked and no provider is called.
                    previous_options = getattr(window,'_last_run_options',None)
                    window._last_run_options = RunOptions()
                    window._select_completion_task(0)
                    window.language_combo.setCurrentIndex(window.language_combo.findData('en'))
                    window._apply_ui_language()
                    window.resize(740,min(620,normal_height))
                    yield .25
                    self.layout_checks('controlled-four-action-narrow',center_required=False)
                    visible = [button for button in window.result_secondary_bar.buttons if button.isVisible()]
                    self.check('controlled partial narrow state keeps all four supporting actions in the shared full-width column',len(visible) == 4 and window.result_secondary_bar._columns == 1)
                    self.shot('coverage-four-action-narrow-top-whole-window')
                    narrow = window.pages.widget(2)
                    narrow.verticalScrollBar().setValue(narrow.verticalScrollBar().maximum())
                    yield .15
                    self.check('controlled partial four-action rows remain fully scrollable',
                        all(narrow.viewport().rect().contains(self.box(button,narrow.viewport())) for button in visible))
                    self.shot('coverage-four-action-narrow-bottom-whole-window')
                    window._last_run_options = previous_options
                    window.language_combo.setCurrentIndex(window.language_combo.findData('zh'))
                    window._apply_ui_language()
                    window.resize(normal_width,normal_height)
                    narrow.verticalScrollBar().setValue(0)
                    yield .25
                if name == 'normal-completed':
                    self.complete(QueueResult((replace(item, media_path=str(states/'sample-gameplay.mp4')),), actual.elapsed_seconds))
                    yield self.notifications_closed
                    yield .15
                    self.shot('review-generic-completion-whole-window')
            # Failed attempt then authoritative success using the same report path.
            failed_payload, retry_path, failed_item = self.synthetic(states, 'failed-then-retried', status='failed', usable=False)
            self.complete(QueueResult((failed_item,), actual.elapsed_seconds)); yield self.notifications_closed; yield .15
            success_payload, _, success_item = self.synthetic(states, 'failed-then-retried')
            self.complete(QueueResult((success_item,), actual.elapsed_seconds)); yield self.notifications_closed; yield .15
            self.state_agreement(retry_path, normalize_recognition_outcome(success_payload), 'failed-then-retried-success')
            # Multi-result selection must change the target project, report and summary together.
            _, first_path, first_item = self.synthetic(states, 'multi-first')
            second_project = states/'second-result.2byteproj'; shutil.copyfile(project_path, second_project)
            second_payload, second_path, second_item = self.synthetic(states, 'multi-second', quality=True)
            second_payload['media']['path'] = str(states/'second-result.mp4')
            second_payload['media']['name'] = 'second-result.mp4'
            second_payload['result']['outputs']['project'] = str(second_project)
            second_path.write_text(json.dumps(second_payload, ensure_ascii=False), 'utf8')
            second_item = replace(second_item, media_path=second_payload['media']['path'], project_path=str(second_project))
            self.complete(QueueResult((first_item, second_item), actual.elapsed_seconds*2)); yield self.notifications_closed; yield .15
            self.check('multi result has compact selector', window.result_task_selector.isVisible() and not window.result_single_filename.isVisible())
            window.result_task_selector.setCurrentIndex(1); yield .2
            self.check('multi selection updates report and project identity', Path(window._last_studio_project).resolve() == second_project.resolve()
                and Path(window._last_recognition_report).resolve() == second_path.resolve())
            self.queue_click(window.open_studio_result_button); yield self.ready
            self.check('multi second Studio callback targets second project', Path(self.page.project_path).resolve() == second_project.resolve())
            window._switch_page(2); yield .2
            window.result_task_selector.setCurrentIndex(0); yield .15
            self.check('multi selection restores first project identity', Path(window._last_studio_project).resolve() == project_path.resolve())
            _, failed_path, failed_item = self.synthetic(states, 'mixed-failed', status='failed', usable=False)
            self.complete(QueueResult((first_item, failed_item), actual.elapsed_seconds*2)); yield self.notifications_closed; yield .15
            window.result_task_selector.setCurrentIndex(1); yield .15
            self.check('mixed selection disables unavailable export and Studio', not window.export_result_button.isEnabled()
                and not window.open_studio_result_button.isEnabled() and not window._last_studio_project)
            # Recognition history recovery invokes the production menu callback.
            recovery = copy.deepcopy(report); recovery['result']['outputs']['project'] = str(project_path)
            recovery_path = states/'history-reopen.json'; recovery_path.write_text(json.dumps(recovery, ensure_ascii=False), 'utf8')
            window._last_recognition_report = str(recovery_path)
            QTimer.singleShot(0, self.guarded_modal(window.recover_recognition_button.trigger)); yield self.ready
            self.check('history recovery reopens actual saved project', Path(self.page.project_path).resolve() == project_path.resolve())
            window._switch_page(2); self.complete(retained); yield self.notifications_closed; yield .15
            # A saved-project failure discovered at return must block navigation visibly.
            damaged_project = states/'save-check-copy.2byteproj'; shutil.copyfile(project_path, damaged_project)
            damaged_item = replace(actual, project_path=str(damaged_project))
            self.complete(QueueResult((damaged_item,), actual.elapsed_seconds)); yield self.notifications_closed; yield .15
            damaged_project.write_bytes(b'{ invalid disposable project')
            messages = []
            replacements = {}
            for name in ('warning','critical','information'):
                replacements[name] = getattr(QMessageBox,name)
                setattr(QMessageBox,name,lambda *args, **kwargs: messages.append([str(x) for x in args[1:3]]) or QMessageBox.StandardButton.Ok)
            try:
                self.click(window.result_return_button)
            finally:
                for name, function in replacements.items():setattr(QMessageBox,name,function)
            self.check('return prevents silent loss when saved project cannot be read', window.pages.currentIndex() == 2
                and bool(messages) and (window.result_exception_summary.isVisible() or window.result_task_summary.isVisible()), messages)
            self.shot('coverage-save-validation-blocks-return-whole-window')
            self.complete(retained); yield self.notifications_closed; yield .15
            self.check('return does not require exported SRT', not actual.srt_path)
            self.click(window.result_return_button)
            self.check('third primary card explicitly returns to main menu', window.pages.currentIndex() == 0)
            self.check('real input report and project sources remain byte-identical',
                Path(inputs['source_report']).read_bytes() == source_report_bytes and Path(inputs['source_project']).read_bytes() == source_project_bytes)
            from .blank_project_audit import _provider_calls, _blocked_external_connections
            self.check('narrow layout has actual natural secondary-wrap evidence',bool(self.result.get('secondary_wrap_evidence')))
            self.check('layout replay sends no provider request', _provider_calls == 0, _provider_calls)
            self.check('layout replay attempts no external connection', not _blocked_external_connections, list(_blocked_external_connections))
            current_cues = projected_cues(load_project(project_path))
            deltas = []
            for index, (before, after) in enumerate(zip(retained_cues, current_cues)):
                changed = {key:[getattr(before,key),getattr(after,key)] for key in ('id','start_ms','end_ms','text','speaker_id')
                           if getattr(before,key) != getattr(after,key)}
                if changed:deltas.append(dict(index=index, changes=changed))
            # Existing Studio Save normalizes this real task's same-lane overlap.
            # It is deliberately retained as a limitation, not claimed unchanged.
            # Keep the historically measured JDG clamp narrowly scoped. Other
            # retained inputs must preserve all cue fields; they do not inherit
            # permission for a JDG-specific normalization.
            permitted = ([{'index':18, 'changes':{'end_ms':[35717,35600]}}]
                if len(retained_cues) == 32 and retained_cues[18].end_ms == 35717 else [])
            self.result['retained_save_normalization'] = dict(scope='Normal Save of disposable Studio copy only; real source bytes remain unchanged',
                cue_count_before=len(retained_cues), cue_count_after=len(current_cues), deltas=deltas,
                limitation='Only the previously measured 32-cue JDG normalization is permitted; other retained input cue fields must be unchanged; no Studio rule changed in this task')
            self.check('normal copy saves preserve cue text identity speaker start and only recorded existing overlap clamp',
                len(current_cues) == len(retained_cues) and (not deltas or deltas == permitted), self.result['retained_save_normalization'])

        def finish(self):
            faulthandler.cancel_dump_traceback_later()
            self.debug_stack_stream.close()
            self.timer.stop()
            self.result['elapsed_seconds'] = round(time.monotonic()-self.started, 3)
            from .blank_project_audit import _provider_calls, _blocked_external_connections
            self.result['provider_calls'] = _provider_calls
            self.result['external_connections_blocked'] = list(_blocked_external_connections)
            window.result_exit_code = 0 if self.result['passed'] else 1
            self.write()
            def stopped():
                self.result['gui_shutdown'] = True
                self.write()
            QApplication.instance().aboutToQuit.connect(stopped)
            QTimer.singleShot(150, self.close_save_dialog)
            window.close()

        def write(self):
            (output/'result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf8')

    window._completion_real_audit = Audit()
