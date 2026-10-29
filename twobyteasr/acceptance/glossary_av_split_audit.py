"""Real-window check: terms with symbols, deleting built-in libraries, source
preview and picture / sound drags in the workbench (2026-10-25).

Runs only for ``TWOBYTEASR_ACCEPTANCE_SCENARIO=glossary-av-split`` (isolated
data; ``scripts/verify_glossary_av_split_headed.py``, source or frozen). The
runner makes three files (``TWOBYTEASR_GLOSSARY_AV``: an empty project, a main
MP4, a second MP4 and a WAV). In the real window this scenario:

1. 术语库: creates a library, adds 漂泊者·男 (heard as 漂泊者难), Re:Zero and
   洛克王国：世界 through the input row; the saved rows and the table keep the
   symbols and the confirmed spelling reads 漂泊者男 back as 漂泊者·男;
2. right-clicks a built-in library in the list, deletes it through the
   confirm sheet (it leaves the list, the built-in file is untouched) and
   restores it from 新建 → 恢复自带词库;
3. 工作台: imports the main MP4, adds the other two files to the media pool,
   double-clicks a pool row: the source plays in the cue-list slot and the
   project pauses; the project playing pauses the source;
4. drops the picture only, the sound only and both (the drop preview shows
   where each lands) and checks the clips; right-clicks the both clip,
   picks 分离音频, moves the picture alone; undo / redo; saves, opens another
   project (the preview closes) and the saved one again (loaded from disk).

Drops are Qt drag events sent to the page at real lane positions (a hidden
desktop has no mouse for the system drag loop); the drag sources are checked
separately. Nothing contacts the network.
"""
from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path


