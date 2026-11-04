"""Actual Bilibili + Generic downloads through the normal application window."""
from __future__ import annotations
import json
from pathlib import Path
import time
import traceback


def start(window, out):
    from PySide6.QtCore import QObject, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .blank_project_audit import _capture
    from ..diagnostics.build_identity import load_build_identity
    from ..media.link_choices import video_formats
    from ..media.link_manifest import load_bundle
    from ..projects.studio_project import save_project, load_project

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.result = dict(passed=False, checks=[], screenshots=[],
                identity=load_build_identity().to_dict(), network="real Bilibili and MDN, no cookies",
                subtitle_account_access="NOT VERIFIED", human_listening="NOT VERIFIED")
            self.steps = self.run()
            self.waiting = 0
            self.deadline = time.monotonic() + 180
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(40)

        def check(self, name, value, detail=None):
            self.result['checks'].append(dict(name=name, passed=bool(value), detail=detail))
            (out/'link-progress.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf-8')
            if not value:
                raise AssertionError(f'{name}: {detail}')

        def shot(self, name, widget):
            _capture(widget, out/(name+'.png'))
            self.result['screenshots'].append(name+'.png')

        def tick(self):
            try:
                modal = QApplication.activeModalWidget()
                if isinstance(modal, QMessageBox):
                    raise RuntimeError(modal.text())
                now = time.monotonic()
                if callable(self.waiting):
                    if not self.waiting():
                        if now > self.deadline:
                            raise TimeoutError('Stage timed out')
                        return
                elif now < self.waiting:
                    return
                delay = next(self.steps)
                self.waiting = delay if callable(delay) else now + float(delay)
                self.deadline = now + 180
            except StopIteration:
                self.result['passed'] = True
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                self.shot('failure', window)
                self.finish()

        def run(self):
            yield .6
            QTest.mouseClick(window.link_download_button, Qt.MouseButton.LeftButton)
            self.controller = window._link_download_controller
            dialog = self.controller.dialog
            self.check('multisite input visible', 'Bilibili' in dialog.url.placeholderText())
            dialog.directory.setText(str(out/'downloads'))
            dialog.url.setText('https://www.bilibili.com/video/BV1JZnr6TEMd')
            QTest.mouseClick(dialog.parse_button, Qt.MouseButton.LeftButton)
            yield lambda: dialog.catalog is not None or dialog.parse_button.isEnabled()
            self.check('real Bilibili catalog', dialog.catalog is not None, dialog.message.text())
            catalog = dialog.catalog
            self.check('Bilibili identity and P1', catalog['platform'] == 'BiliBili' and catalog['video_id'] == 'BV1JZnr6TEMd_p1')
            self.check('Bilibili formats selectable', dialog.video_format.count() > 0 and dialog.audio_format.count() > 0)
            self.check('subtitle access represented truthfully', catalog['subtitle_status'] in {'available', 'none', 'incomplete'}, catalog['subtitle_status'])
            if catalog['subtitle_status'] == 'incomplete':
                self.check('cookie hint visible', dialog.subtitle_status.isVisible() and 'Cookie' in dialog.subtitle_status.text())
            videos = video_formats(catalog)
            chosen = min(videos, key=lambda f: (f.get('height') or 9999, not str(f.get('vcodec', '')).startswith('avc')))
            dialog.video_format.setCurrentIndex(dialog.video_format.findData(chosen['format_id']))
            yield .3
            self.shot('01-bilibili-formats', dialog)
            QTest.mouseClick(dialog.add_button, Qt.MouseButton.LeftButton)
            yield lambda: bool(self.controller.queue.snapshots())
            task_id = self.controller.queue.snapshots()[-1]['task_id']
            yield lambda: self.controller.task(task_id)['state'] in {'imported', 'failed', 'partial'}
            task = self.controller.task(task_id)
            self.check('Bilibili downloaded and imported', task['state'] == 'imported', task)
            manifest_path = Path(task['directory'])/'download.2byte-download.json'
            bundle = load_bundle(manifest_path, verify_media=True)
            self.check('Bilibili media and platform preserved', bundle['manifest']['platform'] == 'BiliBili' and bool(bundle['media_path']))
            self.result['bilibili_manifest'] = str(manifest_path)
            page = self.controller.page()
            self.check('Studio opened with downloaded media', page is not None and page.project is not None)
            dialog.hide()
            yield .5
            self.shot('02-bilibili-studio', window)
            self.controller.quick_paste(page, 'https://b23.tv/BV1JZnr6TEMd')
            yield lambda: self.controller.card.state in {'ready', 'error'}
            card = self.controller.card
            self.check('Bilibili short link in quick card', card.state == 'ready', card.status.text())
            self.check('short link resolves same part', card.catalog['video_id'] == catalog['video_id'])
            if card.catalog['subtitle_status'] == 'incomplete':
                self.check('quick card preserves subtitle uncertainty',
                    '不完整' in card.summary.text() and 'Cookie' in card.chip_layout.itemAt(0).widget().text())
            yield .4  # allow the native window and layout to paint the ready state
            self.check('quick summary fits', card.summary.fontMetrics().horizontalAdvance(card.summary.text()) < card.summary.width())
            self.shot('03-bilibili-quick-card', card)
            self.controller.quick_paste(page, 'https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4')
            yield lambda: self.controller.card.state in {'ready', 'error'}
            card = self.controller.card
            self.check('other site in quick card', card.state == 'ready', card.status.text())
            self.check('generic unknown codec selectable', card.video_format.count() == 1)
            yield .4
            self.shot('04-other-site-quick-card', card)
            QTest.mouseClick(card.download_button, Qt.MouseButton.LeftButton)
            yield lambda: len(self.controller.queue.snapshots()) == 2
            generic_id = self.controller.queue.snapshots()[-1]['task_id']
            yield lambda: self.controller.task(generic_id)['state'] in {'imported', 'failed', 'partial'}
            generic = self.controller.task(generic_id)
            self.check('generic downloaded and imported', generic['state'] == 'imported', generic)
            generic_manifest = Path(generic['directory'])/'download.2byte-download.json'
            other = load_bundle(generic_manifest, verify_media=True)
            self.check('generic receipt keeps platform', other['manifest']['platform'] == 'Generic')
            self.result['generic_manifest'] = str(generic_manifest)
            saved = save_project(page.project, out/'multisite.2byteproj')
            reopened = load_project(saved)
            self.check('project save and reload keeps identity', reopened.project_id == page.project.project_id)
            self.shot('05-imported-project', window)

        def finish(self):
            self.timer.stop()
            window.result_exit_code = 0 if self.result['passed'] else 1
            def write():
                (out/'link-download.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), 'utf-8')
            write()
            def stopped():
                self.result['gui_shutdown'] = True
                write()
            QApplication.instance().aboutToQuit.connect(stopped)
            controller = getattr(window, '_link_download_controller', None)
            if controller:
                controller.shutdown()
                for widget in (controller.dialog, controller.card):
                    if widget:
                        widget.hide()
            page = window.built_page('studio')
            if page and page.project:
                page.undo_stack.setClean()
            QTimer.singleShot(100, window.close)

    window._link_multisite_audit = Audit()
