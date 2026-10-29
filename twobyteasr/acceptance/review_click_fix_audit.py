"""Opt-in real-window check: review click-to-fix, 他/她, glossary autosave, poster (2026-10-15).

Scenario ``review-click-fix`` (driver: scripts/verify_review_click_fix_headed.py).
Studio part, copied project with real media, MOSS/FireRed/Qwen evidence rows
and a real glossary in the isolated user data:

* review card 1 shows the other recognizers' local differences, a confirmed
  glossary alias and 他/她 as marks, painted where a click hits them;
* a mouse click on a mark changes only that part and review stays on the
  caption; the fix of a glossary name is saved into that glossary as an alias;
* P flips the caption's pronouns; undo restores the text and removes the
  automatically saved alias;
* a caption the recognizers agree on still shows card 1 when it has a
  glossary alias or a pronoun to fix.

Poster part: the export validator's poster frame keeps the export resolution
and the result page draws it from a device-pixel copy (sharper than the old
640-px frame), measured on the real window.
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path


def start(window, output):
    from PySide6.QtCore import QObject, QPoint, Qt, QTimer
    from PySide6.QtGui import QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from ..diagnostics.build_identity import load_build_identity

    app = QApplication.instance()
    output = Path(output)

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = {'passed': False, 'identity': load_build_identity().to_dict(), 'checks': [],
                           'pid': os.getpid(), 'executable': sys.executable, 'screenshots': []}
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
        def mark_points(card):
            """Card points painted in the accent colour (the marks), per mark index."""
            from ..design.theme_manager import theme_key
            from ..design.ui_theme import theme_definition
            accent = QColor(theme_definition(theme_key()).accent)
            image = card.text_label.grab().toImage()
            ratio = image.devicePixelRatio() or 1
            found = {}
            for y in range(0, image.height(), 2):
                for x in range(0, image.width(), 2):
                    pixel = image.pixelColor(x, y)
                    if (abs(pixel.red() - accent.red()) + abs(pixel.green() - accent.green())
                            + abs(pixel.blue() - accent.blue())) < 40:
                        point = card.text_label.mapTo(card, QPoint(int(x / ratio), int(y / ratio)))
                        found.setdefault(card._mark_at(point), []).append(point)
            return found

        def card_one(self, page):
            from ..studio.studio_cards import ReviewCandidateCard
            layout = page.review_dock_candidate_layout
            for index in range(layout.count()):
                widget = layout.itemAt(index).widget()
                if isinstance(widget, ReviewCandidateCard) and widget._suggestions:
                    return widget
            return None

        def click_mark(self, card, mark):
            points = self.mark_points(card).get(mark) or []
            if not points:
                return False
            point = points[len(points) // 2]
            QTest.mouseMove(card, point)
            QTest.mouseClick(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
            return True

        # ---------------------------------------------------------------- run
        def run(self):
            yield 1.0
            project = os.environ.get('TWOBYTEASR_STARTUP_PROJECT', '')
            fixture = json.loads((output / 'fixture.json').read_text('utf8'))
            window.open_studio_project(project)
            deadline = time.monotonic() + 40
            page = None
            while time.monotonic() < deadline:
                page = window.built_page('studio')
                if (page is not None and page.project is not None
                        and getattr(page.video, '_startup_state', '') == 'READY'):
                    break
                yield .3
            self.check('studio_opened', page is not None and page.project is not None)
            if page is None or page.project is None:
                return
            window.showMaximized()
            yield 1.5
            page.volume_slider.setValue(0)
            page.video.set_paused(True)
            page._sync_play_button(True)
            yield from self.review(page, fixture)
            yield from self.poster(fixture)

        def review(self, page, fixture):
            import subtitle_core as legacy
            from ..glossary.glossary_autosave import _mapping_keys
            library = fixture['library']
            page._set_review_mode(True)
            yield .8
            page.select_cue('c0')
            page._refresh_review_summary_strip()
            yield .6
            card = self.card_one(page)
            marks = [(row.kind, row.original, row.options[0].text) for row in (card._suggestions if card else ())]
            self.check('card_one_shows_model_marks', marks == [('model', '他', '她'), ('model', '来', '莱')], marks)
            self.shot(page.review_summary_strip, 'review-card-marks')
            points = self.mark_points(card) if card else {}
            painted = sum(len(value) for key, value in points.items() if key >= 0)
            missed = len(points.get(-1, ()))
            self.check('marks_hit_where_painted', {0, 1} <= set(points) and painted >= 4 * max(1, missed),
                       dict(hit={k: len(v) for k, v in points.items()}))
            self.check('click_on_mark', bool(card) and self.click_mark(card, 1))
            yield .6
            cue = page._cue_lookup['c0']
            self.check('mark_fixes_only_that_part', cue.text == '然后他来到了那维莱特的家', cue.text)
            self.check('review_stays_on_caption', page._review_mode and page.selected_cue_id == 'c0',
                       page.selected_cue_id)
            yield 2.2  # the manual-learning debounce (1.5 s) commits the fix
            rows = _mapping_keys(legacy, library)
            self.check('glossary_alias_saved', ('那维来特', '那维莱特') in rows, sorted(rows))
            self.result['status_after_save'] = page.save_state.text()
            page.timeline.setFocus(Qt.FocusReason.OtherFocusReason)
            yield .2
            QTest.keyClick(page.timeline, Qt.Key.Key_P)
            yield .5
            self.check('p_flips_pronouns', page._cue_lookup['c0'].text == '然后她来到了那维莱特的家',
                       page._cue_lookup['c0'].text)
            self.shot(page.review_summary_strip, 'review-after-p')
            page.undo_stack.undo()
            yield .4
            page.undo_stack.undo()
            yield .8
            rows = _mapping_keys(legacy, library)
            self.check('undo_restores_text', page._cue_lookup['c0'].text == '然后他来到了那维来特的家',
                       page._cue_lookup['c0'].text)
            self.check('undo_removes_saved_alias', ('那维来特', '那维莱特') not in rows
                       and ('那维莱特', '那维莱特') in rows, sorted(rows))
            # A caption the recognizers agree on: card 1 next to the banner.
            page.select_cue('c1')
            page._refresh_review_summary_strip()
            yield .6
            card = self.card_one(page)
            marks = [(row.kind, row.original) for row in (card._suggestions if card else ())]
            self.check('consistent_caption_keeps_card_one', marks == [('glossary', '芙宁那'), ('pronoun', '他')], marks)
            self.shot(page.review_summary_strip, 'review-consistent-card')
            self.check('click_glossary_mark', bool(card) and self.click_mark(card, 0))
            yield .6
            self.check('glossary_mark_fixes_alias', page._cue_lookup['c1'].text == '芙宁娜说他马上到',
                       page._cue_lookup['c1'].text)
            page._set_review_mode(False)
            yield .5
            # The edits are saved so closing does not stop at the unsaved-changes prompt.
            page.save()
            yield 1.5
            self.check('project_saved_before_close', page.undo_stack.isClean(), page.save_state.text())

        def poster(self, fixture):
            from PySide6.QtGui import QImage, QPixmap
            from ..exports.export_success import ExportSuccessPanel
            from ..exports.export_validation import validate_output
            from ..system.platform_media import ffmpeg_tool
            video = fixture['poster_video']
            jpeg = output / 'poster.jpg'
            validate_output(ffmpeg_tool('ffmpeg'), video, duration=3.0, fps=30, preview_path=str(jpeg))
            image = QImage(str(jpeg))
            self.check('poster_keeps_export_resolution', (image.width(), image.height()) == (1920, 1080),
                       [image.width(), image.height()])
            old = image.scaledToWidth(640, Qt.TransformationMode.SmoothTransformation)
            sharpness = {}
            for name, source in (('old_640', old), ('new_full', image)):
                panel = ExportSuccessPanel(lambda: None, lambda: None, lambda: None, lambda: None)
                panel.resize(1600, 900)
                panel.show()
                panel.preview.image = QPixmap.fromImage(source)
                panel.preview.update()
                yield .8
                grab = panel.preview.grab().toImage()
                grab.save(str(output / f'poster-{name}.png'))
                self.result['screenshots'].append(str(output / f'poster-{name}.png'))
                sharpness[name] = self.gradient(grab)
                self.result.setdefault('poster_device_pixmap', {})[name] = [
                    panel.preview._scaled[1].width(), panel.preview._scaled[1].height(),
                    round(float(panel.preview.devicePixelRatioF()), 3), panel.preview.width(), panel.preview.height()]
                panel.close()
                panel.deleteLater()
                yield .3
            self.result['poster_sharpness'] = sharpness
            self.check('poster_sharper_than_old', sharpness['new_full'] > sharpness['old_640'] * 1.15, sharpness)
            device = self.result['poster_device_pixmap']['new_full']
            self.check('poster_drawn_at_device_pixels',
                       abs(device[0] - round(device[3] * device[2])) <= 2, device)

        @staticmethod
        def gradient(image):
            """Mean absolute horizontal + vertical luminance step (higher = sharper)."""
            total, count = 0, 0
            width, height = image.width(), image.height()
            for y in range(height // 4, 3 * height // 4, 3):
                for x in range(width // 4, 3 * width // 4, 3):
                    here = image.pixelColor(x, y).lightness()
                    total += abs(here - image.pixelColor(x + 1, y).lightness())
                    total += abs(here - image.pixelColor(x, y + 1).lightness())
                    count += 2
            return round(total / max(1, count), 3)

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
            window.showNormal()
            window.close()

    window._review_click_fix_audit = Audit()