def start(window, output: Path):
    from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
    from PySide6.QtGui import QContextMenuEvent, QDragEnterEvent, QDragMoveEvent, QDropEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMenu, QMessageBox, QPushButton
    app = QApplication.instance()
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads(os.environ['TWOBYTEASR_GLOSSARY_AV'])
    result = dict(checks=[], metrics={}, errors=[], dialogs=[], passed=False, pid=os.getpid(),
                  executable=os.path.realpath(__import__('sys').executable))

    def save_result():
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), 'utf-8')

    def check(name, ok, detail=None):
        result['checks'].append(dict(name=name, passed=bool(ok), detail=detail))
        save_result()
        return bool(ok)

    def settle(ms=300):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    def wait_for(predicate, timeout=40.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            app.processEvents()
            try:
                if predicate():
                    return True
            except Exception:  # noqa: BLE001 - keep polling
                pass
            time.sleep(0.05)
        return False

    def grab(widget, name):
        try:
            widget.grab().save(str(output / f'{name}.png'))
        except Exception as exc:  # noqa: BLE001
            result['errors'].append(f'grab {name}: {exc!r}')

    def capture(name):
        # The whole window with mpv's native pictures (a widget grab leaves them black).
        from .blank_project_audit import _capture
        try:
            _capture(window, output / f'{name}.png')
        except Exception as exc:  # noqa: BLE001
            result['errors'].append(f'capture {name}: {exc!r}')
        return output / f'{name}.png'

    def picture_spread(path, widget):
        # Brightness spread inside ``widget`` on a window capture (0 = flat black).
        from PySide6.QtGui import QImage
        image = QImage(str(path))
        if image.isNull():
            return 0.0
        scale = image.width() / max(1, window.width())
        origin = widget.mapTo(window, QPoint(0, 0))
        values = []
        for gx in range(1, 12):
            for gy in range(1, 8):
                x = round((origin.x() + widget.width() * gx / 12) * scale)
                y = round((origin.y() + widget.height() * gy / 8) * scale)
                if 0 <= x < image.width() and 0 <= y < image.height():
                    values.append(image.pixelColor(x, y).lightness())
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        return (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5

    def handle_boxes():
        for widget in app.topLevelWidgets():
            if isinstance(widget, QMessageBox) and widget.isVisible():
                result['dialogs'].append(dict(title=widget.windowTitle(), text=widget.text()))
                widget.done(0)

    watchdog = QTimer()
    watchdog.timeout.connect(handle_boxes)
    watchdog.start(300)

    # ------------------------------------------------------------ 术语库

    def run_glossary():
        legacy = window.legacy
        window._manage_terms()
        settle(800)
        page = window.term_library_page._ensure_library()
        settle(500)
        page.sidebar_new_button.click()
        settle(200)
        page.game_input.insert('符号验收')
        page.add_game_button.click()
        settle(500)
        key = page._library_key()
        check('new library created and selected', page.state.get('game') == '符号验收', key)
        for heard, written in (('漂泊者难', '漂泊者·男'), ('', 'Re:Zero'), ('', '洛克王国：世界')):
            page.term_alias_editor.clear()
            page.term_editor.clear()
            if heard:
                page.term_alias_editor.insert(heard)
            page.term_editor.insert(written)
            QTest.mouseClick(page.add_term_button, Qt.MouseButton.LeftButton)
            settle(500)
        rows = {(row['from'], row['to']) for row in legacy.learned_mappings_for_game(key)}
        check('saved rows keep the symbols',
              {('漂泊者·男', '漂泊者·男'), ('漂泊者难', '漂泊者·男'), ('Re:Zero', 'Re:Zero'),
               ('洛克王国：世界', '洛克王国：世界')} <= rows, sorted(rows))
        model = page.listing.model()
        shown = {str(model.data(model.index(r, c))) for r in range(model.rowCount()) for c in range(model.columnCount())}
        check('the term table shows the symbols',
              any('漂泊者·男' in text for text in shown) and any('Re:Zero' in text for text in shown)
              and any('洛克王国：世界' in text for text in shown), sorted(shown)[:30])
        grab(page, 'glossary_symbol_terms')
        from ..glossary.terminology import TermResolver, snapshot_glossaries
        resolver = TermResolver(snapshot_glossaries(legacy, (key,)))
        check('the confirmed spelling reads 漂泊者男 / 漂泊者难 back as 漂泊者·男',
              resolver.resolve('我是漂泊者男').text == '我是漂泊者·男'
              and resolver.resolve('漂泊者难来了').text == '漂泊者·男来了',
              [resolver.resolve('我是漂泊者男').text, resolver.resolve('漂泊者难来了').text])

        # A built-in library, deleted from the list and restored.
        names = [str(page.game_list.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(page.game_list.count())]
        builtin = next((n for n in names if page._game_identity(n) in page.protected_game_ids), '')
        check('a built-in library is listed', builtin, names)
        if not builtin:
            return
        profiles_before = Path(legacy.GAME_PROFILES_PATH).read_bytes()
        item = next(page.game_list.item(i) for i in range(page.game_list.count())
                    if page.game_list.item(i).data(Qt.ItemDataRole.UserRole) == builtin)
        page.game_list.scrollToItem(item)
        settle(300)
        row = page.game_list.itemWidget(item)
        point = row.rect().center()
        QApplication.sendEvent(row, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, row.mapToGlobal(point)))
        settle(500)
        menu = getattr(page, '_game_menu', None)
        texts = [a.text() for a in menu.actions() if a.text()] if menu else []
        check('right click on a built-in library offers 删除词库…, not 改名',
              menu is not None and menu.isVisible() and '删除词库…' in texts and '改名…' not in texts, texts)
        if menu is not None:
            grab(menu, 'glossary_builtin_menu')
            menu.hide()
            next(a for a in menu.actions() if a.text() == '删除词库…').trigger()
        settle(500)
        sheet = getattr(page, '_del_game_sheet', None)
        sheet_text = ' '.join(label.text() for label in sheet.findChildren(QLabel)) if sheet else ''
        check('the confirm sheet says it is built-in and how to restore it',
              sheet is not None and sheet.isVisible() and '软件自带' in sheet_text and '恢复自带词库' in sheet_text,
              sheet_text)
        grab(page, 'glossary_builtin_confirm')
        if sheet is not None:
            button = next(b for b in sheet.findChildren(QPushButton) if b.text() == '删除')
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        settle(800)
        names = [str(page.game_list.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(page.game_list.count())]
        check('the built-in library left the list and is hidden',
              builtin not in names and legacy.is_runtime_game_profile_hidden(builtin), names)
        check('the built-in profile file is unchanged', Path(legacy.GAME_PROFILES_PATH).read_bytes() == profiles_before)
        page.sidebar_new_button.click()
        settle(400)
        check('新建 offers 恢复自带词库（1）', page.restore_builtin_button.isVisible()
              and '1' in page.restore_builtin_button.text(), page.restore_builtin_button.text())
        QTest.mouseClick(page.restore_builtin_button, Qt.MouseButton.LeftButton)
        settle(500)
        popup = page.restore_builtin_popup
        grab(popup, 'glossary_restore_popup')
        choice = next((b for b in popup.findChildren(QPushButton) if b.text() == builtin), None)
        check('the restore list names the deleted library', popup.isVisible() and choice is not None)
        if choice is not None:
            QTest.mouseClick(choice, Qt.MouseButton.LeftButton)
        settle(800)
        names = [str(page.game_list.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(page.game_list.count())]
        check('restored: back in the list, selected, not hidden',
              builtin in names and page.state.get('game') == builtin
              and not legacy.is_runtime_game_profile_hidden(builtin), names)
        grab(page, 'glossary_restored')

    # ------------------------------------------------------------ 工作台

    def page_of():
        return window._studio_page_instance

    def pause(studio):
        try:
            studio.video.set_paused(True)
            studio._sync_play_button(True)
        except Exception:  # noqa: BLE001
            pass

    def open_project(path):
        ready = {'v': False}
        window.open_studio_project(str(path), mode='edit', source='startup_audit',
                                   on_ready=lambda *a, **k: ready.__setitem__('v', True))
        wait_for(lambda: ready['v'], 90)
        settle(1500)
        studio = page_of()
        pause(studio)
        return studio

    def asset_id(studio, name):
        return next(a.asset_id for a in studio.project.media_pool if a.display_name == name)

    def lane_point(studio, kind, track_id, ms):
        timeline = studio.timeline
        rects = timeline._video_track_rects() if kind == 'video' else timeline._audio_track_rects()
        row = rects[track_id]
        local = QPoint(round(timeline._time_to_x(ms)) + 3, round(row.center().y()))
        return timeline.mapTo(studio, local)

    def drop(studio, mime, point, tag):
        """Qt drag events at a page point, as the system drag loop sends them."""
        actions = Qt.DropAction.CopyAction
        enter = QDragEnterEvent(point, actions, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(studio, enter)
        move = QDragMoveEvent(point, actions, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(studio, move)
        settle(200)
        preview = dict(studio.timeline._media_drop_preview or {})
        grab(studio.timeline, f'{tag}_preview')
        before = studio.undo_stack.count()
        QApplication.sendEvent(studio, QDropEvent(QPointF(point), actions, mime, Qt.MouseButton.LeftButton,
                                                  Qt.KeyboardModifier.NoModifier))
        settle(600)
        grab(studio.timeline, f'{tag}_dropped')
        return move.isAccepted(), preview, studio.undo_stack.count() - before

    def double_click(widget, pos):
        """The events Windows sends (QTest.mouseDClick never reaches itemDoubleClicked)."""
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QMouseEvent
        global_pos = QPointF(widget.mapToGlobal(pos))
        for kind, buttons in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                              (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
                              (QEvent.Type.MouseButtonDblClick, Qt.MouseButton.LeftButton),
                              (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
            QApplication.sendEvent(widget, QMouseEvent(kind, QPointF(pos), global_pos, Qt.MouseButton.LeftButton,
                                                       buttons, Qt.KeyboardModifier.NoModifier))
            settle(30)

    def vt(studio, track_id):
        # Undoable media edits swap in new track objects: always look up by id.
        return next((t for t in studio.project.video_tracks if t.id == track_id), None)

    def lane_of(studio, video_track_id):
        return next((g.audio_track_id for g in studio.project.av_track_groups
                     if g.linked and g.video_track_id == video_track_id), '')

    def run_workbench():
        from ..studio.studio_source_monitor import media_part_mime
        from ..timeline.studio_media_pool import linked_audio_clip
        studio = open_project(config['project'])
        check('empty project opened', studio is not None and studio.project is not None)
        studio._begin_media_drop([config['main']], 0)
        check('main MP4 imported', wait_for(lambda: len(studio.project.media_pool) >= 1
                                             and studio.project.video_tracks and studio.project.video_tracks[0].clips, 90))
        settle(1500)
        for name in ('clip', 'song'):
            count = len(studio.project.media_pool)
            studio.project_controller._attach_media_to_current(Path(config[name]), add_to_timeline=False)
            check(f'{Path(config[name]).name} added to the media pool',
                  wait_for(lambda: len(studio.project.media_pool) > count, 90))
            settle(800)
        pause(studio)
        studio.timeline.set_visible_window(0, 16000)
        settle(400)
        studio._toggle_drawer(studio.media_pool_tab_index)
        if not studio.context_panel.isVisible():
            studio._set_major_panel_visible('context', True)
        settle(600)
        tree = studio.media_pool_panel.assets
        item = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                    if tree.topLevelItem(i).text(0) == Path(config['clip']).name)
        tree.scrollToItem(item)
        rect = tree.visualItemRect(item)
        double_click(tree.viewport(), rect.center())
        settle(800)
        monitor = getattr(studio, 'source_monitor', None)
        check('double-click shows the source where the cue list is',
              monitor is not None and studio.cue_list_stack.currentWidget() is monitor and monitor.isVisible()
              and monitor.title.text() == Path(config['clip']).name)
        loaded = wait_for(lambda: monitor.canvas is not None and monitor.canvas.controller is not None, 30)
        check('the preview player loaded the source', loaded)
        monitor.canvas.seek(1.0)
        settle(1500)
        shot = capture('workbench_source_preview')
        spread = picture_spread(shot, monitor.canvas)
        result['metrics']['preview_picture_spread'] = round(spread, 1)
        check('the preview shows the picture (not a flat frame)', spread > 8, round(spread, 1))
        before_undo = studio.undo_stack.count()
        studio.video.set_paused(False)
        studio._sync_play_button(False)
        settle(800)
        QTest.mouseClick(monitor.play_button, Qt.MouseButton.LeftButton)
        played = wait_for(lambda: monitor.canvas.visual_position() > 0.6, 20)
        check('the source plays and the project pauses', played and studio.video._paused,
              dict(position=monitor.canvas.visual_position(), project_paused=studio.video._paused))
        capture('workbench_source_playing')
        studio._toggle_playback()
        check('playing the project pauses the source', wait_for(lambda: monitor.canvas._paused, 10))
        pause(studio)
        settle(400)
        check('previewing did not edit the project', studio.undo_stack.count() == before_undo)

        # Drag sources: the chips and the pool rows carry the source and its part.
        from ..studio import studio_source_monitor as source_monitor
        started = []
        real_start = source_monitor.start_media_part_drag
        source_monitor.start_media_part_drag = lambda widget, aid, part='both': started.append((aid, part))
        try:
            chip = monitor.chips['video']
            QTest.mousePress(chip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(8, 8))
            QTest.mouseMove(chip, QPoint(40, 30))
            QTest.mouseRelease(chip, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(40, 30))
        finally:
            source_monitor.start_media_part_drag = real_start
        clip_id = asset_id(studio, Path(config['clip']).name)
        check('dragging the 仅视频 chip starts a picture-only drag', started == [(clip_id, 'video')], started)
        row_mime = tree.mimeData([item])
        check('a pool row drags the whole source', bytes(row_mime.data(source_monitor.MEDIA_PART_MIME)).decode()
              == json.dumps({'asset_id': clip_id, 'part': 'both'}))
        tracks_before = [t.id for t in studio.project.video_tracks]

        # 1) picture only, dropped on V1 at 2 s: V1 stays the main edit, a new track takes it.
        accepted, preview, steps = drop(studio, media_part_mime(clip_id, 'video'),
                                        lane_point(studio, 'video', tracks_before[0], 2000), 'drop_video_only')
        new_track = next((t for t in studio.project.video_tracks if t.id not in tracks_before), None)
        new_id = new_track.id if new_track else ''
        clip = new_track.clips[0] if new_track and new_track.clips else None
        check('仅视频: the preview showed a new video track and the drop made one clip, one undo step',
              accepted and preview.get('new_video_track') and steps == 1 and clip is not None, preview)
        check('仅视频: no linked audio, silent clip',
              clip is not None and clip.audio_enabled is False
              and linked_audio_clip(studio.project, new_track.id, clip.id) is None
              and not [c for c in next(t for t in studio.project.audio_tracks
                                       if t.id == lane_of(studio, new_track.id)).clips])
        # 2) sound only, dropped on the main A lane where the main sound is: a new audio track.
        song_id = asset_id(studio, Path(config['song']).name)
        a1 = lane_of(studio, tracks_before[0])
        audio_before = [t.id for t in studio.project.audio_tracks]
        accepted, preview, steps = drop(studio, media_part_mime(song_id, 'audio'),
                                        lane_point(studio, 'audio', a1, 1000), 'drop_audio_only')
        new_audio = next((t for t in studio.project.audio_tracks if t.id not in audio_before), None)
        check('仅音频 on a busy lane: a new audio track holds one free clip',
              accepted and preview.get('new_audio_track') and steps == 1 and new_audio is not None
              and [c.linked_video_clip_id for c in new_audio.clips] == [''], preview)
        check('the new audio track is drawn', new_audio is not None and new_audio.id in studio.timeline._audio_track_rects())
        # 3) both, from the pool row, on the new track after the picture-only clip.
        accepted, preview, steps = drop(studio, row_mime, lane_point(studio, 'video', new_id, 9000), 'drop_both')
        both = next((c for c in vt(studio, new_id).clips if c.timeline_in_ms >= 8000), None)
        check('视频+音频 lands on the track under the pointer with its linked audio',
              accepted and preview.get('video_track_id') == new_id and steps == 1 and both is not None
              and linked_audio_clip(studio.project, new_id, both.id) is not None, preview)
        if both is None:
            return
        capture('workbench_three_drops')

        # 4) 分离音频 through a real right click on the clip.
        timeline = studio.timeline
        row = timeline._video_track_rects()[new_id]
        local = QPoint(round((timeline._time_to_x(both.timeline_in_ms) + timeline._time_to_x(both.timeline_out_ms)) / 2),
                       round(row.center().y()))
        seen = {}

        def pick(attempt=0):
            menus = [w for w in app.topLevelWidgets() if isinstance(w, QMenu) and w.isVisible()]
            if not menus:
                if attempt < 40:
                    QTimer.singleShot(100, lambda: pick(attempt + 1))
                return
            menu = menus[-1]
            action = next((a for a in menu.actions() if a.text() == '分离音频'), None)
            seen.update(texts=[a.text() for a in menu.actions() if a.text()],
                        enabled=action.isEnabled() if action else None)
            grab(menu, 'clip_menu_detach')
            menu.close()
            if action is not None and action.isEnabled():
                QTimer.singleShot(0, action.trigger)

        QTimer.singleShot(400, pick)
        QApplication.sendEvent(timeline, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, local,
                                                           timeline.mapToGlobal(local)))
        settle(900)
        both = next(c for c in vt(studio, new_id).clips if c.id == both.id)
        lane = next(t for t in studio.project.audio_tracks if t.id == lane_of(studio, new_id))
        free = [c for c in lane.clips if not c.linked_video_clip_id]
        check('分离音频 is in the clip menu and splits picture and sound',
              seen.get('enabled') and both.audio_enabled is False and len(free) == 1
              and (free[0].timeline_in_ms, free[0].timeline_out_ms) == (both.timeline_in_ms, both.timeline_out_ms),
              dict(seen=seen, free=[(c.timeline_in_ms, c.timeline_out_ms) for c in free]))
        grab(timeline, 'detached')
        from ..timeline.studio_clip_edit import clip_edit_command
        sound_span = (free[0].timeline_in_ms, free[0].timeline_out_ms) if free else None
        studio.undo_stack.push(clip_edit_command(studio.project, new_id, 'move', clip_id=both.id,
                                                 start=both.timeline_in_ms + 2000,
                                                 end=both.timeline_out_ms + 2000))
        settle(500)
        lane = next(t for t in studio.project.audio_tracks if t.id == lane_of(studio, new_id))
        check('the picture moves alone; the detached sound stays',
              [(c.timeline_in_ms, c.timeline_out_ms) for c in lane.clips if not c.linked_video_clip_id] == [sound_span])
        grab(timeline, 'detached_moved')
        studio.undo_stack.undo()
        studio.undo_stack.undo()
        settle(500)
        restored = next(c for t in studio.project.video_tracks for c in t.clips if c.id == both.id)
        check('undo brings back one linked clip', restored.audio_enabled
              and linked_audio_clip(studio.project, new_id, restored.id) is not None)
        studio.undo_stack.redo()
        settle(500)

        # Plays through the new clips without errors.
        studio._seek(0.5)
        studio.video.set_paused(False)
        studio._sync_play_button(False)
        settle(2500)
        pause(studio)
        check('the project plays through the new clips', not getattr(studio.video, 'playback_source_dead', False))
        capture('workbench_after')

        # Save and reopen.
        expected = dict(video=[(t.id, [(c.timeline_in_ms, c.audio_enabled) for c in t.clips])
                               for t in studio.project.video_tracks],
                        audio=[(t.id, [(c.timeline_in_ms, bool(c.linked_video_clip_id)) for c in t.clips])
                               for t in studio.project.audio_tracks])
        studio.save()
        settle(800)
        path = studio.project_path
        other = open_project(config['other_project'])
        check('opening another project closes the source preview',
              other.cue_list_stack.currentIndex() == 0 and not other.source_monitor.asset_id)
        reopened = open_project(path)
        again = dict(video=[(t.id, [(c.timeline_in_ms, c.audio_enabled) for c in t.clips])
                            for t in reopened.project.video_tracks],
                     audio=[(t.id, [(c.timeline_in_ms, bool(c.linked_video_clip_id)) for c in t.clips])
                            for t in reopened.project.audio_tracks])
        check('saved and reopened: picture-only, free and detached clips are unchanged', again == expected,
              dict(expected=expected, again=again))

    def run_all():
        try:
            for dialog in [w for w in app.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]:
                QDialog.done(dialog, 0)
            window.showNormal()
            window.resize(1600, 980)
            settle(800)
            run_glossary()
            run_workbench()
        except Exception:  # noqa: BLE001
            result['errors'].append(traceback.format_exc())
        watchdog.stop()
        result['passed'] = bool(result['checks']) and all(c['passed'] for c in result['checks']) and not result['errors']
        save_result()
        studio = page_of()
        if studio is not None and getattr(studio, 'project', None) is not None:
            try:
                studio.save()
            except Exception as exc:  # noqa: BLE001
                result['errors'].append(f'save before close: {exc!r}')
        window.close()
        QTimer.singleShot(500, app.quit)

    def shutdown():
        result['gui_shutdown'] = True
        save_result()

    app.aboutToQuit.connect(shutdown)
    QTimer.singleShot(2500, run_all)
