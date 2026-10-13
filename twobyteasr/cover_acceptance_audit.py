"""Offline, in-process source/frozen acceptance through real Qt controls."""
import copy
import hashlib
import json
import os
from pathlib import Path
import time
import traceback

from PySide6.QtCore import QEvent, QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QColor, QImage, QInputMethodEvent, QPainter, QPainterPath, QPen
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QFileDialog, QPushButton

from .studio_acceptance_audit import require


def start(window, out):
    def run():
        from .build_identity import load_build_identity
        import psutil
        report = dict(passed=False, checks={}, frames=[], exports=[], resources=[], build=load_build_identity().to_dict())
        started = time.perf_counter()
        page = window.studio_page
        editor = None
        timers = []
        process = psutil.Process()
        def pump(seconds):
            end = time.monotonic()+seconds
            while time.monotonic() < end:
                QApplication.processEvents()
                time.sleep(.004)
        def wait(predicate, timeout=90):
            end = time.monotonic()+timeout
            while not predicate() and time.monotonic() < end:
                pump(.02)
            require(predicate(), 'Timed out: '+str(predicate))
        def check(name, value):
            report['checks'][name] = bool(value)
            (out/'cover-progress.json').write_text(json.dumps(report['checks'], ensure_ascii=False, indent=2), encoding='utf-8')
            require(value, name)
        def resources(label):
            report['resources'].append(dict(label=label, seconds=time.perf_counter()-started,
                rss_bytes=process.memory_info().rss, handles=process.num_handles(), threads=process.num_threads(),
                children=[{'name': p.name(), 'pid': p.pid} for p in process.children(recursive=True)]))
        def action(key):
            QTest.mouseClick(editor.toolbar.widgetForAction(editor.cover_actions[key]), Qt.LeftButton)
            pump(.06)
        def fill_dialog(path):
            timer = QTimer(window)
            timers.append(timer)
            timer.setInterval(200)
            state = {'dialog': None, 'tries': 0}
            def fill():
                dialog = QApplication.activeModalWidget()
                if isinstance(dialog, QFileDialog):
                    state['tries'] += 1
                    if state['dialog'] is not dialog:
                        state['dialog'] = dialog
                        dialog.setDirectory(str(Path(path).parent))
                    else:
                        # QFileSystemModel loads asynchronously; selecting an
                        # absolute file before directoryLoaded clears the name.
                        from PySide6.QtWidgets import QLineEdit
                        field = dialog.findChild(QLineEdit, 'fileNameEdit')
                        if field is not None:
                            field.setText(Path(path).name)
                        else:
                            dialog.selectFile(Path(path).name)
                        dialog.accept()
                        if not dialog.isVisible():
                            timer.stop()
                    if state['tries'] > 30:
                        dialog.reject();timer.stop()
            timer.timeout.connect(fill)
            timer.start()
        def export_by_ui(path, jpeg=False):
            timer = QTimer(window)
            timers.append(timer)
            timer.setInterval(30)
            def fill():
                dialog = QApplication.activeModalWidget()
                if isinstance(dialog, QDialog) and dialog.windowTitle() == '导出封面图片':
                    timer.stop()
                    from PySide6.QtWidgets import QComboBox
                    dialog.findChild(QComboBox).setCurrentIndex(1 if jpeg else 0)
                    fill_dialog(path)
                    QTest.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok), Qt.LeftButton)
            timer.timeout.connect(fill)
            timer.start()
            action('export')
            wait(lambda: not editor.busy)
            check('export_'+Path(path).name, Path(path).is_file() and editor.last_export == str(path))
        def text_input(text):
            editor.text_edit.setFocus()
            editor.text_edit.selectAll()
            for index, line in enumerate(text.split('\n')):
                if index:
                    QTest.keyClick(editor.text_edit, Qt.Key_Return)
                preedit = QInputMethodEvent('zhongwen', [])
                QApplication.sendEvent(editor.text_edit, preedit)
                event = QInputMethodEvent()
                event.setCommitString(line)
                QApplication.sendEvent(editor.text_edit, event)
            pump(.12)
            check('ime_preedit_cleared', not editor.text_edit.document().firstBlock().layout().preeditAreaText())
        def number(widget, value):
            widget.setFocus()
            widget.selectAll()
            QTest.keyClicks(widget, str(value))
            QTest.keyClick(widget, Qt.Key_Return)
            pump(.05)
        def select_layers(*ids):
            editor.layers.clearSelection()
            for index, key in enumerate(ids):
                item = next(editor.layers.item(n) for n in range(editor.layers.count()) if editor.layers.item(n).data(Qt.UserRole) == key)
                QTest.mouseClick(editor.layers.viewport(), Qt.LeftButton,
                    Qt.ControlModifier if index else Qt.NoModifier, editor.layers.visualItemRect(item).center())
            pump(.03)
        def drag(key, delta):
            point = editor.view.mapFromScene(editor.view.items_by_id[key].sceneBoundingRect().center())
            QTest.mousePress(editor.view.viewport(), Qt.LeftButton, pos=point)
            for i in range(1, 11):
                QTest.mouseMove(editor.view.viewport(), point+QPoint(round(delta.x()*i/10), round(delta.y()*i/10)), delay=8)
            QTest.mouseRelease(editor.view.viewport(), Qt.LeftButton, pos=point+delta)
            pump(.03)
        try:
            QApplication.setAttribute(Qt.AA_DontUseNativeDialogs, True)
            wait(lambda: page.project is not None and page._readiness.ready)
            page._set_volume(0)
            page.video.set_paused(True)
            window.resize(1500, 920)
            window.move(20, 20)
            pump(.3)
            resources('studio_before')
            # A real transparent PNG, intentionally supplied as a file so the
            # import/relink/save flow exercises alpha and original asset bytes.
            sticker = QImage(380, 240, QImage.Format_ARGB32_Premultiplied)
            sticker.fill(Qt.transparent)
            painter = QPainter(sticker)
            painter.setRenderHint(QPainter.Antialiasing)
            arrow = QPainterPath(QPointF(45, 25))
            arrow.lineTo(65, 152);arrow.lineTo(104, 120);arrow.cubicTo(176, 196, 262, 200, 338, 207)
            arrow.cubicTo(276, 151, 209, 118, 155, 76);arrow.lineTo(194, 43);arrow.closeSubpath()
            painter.setBrush(QColor('#ffcb50'));painter.setPen(QPen(QColor('#fff8e1'), 10, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPath(arrow);painter.end()
            sticker_path = out/'透明指示贴图.png';sticker.save(str(sticker_path))
            # Preserve an actual unsaved Studio edit and undo history.
            if page.project.cues:
                page.cue_controller.set_text(page.project.cues[0].id, page.project.cues[0].text+' · 编辑保留')
            page._seek(8.25)
            click_ms = int(page.timeline.playhead_ms)
            original_cues = copy.deepcopy(page.project.to_dict()['cues'])
            undo_index = page.undo_stack.index()
            original_project = page.project
            original_range = copy.deepcopy(page.project.studio_state)
            page.cover_controller.settings.setValue('cover/subtitles', False)
            QTest.mouseClick(page.make_cover_button, Qt.LeftButton)
            wait(lambda: page.cover_controller.editor is not None and not page.cover_controller.busy, 120)
            editor = page.cover_controller.editor
            editor.resize(1250, 810)
            editor.move(25, 25)
            pump(.3)
            report['dpi'] = editor.devicePixelRatioF()
            report['frames'].append(page.cover_controller.last_receipt)
            check('actual_studio_cover_entry', editor.isVisible())
            check('immediate_seek_frozen', abs(editor.session.document.source['milliseconds']-click_ms) < 60)
            check('high_resolution_base', (editor.session.document.width, editor.session.document.height) == (2560, 1440))
            check('base_locked', editor.session.document.layers[0].locked)
            check('settings_isolated', Path(editor.settings.fileName()).is_relative_to(out))
            fill_dialog(sticker_path);action('image');wait(lambda: not editor.busy)
            image_id = next(iter(editor.session.selected))
            layer = editor.session.document.layer(image_id)
            check('transparent_image_added', len(editor.session.document.layers) == 2 and layer.asset in editor.session.document.assets)
            item = editor.view.items_by_id[image_id]
            point = editor.view.mapFromScene(item.sceneBoundingRect().center())
            old_x = layer.x
            drag_times = []
            QTest.mousePress(editor.view.viewport(), Qt.LeftButton, pos=point)
            for index in range(1, 21):
                before = time.perf_counter()
                QTest.mouseMove(editor.view.viewport(), point+QPoint(index*4, -index*2), delay=8)
                QApplication.processEvents()
                drag_times.append((time.perf_counter()-before)*1000)
            QTest.mouseRelease(editor.view.viewport(), Qt.LeftButton, pos=point+QPoint(80, -40))
            check('mouse_move', editor.session.document.layer(image_id).x > old_x)
            item = editor.view.items_by_id[image_id]
            bounds = item.sceneBoundingRect();anchor = bounds.topLeft();corner = editor.view.mapFromScene(bounds.bottomRight())
            previous_count = editor.session.undo.count()
            QTest.mousePress(editor.view.viewport(), Qt.LeftButton, pos=corner)
            QTest.mouseMove(editor.view.viewport(), corner+QPoint(42, 28), delay=30)
            QTest.mouseRelease(editor.view.viewport(), Qt.LeftButton, pos=corner+QPoint(42, 28))
            layer = editor.session.document.layer(image_id)
            check('corner_scaling_anchor', layer.width > bounds.width() and abs(layer.x-anchor.x()) < .01 and abs(layer.y-anchor.y()) < .01)
            check('drag_single_undo', editor.session.undo.count() == previous_count+1)
            scaled_width = layer.width
            action('undo');action('redo')
            check('undo_redo', abs(editor.session.document.layer(image_id).width-scaled_width) < .01)
            report['drag_event_ms'] = dict(median=sorted(drag_times)[len(drag_times)//2], p95=sorted(drag_times)[-2], maximum=max(drag_times))
            # Arrange the sticker using visible numeric fields, then add title.
            number(editor.geometry['x'], 1550);number(editor.geometry['y'], 540)
            action('text');text_input('蓝色星原\n巨刺凶鸟初见')
            title_id = next(iter(editor.session.selected))
            number(editor.geometry['x'], 70);number(editor.geometry['y'], 820)
            number(editor.geometry['width'], 1640);number(editor.text_numbers['size'], 150)
            number(editor.text_numbers['stroke'], 6)
            number(editor.text_numbers['shadow_blur'], 9)
            check('chinese_multiline_ime', editor.session.document.layer(title_id).text == '蓝色星原\n巨刺凶鸟初见')
            QTest.keyClick(editor.text_edit, Qt.Key_A, Qt.ControlModifier)
            QTest.keyClick(editor.text_edit, Qt.Key_Delete)
            pump(.06)
            check('delete_text_not_layer', editor.session.document.layer(title_id) is not None and editor.session.document.layer(title_id).text == '')
            text_input('蓝色星原\n巨刺凶鸟初见')
            prior = [layer.id for layer in editor.session.document.layers]
            down = next(button for button in editor.findChildren(QPushButton) if button.text() == '下移')
            QTest.mouseClick(down, Qt.LeftButton);pump(.1)
            check('layer_reorder', [layer.id for layer in editor.session.document.layers] != prior)
            action('undo')
            # List multi-selection and native graphics dragging must respect locks.
            select_layers(image_id, title_id)
            positions = {key: (editor.session.document.layer(key).x, editor.session.document.layer(key).y) for key in (image_id, title_id)}
            drag(image_id, QPoint(18, -8))
            shifts = [(editor.session.document.layer(key).x-positions[key][0], editor.session.document.layer(key).y-positions[key][1]) for key in positions]
            check('multiselect_mouse_move', abs(shifts[0][0]) > 10 and abs(shifts[0][0]-shifts[1][0]) < .1)
            action('undo');select_layers(image_id)
            editor.scroll.ensureWidgetVisible(editor.locked);pump(.03)
            QTest.mouseClick(editor.locked, Qt.LeftButton, pos=QPoint(8, editor.locked.height()//2));pump(.03)
            check('lock_control_enabled', editor.session.document.layer(image_id).locked)
            locked_pos = editor.session.document.layer(image_id).x
            drag(image_id, QPoint(24, 0))
            check('locked_image_does_not_move', editor.session.document.layer(image_id).x == locked_pos)
            QTest.mouseClick(editor.locked, Qt.LeftButton, pos=QPoint(8, editor.locked.height()//2));pump(.03)
            editor.view.setFocus();QTest.keyClick(editor.view, Qt.Key_D, Qt.ControlModifier);pump(.03)
            check('duplicate_layer', len(editor.session.document.layers) == 4)
            QTest.keyClick(editor.view, Qt.Key_Delete);pump(.03)
            check('delete_layer', len(editor.session.document.layers) == 3)
            action('undo');action('redo')
            from PySide6.QtCore import QMimeData, QUrl
            from PySide6.QtGui import QDragEnterEvent, QDropEvent
            mime = QMimeData();mime.setUrls([QUrl.fromLocalFile(str(sticker_path))])
            enter = QDragEnterEvent(QPoint(100, 100), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            QApplication.sendEvent(editor.view.viewport(), enter)
            drop = QDropEvent(QPointF(100, 100), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            QApplication.sendEvent(editor.view.viewport(), drop);wait(lambda: not editor.busy)
            check('file_drop_adds_image', drop.isAccepted() and len(editor.session.document.layers) == 4)
            action('undo')
            select_layers(title_id)
            editor.name_edit.setText('主标题 · 可继续编辑');QTest.keyClick(editor.name_edit, Qt.Key_Return);pump(.03)
            check('rename_layer', editor.session.document.layer(title_id).name == '主标题 · 可继续编辑')
            item = next(editor.layers.item(n) for n in range(editor.layers.count()) if editor.layers.item(n).data(Qt.UserRole) == title_id)
            item.setCheckState(Qt.Unchecked);pump(.03)
            check('hide_layer', not editor.view.items_by_id[title_id].isVisible());action('undo')
            # Replace the frozen base with an equally sized imported picture, then
            # undo; existing title/sticker identities and transforms must survive.
            preserved = [layer.id for layer in editor.session.document.layers]
            editor.add_images([str(sticker_path)], background=True);wait(lambda: not editor.busy)
            check('replace_base_preserves_layers', [layer.id for layer in editor.session.document.layers] == preserved and editor.session.document.layer(title_id).text.startswith('蓝色星原'))
            action('undo');select_layers(title_id)
            editor.text_edit.clearFocus();editor.view.setFocus();pump(.2)
            editor.grab().save(str(out/'cover-editor.png'))
            check('sidebar_canvas_usable', editor.view.width() >= 500 and editor.scroll.width() >= 250)
            doc_path = out/'示例封面.2bytecover'
            fill_dialog(doc_path);action('save');wait(lambda: not editor.busy)
            check('saved_editable_document', doc_path.is_file() and not editor.session.dirty)
            export_by_ui(out/'示例封面.png')
            export_by_ui(out/'示例封面.jpg', jpeg=True)
            png = QImage(str(out/'示例封面.png'));jpg = QImage(str(out/'示例封面.jpg'))
            check('full_pixel_exports', png.width() == 2560 and png.height() == 1440 and jpg.size() == png.size())
            # Export on a 20% viewport must stay exactly identical.
            editor.view.set_zoom(.2)
            export_by_ui(out/'viewport-independent.png')
            check('viewport_does_not_change_export', QImage(str(out/'viewport-independent.png')) == png)
            check('image_export_does_not_clean_unsaved', not editor.session.dirty)
            signature = editor.session.document.signature()
            metrics = editor.metrics.copy()
            editor.close();pump(.3);wait(lambda: page.cover_controller.editor is None)
            del editor;editor = None
            # Clean source image; archive must reopen without its imported file.
            sticker_path.unlink()
            editor = page.cover_controller.show_editor()
            editor.open_document(doc_path);wait(lambda: not editor.busy);pump(.15)
            check('reopen_after_source_removed', editor.session.document.signature() == signature)
            check('text_still_editable', editor.session.document.layer(title_id).kind == 'text')
            editor.edit_text(title_id);text_input('蓝色星原\n巨刺凶鸟再挑战')
            editor.export_document(out/'不存在目录'/'失败.png');wait(lambda: not editor.busy)
            check('failed_export_retains_dirty', editor.session.dirty and '失败' in editor.status.text())
            export_by_ui(out/'retry.png')
            check('export_keeps_editable_dirty', editor.session.dirty)
            fill_dialog(out/'继续修改.2bytecover');action('save_as');wait(lambda: not editor.busy)
            check('save_as_preserves_original', doc_path.read_bytes() != (out/'继续修改.2bytecover').read_bytes())
            resources('cover_after_reopen')
            report['editor_metrics'] = metrics+editor.metrics
            editor.close();pump(.3);wait(lambda: page.cover_controller.editor is None);editor = None
            check('studio_same_project', page.project is original_project)
            check('studio_cues_unmodified', page.project.to_dict()['cues'] == original_cues)
            check('studio_undo_preserved', page.undo_stack.index() == undo_index)
            check('studio_playhead_preserved', abs(page.timeline.playhead_ms-click_ms) < 70)
            check('studio_range_selection_preserved', page.project.studio_state == original_range)
            sustain = max(0, min(600, int(os.environ.get('TWOBYTEASR_COVER_SUSTAIN', '0'))))
            if sustain:
                duration_start = time.perf_counter();cycle = 0;report['sustained'] = []
                while time.perf_counter()-duration_start < sustain:
                    editor = page.cover_controller.show_editor()
                    editor.open_document(doc_path);wait(lambda: not editor.busy)
                    select_layers(image_id)
                    for _ in range(8):
                        editor.session.duplicate_selected()
                    editor.view.setFocus();QTest.keyClick(editor.view, Qt.Key_A, Qt.ControlModifier)
                    began = time.perf_counter()
                    key = next(key for key in editor.session.selected if editor.session.document.layer(key).kind == 'image')
                    drag(key, QPoint(16, -6));drag(key, QPoint(-16, 6))
                    drag_elapsed = time.perf_counter()-began
                    editor.add_images([str(out/'示例封面.png')], background=True);wait(lambda: not editor.busy)
                    editor.save_document(out/'持续修改.2bytecover');wait(lambda: not editor.busy)
                    editor.export_document(out/'持续导出.png');wait(lambda: not editor.busy)
                    editor.export_document(out/'持续导出.jpg');wait(lambda: not editor.busy)
                    report['sustained'].append(dict(cycle=cycle, layers=len(editor.session.document.layers), drag_seconds=drag_elapsed, metrics=editor.metrics.copy()))
                    editor.close();pump(.15);wait(lambda: page.cover_controller.editor is None);editor=None
                    page._toggle_playback();pump(.35);page.video.set_paused(True)
                    if cycle % 4 == 0:
                        resources('sustained_'+str(cycle))
                    cycle += 1
                report['sustain_elapsed_seconds'] = time.perf_counter()-duration_start
                check('sustained_cycles', cycle >= 3)
            if os.environ.get('TWOBYTEASR_COVER_QUICK') != '1':
                # Repeated full-resolution capture/open/close in this process.
                for index, stamp in enumerate((4.49, 4.51, 8.25)):
                    page._seek(stamp)
                    QTest.mouseClick(page.make_cover_button, Qt.LeftButton)
                    wait(lambda: page.cover_controller.editor is not None and not page.cover_controller.busy, 120)
                    editor = page.cover_controller.editor
                    report['frames'].append(page.cover_controller.last_receipt)
                    editor.session.saved_signature = editor.session.document.signature()
                    editor.close();pump(.2);wait(lambda: page.cover_controller.editor is None);editor = None
                    resources('capture_cycle_'+str(index))
                frames = out/'frames';frames.mkdir()
                page.frame_capture.settings.setValue('frame_export/directory', str(frames))
                page.frame_capture.settings.setValue('frame_export/subtitles', True)
                page.frame_capture.last = None
                QTest.mouseClick(page.save_frame_button, Qt.LeftButton)
                wait(lambda: not page.frame_capture.busy, 120)
                check('same_process_save_frame', page.frame_capture.last is not None)
                report['frames'].append(page.frame_capture.last)
                page._toggle_playback();pump(1.4);page.video.set_paused(True)
                check('studio_play_after_cover', page.timeline.playhead_ms > 8500)
                from .project_range import set_range
                set_range(page.project, 7500, 10000)
                QTest.mouseClick(page.studio_render_button, Qt.LeftButton)
                wait(lambda: page.export_workspace is not None)
                ui = page.export_workspace;pump(.3)
                (out/'video').mkdir()
                ui.directory.setText(str(out/'video'));ui.filename.setText('cover-return-range')
                ui.filename_prefix.clear();ui.filename_suffix.clear()
                ui.resolution.setCurrentIndex(ui.resolution.findData((1280,720)))
                if ui.encoder.findData('libx264') < 0:
                    ui.encoder.addItem('Software x264', 'libx264')
                ui.encoder.setCurrentIndex(ui.encoder.findData('libx264'))
                began = time.perf_counter();QTest.mouseClick(ui.export_button, Qt.LeftButton)
                wait(lambda: ui._last_job is not None);wait(lambda: not ui._running, 160)
                check('same_process_range_export', ui.pages.currentWidget() == ui.success_page)
                report['exports'].append(dict(path=ui._last_job.output_path, elapsed_seconds=time.perf_counter()-began,
                                              metadata=ui._last_job.completion_metadata))
            resources('end')
            report['passed'] = True
        except Exception:
            report['error'] = traceback.format_exc()
        finally:
            for timer in timers:
                timer.stop()
            if editor:
                editor.grab().save(str(out/'cover-failure.png'))
                editor.session.saved_signature = editor.session.document.signature()
                editor.close()
            report['elapsed_seconds'] = time.perf_counter()-started
            window.grab().save(str(out/'studio-return.png'))
            (out/'cover-runtime.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
            page.video.set_paused(True);page.undo_stack.setClean();window.close()
    QTimer.singleShot(600, run)
