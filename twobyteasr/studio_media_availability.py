"""Project-scoped media health UI and cancellation/generation protection."""
import threading

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QImage, QPainter, QColor, QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QMessageBox

from .media_availability import apply_availability, media_available, probe_sources

from .i18n import bind_text

from .i18n import tr


class StudioMediaAvailability(QObject):
    checked = Signal(object, object, object)
    relink_checked = Signal(object, str, str, int, object)

    def __init__(self, page, layout):
        super().__init__(page)
        self.page = page
        self.pending = False
        self.cancelled = threading.Event()
        self.relink_generation = 0
        self.relink_cancel = threading.Event()
        self.gap_visible = False
        self.banner = QFrame(page)
        self.banner.setObjectName('studioMediaWarning')
        row = QHBoxLayout(self.banner)
        self.label = QLabel()
        self.label.setWordWrap(True)
        row.addWidget(self.label, 1)
        self.relink = QPushButton('重新链接 / 查看素材')
        self.relink.clicked.connect(self.choose_offline)
        row.addWidget(self.relink)
        layout.addWidget(self.banner)
        self.banner.hide()
        self.checked.connect(self.apply)
        self.relink_checked.connect(self.apply_relink)
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.check)
        self.timer.start()
        page.destroyed.connect(lambda *_: self.cancelled.set())

    def show_media(self):
        self.page._show_context_panel()
        self.page.context_drawer.setCurrentIndex(self.page.media_pool_tab_index)

    def choose_offline(self):
        from PySide6.QtWidgets import QInputDialog
        project = self.page.project
        missing = [a for a in project.media_pool if a.offline] if project else []
        if not missing:
            self.show_media()
            return
        selected = str(self.page.timeline.selected_video_clip_id or self.page.timeline.selected_segment_id or '')
        asset_id = next((c.asset_id for t in project.video_tracks for c in t.clips if c.id == selected), '')
        asset = next((a for a in missing if a.asset_id == asset_id), None)
        if asset is None and len(missing) == 1:
            asset = missing[0]
        if asset is None:
            labels = [f'{a.display_name} — {a.canonical_source} [{a.asset_id}]' for a in missing]
            label, ok = QInputDialog.getItem(self.page, '重新链接素材', '选择需要重新链接的脱机素材：', labels, 0, False)
            if not ok or self.page.project is not project:
                return
            asset = missing[labels.index(label)]
        self.choose_relink(asset.asset_id)

    def choose_relink(self, asset_id):
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog
        from .studio_media_pool_ui import MEDIA_FILTER
        project = self.page.project
        asset = next((a for a in project.media_pool if a.asset_id == asset_id), None) if project else None
        if asset is None:
            bind_text(self.page.save_state, '该素材已不在当前工程中，请重新选择')
            return
        # Nonexistent/network source directories must not trap the file picker.
        initial = Path.home()
        source = Path(asset.canonical_source)
        if not str(source).startswith(('\\\\', '//')) and source.parent.is_dir():
            initial = source.parent
        path, _ = QFileDialog.getOpenFileName(self.page, tr('重新链接素材'), str(initial), MEDIA_FILTER)
        if path and self.page.project is project:
            self.begin_relink(asset_id, path)

    def cancel_relink(self):
        self.relink_generation += 1
        self.relink_cancel.set()
        bind_text(self.page.media_pool_panel.relink_button, '重新定位')
        bind_text(self.page.save_state, '素材检查已结束')

    def begin_relink(self, asset_id, path):
        self.cancel_relink()
        project = self.page.project
        asset = next((a for a in project.media_pool if a.asset_id == asset_id), None)
        if asset is None:
            return
        old_path = asset.canonical_source
        generation = self.relink_generation
        event = self.relink_cancel = threading.Event()
        bind_text(self.page.media_pool_panel.relink_button, '取消检查')
        bind_text(self.page.save_state, '正在检查所选素材…')
        def cancelled():
            return event.is_set() or self.cancelled.is_set() or self.page.project is not project
        def work():
            try:
                result = probe_sources([path], decode=True, timeout=6, cancel_check=cancelled)[path]
                if not cancelled():
                    self.relink_checked.emit(project, asset_id, old_path, generation, result)
            except InterruptedError:
                pass
            except Exception as exc:
                if not cancelled():
                    self.relink_checked.emit(project, asset_id, old_path, generation,
                        dict(status='error', reason=f'素材检查失败：{exc}', path=path))
        threading.Thread(target=work, name='studio-media-relink', daemon=True).start()

    def apply_relink(self, project, asset_id, old_path, generation, result):
        page = self.page
        if page.project is not project or generation != self.relink_generation:
            return
        self.cancel_relink()
        asset = next((a for a in project.media_pool if a.asset_id == asset_id), None)
        if asset is None or asset.canonical_source != old_path:
            return
        if result['status'] != 'available':
            bind_text(page.save_state, '重新链接失败')
            QMessageBox.warning(page, tr('无法使用所选素材'), result['reason'])
            return
        identity = result['identity']
        required_end = max((clip.source_out_ms for track in (*project.video_tracks, *project.audio_tracks)
                            for clip in track.clips if clip.asset_id == asset_id), default=0)
        warnings = []
        duration = int(identity.get('duration_ms') or 0)
        if duration and duration < required_end:
            warnings.append('所选素材比已编辑的源时间范围短，超出部分会显示空白或静音。')
        if duration and duration < int(asset.duration_ms or 0):
            warnings.append('所选素材比原素材短；将保留原片段时间和源入出点。')
        elif abs(duration - int(asset.duration_ms or 0)) > max(3000, asset.duration_ms * .02):
            warnings.append('所选素材的时长与原素材不同。')
        if asset.video_metadata.get('width') and not identity.get('has_video'):
            warnings.append('所选素材没有视频流。')
        if asset.audio_metadata.get('has_audio') is not False and any(
                c.asset_id == asset_id for t in project.audio_tracks for c in t.clips) and not identity.get('has_audio'):
            warnings.append('所选素材没有音轨，对应音频将无声；原有音频剪辑与音量设置仍会保留。')
        if warnings and QMessageBox.question(page, tr('所选素材与原素材不一致'),
                tr('{value0}\n\n仍要重新链接并保留现有剪辑吗？', value0='\n'.join(warnings)),
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes:
            return
        from .studio_media_commands import media_graph_command
        from .studio_media_pool import relink_media_asset
        path = result['path']
        command = media_graph_command(project, '重新链接素材',
            lambda working: relink_media_asset(working, asset_id, path,
                                               fingerprint=str(identity.get('fingerprint') or ''),identity=identity))
        # Publish verified health before the undo command triggers renderer hydration.
        project._media_availability = {**getattr(project, '_media_availability', {}), path: result}
        page.undo_stack.push(command)
        page._active_video_preview_key = ''
        page._audio_contract_signature = None
        page._sync_multitrack_preview_at(int(page.timeline.playhead_ms))
        page.ensure_active_subtitle_renderer(reason='media_relink')
        page.media_pool_panel.refresh()
        page.relink_button.setVisible(not media_available(project, project.media.path))
        bind_text(page.save_state, '素材已重新链接 · 可撤销')
        self.refresh()

    def refresh(self):
        project = self.page.project
        missing = [a for a in project.media_pool if a.offline] if project else []
        self.banner.setVisible(bool(missing))
        if missing:
            detail = '全部素材脱机 · 字幕和时间轴仍可编辑、播放' if len(missing) == len(project.media_pool) else '可用素材和字幕可继续编辑、播放'
            from .audio_playback_graph import solo_track_ids
            selected=solo_track_ids(project)
            linked={g.video_track_id:g.audio_track_id for g in project.av_track_groups}
            bad={a.asset_id for a in missing}
            silent_solos=[t.name for t in (*project.video_tracks,*project.audio_tracks)
                          if (t.id in selected or linked.get(t.id) in selected)
                          and any(c.asset_id in bad and c.timeline_in_ms<=self.page.timeline.playhead_ms<c.timeline_out_ms for c in t.clips)]
            if silent_solos:detail+=' · 独听素材脱机：'+ '、'.join(dict.fromkeys(silent_solos))+'（关闭 S 恢复混音）'
            bind_text(self.label, '{value0} 个素材脱机 · {detail}', value0=len(missing), detail=detail)
            states = getattr(project, '_media_availability', {})
            bind_text(self.label, '\n'.join((f"{a.display_name}：{states.get(a.canonical_source, {}).get('reason', '媒体不可用')}\n{a.canonical_source}" for a in missing)), property='toolTip')
        self.page.timeline.update()

    def show_gap(self, timeline_ms):
        page = self.page
        if not (getattr(page.video, '_clock_only', False) or not getattr(page.video, '_media_has_video', True)):
            return
        offline = {a.asset_id: a for a in page.project.media_pool if a.offline}
        active = {c.asset_id for t in page.project.video_tracks if t.enabled for c in t.clips
                  if c.enabled and c.timeline_in_ms <= timeline_ms < c.timeline_out_ms and c.asset_id in offline}
        image = QImage(1920, 1080, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor('#202124'))
        painter = QPainter(image)
        painter.setPen(QColor('#c4c5c7'))
        painter.setFont(QFont('Microsoft YaHei UI', 32))
        painter.drawText(QRect(80, 390, 1760, 90), Qt.AlignCenter,
                         '媒体脱机' if active else '当前位置没有视频')
        painter.setFont(QFont('Microsoft YaHei UI', 20))
        painter.drawText(QRect(80, 500, 1760, 140), Qt.AlignHCenter | Qt.TextWordWrap,
                         '、'.join(offline[key].display_name for key in sorted(active)) if active else '字幕与时间轴仍可播放')
        painter.end()
        from .studio_mpv import VIDEO_OVERLAY_ID
        page.video.publish_compositor_overlay(VIDEO_OVERLAY_ID, image, page.video.rect(),
                                               source_bounds=image.rect(),
                                               context={'caller':'offline_placeholder'})
        self.gap_visible = True

    def clear_gap(self):
        if self.gap_visible:
            from .studio_mpv import VIDEO_OVERLAY_ID
            self.page.video.remove_compositor_overlay(VIDEO_OVERLAY_ID,force=True)
            self.gap_visible = False

    def check(self):
        page = self.page
        if self.pending or self.cancelled.is_set() or getattr(page, '_close_requested', False):
            return
        project = page.project
        if project is None or not page.isVisible():
            self.refresh()
            return
        paths = tuple(a.canonical_source for a in project.media_pool)
        if not paths:
            self.refresh()
            return
        self.pending = True

        def cancelled():
            return self.cancelled.is_set() or page.project is not project or getattr(page, '_close_requested', False)

        previous = dict(getattr(project, '_media_availability', {}))

        def work():
            try:
                results = probe_sources(paths, cancel_check=cancelled, decode=True, previous=previous)
                if not cancelled():
                    self.checked.emit(project, paths, results)
            except (InterruptedError, RuntimeError):
                pass
            finally:
                self.pending = False
        threading.Thread(target=work, name='studio-media-availability', daemon=True).start()

    def apply(self, project, paths, results):
        page = self.page
        if page.project is not project or tuple(a.canonical_source for a in project.media_pool) != paths:
            return
        changed = apply_availability(project, results)
        self.refresh()
        if not changed:
            return
        page.media_pool_panel.refresh()
        page._audio_contract_signature = None
        page._active_video_preview_key = ''
        page._sync_multitrack_preview_at(int(page.timeline.playhead_ms))
        page.ensure_active_subtitle_renderer(reason='media_availability')
        page._studio_trace('MEDIA_AVAILABILITY', assets=[dict(asset_id=a.asset_id, offline=a.offline,
            status=results.get(a.canonical_source, {}).get('status')) for a in project.media_pool])
