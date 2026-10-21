"""Opt-in real-window check: style tab background switch / recolor and the label grid (2026-10-17/18).

Scenario ``style-background-grid`` (driver: scripts/verify_style_background_grid_headed.py).
Studio opens a two-caption project with real media in isolated user data:

* background red -> rich shadow (VisualGraph) -> pink -> switch off -> switch on: the graph panel the renderers
  draw follows every step and the caption's drawn pixels shrink when the background is off;
* the background switch is one undo step;
* every left label of the style tab shares one column, every control starts on one line, both
  checkboxes use one style, the shadow / glow switches share the trailing slot, no row overlaps;
* with English labels the column widens instead of clipping ``Background``;
* 2026-10-18: square swatches with no 宽度 / 半径 / 方向 captions, no text preview, the shadow
  fields in a 2 x 2 grid beside the disc, active rows fade their color from the right edge,
  one click on the font field opens a list that stays open, and the motion tab's category
  filter back to 全部 does not stack tiles.
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QObject, QPoint, QTimer
    from PySide6.QtWidgets import QApplication, QCheckBox, QScrollArea, QToolButton
    from ..diagnostics.build_identity import load_build_identity

    app = QApplication.instance()
    output = Path(output)
    theme = os.environ.get('TWOBYTEASR_STYLE_AUDIT_THEME', 'grape')

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = {'passed': False, 'identity': load_build_identity().to_dict(), 'checks': [],
                           'pid': os.getpid(), 'executable': sys.executable, 'screenshots': [],
                           'theme': theme, 'values': {}}
            self.steps = self.run()
            self.wait_until = 0
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(40)

        def check(self, name, value, detail=None):
            self.result['checks'].append({'name': name, 'passed': bool(value), 'detail': detail})

        def tick(self):
            if time.monotonic() < self.wait_until:
                return
            try:
                self.wait_until = time.monotonic() + next(self.steps)
            except StopIteration:
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                self.finish()

        def shot(self, widget, name):
            path = output / f'{name}.png'
            widget.grab().save(str(path))
            self.result['screenshots'].append(str(path))

        @staticmethod
        def state(page):
            from ..caption_style.style_resolution import resolve_cue_visual
            from ..caption_style.visual_snapshot import build_visual_cue_snapshot
            cue_id = page.session.selected_cue_id
            recipe = build_visual_cue_snapshot(page.session.project, cue_id).style_recipe or {}
            panel = (recipe.get('visualGraph') or {}).get('panelLayer') or {}
            cue = page.session._cue_lookup[cue_id]
            trace = page.subtitle_visibility_trace(reason='style_background_grid')
            pixels = [row.get('alpha_nonzero', 0) for row in trace.get('cue_pixels', ()) if row.get('cue_id') == cue_id]
            return {'border': resolve_cue_visual(page.session.project, cue).style.border_style,
                    'panel': [panel.get('primitive'), (panel.get('params') or {}).get('color')],
                    'graph': bool(recipe.get('visualGraph')), 'pixels': pixels[0] if pixels else None,
                    'background_switch': page.style_background.isChecked(),
                    'shadow_controls': [page.style_shadow_opacity.value(), page.style_shadow_blur.value()],
                    'recipe_shadow_opacity': ((recipe.get('outline') or {}).get('shadow') or {}).get('opacity'),
                    'style_id': cue.style_id,
                    'selected': cue_id, 'scope': page.style_scope.currentData(),
                    'playhead_ms': int(getattr(page.timeline, 'playhead_ms', -1) or 0),
                    'undo': page.undo_stack.count()}

        @staticmethod
        def hold(page):
            """Keep playback paused on the first caption. Studio opened by the
            acceptance launcher can start playing by itself; selection then follows
            the playhead into the second caption and the steps would edit that one
            (2026-10-18: one warm run "lost" the rich shadow exactly this way)."""
            page.video.set_paused(True)
            page._sync_play_button(True)
            if page.session.selected_cue_id != 'c0':
                page.select_cue('c0')
            if int(getattr(page.timeline, 'playhead_ms', 0) or 0) > 2000:
                page._seek(0.2)  # seconds

        def settle_state(self, page, name, previous=None):
            # The caption scene repaints asynchronously: wait for a pixel row that
            # differs from the previous step (or for 4 s when the count may stay).
            value = None
            for _ in range(20):
                yield .2
                value = self.state(page)
                if value['pixels'] and (previous is None or value['pixels'] != previous):
                    break
            self.result['values'][name] = value
            self.result.setdefault('selected_during_steps', []).append(value['selected'])
            return value

        @staticmethod
        def scroll_root(page):
            widget = page.style_apply_geometry.parentWidget()
            while widget is not None and not isinstance(widget, QScrollArea):
                widget = widget.parentWidget()
            return widget

        # ---------------------------------------------------------------- run
        def run(self):
            yield 1.0
            from ..design.theme_manager import apply_theme
            apply_theme(theme)
            project = os.environ.get('TWOBYTEASR_STARTUP_PROJECT', '')
            window.open_studio_project(project)
            deadline = time.monotonic() + 40
            page = None
            while time.monotonic() < deadline:
                page = window.built_page('studio')
                if (page is not None and page.project is not None
                        and getattr(page.video, '_startup_state', '') == 'READY'):
                    break
                yield .3
            self.check('studio_opened', page is not None and page.project is not None,
                       getattr(getattr(page, 'video', None), '_startup_state', None))
            if page is None or page.project is None:
                return
            window.showMaximized()
            yield 1.5
            page.volume_slider.setValue(0)
            page.video.set_paused(True)
            page._sync_play_button(True)
            page.select_cue('c0')
            page.context_drawer.setCurrentIndex(1)
            yield 1.0
            yield from self.background(page)
            yield from self.grid(page)
            yield from self.shadow_editor(page)
            yield from self.font_click(page)
            yield from self.motion_filter(page)
            yield from self.english(page)

        def background(self, page):
            self.hold(page)
            page.style_scope.setCurrentIndex(page.style_scope.findData('current'))
            yield .3
            before = yield from self.settle_state(page, '0-start')
            self.hold(page)
            page._set_style_color(page.style_back_color, '#FFFF0000')
            red = yield from self.settle_state(page, '1-red', before['pixels'])
            self.hold(page)
            page.style_shadow_opacity.setValue(48)
            page.style_shadow_blur.setValue(3)
            page._commit_style_now()
            shadow = yield from self.settle_state(page, '2-red-rich-shadow')
            self.check('red_background_on', red['border'] == 3 and shadow['border'] == 3, [red, shadow])
            self.check('rich_shadow_makes_graph_with_red_panel',
                       shadow['graph'] and shadow['panel'] == ['ROUNDED_PANEL', '#FFFF0000'], shadow)
            self.hold(page)
            page._set_style_color(page.style_back_color, '#FFF2A6C8')
            pink = yield from self.settle_state(page, '3-pink')
            self.check('pink_panel_after_recolor', pink['panel'] == ['ROUNDED_PANEL', '#FFF2A6C8'], pink)
            self.shot(window, '01-pink-window')
            steps = page.undo_stack.count()
            self.hold(page)
            page.style_background.click()  # the switch, off
            off = yield from self.settle_state(page, '4-switch-off', pink['pixels'])
            self.check('switch_off_removes_background', off['border'] == 1 and off['panel'][0] == 'NONE', off)
            self.check('switch_is_one_undo_step', page.undo_stack.count() == steps + 1,
                       [steps, page.undo_stack.count()])
            self.check('drawn_pixels_shrink_without_background',
                       bool(off['pixels'] and pink['pixels'] and off['pixels'] < pink['pixels']),
                       [before['pixels'], red['pixels'], pink['pixels'], off['pixels']])
            self.shot(page.context_drawer, '02-style-after-switch-off')
            self.hold(page)
            page.style_background.click()
            back = yield from self.settle_state(page, '5-switch-on', off['pixels'])
            self.check('steps_stay_on_the_first_caption',
                       set(self.result.get('selected_during_steps', [])) == {'c0'},
                       self.result.get('selected_during_steps'))
            self.check('switch_on_restores_pink', back['border'] == 3
                       and back['panel'] == ['ROUNDED_PANEL', '#FFF2A6C8'], back)

        def grid(self, page):
            scroll = self.scroll_root(page)
            root = scroll.widget()
            for header in root.findChildren(QToolButton, 'styleSectionHeader'):
                if header.isVisibleTo(root):
                    header.setChecked(True)
            for row in page._appearance_rows.values():
                if row.content.isVisible():  # never "collapse" 填充 (its ✎ would turn into ▸)
                    row.set_expanded(False)
            page._appearance_rows['outline'].set_expanded(True)
            scroll.verticalScrollBar().setValue(0)
            yield .6

            def x(item):
                return item.mapTo(root, QPoint(0, 0)).x()

            column = page._style_label_column
            inner = [label for label, extra in column._labels if extra == 0 and label.isVisibleTo(root)]
            outer = [label for label, extra in column._labels if extra and label.isVisibleTo(root)]
            self.check('section_labels_one_column', len({x(label) for label in inner}) == 1
                       and len({label.width() for label in inner}) == 1,
                       sorted({(x(label), label.width()) for label in inner}))
            self.check('outer_labels_end_with_section_labels',
                       {x(label) + label.width() for label in outer} == {x(label) + label.width() for label in inner[:1]},
                       [x(label) + label.width() for label in outer + inner[:1]])
            controls = [page.style_scope, page.style_apply_geometry, page.style_preset, page.style_font,
                        page.style_font_size, page.style_fill_swatch, page.style_outline_swatch,
                        page.style_back_swatch, page.style_shadow_swatch, page.style_glow_swatch,
                        page.style_outline2, page.style_alignment, page.style_position_x]
            starts = {x(item) for item in controls}
            self.check('controls_start_on_one_line', len(starts) == 1, sorted(starts))
            self.check('switches_share_trailing_slot',
                       x(page.style_shadow_switch) == x(page.style_glow) == x(page.style_background),
                       [x(page.style_background), x(page.style_shadow_switch), x(page.style_glow)])
            swatches = [page.style_fill_swatch, page.style_outline_swatch, page.style_back_swatch,
                        page.style_shadow_swatch, page.style_glow_swatch]
            self.check('swatches_are_squares', all(abs(w.width() - w.height()) <= 2 for w in swatches),
                       [(w.width(), w.height()) for w in swatches])
            from PySide6.QtWidgets import QLabel
            captions = {label.text() for row in page._appearance_rows.values()
                        for label in row.findChildren(QLabel) if label.isVisibleTo(row)}
            self.check('no_width_radius_direction_captions', not captions & {'宽度', '半径', '方向', '透明'},
                       sorted(captions))
            self.check('text_preview_hidden', not page.style_preview.isVisibleTo(root))
            rows_tint = {name: list(row._tint_colors) for name, row in page._appearance_rows.items()}
            self.check('active_rows_carry_their_color', bool(rows_tint['fill']) and bool(rows_tint['background'])
                       and bool(rows_tint['shadow']) and not rows_tint['glow'], rows_tint)
            boxes = [box for box in root.findChildren(QCheckBox) if box.isVisibleTo(root) and box.text()]
            self.check('checkboxes_one_style', {box.objectName() for box in boxes} == {'styleInlineCheck'},
                       sorted({(box.text(), box.objectName()) for box in boxes}))
            row = [page.style_font_size, page.style_spacing, page.style_bold, page.style_italic, page.style_underline]
            spans = [(x(item), x(item) + item.width()) for item in row]
            self.check('text_row_does_not_overlap', all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))
                       and spans[-1][1] <= root.width(), spans)
            preset = [page.style_preset, page.style_library_button]
            pspans = [(x(item), x(item) + item.width()) for item in preset]
            self.check('preset_row_does_not_overlap', pspans[0][1] <= pspans[1][0], pspans)
            shown = page.style_preset.displayed_text()
            full = page.style_preset.currentText()
            self.check('preset_name_whole_or_elided', shown == full or (shown.endswith('…') and len(shown) < len(full)),
                       [full, shown, page.style_preset.width()])
            summary = page._appearance_rows['shadow'].inline_summary
            self.check('shadow_summary_elided_not_cut', summary.fontMetrics().horizontalAdvance(
                super(type(summary), summary).text()) <= summary.contentsRect().width() + 1,
                [summary.text(), summary.contentsRect().width()])
            self.result['values']['grid'] = dict(label_width=column.width, control_x=sorted(starts),
                                                 text_row=spans, preset_row=pspans)
            # A wider tool panel keeps the grid (combo caps used to centre two rows).
            from PySide6.QtWidgets import QSplitter
            splitter = page.context_drawer.parentWidget()
            while splitter is not None and not isinstance(splitter, QSplitter):
                splitter = splitter.parentWidget()
            if splitter is not None:
                sizes = splitter.sizes()
                wide = list(sizes)
                wide[-1] += 180
                wide[1] = max(200, wide[1] - 180)
                splitter.setSizes(wide)
                yield .6
                wide_starts = {x(item) for item in controls}
                self.check('controls_start_on_one_line_when_wider', len(wide_starts) == 1,
                           [page.context_drawer.width(), sorted(wide_starts)])
                splitter.setSizes(sizes)
                yield .6
            self.shot(page.context_drawer, '03-style-top')
            scroll.ensureWidgetVisible(page._appearance_rows['glow'], 0, 40)
            yield .4
            self.shot(page.context_drawer, '04-style-appearance')
            scroll.ensureWidgetVisible(page.style_margin_v, 0, 40)
            yield .4
            self.shot(page.context_drawer, '05-style-position')

        def shadow_editor(self, page):
            scroll = self.scroll_root(page)
            root = scroll.widget()
            page._appearance_rows['shadow'].set_expanded(True)
            scroll.ensureWidgetVisible(page._appearance_rows['glow'], 0, 40)
            yield .5

            def pos(item):
                return item.mapTo(root, QPoint(0, 0))

            disc = page.style_shadow_angle
            fields = [page.style_shadow_distance, page.style_shadow_opacity, page.style_shadow_blur,
                      page.style_shadow_spread]
            xs = sorted({pos(f).x() for f in fields})
            ys = sorted({pos(f).y() for f in fields})
            self.check('shadow_fields_two_by_two_beside_disc',
                       len(xs) == 2 and len(ys) == 2 and xs[0] > pos(disc).x() + disc.width()
                       and pos(disc).y() <= ys[1] and pos(disc).y() + disc.height() >= ys[0]
                       and not page.style_shadow_angle_value.isVisibleTo(root),
                       dict(disc=[pos(disc).x(), pos(disc).y(), disc.width()], xs=xs, ys=ys))
            self.shot(page.context_drawer, '07-shadow-editor')
            page._appearance_rows['shadow'].set_expanded(False)
            yield .3

        def font_click(self, page):
            from PySide6.QtCore import QPointF, Qt as QtNS
            from PySide6.QtGui import QEnterEvent
            from PySide6.QtTest import QTest
            scroll = self.scroll_root(page)
            scroll.verticalScrollBar().setValue(0)
            yield .4
            combo = page.style_font
            editor = combo.lineEdit()
            top = window.windowHandle()
            point = editor.mapTo(window, editor.rect().center())
            QApplication.sendEvent(top, QEnterEvent(QPointF(point), QPointF(point),
                                                    QPointF(window.mapToGlobal(point))))
            QTest.mouseMove(top, point)
            QTest.mousePress(top, QtNS.MouseButton.LeftButton, QtNS.KeyboardModifier.NoModifier, point)
            yield .15
            QTest.mouseRelease(top, QtNS.MouseButton.LeftButton, QtNS.KeyboardModifier.NoModifier, point)
            opened = False
            for _ in range(15):  # the first open loads the font list
                yield .2
                opened = combo.view().isVisible()
                if opened:
                    break
            yield .6
            still = combo.view().isVisible()
            self.check('font_list_stays_open_after_one_click', opened and still,
                       dict(opened=opened, still=still, items=combo.count(), text=combo.currentText()))
            if still:
                self.shot(combo.view().window(), '08-font-list')
            combo.hidePopup()
            yield .4

        def motion_filter(self, page):
            page.context_drawer.setCurrentIndex(page.motion_tab_index)
            yield .8
            panel = page.motion_inspector
            stage = panel.stages[panel.tabs.currentIndex()]

            def overlapping():
                rects = [tile.geometry() for (s, _k), tile in panel.cards.items() if s == stage and tile.isVisible()]
                return sum(1 for i, a in enumerate(rects) for b in rects[i + 1:] if a.intersects(b))

            first = next(category for category in panel.chips[stage] if category != 'all')
            panel.chips[stage][first].click()
            yield .5
            panel.chips[stage]['all'].click()
            yield .6
            self.check('motion_filter_back_to_all_no_stacked_tiles', overlapping() == 0
                       and panel.stack.height() >= panel.hosts[stage].sizeHint().height(),
                       dict(overlaps=overlapping(), stack=panel.stack.height(),
                            needed=panel.hosts[stage].sizeHint().height()))
            self.shot(page.context_drawer, '09-motion-all')
            page.context_drawer.setCurrentIndex(1)
            yield .5

        def english(self, page):
            from ..i18n import save_language
            save_language('en')  # isolated settings
            yield 1.0
            column = page._style_label_column
            background = page._appearance_rows['background'].title_label
            self.check('english_column_fits_background', column.width >= column._text_width(background)
                       and background.width() >= column._text_width(background),
                       [background.text(), column.width, column._text_width(background)])
            scroll = self.scroll_root(page)
            scroll.ensureWidgetVisible(page._appearance_rows['glow'], 0, 40)
            yield .4
            self.shot(page.context_drawer, '06-english-appearance')
            save_language('zh')
            yield .5

        def finish(self):
            self.timer.stop()
            checks = self.result['checks']
            self.result['passed'] = bool(checks) and all(c['passed'] for c in checks) and 'error' not in self.result
            path = output / 'result.json'
            path.write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf8')

            def shutdown_done():
                self.result['gui_shutdown'] = True
                path.write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf8')

            app.aboutToQuit.connect(shutdown_done)
            page = window.built_page('studio')
            if page is not None:
                # The audit's edits are not the user's: do not ask to save them.
                page.undo_stack.setClean()
            window.showNormal()
            window.close()

    window._style_background_grid_audit = Audit()
