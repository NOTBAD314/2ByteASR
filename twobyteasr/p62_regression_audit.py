"""Opt-in P6.2 regression through the normal isolated source/frozen window."""
from pathlib import Path
import json
import time
import traceback


def start(window, output):
    from PySide6.QtCore import QObject, QTimer
    from PySide6.QtWidgets import QApplication
    from .build_identity import load_build_identity
    from .studio_edit_sequence import sequence_of
    from .studio_project import load_project

    class Audit(QObject):
        def __init__(self):
            super().__init__(window)
            self.page = window.studio_page
            self.result = dict(build=vars(load_build_identity()), checks={}, phases=[])
            self.started = time.perf_counter()
            self.sequence = self.run()
            self.waiting = 0.
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(25)

        def check(self, name, value):
            self.result['checks'][name] = bool(value)
            if not value:
                raise AssertionError(name)

        def tick(self):
            try:
                now = time.perf_counter()
                if now-self.started > 120:
                    raise TimeoutError('P6.2 normal-entry regression deadline')
                if callable(self.waiting):
                    if not self.waiting(): return
                elif now < self.waiting:
                    return
                step = next(self.sequence)
                self.waiting = step if callable(step) else time.perf_counter()+step
            except StopIteration:
                self.finish()
            except Exception:
                self.result['error'] = traceback.format_exc()
                self.finish()

        def run(self):
            page = self.page
            media = output/'ingest-source.mp4'
            xml = media.with_suffix('.xml')
            page.video.set_paused(True)
            previous_project = page.project
            page._create_blank_studio()
            yield lambda: (page.project is not previous_project and not page.project.media.path
                           and not getattr(page._readiness, 'active', False))
            page.session.project_path = output/'edited.2byteproj'
            self.check('blank_project', page.project is not None and not page.project.media.path)
            before = time.perf_counter()
            page._open_or_create_media_project(media)
            self.result['ingest_dispatch_ms'] = (time.perf_counter()-before)*1000
            yield lambda: page._media_ingest_state in {'READY', 'ERROR'}
            self.check('ingest_ready', page._media_ingest_state == 'READY')
            self.check('native_player_running', page.video.controller and page.video.controller.running)
            self.check('real_media_identity', page.project.media.duration_ms > 10000 and page.project.media.width == 1920)
            yield lambda: page.timeline.waveform_state in {'READY', 'ERROR'}
            self.check('waveform_ready', page.timeline.waveform_state == 'READY' and page.timeline.cache is not None)
            sequence = sequence_of(page.project)
            self.result['xml_match'] = dict(mode=page.project.studio_state.get('media_xml_match'), path=sequence.danmaku_path)
            self.check('same_stem_xml_paired', Path(sequence.danmaku_path).resolve() == xml.resolve())
            self.check('video_initially_locked', sequence.video_track_locked)
            initial = len(sequence.segments)
            for point in range(1000, 11000, 1000):
                page._razor_video_at(point)
            self.check('locked_razor_no_change', len(sequence_of(page.project).segments) == initial)
            page._toggle_video_lock()
            self.check('unlock', not sequence_of(page.project).video_track_locked)
            for point in range(1000, 11000, 1000):
                page._razor_video_at(point)
                yield .03
            cut = len(sequence_of(page.project).segments)
            self.check('ten_razors', cut == initial+10)
            page.undo_stack.undo()
            self.check('undo', len(sequence_of(page.project).segments) == cut-1)
            page.undo_stack.redo()
            self.check('redo', len(sequence_of(page.project).segments) == cut)
            page._toggle_video_lock()
            page._razor_video_at(15000)
            self.check('relock_blocks_razor', sequence_of(page.project).video_track_locked and len(sequence_of(page.project).segments) == cut)
            page.save()
            saved_path = Path(page.project_path)
            self.check('saved_inside_audit', saved_path.resolve().is_relative_to(output.resolve()) and saved_path.is_file())
            restored = sequence_of(load_project(saved_path))
            self.check('saved_graph_and_xml', len(restored.segments) == cut and Path(restored.danmaku_path).resolve() == xml.resolve())
            previous_project = page.project
            self.reopened_ready = False
            page.open_project(saved_path, on_ready=lambda: setattr(self, 'reopened_ready', True))
            yield lambda: self.reopened_ready
            self.check('reopen_loaded_new_object', page.project is not previous_project)
            self.check('reopen_native_ready', page.video.controller and page.video.controller.running)
            reopened = sequence_of(page.project)
            self.check('reopened_graph_and_lock', len(reopened.segments) == cut and reopened.video_track_locked)
            self.check('reopened_xml', Path(reopened.danmaku_path).resolve() == xml.resolve())
            page.video.set_paused(True)
            page.timeline.update()
            yield lambda: bool(page.timeline._thumbnails.memory)
            self.result['filmstrip'] = dict(entries=len(page.timeline._thumbnails.memory), metrics=dict(page.timeline._thumbnails.metrics))
            self.check('real_thumbnail_pixels', any(not pixmap.isNull() for pixmap in page.timeline._thumbnails.memory.values()))
            yield .4
            self.check('qt_screenshot', window.grab().save(str(output/'studio-qt.png')))
            page.video.controller.screenshot_to_file(output/'native-video.png')
            yield .3
            self.check('native_screenshot', (output/'native-video.png').is_file())

        def finish(self):
            self.timer.stop()
            self.result['elapsed_seconds'] = time.perf_counter()-self.started
            self.result['passed'] = not self.result.get('error') and all(self.result['checks'].values())
            (output/'result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2), encoding='utf8')
            self.page.undo_stack.setClean()
            self.page.close_page()
            window.hide()
            QTimer.singleShot(300, QApplication.instance().quit)

    window._p62_regression_audit = Audit()
