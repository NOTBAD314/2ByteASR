"""Real-widget, native-pixel acceptance for the Studio feedback follow-up.

Invoked only through the existing temporary-project/config isolation guard.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def start_studio_polish_acceptance(window, output):
    import numpy as np
    from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QTimer, Qt
    from PySide6.QtGui import QImage, QMouseEvent, QFontInfo
    from PySide6.QtWidgets import QApplication, QFrame, QToolButton, QLabel, QPushButton
    from PySide6.QtTest import QTest
    from .theme_manager import apply_theme
    from .ui_theme import THEMES
    from .timeline_theme import timeline_palette
    from .studio_cards import ReviewCandidateCard
    from .studio_qc import QCCandidate
    from .build_identity import load_build_identity

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.results = dict(runtime='frozen' if getattr(sys, 'frozen', False) else 'source',
                build=vars(load_build_identity()), checks={}, themes=[], drag=[], window_events=[], screen_samples=[])
            self.started = self.last_screen = time.perf_counter()
            self.waiting = 0.
            self.monitor = False
            window.installEventFilter(self)
            self.sequence = self.scenario()
            self.timer = QTimer(self)
            self.timer.setInterval(10)
            self.timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.timer.timeout.connect(self.tick)
            self.timer.start()

        def eventFilter(self, watched, event):
            if self.monitor and watched is window and event.type() in (QEvent.Type.Hide, QEvent.Type.Show, QEvent.Type.WinIdChange):
                self.results['window_events'].append((round(time.perf_counter()-self.started, 3), event.type().name))
            return False

        def check(self, name, value):
            self.results['checks'][name] = bool(value)
            assert value, name

        @staticmethod
        def pixels(image):
            image = image.convertToFormat(QImage.Format.Format_RGBA8888)
            return np.frombuffer(image.bits(), dtype=np.uint8).reshape(image.height(), image.bytesPerLine())[:, :image.width()*4].reshape(image.height(), image.width(), 4).copy()

        def native_centroid(self, name):
            target = output/f'{name}-native.png'
            self.page.video.controller.screenshot_to_file(target)
            pixels = self.pixels(QImage(str(target)))
            mask = (pixels[:, :, :3].min(axis=2) > 225)
            yy, xx = np.nonzero(mask)
            assert len(xx) > 40, f'No subtitle glyph pixels in {name}'
            return [float(xx.min()+xx.max())/2, float(yy.min()+yy.max())/2, len(xx), int(yy.max()-yy.min()+1)]

        def shot(self, name):
            # Qt chrome remains auditable even if the user foregrounds another
            # application. Native video has separate mpv pixel evidence.
            window.grab().save(str(output/f'{name}.png'))

        def tick(self):
            now = time.perf_counter()
            try:
                if self.monitor and now-self.last_screen > .08:
                    self.last_screen = now
                    image = window.screen().grabWindow(int(window.winId())).toImage()
                    if not image.isNull():
                        pixels = self.pixels(image)[::8, ::8, :3]
                        self.results['screen_samples'].append(float((pixels.max(axis=2) < 8).mean()))
                if now-self.started > 150:
                    raise TimeoutError('Studio polish acceptance timed out')
                if callable(self.waiting):
                    if not self.waiting(): return
                elif now < self.waiting: return
                pending = next(self.sequence)
                self.results['phase_line'] = self.sequence.gi_frame.f_lineno
                self.waiting = pending if callable(pending) else time.perf_counter()+float(pending)
            except StopIteration:
                self.finish()
            except Exception:
                import traceback
                self.results['error'] = traceback.format_exc()
                self.finish()

        def scenario(self):
            page = self.page
            yield lambda: page.project is not None and len(page.project.video_tracks) == 3
            page._queue_advanced_preview_job = lambda *a, **kw: None
            window.resize(1600, 960)
            window.raise_(); window.activateWindow()
            page.video.set_paused(True)
            yield .4
            transform_times = []
            transform = page.advanced_cue_overlay.set_transform_preview
            def timed_transform(values):
                start = time.perf_counter()
                try: return transform(values)
                finally: transform_times.append((time.perf_counter()-start)*1000)
            page.advanced_cue_overlay.set_transform_preview = timed_transform
            self.monitor = True
            menu = page.cue_more_button.menu()  # Created before any theme switch.
            for key in ('grape', 'warm', 'plum', 'slate', 'lavender', 'grape'):
                window._switch_page(0)
                start = time.perf_counter()
                apply_theme(key, QApplication.instance())
                self.results['themes'].append(dict(key=key, apply_ms=round((time.perf_counter()-start)*1000, 1)))
                yield .15
                self.shot(f'home-{key}')
                window._switch_page(page)
                yield .2
                actual = page.timeline.grab().toImage().pixelColor(10, 10).name()
                self.check(f'timeline_pixel_{key}', actual == timeline_palette(key).header)
                menu.popup(page.cue_more_button.mapToGlobal(QPoint(0, -menu.sizeHint().height())))
                yield .12
                self.check(f'reused_menu_{key}', menu._secondary_theme_key == key)
                menu.grab().save(str(output/f'menu-{key}.png'))
                menu.hide()
                if key == 'grape': self.shot('studio-grape')
            combo = page.video_fit_mode
            chain = []
            node = page.style_font.lineEdit()
            while node is not None:
                chain.append(dict(type=type(node).__name__, name=node.objectName(), sheet=node.styleSheet(),
                    root_sheet=bool(getattr(node, '_theme_root_sheet', ''))))
                node = node.parentWidget()
            (output/'font-style-chain.json').write_text(json.dumps(chain, ensure_ascii=False, indent=2), encoding='utf-8')
            page.style_font.grab().save(str(output/'font-control.png'))
            self.check('font_control_inherits_current_theme', not getattr(page.style_font, '_theme_root_sheet', None))
            self.check('font_control_actual_pixel', page.style_font.grab().toImage().pixelColor(50, 8).name() == THEMES['grape'].input_surface)
            combo.showPopup()
            yield .15
            combo.view().window().grab().save(str(output/'fit-popup.png'))
            self.check('combo_current_theme', combo.view().palette().color(combo.view().palette().ColorRole.Text).name() == THEMES['grape'].text)
            combo.hidePopup()
            page.select_cue('cue')
            page._seek(2.)
            yield .35
            page._set_review_mode(True)
            yield .2
            card = ReviewCandidateCard(1, QCCandidate('实时拖拽字幕', ('Qwen',)), current_text='拖动字幕', parent=page.review_dock_candidates)
            page.review_dock_candidate_layout.addWidget(card, 0, 0)
            card.show()
            yield .15
            self.results['review_font'] = dict(family=QFontInfo(card.text_label.font()).family(), px=card.text_label.font().pixelSize())
            self.check('review_readable_font', card.text_label.font().pixelSize() >= 14)
            self.shot('review-grape')
            page._set_review_mode(False)
            # Static dark V1 makes the white glyph centroid measurable in mpv.
            for track in page.project.video_tracks[1:]: track.enabled = False
            page._sync_video_compositor(2000)
            page._seek(2.)
            page.select_cue('cue')
            page.position_edit_button.setChecked(True)
            page.ensure_active_subtitle_renderer(reason='acceptance_drag')
            yield .4
            overlay = page.position_overlay
            self.check('drag_handles_visible', overlay.isVisible())
            before = self.native_centroid('drag-before')
            origin = overlay._subtitle_rect().center().toPoint() if hasattr(overlay._subtitle_rect().center(), 'toPoint') else overlay._subtitle_rect().center()
            undo = page.undo_stack.index()
            ass = page._ass_generation
            QTest.mousePress(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, origin)
            yield .15
            # Input every 10ms must not starve a 24ms preview timer.
            for i in range(1, 41):
                point = origin + QPoint(i*2, -i)
                event = QMouseEvent(QEvent.Type.MouseMove, QPointF(point), QPointF(overlay.mapToGlobal(point)),
                    Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier)
                QApplication.sendEvent(overlay, event)
                if i in (10, 20, 30, 40):
                    self.results['drag'].append(dict(step=i, centroid=self.native_centroid(f'drag-{i}'),
                        source_generation=page.advanced_cue_overlay._layer_generation))
                yield .01
            during = self.results['drag'][-1]['centroid']
            self.check('glyph_moves_before_release', during[0]-before[0] > 60 and before[1]-during[1] > 25)
            self.check('no_ASS_compile_during_drag', page._ass_generation == ass)
            self.check('no_undo_entries_during_drag', page.undo_stack.index() == undo)
            QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, point)
            yield .45
            self.check('one_drag_command', page.undo_stack.index() == undo+1)
            committed = self.native_centroid('drag-committed')
            self.check('commit_has_one_glyph_copy', committed[3] < before[3]*1.3)
            page.undo_stack.undo()
            yield .4
            undone = self.native_centroid('drag-undo')
            self.check('undo_restores_glyph_pixels', abs(undone[0]-before[0]) < 5 and abs(undone[1]-before[1]) < 5)
            # Cancel a second real gesture; transient pixels must not persist.
            origin = overlay._subtitle_rect().center().toPoint()
            QTest.mousePress(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, origin)
            yield .15
            point = origin + QPoint(50, -30)
            QApplication.sendEvent(overlay, QMouseEvent(QEvent.Type.MouseMove, QPointF(point),
                QPointF(overlay.mapToGlobal(point)), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.AltModifier))
            yield .1
            QTest.keyClick(overlay, Qt.Key.Key_Escape)
            yield .4
            cancelled = self.native_centroid('drag-cancelled')
            self.check('cancel_restores_pixels_and_undo', page.undo_stack.index() == undo and
                abs(cancelled[0]-before[0]) < 5 and abs(cancelled[1]-before[1]) < 5)
            # Keep multi-track composition active with transparent secondary
            # clips so its subtitle pixels remain independently measurable.
            for track in page.project.video_tracks[1:]:
                track.enabled = True
                for clip in track.clips: clip.transform.opacity = 0.
            page._sync_video_compositor(2000)
            page.ensure_active_subtitle_renderer(reason='multi_drag')
            yield .45
            self.check('multitrack_drag_renderer_active', page._multitrack_composition_active)
            multi_before = self.native_centroid('multi-before')
            origin = overlay._subtitle_rect().center().toPoint()
            QTest.mousePress(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, origin)
            yield .15
            for i in range(1, 21):
                point = origin + QPoint(i*3, -i)
                QApplication.sendEvent(overlay, QMouseEvent(QEvent.Type.MouseMove, QPointF(point),
                    QPointF(overlay.mapToGlobal(point)), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.AltModifier))
                yield .01
            yield .05
            multi_during = self.native_centroid('multi-during')
            self.check('multitrack_glyph_moves_before_release', multi_during[0]-multi_before[0] > 60)
            QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, point)
            yield .4
            self.check('multitrack_one_command', page.undo_stack.index() == undo+1)
            page.undo_stack.undo()
            yield .4
            multi_undo = self.native_centroid('multi-undo')
            self.check('multitrack_undo_restores_pixels', abs(multi_before[0]-multi_undo[0]) < 5 and abs(multi_before[1]-multi_undo[1]) < 5)
            self.results['transform_ms'] = dict(count=len(transform_times), p95=round(float(np.percentile(transform_times, 95)), 2),
                maximum=round(max(transform_times), 2))
            # Exercise play / pause / speed and seek while monitoring the whole HWND.
            for speed in (1., 2.):
                for track in page.project.video_tracks[1:]: track.enabled = True
                for track in page.project.video_tracks[1:]:
                    for clip in track.clips: clip.transform.opacity = 1.
                page._sync_video_compositor(2000)
                page.video.set_speed(speed)
                page.video.set_paused(False)
                yield .7
                page.video.set_paused(True)
                yield .15
                page._seek(.8)
                yield .25
            page.show_project_hub(skip_dirty_guard=True)
            yield .4
            yield lambda: not getattr(page, '_hub_scan_pending', False)
            # Synthetic records stay inside the guarded acceptance directory.
            page._request_library_scan = lambda *a, **kw: None
            fixture = Path(os.environ['TWOBYTEASR_STARTUP_PROJECT'])
            cover = output/'drag-before-native.png'
            page._hub_library_records = [dict(path=str(fixture), name='游戏实况 · 字幕校对', cue_count=1,
                duration_ms=6000, source_media=str(output/'tone-0.mp4'), cover_path=str(cover),
                updated_at='2026-09-08T13:00:00', last_opened='2026-09-08T13:00:00'),
                dict(path=str(fixture), name='离线素材 · 待重新链接', cue_count=12, duration_ms=6000,
                source_media=str(output/'missing.mp4'), cover_path=str(cover))]
            page._set_project_library_view('list')
            page._rebuild_project_library()
            yield .3
            self.check('hub_no_orphan_dividers', all(not w.isVisible() for w in page.studio_toolbar.findChildren(QFrame, 'toolbarDivider')))
            self.shot('hub-grape')
            rows = [w for w in page.project_list_host.findChildren(QToolButton, 'projectListRow') if w.isVisible()]
            self.check('compact_rows_populated', len(rows) == 2)
            self.check('compact_rows_stay_compact', rows[1].y() - rows[0].geometry().bottom() <= 10)
            for row in rows:
                status = row.findChild(QLabel, 'projectRowStatus')
                button = row.findChild(QPushButton, 'projectRowOpen')
                self.check('compact_row_alignment_' + status.property('status'), row.height() >= 76 and
                    abs(status.geometry().center().y()-button.geometry().center().y()) <= 2 and
                    status.geometry().right() < button.geometry().left())
            self.check('whole_window_stayed_visible', not self.results['window_events'])
            self.check('no_whole_black_sample', bool(self.results['screen_samples']) and max(self.results['screen_samples']) < .90)
            QTest.mouseClick(rows[0].findChild(QPushButton, 'projectRowOpen'), Qt.MouseButton.LeftButton)
            yield lambda: page.project is not None
            self.check('compact_continue_opens_fixture', Path(page.project_path).resolve() == fixture.resolve())

        def finish(self):
            self.timer.stop()
            self.monitor = False
            self.page.close_page()
            (output/'studio-polish-acceptance.json').write_text(json.dumps(self.results, ensure_ascii=False, indent=2), encoding='utf-8')
            window.hide()
            QTimer.singleShot(200, QApplication.instance().quit)

    window._acceptance_audit = Audit()
